#!/bin/bash

SCRIPTSPATH=${SCRIPTSPATH:=$HOME/loongshot/scripts}
BUILDER=${BUILDER:=loong1}
BUILDDIR=${BUILDDIR:=/mnt/repos}
BUILDLIST=${BUILDLIST:="1"}
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
        --save)
            SAVE="yes"
            shift
            ;;
        --nosync) # Don't sync package database
            shift
            SKIP="yes"
            ;;
        --nokde)
            shift
            NOKDE="--nokde"
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
    if [[ -z "$SKIP" ]]; then
        echo "Start to syncing database"
        ${SCRIPTSPATH}/compare86.py $REPOSWITCH -S
        ${SCRIPTSPATH}/dbinit.py -S
    fi
    # All packages should be build
    PKG=$(${SCRIPTSPATH}/compare86.py $REPOSWITCH -BEC | awk '{print $1}')

    # Filter out packages not to build
    # 1. Same version failed last time
    # 2. Blacklists
    # 3. KDE packages use upstream list
    PKG=$(echo $PKG | tr ' ' '\n' | ${SCRIPTSPATH}/filterpkg.py $REPOSWITCH --list $BUILDLIST $NOKDE)
    if [ $? -eq 1 ]; then
        # filterpkg.py may fail when insert_task fails
        exit 1
    fi
    echo $PKG | tr ' ' '\n' > today.lst
    echo "Start to ordering..."
    PKG=$(timeout 20 ./genrebuild --dbpath ~/.cache/compare86/x86 `echo $PKG` | tr ' ' ',')
    if [[ ! -z "$SAVE" ]]; then
        echo $PKG
        exit 1
    fi
    if [[ -z "$PKG" ]]; then
        exit 1
    fi
    ./dbcmd.py task --add "$PKG" $REPOSWITCH --list $BUILDLIST
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
    if [[ -z "$SKIP" ]]; then
        echo "Syncing database again"
        ${SCRIPTSPATH}/compare86.py -sTS
        ${SCRIPTSPATH}/dbinit.py -S
    fi
fi
