#!/bin/bash
# check repo for old package files and delete them

REPODIR=/srv/http/loongarch/archlinux

check() {
    REPO=$1
    echo "Checking repo $1 ..."
    WORKDIR=$(mktemp -d)
    cd $WORKDIR
    all_files=()
    about_to_delete=()
    for i in $(ls $REPODIR/$REPO/os/loong64/*.zst); do
        all_files+=($(basename $i))
    done
    tar xfz $REPODIR/$REPO/os/loong64/$REPO.db.tar.gz
    for pkg in "${all_files[@]}"; do
        n1=${pkg%-loong64.pkg.tar.zst}
        n2=${n1%-any.pkg.tar.zst}
        if [ ! -d $n2 ]; then
            echo "$pkg"
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

check core-staging
check core-testing
check extra-testing
check extra-staging
