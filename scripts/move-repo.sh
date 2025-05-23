#!/bin/bash
#
# Move packages from current directory to the REPO dir.
# Run under the directory of where *.zst was saved.
# The directcory name should match the name of the local db file.
#   eg: your zst file should located in /some/path/extra-staging/os/loong64/
#

umask 002
REPODIR=/srv/http/loongarch

source /usr/share/makepkg/util/message.sh
colorize

if [[ $# -lt 1 ]]; then
    echo "Usage: ${0##*/} <repo-name> [optional filelist]"
    exit 1
fi

FROM=$(basename `pwd | sed 's/\/os\/loong64$//g'`)
TO=$1

# destination
if [[ "$TO" == *"/"* ]]; then
    # with full path
    NEWPATH=$TO/os/loong64
    TO=$(basename $TO)
    NEWREPO=$NEWPATH
else
    NEWREPO=$REPODIR/archlinux/$TO/os/loong64
    NEWPATH=$REPODIR/archlinux/pool/packages
fi

if [ "$(realpath $NEWPATH)" = "$(realpath `pwd`)" ]; then
    echo "The paths refer to the same directory."
    exit 1
fi

if [[ ! -d $NEWPATH ]]; then
    echo "Destination path don't exist!"
    exit 1
fi

if [[ $# -gt 1 ]]; then
    shift
    ALLFILES=($@)
else
    ALLFILES=$(ls *.zst)
fi

# arrary of packages
ALLPKG=()
ALLZST=()
fcount=1

do_move(){
    if [ "${#ALLPKG[@]}" -eq 0 ]; then
        return
    fi

    if [ -f $FROM.db.tar.gz ]; then
        repo-remove $FROM.db.tar.gz "${ALLPKG[@]}"
    fi

    for i in "${!ALLZST[@]}"; do
        echo "Copying file: ${ALLZST[$i]} ..."
        if [ -L ${ALLZST[$i]} ]; then
            cp -a ${ALLZST[$i]}{,.sig} $NEWREPO
        else
            if [ ! -f $NEWPATH/${ALLZST[$i]} ]; then
                cp ${ALLZST[$i]}{,.sig} $NEWPATH
                if [[ $NEWPATH != $NEWREPO ]]; then
                    ln -sf ../../../pool/packages/${ALLZST[$i]}{,.sig} $NEWREPO
                fi
            else
                error "${ALLZST[$i]} already there, ignore it."
                unset 'ALLZST[$i]'
            fi
        fi
    done
    repo-add --include-sigs -R $NEWREPO/$TO.db.tar.gz "${ALLZST[@]}" | tee add.log
    exit_code=${PIPESTATUS[0]}
    if [[ ! $exit_code -eq 0 ]]; then
        exit 2
    fi
    about_to_delete=()
    for pkg in $(grep -oP "Removing old package file '\K[^']*(?=')" add.log); do
        about_to_delete+=($pkg)
    done
    if [ ! "${#about_to_delete[@]}" -eq 0 ]; then
        for file in "${about_to_delete[@]}"; do
            echo "Deleting $file ..."
            rm -f $NEWREPO/$file{,.sig} # somehow repo-add -R don't remove old links.
            rm -f $NEWPATH/$file{,.sig}
        done
    fi
    rm -f add.log
    for i in "${ALLZST[@]}"; do
        echo "Deleting file: $i ..."
        rm -f $i{,.sig}
    done
    fcount=1
    ALLZST=()
    ALLPKG=()
}

for pkg in ${ALLFILES[@]}; do
    ((fcount++))
    if [ ! -f $pkg.sig ]; then
        echo "Signing $pkg ..."
        gpg --detach-sign $pkg || exit 1
    fi
    chmod 664 $pkg{,.sig}
    ALLZST+=($pkg)
    j=${pkg%-*}
    k=${j%-*}
    ALLPKG+=(${k%-*})
    if [[ $fcount -gt 100 ]]; then
        do_move
    fi
done
do_move
