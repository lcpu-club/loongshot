#!/bin/bash

REPODIR=/srv/http/loongarch/archlinux

check() {
    REPO=$1
    echo "Checking repo $1 ..."
    WORKDIR=$(mktemp -d)
    cd $WORKDIR
    about_to_delete=()
    tar xfz $REPODIR/$REPO/os/loong64/$REPO.db.tar.gz
    for i in $(ls $REPODIR/$REPO/os/loong64/*.zst); do
        pkg=$(basename $i)
        n1=${pkg%-loong64.pkg.tar.zst}
        n2=${n1%-any.pkg.tar.zst}
        if [ ! -d $n2 ]; then
            echo $pkg
            about_to_delete+=($pkg)
        fi
    done
    if [ ${#about_to_delete[@]} -eq 0 ]; then
        echo "Repo $REPO is clean"
    else
        echo "Are you sure you want to delete all the files in the array? (yes/no)"
        read -r answer
        if [ "$answer" == "yes" ]; then
            for file in "${about_to_delete[@]}"; do
                echo "Deleting $file"
                rm $REPODIR/$REPO/os/loong64/$file -f
                rm $REPODIR/$REPO/os/loong64/$file.sig -f
            done
        fi
    fi
    rm $WORKDIR -rf
}

check extra-testing
check extra-staging
check core-testing
check core-staging
