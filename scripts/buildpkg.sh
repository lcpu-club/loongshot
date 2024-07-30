#!/bin/bash

# variable should defined in loong.sh:
# 1. LOONGREPO, local dir of loongarch-package repository
# 2. BUILDER, build server to use
# 3. WORKDIR, local working dir

. loong.sh
PKGDIR=$1
# clone arch package repo
if [[ -d $WORKDIR/$PKGDIR ]]; then
    cd $WORKDIR/$PKGDIR
    git pull
else
    cd $WORKDIR
    pkgctl repo clone --protocol=https $PKGDIR || exit 1
    cd $PKGDIR
fi

# apply patch
if [[ -d "$LOONGREPO/$PKGDIR" ]]; then
    cat $LOONGREPO/$PKGDIR/loong.patch | patch -p0  || exit 1
fi

# copy package source to build server
rsync -avzP $WORKDIR/$PKGDIR/ $BUILDER:/home/arch/repos/$PKGDIR/ --delete --exclude=.*

# build package on server
ssh -t $BUILDER "cd /home/arch/repos/$PKGDIR; extra-loong64-build -- -- -A" || exit 1

rsync -avzP $BUILDER:/home/arch/repos/$PKGDIR/ $WORKDIR/build/$PKGDIR/ || exit 1
