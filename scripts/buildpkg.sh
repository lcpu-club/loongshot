#!/bin/bash

# Variables should be defined in loong.sh:
# 1. LOONGREPO, local dir of loongarch-package repository
# 2. BUILDER, build server to use
# 3. WORKDIR, local working dir
# 4. REPOS, loongarch repo mirror path for testing
# 5. PACKAGER, packager name
# 6. T0SERVER, repo server

. loong.sh

if [[ $# -lt 1 ]]; then
    echo "Usage: ${0##*/} <pkg-file> [option]"
    echo "Option:"
    echo "  --sign     Sign the final package file and database file."
    echo "  --keepsrc  Don't re-download the source code to build."
    echo "  --debug    Debug the building, don't upload."
    echo "  --stag     Use staging repo."
    echo "  --core     New package add to core."
    echo "  --ver      Build a specific version."
    echo "  --nocheck  Pass --nocheck to makepkg."
    echo "  --         Options after this will be passed to makepkg."
    exit 1
fi

E_CLONE=2
E_PATCH=3
E_BUILD=4
E_NET=5
T0REPOPATH=/srv/http/loongarch/archlinux/

PKGBASE=$1
shift

NOKEEP="--delete --delete-excluded"
TESTING="-testing"
CORE="extra"
REPOTAG=""
NOCHECK=""

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
            TESTING="-staging"
            shift
            ;;
        --core)
            CORE="core"
            shift
            ;;
        --ver)
            shift
            REPOTAG=$1
            shift
            ;;
        --nocheck)
            NOCHECK="--nocheck"
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
if [[ -d $WORKDIR/$PKGBASE ]]; then
    cd $WORKDIR/$PKGBASE
    pkgctl repo switch main -f 2>/dev/null
    git pull || exit $E_CLONE
else
    cd $WORKDIR || exit 1
    pkgctl repo clone --protocol=https $PKGBASE || exit $E_CLONE
    cd $PKGBASE
fi

# borrow code from felixonmars, get pkgver and repo name
sudo pacman -Sy
PKGNAME=$(. PKGBUILD; echo $pkgname)
if [[ -z "$REPOTAG" ]]; then
    for _REPO in core extra; do
        PKGVER=$(pacman -Sl $_REPO | grep "^$_REPO $PKGNAME " | cut -d " " -f 3)
        if [[ -n "$PKGVER" ]]; then
            REPO=$_REPO
            break
        fi
    done
else
    PKGVER=$REPOTAG
fi

