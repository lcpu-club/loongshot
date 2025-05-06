#!/bin/bash

WORKDIR=${WORKDIR:=$HOME/repos}
ZSTLOGDIR=${ZSTLOGDIR:=$HOME/logs}
SCRIPTSPATH=${SCRIPTSPATH:=$HOME/loongshot/scripts}
BUILDER=${BUILDER:=loong1}
BUILDDIR=${BUILDDIR:=/mnt/repos}
BUILDLIST=${BUILDLIST:="1"}

max_retries=2
max_size=102400  # if the build fails quick ( with small size ), try to recovery
DOUBLEDASH="--"

for para in "$@"; do
    if [[ $para == "--" ]]; then
        DOUBLEDASH=""
        break
    fi
    if [[ $para == *":"* ]]; then
        BUILDER=${para%:*}
        BUILDDIR=${para#*:}
    fi
done

umask 002

while [ 1 ]; do
    retries=0

    pkg=`$SCRIPTSPATH/dbcmd.py task --get --build --list $BUILDLIST`
    orig=$pkg

    if [[ "$pkg" == None ]]; then
        exit 0
    fi

    if [[ "$pkg" == %stop ]]; then
        exit 1
    fi

    if [[ "$pkg" == *:nocheck ]]; then
        NOCHECK=--nocheck
        pkg=${pkg%:nocheck}
    else
        NOCHECK=""
    fi

    # the pkg can have version info in it
    if [[ "$pkg" == *:* ]]; then
        VER="--ver ${pkg#*:}"  # Extracts the version part after the first ":"
        pkg=${pkg%%:*};  # Extracts the pkgbase part before the first ":"
    else
        VER=""
    fi

    while [[ $retries -lt $max_retries ]]; do
        ./0build.sh $pkg $VER "$@" $DOUBLEDASH $NOCHECK
        ((retries++))
        if [[ -f all.log.$BUILDER ]]; then
            ALLLOGS=all.log.$BUILDER
        else
            PKGVER=$(source $WORKDIR/$pkg/PKGBUILD; echo $epoch${epoch:+:}$pkgver-$pkgrel)
            ALLLOGS=$ZSTLOGDIR/$pkg/$pkg-$PKGVER.log
        fi

        if [ $(stat -c %s "$ALLLOGS") -lt $max_size ]; then

            # restart to download the corrupted packages
            grep "pkg.tar.zst is corrupted" $ALLLOGS >/dev/null 2>&1 && continue

            # update config.{sub,guess} and retry
            grep -q "unable to guess system type" $ALLLOGS && echo $pkg >> ~/loongarch-packages/update_config && continue

            # re-download failed files
            if grep -q "One or more files did not pass the validity check" $ALLLOGS; then
                for failed in `awk '/Validating source files with/{flag=1; next} /One or more files did not pass the validity check/{flag=0} flag && /FAILED/ {print $1}' "$ALLLOGS"`; do
                    ssh $BUILDER -t "rm $BUILDDIR/$pkg/$failed -rf"
                done
                continue
            fi

            if grep -q "Could not download sources." $ALLLOGS; then
                for failed in `awk '/is not a clone/ && $3 ~ /^\/mnt\/repos\//  {print $3}' "$ALLLOGS"`; do
                    # remove bad repo
                    ssh $BUILDER -t "rm $failed -rf"
                done
                continue
            fi

            if grep -q -e "remote: GitLab is not responding" -e "Resolving timed out after 10000 milliseconds" -e "Connection timed out after 10001 milliseconds" $ALLLOGS; then
                sleep 100
                continue
            fi
        fi
        break
    done

    $SCRIPTSPATH/dbcmd.py task --done $orig --list $BUILDLIST

    # tracking the soname changes
    grep -A4 "WARNING.*Sonames differ" $ALLLOGS >> sonames.log
done
