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
if [[ $# -lt 1 ]]; then
    echo "Usage: ${0##*/} <pkg-file> [option]"
    echo "Option:"
    echo "  --sign     Sign the final package file and database file."
    echo "  --keepsrc  Don't re-download the source code to build."
    echo "  --debug    Debug the building, don't upload."
    echo "  --stag     Use staging repo."
    echo "  --core     New package add to core."
    echo "  --         Options after this will be passed to makepkg."
    exit 1
fi

PKGDIR=$1
shift
TESTING="testing"

NOKEEP="--delete --delete-excluded"
CORE="extra"

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
        --stag)
            TESTING="staging"
            shift
            ;;
        --core)
            CORE="core"
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
    cd $WORKDIR || exit 1
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

# for rust packages, $CARCH need to change to `uname -m`=loongarch64
sed -i '/cargo fetch/s/\$CARCH/`uname -m`/' PKGBUILD
sed -i '/cargo fetch/s/\x86_64/`uname -m`/' PKGBUILD

# insert two lines of code after cd to the source.
update_config() {
    cd $WORKDIR/$PKGDIR
    sed -i '/^build()/,/configure/ {/^[[:space:]]*cd[[:space:]]\+/ { s/$/\n  for c_s in $(find -type f -name config.sub -o -name configure.sub); do cp -f \/usr\/share\/automake-1.1?\/config.sub "$c_s"; done\n  for c_g in $(find -type f -name config.guess -o -name configure.guess); do cp -f \/usr\/share\/automake-1.1?\/config.guess "$c_g"; done/; t;};}' PKGBUILD
}

[[ $(grep "^$PKGDIR$" $LOONGREPO/update_config) ]] && update_config

# copy package source to build server
rsync -avzP $WORKDIR/$PKGDIR/ $BUILDER:/home/arch/repos/$PKGDIR/ $NOKEEP --exclude=.*

check_build() {
    ssh $BUILDER "cd /home/arch/repos/$PKGDIR; ls *.log"
    if [[ "$?" -eq 2 ]]; then
        exit $E_NET # probably network issue
    else
        # sync back logs
        rsync -avzP $BUILDER:/home/arch/repos/$PKGDIR/*.log $WORKDIR/build/$PKGDIR/ || exit 1
        if [ ! -z "$DEBUG" ]; then
            exit 1 # Don't update log
        fi
        curl -s -X POST $WEBSRV/op/update/$PKGDIR -d "build_status=fail" || (echo "Failed to POST faillog"; exit 1)
        exit $E_BUILD
    fi
}
# build package on server
ssh -t $BUILDER "cd /home/arch/repos/$PKGDIR; extra-$TESTING-loong64-build -- -- -A -L $@" || check_build

rsync -avzP $BUILDER:/home/arch/repos/$PKGDIR/ --include='PKGBUILD' --include='*.log' --include='*.zst' --exclude='*' $WORKDIR/build/$PKGDIR/ || exit 1
if [ ! -z "$DEBUG" ]; then
    exit 1
fi
cd $WORKDIR/build/$PKGDIR

JSON=$(curl -s -X GET $WEBSRV/op/show/$PKGDIR) || (echo "Failed to GET"; exit 1)

if [[ "$JSON" == *"no package found"* ]]; then
   repo_value=$CORE-$TESTING
else
   repo_value=${JSON#*\"repo\":\"}
   repo_value=${repo_value%%\"*}-$TESTING
fi

add_to_repo() {
    rm -f $1-$PKGVERREL-$ARCH.pkg.tar.zst.sig # remove sig first if exists
    if [ ! -z "$SIGN" ]; then
        gpg --detach-sign $1-$PKGVERREL-$ARCH.pkg.tar.zst
    fi
    # signing might fail
    if [ -f $1-$PKGVERREL-$ARCH.pkg.tar.zst.sig ]; then
        cp $1-$PKGVERREL-$ARCH.pkg.tar.zst.sig $REPOS/$repo_value/os/loong64/
    else
        # remove the old sig file in repos if exists
        rm -f $REPOS/$repo_value/os/loong64/$1-$PKGVERREL-$ARCH.pkg.tar.zst.sig
    fi
    flock /tmp/loong-repo-$REPO.lck repo-add -R $REPOS/$repo_value/os/loong64/$repo_value.db.tar.gz $1-$PKGVERREL-$ARCH.pkg.tar.zst
    cp $1-$PKGVERREL-$ARCH.pkg.tar.zst $REPOS/$repo_value/os/loong64/
    curl -s -X POST $WEBSRV/op/edit/$1 --data-urlencode "loong_ver=$PKGVERREL" --data-urlencode "x86_ver=$ARCHVERREL" -d "repo=${repo_value%%-$TESTING}&build_status=testing" || (echo "Failed to POST result"; exit 1)
}

(source PKGBUILD; for pkg in ${pkgname[@]}; do add_to_repo $pkg; done)

