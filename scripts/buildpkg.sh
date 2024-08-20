#!/bin/bash

# Variables should be defined in loong.sh:
# 1. LOONGREPO, local dir of loongarch-package repository
# 2. BUILDER, build server to use
# 3. WORKDIR, local working dir
# 4. REPOS, loongarch repo mirror path for testing

E_CLONE=2
E_PATCH=3
E_BUILD=4
E_NET=5

. loong.sh
PKGDIR=$1
shift

NOKEEP="--delete --delete-excluded"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --keepsrc)
            NOKEEP=
            shift
            ;;
        --sign)
            SIGN=-s
            shift
            ;;
        --debug)
            DEBUG=1
            shift
            ;;
        --)
            shift
            break
            ;;
        *)
            shift
            ;;
    esac
done

# clone arch package repo
if [[ -d $WORKDIR/$PKGDIR ]]; then
    cd $WORKDIR/$PKGDIR
    git reset HEAD --hard
    git pull
else
    cd $WORKDIR
    pkgctl repo clone --protocol=https $PKGDIR || exit $E_CLONE
    cd $PKGDIR
fi

# version info may change after patching
ARCHVERREL=$(source PKGBUILD; echo $pkgver-$pkgrel)
ARCH=$(source PKGBUILD; echo $arch)
if [[ "$ARCH" != "any" ]]; then
    ARCH="loong64"
fi
EPOCH=$(source PKGBUILD; echo $epoch)

# apply patch
if [[ -d "$LOONGREPO/$PKGDIR" ]]; then
    cat $LOONGREPO/$PKGDIR/loong.patch | patch -p1 || exit $E_PATCH
    find $LOONGREPO/$PKGDIR -type f -name "*" ! -name "loong.patch" -exec cp {} . \;
fi

PKGVERREL=$(source PKGBUILD; echo $pkgver-$pkgrel)
if [ ! -z "$EPOCH" ]; then
    PKGVERREL=$EPOCH:$PKGVERREL
fi

# insert two lines of code after cd to the source.
update_config() {
    cd $WORKDIR/$PKGDIR
    sed -i '/^build()/,/configure/ {/^[[:space:]]*cd[[:space:]]\+/ { s/$/\n  for c_s in $(find -type f -name config.sub -o -name configure.sub); do cp -f \/usr\/share\/automake-1.1?\/config.sub "$c_s"; done\n  for c_g in $(find -type f -name config.guess -o -name configure.guess); do cp -f \/usr\/share\/automake-1.1?\/config.guess "$c_g"; done/; t;};}' PKGBUILD
}

[[ $(grep -w $PKGDIR $LOONGREPO/update_config) ]] && update_config

# copy package source to build server
rsync -avzP $WORKDIR/$PKGDIR/ $BUILDER:/home/arch/repos/$PKGDIR/ $NOKEEP --exclude=.*

check_build() {
    ssh $BUILDER "cd /home/arch/repos/$PKGDIR; ls *.log"
    if [[ "$?" -eq 2 ]]; then
        exit $E_NET # probably network issue
    else
        if [ ! -z "$DEBUG" ]; then
            exit 1
        fi
        # sync back logs
        rsync -avzP $BUILDER:/home/arch/repos/$PKGDIR/ $WORKDIR/build/$PKGDIR/ || exit 1
        curl -s -X POST $WEBSRV/op/update/$PKGDIR -d "build_status=fail" || (echo "Failed to POST faillog"; exit 1)
        exit $E_BUILD
    fi
}
# build package on server
ssh -t $BUILDER "cd /home/arch/repos/$PKGDIR; extra-loong64-build -- -- -A $@" || check_build

rsync -avzP $BUILDER:/home/arch/repos/$PKGDIR/ $WORKDIR/build/$PKGDIR/ || exit 1
if [ ! -z "$DEBUG" ]; then
    exit 1
fi
cd $WORKDIR/build/$PKGDIR

JSON=$(curl -s -X GET $WEBSRV/op/show/$PKGDIR) || (echo "Failed to GET"; exit 1)

repo_value=${JSON#*\"repo\":\"}
repo_value=${repo_value%%\"*}-testing

add_to_repo() {
    if [ ! -z "$SIGN" ]; then
        gpg --pinentry-mode loopback --detach-sign $1-$PKGVERREL-$ARCH.pkg.tar.zst
        cp $1-$PKGVERREL-$ARCH.pkg.tar.zst.sig $REPOS/$repo_value/os/loong64/
    fi
    flock /tmp/loong-repo-$REPO.lck repo-add $SIGN -R $REPOS/$repo_value/os/loong64/$repo_value.db.tar.gz $1-$PKGVERREL-$ARCH.pkg.tar.zst
    cp $1-$PKGVERREL-$ARCH.pkg.tar.zst $REPOS/$repo_value/os/loong64/
    curl -s -X POST $WEBSRV/op/edit/$1 -d "loong_ver=$PKGVERREL&x86_ver=$ARCHVERREL&repo=${repo_value%%-testing}&build_status=testing" || (echo "Failed to POST result"; exit 1)
}

(source PKGBUILD; for pkg in ${pkgname[@]}; do add_to_repo $pkg; done)

