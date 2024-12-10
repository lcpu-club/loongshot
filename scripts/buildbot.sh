#!/bin/bash

WORKDIR=${WORKDIR:=$HOME/repos}
ZSTLOGDIR=${ZSTLOGDIR:=$HOME/logs}
SCRIPTSPATH=${SCRIPTSPATH:=$HOME/loongshot/scripts}

max_retries=2
DOUBLEDASH="--"

for para in "$@"; do
    if [[ $para == "--" ]]; then
        DOUBLEDASH=""
        break
    fi
done

umask 002

while [ 1 ]; do
    retries=0

    pkg=`$SCRIPTSPATH/dbcmd.py task --get`
    orig=$pkg

    if [[ "$pkg" == None ]] || [[ "$pkg" == %stop ]]; then
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
        if [[ -f all.log ]]; then
            ALLLOGS=all.log
        else
            PKGVER=$(source $WORKDIR/$pkg/PKGBUILD; echo $epoch${epoch:+:}$pkgver-$pkgrel)
            ALLLOGS=$ZSTLOGDIR/$pkg/$pkg-$PKGVER.log
        fi

        # restart to download the corrupted packages
        grep "pkg.tar.zst is corrupted" $ALLLOGS >/dev/null 2>&1 && continue
        # update config.{sub,guess} and retry
        grep -q "unable to guess system type" $ALLLOGS && echo $pkg >> ~/loongarch-packages/update_config && continue
        break
    done

    $SCRIPTSPATH/dbcmd.py task --remove $orig

    # tracking the soname changes
    grep -A4 "WARNING.*Sonames differ" $ALLLOGS >> sonames.log
done
