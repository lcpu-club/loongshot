#!/bin/bash

# ===== Variables you should check ======
LOONGREPO=${LOONGREPO:=/home/arch/loongarch-packages}
WORKDIR=${WORKDIR:=/home/arch/workdir}
ZSTLOGDIR=${ZSTLOGDIR:=/home/arch/workdir/build}
PACKAGER=${PACKAGER:="LCPU <lcpu@pku.edu.cn>"}
SCRIPTSPATH=${SCRIPTSPATH:=/home/arch/loongshot/scripts}
LOGPATH=/home/arch/loong-status/build_logs
LOCALREPO=/srv/http/build-repo

if [[ $# -lt 1 ]]; then
    echo "Usage: ${0##*/} <pkgbase> [option]"
    echo "Option:"
    echo "  --stag     Use staging repo."
    echo "  --test     Use testing repo."
    echo "  --ver      Build a specific version."
    echo "  --clean    Clean the chroot directory."
    echo "  --builder  Build machine to use, default is 'localhost'."
    echo "             Remote builder syntax is <host>:<workdir>"
    echo "  --delsrc   Delete downloaded and generated files."
    echo "  --debug    Just build the package, don't inform server."
    echo "  --         Options after this will be passed to makepkg."
    exit 1
fi

export LC_ALL=en_US.UTF-8

PKGBASE=$1
shift

TESTING="" # use extra-loong64-build by default
PKGVER=""
CLEAN=""
BUILDER="localhost"
# workdir for the builder
BUILDPATH="/home/arch/repos"
DEBUG=""
BUILDREPO=$($SCRIPTSPATH/compare86.py -p $PKGBASE | awk '{print $5}' | tail -1)

source /usr/share/makepkg/util/message.sh
colorize

if [ ! -d "$LOONGREPO" ] || [ ! -d "$WORKDIR" ]; then
    error "Please set LOONGREPO and WORKDIR in the source code..."
    exit 1
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --stag)
            TESTING="-staging"
            shift
            ;;
        --test)
            TESTING="-testing"
            shift
            ;;
        --ver)
            shift
            PKGVER=$1
            shift
            ;;
        --clean)
            CLEAN="-c"
            shift
            ;;
        --debug)
            DEBUG="yes"
            shift
            ;;
        --builder)
            shift
            BUILDER=${1%:*}
            BP=${1#*:}
            if [[ "$BP" != "$BUILDER" ]]; then
                BUILDPATH="$BP"
            fi
            shift
            ;;
        --delsrc)
            NOKEEP="--delete --delete-excluded"
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

EXTRAARG="$@"

