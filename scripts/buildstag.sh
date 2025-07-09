#!/bin/bash

SCRIPTSPATH=${SCRIPTSPATH:=$HOME/loongshot/scripts}
BUILDER=${BUILDER:=loong1}
BUILDDIR=${BUILDDIR:=/mnt/repos}
TESTING=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --stag)
            TESTING="-staging"
            shift
            ;;
        --test)
            TESTING="-testing"
            shift
            ;;
        --resume)
            RESUME="yes"
            shift
            ;;
        --skip) # a file of list of packages to skip
            shift
            SKIP=$1
            shift
            ;;
        *)
            shift
            ;;
    esac
done

# test gpg first
ssh -t $BUILDER "touch k; [[ -f k.sig ]] && rm k.sig; gpg --detach-sign k"
if [[ ! "$?" -eq 0 ]]; then
    exit 1
fi

if [[ ! -z "$TESTING" ]]; then
    REPOSWITCH=-${TESTING%ing}
fi

if [[ -z "$RESUME" ]]; then
    if [[ -z "$TESTING" ]]; then
        ./compare86.py -SBEC | awk '{print $1}' > /tmp/1.txt
    else
        ./compare86.py $REPOSWITCH -SBEC | awk '{print $1}' > /tmp/1.txt
    fi
    PAGER=cat psql -U pguser -d archdb -c "select distinct base from packages where flags & 32768 != 0 and log_version = x86_version" | sed 's/^ //;s/\r$//;1,2d;$d' | sed '$d'> buildfail.lst
    grep -Fvxf buildfail.lst /tmp/1.txt > /tmp/2.txt

    # a list of packages to skip
    if [[ ! -z "$SKIP" ]]; then
        grep -Fvxf $SKIP.lst /tmp/2.txt > /tmp/3.txt
    else
        mv /tmp/2.txt /tmp/3.txt
    fi
    # black list of some binary packages
    grep -Fvxf black.lst /tmp/3.txt > today.lst
    if [[ ! -s today.lst ]]; then
        exit 1
    fi
    sudo pacman -Sy
    PKG=$(timeout 20 ./genrebuild `cat today.lst` | tr ' ' ',')
    if [[ -z "$PKG" ]]; then
            exit 1
    fi
    ./dbcmd.py task --add "$PKG" $REPOSWITCH
fi

./buildbot.sh $REPOSWITCH --builder $BUILDER:$BUILDDIR -- --skippgpcheck

if [[ $? -eq 0 ]]; then
        cd /srv/http/build-repo/temp-extra${TESTING}/os/loong64
        $SCRIPTSPATH/move-repo.sh extra${TESTING}
        cd /srv/http/build-repo/temp-core${TESTING}/os/loong64
        $SCRIPTSPATH/move-repo.sh core${TESTING}
        DEBUG_POOL=/srv/http/debug-pool
        cd /srv/http/build-repo/debug-pool
        for pkg in *.zst; do
            pkgname=${pkg%-debug-*}
            # remove older version
            rm -f $DEBUG_POOL/$pkgname-debug*
            mv $pkg{,.sig} $DEBUG_POOL
        done
fi
