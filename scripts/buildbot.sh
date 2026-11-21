#!/bin/bash

WORKDIR=${WORKDIR:=$HOME/repos}
ZSTLOGDIR=${ZSTLOGDIR:=$HOME/logs}
SCRIPTSPATH=${SCRIPTSPATH:=$HOME/loongshot/scripts}
BUILDER=${BUILDER:=loong1}
BUILDDIR=${BUILDDIR:=/mnt/repos}
BUILDLIST=${BUILDLIST:="1"}
SMALL=${SMALL:-}  # set SMALL=1 on a builder without enough memory for bigmem packages

max_retries=3
max_size=204800  # if the build fails quick ( with small size ), try to recovery
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

# Transient network errors that are worth a retry
NET_ERRORS=(
    "remote: GitLab is not responding"
    "Resolving timed out after 10000 milliseconds"
    "Connection timed out after 10001 milliseconds"
    "fatal: unable to access 'https://gitlab.archlinux.org"
    "Can't copy PKGBUILD to builder"
    "error: RPC failed; HTTP 403 curl 22 The requested URL returned error: 403"
)

has_net_error() {
    local pat
    for pat in "${NET_ERRORS[@]}"; do
        grep -e "$pat" "$1" && return 0
    done
    return 1
}

umask 002

while [ 1 ]; do
    retries=0

    pkg=`$SCRIPTSPATH/dbcmd.py task --get --build --list $BUILDLIST ${SMALL:+--small}`
    orig=$pkg

    if [[ "$pkg" == None ]]; then
        exit 0
    fi

    if [[ "$pkg" == %stop ]]; then
        echo "dbcmd.py returned %stop, stopping this builder." >&2
        echo "  another builder hit a haskell failure, or a %stop entry is in the queue." >&2
        echo "  a queue waiting for a failed task also stops this way; see:" >&2
        echo "  dbcmd.py task --block --list $BUILDLIST" >&2
        exit 1
    fi

    if [[ "$pkg" == %wait ]]; then
        # Other builders still work on this tasklist: the queue is not finished
        # yet, so keep waiting instead of letting buildstag.sh move the repo.
        # Waiting is normal now: a task is not handed out before the tasks it
        # would invalidate have started.
        sleep 10
        continue
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
        BUILD_STATUS=$?
        ((retries++))
        if [[ -f all.log.$BUILDER ]]; then
            ALLLOGS=all.log.$BUILDER
        else
            PKGVER=$(source $WORKDIR/$pkg/PKGBUILD; echo $epoch${epoch:+:}$pkgver-$pkgrel)
            ALLLOGS=$ZSTLOGDIR/$pkg/$pkg-$PKGVER.log
        fi

        # only try to recover from a failed build; status 3 is a signing
        # failure on the builder, retrying would just rebuild the package and
        # fail to sign it again
        if [[ "$BUILD_STATUS" -eq 0 ]] || [[ "$BUILD_STATUS" -eq 3 ]]; then
            break
        fi

        # ARCH=any packages have no build log at all, everything below only
        # makes sense when there is one.
        if [[ -f "$ALLLOGS" ]] && [ $(stat -c %s "$ALLLOGS") -lt $max_size ]; then

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
                if grep -q "server does not seem to support byte ranges" $ALLLOGS; then
                    ssh $BUILDER -t "rm $BUILDDIR/$pkg/*.part -f"
                    continue
                fi
                for failed in `awk '/is not a clone/ && $3 ~ /^\/mnt\/repos\//  {print $3}' "$ALLLOGS"`; do
                    # remove bad repo
                    ssh $BUILDER -t "rm $failed -rf"
                done
                continue
            fi

            # gitlab/network hiccups: wait a bit and retry the same package
            if has_net_error "$ALLLOGS"; then
                sleep 100
                ((retries--))
                continue
            fi
        fi

        # haskell packages often fail in check, retrying may just work
        if [[ "$pkg" == haskell* ]] && grep -q "A failure occurred in check" "$ALLLOGS"; then
            continue
        fi
        break
    done

    $SCRIPTSPATH/dbcmd.py task --done $orig --list $BUILDLIST

    # A signing failure (status 3) means the package was built and added to the
    # local-repo, but the .sig is missing.  Signing goes through the same key on
    # every builder, so stop them all instead of rebuilding the same packages.
    if [[ "$BUILD_STATUS" -eq 3 ]]; then
        $SCRIPTSPATH/dbcmd.py task --insert "%stop" --list $BUILDLIST

    # A haskell failure is usually the GHC package database being broken, not
    # a problem of this package: every other builder would fail the same way,
    # so stop them all instead of collecting the same error over and over.
    elif [[ "$BUILD_STATUS" -ne 0 ]] && [[ "$pkg" == haskell* ]]; then
        $SCRIPTSPATH/dbcmd.py task --insert "%stop" --list $BUILDLIST
    fi
done
