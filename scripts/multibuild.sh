#!/bin/bash

max_retries=2
total_pkgs=$(wc -l < pkg)
current_pkg=0

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

    while [[ $retries -lt $max_retries ]]; do
        ./loong-build.sh "$i" --test "$@" $NOCHECK
        ((retries++))
        PKGVER=$(source $WORKDIR/$i/PKGBUILD; echo $epoch${epoch:+:}$pkgver-$pkgrel)
        ALLLOGS=$WORKDIR/$i/$i-$PKGVER.log

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