# switch to the current release tag
if [[ ! -z "$PKGVER" ]]; then
    pkgctl repo switch ${PKGVER//:/-} 2>/dev/null || exit $E_CLONE
fi

# no same pkg found in x86 repos
if [[ -z "$REPO" ]]; then
    REPO=$CORE
    repo_value=$CORE$TESTING
else
    repo_value=$REPO$TESTING
fi

ARCH=$(source PKGBUILD; echo $arch)
if [[ "$ARCH" != "any" ]]; then
    ARCH="loong64"
fi

# apply patch
if [[ -d "$LOONGREPO/$PKGBASE" ]]; then
    cat $LOONGREPO/$PKGBASE/loong.patch | patch -p1 || exit $E_PATCH
    find $LOONGREPO/$PKGBASE -type f -name "*" ! -name "loong.patch" -exec cp {} . \;
fi

# package may not in arch's repo
if [[ -z "$PKGVER" ]]; then
    EPOCH=$(source PKGBUILD; echo $epoch)
    PKGVERREL=$(source PKGBUILD; echo $pkgver-$pkgrel)
    if [ ! -z "$EPOCH" ]; then
        PKGVERREL=$EPOCH:$PKGVERREL
    fi
    PKGVER="missing"
else
    PKGVERREL=$PKGVER
fi

#if [[ "$T0SERVER" == "localhost" ]]; then
#    _PKGVER=$(findpkg.py $T0REPOPATH $repo_value $PKGNAME)
#else
#    _PKGVER=$(ssh -t $T0SERVER "findpkg.py $T0REPOPATH $repo_value $PKGNAME")
#fi
_PKGVER=$(findpkg.py $T0REPOPATH $repo_value $PKGNAME)
if [[ ! -z "$_PKGVER" ]] && [[ "$_PKGVER" == "$PKGVERREL"* ]]; then
    # Same package found in server. Incrementing point pkgrel...
    PKGREL=${_PKGVER#*-}
    PKGREL=$(echo $PKGREL + .1 | bc)
    sed -i "s/^pkgrel=.*/pkgrel=$PKGREL/" PKGBUILD
    PKGVERREL=${PKGVERREL%-*}-$PKGREL
fi

# for rust packages, $CARCH need to change to `uname -m`=loongarch64
sed -i '/cargo fetch/s/\$CARCH/`uname -m`/' PKGBUILD
sed -i '/cargo fetch/s/\${CARCH}/`uname -m`/' PKGBUILD
sed -i '/cargo fetch/s/\x86_64/`uname -m`/' PKGBUILD

# When use cpython, $CARCH also need to chage to `uname -m`
sed -i 's/\$CARCH-cpython-/`uname -m`-cpython-/g' PKGBUILD
sed -i 's/\${CARCH}-cpython-/`uname -m`-cpython-/g' PKGBUILD
sed -i 's/lib.linux-x86_64-cpython/lib.linux-$(uname -m)-cpython/' PKGBUILD

# More lua packages are building with luarocks, so..
sed -i 's/linux-\$CARCH.rock/linux-`uname -m`.rock/g' PKGBUILD

# insert two lines of code after cd to the source.
update_config() {
    cd $WORKDIR/$PKGBASE
    sed -i '/^build()/,/configure/ {/^[[:space:]]*cd[[:space:]]\+/ { s/$/\n  for c_s in $(find -type f -name config.sub -o -name configure.sub); do cp -f \/usr\/share\/automake-1.1?\/config.sub "$c_s"; done\n  for c_g in $(find -type f -name config.guess -o -name configure.guess); do cp -f \/usr\/share\/automake-1.1?\/config.guess "$c_g"; done/; t;};}' PKGBUILD
}

[[ $(grep "^$PKGBASE$" $LOONGREPO/update_config) ]] && update_config

[[ $(grep "^$PKGBASE$" $LOONGREPO/ruby_mapping) ]] && echo "checkdepends+=(ruby-mapping)" >> PKGBUILD

# copy package source to build server
rsync -avzP $WORKDIR/$PKGBASE/ $BUILDER:/home/arch/repos/$PKGBASE/ $NOKEEP --exclude=.*

check_build() {
    ssh $BUILDER "cd /home/arch/repos/$PKGBASE; ls *.log >/dev/null 2>&1"
    if [[ "$?" -eq 2 ]]; then
        exit $E_NET # probably network issue
    else
        # sync back logs
        rsync -avzP $BUILDER:/home/arch/repos/$PKGBASE/*.log $WORKDIR/build/$PKGBASE/ || exit 1
        if [ ! -z "$DEBUG" ]; then
            exit 1 # Don't update log
        fi
        curl -s -X POST $WEBSRV/op/update/$PKGBASE -d "build_status=fail" || (echo "Failed to POST faillog"; exit 1)
        exit $E_BUILD
    fi
}
# build package on server
ssh -t $BUILDER "cd /home/arch/repos/$PKGBASE; PACKAGER=\"$PACKAGER\" extra$TESTING-loong64-build -- -- -A -L $NOCHECK $@" || check_build

rsync -avzP $BUILDER:/home/arch/repos/$PKGBASE/ --include='PKGBUILD' --include='*.log' --include='*.zst' --exclude='*' $WORKDIR/build/$PKGBASE/ || exit 1
if [ ! -z "$DEBUG" ]; then
    exit 1
fi
cd $WORKDIR/build/$PKGBASE
if [[ -z $NOCHECK ]]; then
    rm -f .nocheck
else
    touch .nocheck
fi

add_to_repo() {
    rm -f $1-$PKGVERREL-$ARCH.pkg.tar.zst.sig # remove sig first if exists
    if [ ! -z "$SIGN" ]; then
        gpg --detach-sign $1-$PKGVERREL-$ARCH.pkg.tar.zst
    fi
    if [[ "$T0SERVER" == "localhost" ]]; then
        # signing might fail
        if [ -f $1-$PKGVERREL-$ARCH.pkg.tar.zst.sig ]; then
            cp $1-$PKGVERREL-$ARCH.pkg.tar.zst.sig $REPOS/$repo_value/os/loong64/
        else
            # remove the old sig file in repos if exists
            rm -f $REPOS/$repo_value/os/loong64/$1-$PKGVERREL-$ARCH.pkg.tar.zst.sig
        fi
        flock /tmp/loong-repo-$REPO.lck repo-add -R $REPOS/$repo_value/os/loong64/$repo_value.db.tar.gz $1-$PKGVERREL-$ARCH.pkg.tar.zst
        cp $1-$PKGVERREL-$ARCH.pkg.tar.zst $REPOS/$repo_value/os/loong64/
        chmod 664 $REPOS/$repo_value/os/loong64/$1-$PKGVERREL-$ARCH.pkg.tar.zst{,.sig}
    else
        scp "./$1-$PKGVERREL-$ARCH.pkg.tar.zst" $T0SERVER:$REPOS/os/loong64/
        ssh -tt $T0SERVER "cd $REPOS/os/loong64/; repo-add -R local-repo.db.tar.gz $1-$PKGVERREL-$ARCH.pkg.tar.zst"
    fi
    curl -s -X POST $WEBSRV/op/edit/$1 --data-urlencode "loong_ver=$PKGVERREL" --data-urlencode "x86_ver=$PKGVER" -d "repo=${repo_value%%$TESTING}&build_status=testing" || (echo "Failed to POST result"; exit 1)
}

(source PKGBUILD; for pkg in ${pkgname[@]}; do add_to_repo $pkg; done)
