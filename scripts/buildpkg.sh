#!/bin/bash

# Variables should be defined in loong.sh:
# 1. LOONGREPO, local dir of loongarch-package repository
# 2. BUILDER, build server to use
# 3. WORKDIR, local working dir
# 4. REPOS, loongarch repo mirror path for testing

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

# version info may change after patching
ARCHVERREL=$(source PKGBUILD; echo $pkgver-$pkgrel)
ARCH=$(source PKGBUILD; echo $arch)
if [[ "$ARCH" != "any" ]]; then
    ARCH="loong64"
fi

# apply patch
if [[ -d "$LOONGREPO/$PKGDIR" ]]; then
    cat $LOONGREPO/$PKGDIR/loong.patch | patch -p0  || exit 1
fi

PKGVERREL=$(source PKGBUILD; echo $pkgver-$pkgrel)

# copy package source to build server
rsync -avzP $WORKDIR/$PKGDIR/ $BUILDER:/home/arch/repos/$PKGDIR/ --delete --exclude=.*

# build package on server
ssh -t $BUILDER "cd /home/arch/repos/$PKGDIR; extra-loong64-build -- -- -A" || exit 1

rsync -avzP $BUILDER:/home/arch/repos/$PKGDIR/ $WORKDIR/build/$PKGDIR/ || exit 1

cd $WORKDIR/build/$PKGDIR

JSON=$(curl -s -X GET $WEBSRV/op/show/$PKGDIR) || (echo "Failed to GET"; exit 1)

repo_value=${JSON#*\"repo\":\"}
repo_value=${repo_value%%\"*}-testing

repo-add $REPOS/$repo_value/os/loong64/$repo_value.db.tar.gz $PKGDIR-$PKGVERREL-$ARCH.pkg.tar.zst
cp $PKGDIR-$PKGVERREL-$ARCH.pkg.tar.zst $REPOS/$repo_value/os/loong64/

curl -s -X POST $WEBSRV/op/edit/$PKGDIR -d "loong_ver=$PKGVERREL&x86_ver=$ARCHVERREL&repo=${repo_value%%-testing}&build_status=testing"
