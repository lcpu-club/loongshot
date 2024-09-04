#!/bin/bash
#
# Move all the packages from current directory to the REPO dir.
# Run under the directory of where *.zst was saved.
# The directcory name should match the name of the local db file.
# If the current dir is one of the public repo, use flock before run this script:
#
#    flock /tmp/loong-repo-<repo>.lock ./move-repo.sh <repo-name>
#

if [[ $# -lt 1 ]]; then
    echo "Usage: ${0##*/} <repo-name>"
    exit 0
fi

FROM=$(basename `pwd | sed 's/\/os\/loong64$//g'`)
TO=$1

# destination
NEWPATH=/srv/http/loongarch/archlinux/$TO/os/loong64

# arrary of packages
ALLPKG=()

for pkg in *.zst; do
    if [ ! -f $pkg.sig ]; then
        gpg --detach-sign $pkg || exit 0
    fi
    j=${pkg%-*}
    k=${j%-*}
    ALLPKG+=(${k%-*})
done

if [ -f $FROM.db.tar.gz ]; then
    repo-remove $FROM.db.tar.gz "${ALLPKG[@]}"
fi

flock /tmp/loong-repo-$TO.lock repo-add -R $NEWPATH/$TO.db.tar.gz *.zst

mv *.zst $NEWPATH
mv *.zst.sig  $NEWPATH