build_package() {
    # packages beloong only to loong
    if [[ -f $LOONGREPO/$PKGBASE/PKGBUILD ]]; then
        cp $LOONGREPO/$PKGBASE $WORKDIR/ -a
        cd $WORKDIR/$PKGBASE
    else
        # clone arch package repo
        if [[ -d $WORKDIR/$PKGBASE ]]; then
            cd $WORKDIR/$PKGBASE
            pkgctl repo switch main -f
            git pull 2>&1 || return
        else
            cd $WORKDIR 2>&1 || return
            pkgctl repo clone --protocol=https $PKGBASE 2>&1 || return
            cd $PKGBASE
        fi

        if [[ -z "$PKGVER" ]]; then
            # get the release tag from x86_64's repo
            if [[ ! -z "$TESTING" ]]; then
                REPOSWITCH=-${TESTING%ing}
            fi
            PKGVER=`$SCRIPTSPATH/compare86.py $REPOSWITCH -p $PKGBASE |grep x86_64|awk -F= '{print $2}'`
        fi

        # switch to the current release tag
        if [[ ! -z "$PKGVER" ]]; then
            if ! pkgctl repo switch ${PKGVER//:/-}; then
                msg "Release tag could not be found."
                return
            fi
        fi
        # apply patch
        if [[ -d "$LOONGREPO/$PKGBASE" ]]; then
            if ! patch -Np1 -i $LOONGREPO/$PKGBASE/loong.patch; then
                msg "Fail to apply loong's patch."
                return
            fi
            # copy additional files
            find $LOONGREPO/$PKGBASE -type f -name "*" ! -name "loong.patch" -exec cp {} . \;
            msg "Loong's patch applied."
        fi
    fi

    # package may not in arch's repo
    if [[ -z "$PKGVER" ]]; then
        PKGVERREL=$(source PKGBUILD; echo $epoch${epoch:+:}$pkgver-$pkgrel)
    else
        PKGVERREL=$PKGVER
    fi

    # Try to find the pkgver from tier0 server
    PKGNAME=$(. PKGBUILD; echo $pkgname)
    _PKGVER=$($SCRIPTSPATH/compare86.py -sTp $PKGBASE | grep "loong64 with ver=$PKGVERREL" | awk -F= '{print $2}')
    if [[ ! -z "$_PKGVER" ]]; then
        # Same package found in server. Incrementing point pkgrel...
        PKGREL=${_PKGVER#*-}
        PKGREL=$(echo $PKGREL + .1 | bc)
        sed -i "s/^pkgrel=.*/pkgrel=$PKGREL/" PKGBUILD
        PKGVERREL=${PKGVERREL%-*}-$PKGREL
    fi

    if grep -qFx "$PKGBASE" $SCRIPTSPATH/trueany.lst; then
        MIRRORSITE=https://mirrors.pku.edu.cn/archlinux
        cd $LOCALREPO/temp-$BUILDREPO$TESTING/os/loong64
        (source $WORKDIR/$PKGBASE/PKGBUILD;
        for pkg in ${pkgname[@]}; do
            FILENAME=$pkg-$PKGVERREL-any.pkg.tar.zst
            wget $MIRRORSITE/$BUILDREPO$TESTING/os/x86_64/$FILENAME
            wget $MIRRORSITE/$BUILDREPO$TESTING/os/x86_64/$FILENAME.sig
            repo-add -R temp-$BUILDREPO$TESTING.db.tar.gz $FILENAME
        done)
        DEBUG="yes" # don't upload logs for true-any packages
        return
    fi

    # for rust packages, $CARCH need to change to `uname -m`=loongarch64
    sed -i '/cargo fetch/s/\$CARCH\|\${CARCH}\|x86_64/`uname -m`/' PKGBUILD

    # When use cpython, $CARCH also need to chage to `uname -m`
    sed -i 's/\$CARCH-cpython-\|\${CARCH}-cpython-/`uname -m`-cpython-/g; s/lib\.linux-x86_64-cpython/lib.linux-`uname -m`-cpython/' PKGBUILD

    # More lua packages are building with luarocks, so..
    sed -i 's/linux-\$CARCH.rock/linux-`uname -m`.rock/g' PKGBUILD

    # insert two lines of code after cd to the source.
    update_config() {
        cd $WORKDIR/$PKGBASE
        sed -i '/^build()/,/configure/ {/^[[:space:]]*cd[[:space:]]\+/ { s/$/\n  for c_s in $(find -type f -name config.sub -o -name configure.sub); do cp -f \/usr\/share\/automake-1.1?\/config.sub "$c_s"; done\n  for c_g in $(find -type f -name config.guess -o -name configure.guess); do cp -f \/usr\/share\/automake-1.1?\/config.guess "$c_g"; done/; t;};}' PKGBUILD
    }

    if grep -q "^$PKGBASE$" "$LOONGREPO/update_config"; then
        update_config
        msg "Updating config.{sub,guess}."
    fi

    if grep -q "^$PKGBASE$" "$LOONGREPO/ruby_mapping"; then
        echo "checkdepends+=(ruby-mapping)" >> PKGBUILD
    fi

    for arg in ${EXTRAARG[@]}; do
        msg "Build with $arg."
    done

    STARTTIME=$SECONDS
    rsync -avzP $WORKDIR/$PKGBASE/ $BUILDER:$BUILDPATH/$PKGBASE/ $NOKEEP --exclude=.*
    if [[ ! $? -eq 0 ]]; then
        msg "Can't copy PKGBUILD to builder."
        return
    fi
    ssh -t $BUILDER "cd $BUILDPATH/$PKGBASE; PACKAGER=\"$PACKAGER\" extra$TESTING-loong64-build $CLEAN -- -- -A -L $EXTRAARG" 2>/dev/null
    EXITCODE=$?

    ENDTIME=$SECONDS
    TIMECOST=$((ENDTIME - STARTTIME))

    # add the zst file to the local-repo
    if [[ "$EXITCODE" -eq 0 ]]; then
        (source PKGBUILD;
        if [[ "$arch" == "any" ]]; then
            ARCH="any"
        else
            ARCH="loong64"
        fi
        cd $LOCALREPO/temp-$BUILDREPO$TESTING/os/loong64
        for pkg in ${pkgname[@]}; do
            FILENAME=$pkg-$PKGVERREL-$ARCH.pkg.tar.zst
            ssh -t $BUILDER "cd $BUILDPATH/$PKGBASE; [[ -f $FILENAME.sig ]] && rm $FILENAME.sig; gpg --detach-sign $FILENAME"
            scp $BUILDER:$BUILDPATH/$PKGBASE/$FILENAME{,.sig} .
            repo-add -R temp-$BUILDREPO$TESTING.db.tar.gz $FILENAME
        done)
        msg "$PKGBASE-$PKGVERREL built on $BUILDER, time cost: $TIMECOST"
    else
        msg "$PKGBASE-$PKGVERREL failed on $BUILDER, time cost: $TIMECOST"
    fi
}

build_package | tee all.log

if [[ "$DEBUG" == "yes" ]]; then
    exit 1
else
    # 1. mkdir for log. 2. upload. 3. parse the log
    mkdir -p $LOGPATH/$PKGBASE
    cp all.log $LOGPATH/$PKGBASE/
    parselog.py $PKGBASE
    if [[ -f $WORKDIR/$PKGBASE/PKGBUILD ]]; then
        PKGVERREL=$(source $WORKDIR/$PKGBASE/PKGBUILD; echo $epoch${epoch:+:}$pkgver-$pkgrel)
        mkdir -p $ZSTLOGDIR/$PKGBASE
        mv all.log $ZSTLOGDIR/$PKGBASE/$PKGBASE-$PKGVERREL.log
    fi
fi
