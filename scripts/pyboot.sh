#!/bin/bash

STEP=$1
WORKDIR=/home/pluto/repos

# clone repos
if [[ "$STEP" -eq 1 ]]; then
    for i in `cat pyboot.lst`;  do
        if [[ -d $WORKDIR/$i ]]; then
            cd $WORKDIR/$i
            git checkout main -f
            git pull
        else
            cd $WORKDIR
            pkgctl repo clone --protocol=https $i
        fi
        sleep 20 # Wait 20 seconds to make gitlab happy
    done
fi

PAGER=cat
# Check the commit message and tags
if [[ "$STEP" -eq 2 ]]; then
    for i in `cat pyboot.lst`;  do
        cd $WORKDIR/$i
        echo $i
        git log -n 2 --pretty=format:"%s"
        echo
    done
fi

# extract tags to bootstrap
if [[ "$STEP" -eq 3 ]]; then
    for i in `cat pyboot.lst`;  do
        cd $WORKDIR/$i
        echo "$i:$(git tag --sort=-creatordate | sed -n '2p'):nocheck"
    done
fi

# extract tags to nocheck build
if [[ "$STEP" -eq 4 ]]; then
    for i in `cat pyboot.lst`;  do
        cd $WORKDIR/$i
        echo "$i:$(git tag --sort=-creatordate | sed -n '1p'):nocheck"
    done
fi
