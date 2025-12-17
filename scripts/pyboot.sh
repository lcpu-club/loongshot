#!/bin/bash
# 
# This script just review the commit logs of archlinux packages repo and
# generate packages list(with right version tags) to bootstrap python.


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
        git checkout main -f &> /dev/null
        echo $i
        git log -n 4 --pretty=format:"%ad :%s"
        echo
    done
fi

# extract tags to bootstrap
if [[ "$STEP" -eq 3 ]]; then
    for i in `cat pyboot.lst`;  do
        cd $WORKDIR/$i
        git checkout main -f &> /dev/null
        TAG=`git log -n 1 --oneline --decorate --grep="Bootstrap" | grep -o 'tag: [^)]*' | sed 's/tag: //'`
        echo "$i:$TAG:nocheck"
    done
fi

# extract tags to nocheck build
# python-setuptools needs more dependencies and can't just build from here.
# use script `canrebuild` from here to start build other python packages.
if [[ "$STEP" -eq 4 ]]; then
    for i in `cat pyboot.lst`;  do
        cd $WORKDIR/$i
        git checkout main -f &> /dev/null
        TAG=`git log -n 1 --oneline --decorate --grep="Rebuild bootstrapped" | grep -o 'tag: [^),]*' | sed 's/tag: //'`
        echo "$i:$TAG:nocheck"
    done
fi
