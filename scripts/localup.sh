#!/bin/bash

LOCALREPO=${LOCALREPO:=/home/arch/local-repo/}
TIER0SERVER=tier0
_remote_path=/srv/http/loongarch/archlinux

if [[ $# -lt 1 ]]; then
    echo "Usage: ${0##*/} <repo-name> [option]"
    echo "Option:"
    echo "  --builder    Which builder to use(where local-repo is)."
    exit 1
fi

BUILDER="localhost"
REPO=$1

while [[ $# -gt 0 ]]; do
    case "$1" in
        --builder)
            shift
            BUILDER="$1"
            shift
            ;;
        *)
            shift
            ;;
    esac
done

WORKDIR=$(mktemp -d)
if [[ "$BUILDER" == "localhost" ]]; then
    cp $LOCALREPO/os/loong64/*.zst $WORKDIR || exit 1
else
    scp $BUILDER:/$LOCALREPO/os/loong64/*.zst $WORKDIR || exit 1
fi

cd $WORKDIR

ALLFILES=()

for pkg in *.zst; do
    if [ ! -f $pkg.sig ]; then
        echo "Signing $pkg ..."
        gpg --detach-sign $pkg || exit 1
    fi
    ALLFILES+=($pkg)
done

REMOTE=$(ssh -tt $TIER0SERVER "mktemp -d")
rsync $WORKDIR/* $TIER0SERVER:$REMOTE/ || exit 2
ssh -tt $TIER0SERVER "cd $REMOTE; /home/arch/loongshot/scripts/move-repo.sh $REPO; rmdir $REMOTE"

rm -rf $WORKDIR

echo "Are you sure you want to delete all the files in local-repo?(y/n)"
read -r answer
if [ "$answer" == "y" ]; then
    if [[ "$BUILDER" == "localhost" ]]; then
        rm $LOCALREPO/os/loong64/*.zst
    else
        ssh -tt $BUILDER "cd $LOCALREPO/os/loong64; rm *.zst -f; rm local-repo* -f; repo-add local-repo.db.tar.gz"
    fi
fi
