#!/bin/bash

# "--sign" to sign the package
SIGN=
ALLLOGS=all.log

max_retries=2
total_pkgs=$(wc -l < pkg)
current_pkg=0
umask 022
rm -f multistop
for i in $(cat pkg); do
    retries=0
    ((current_pkg++))

    if [[ "$i" == *:nocheck ]]; then
        NOCHECK=--nocheck
        i=${i%:nocheck}
    else
        NOCHECK=""
    fi
    while [[ $retries -lt $max_retries ]]; do
        STARTTIME=$SECONDS
        ./buildpkg.sh "$i" $SIGN $NOCHECK --keepsrc "$@" | tee $ALLLOGS
        exit_code=${PIPESTATUS[0]}
        ((retries++))

        # restart to download the corrupted packages
        grep "pkg.tar.zst is corrupted" $ALLLOGS >/dev/null 2>&1 && continue

        if [[ ! $exit_code -eq 5 ]]; then
            break
        fi
    done
    ENDTIME=$SECONDS
    TIMECOST=$((ENDTIME - STARTTIME))
    mkdir -p ~/workdir/build/$i/
    echo $TIMECOST > ~/workdir/build/$i/.timecost

    # tracking the soname changes
    grep -A4 "WARNING.*Sonames differ" $ALLLOGS >> sonames

    # tracking packages needs to update config.{guess, sub}
    grep -q "unable to guess system type" $ALLLOGS && echo $i >> configs

    # exit_code might be 5 in this case
    grep -q "error: unresolvable package conflicts detected" $ALLLOGS && (echo $i >> conflicts; exit_code=6)

    # download link breaks
    grep -q "The requested URL returned error: 404" $ALLLOGS && echo $i >> 404s

    mv $ALLLOGS ~/workdir/build/$i/

    if [[ $exit_code -eq 5 ]]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') - $i" >> netfail
    fi

    if [[ $exit_code -eq 3 ]]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') - $i" >> patchfail
    fi

    if [[ $exit_code -eq 4 ]]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') - $i" >> buildfail
    fi

    echo "$i - $current_pkg/$total_pkgs" > progress

    if [[ -f "multistop" ]]; then
        exit 0
    fi
done
rm -f progress
