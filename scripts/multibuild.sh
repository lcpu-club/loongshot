#!/bin/bash

max_retries=2
total_pkgs=$(wc -l < pkg)
current_pkg=0

DOUBLEDASH="--"

for para in "$@"; do
    if [[ $para == "--" ]]; then
        DOUBLEDASH=""
        break
    fi
done

umask 022
rm -f multistop
for i in $(cat pkg); do
    retries=0
    ((current_pkg++))

    # comment out
    if [[ "$i" == --* ]]; then
        continue
    fi

    if [[ "$i" == *:nocheck ]]; then
        NOCHECK=--nocheck
        i=${i%:nocheck}
    else
        NOCHECK=""
    fi

    # the pkg can have version info in it
    if [[ "$i" == *:* ]]; then
        VER="--ver ${i#*:}"  # Extracts the version part after the first ":"
        i=${i%%:*};  # Extracts the pkgbase part before the first ":"
    else
        VER=""
    fi

    while [[ $retries -lt $max_retries ]]; do
        ./loong-build.sh "$i $VER" --test "$@" $DOUBLEDASH $NOCHECK
        ((retries++))
        if [[ -f all.log ]]; then
            ALLLOGS=all.log
        else
            PKGVER=$(source $WORKDIR/$i/PKGBUILD; echo $epoch${epoch:+:}$pkgver-$pkgrel)
            ALLLOGS=$WORKDIR/$i/$i-$PKGVER.log
        fi

        # restart to download the corrupted packages
        grep "pkg.tar.zst is corrupted" $ALLLOGS >/dev/null 2>&1 && continue
        # update config.{sub,guess} and retry
        grep -q "unable to guess system type" $ALLLOGS && echo $i >> ~/loongarch-packages/update_config && continue
        break
    done

    # tracking the soname changes
    grep -A4 "WARNING.*Sonames differ" $ALLLOGS >> sonames.log

    echo "$i - $current_pkg/$total_pkgs" > progress.log

    if [[ -f "multistop" ]]; then
        exit 0
    fi
done
rm -f progress.log
