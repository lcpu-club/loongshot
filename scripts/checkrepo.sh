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
    for i in $(ls $REPODIR/$REPO/os/loong64/*.zst 2>/dev/null); do
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
    for i in $(ls 2>/dev/null); do
        if [ -d $i ]; then
            ls $REPODIR/$REPO/os/loong64/$i-*.zst > /dev/null 2>&1 || echo -e "\e[1;31mError:\e[0m Missing $i."
            ls $REPODIR/$REPO/os/loong64/$i-*.zst.sig > /dev/null 2>&1 || echo -e "\e[1;31mError:\e[0m Missing $i's sig file."
        fi
    done
    rm $WORKDIR -rf
}

check core-staging
check extra-staging
check core-testing
check extra-testing
check core
check extra
