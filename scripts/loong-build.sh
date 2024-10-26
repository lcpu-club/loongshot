#!/bin/bash

# ===== Variables you should check ======
LOONGREPO=${LOONGREPO:=/home/arch/loongarch-packages}
WORKDIR=${WORKDIR:=/home/arch/repos}
PACKAGER=${PACKAGER:="John Doe <john@doe.com>"}
SCRIPTSPATH=${SCRIPTSPATH:=/home/arch/loongshot/scripts}
LOCALREPO=${LOCALREPO:=/home/arch/local-repo/} # always copy zst to local-repo
TIER0=tier0

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
    echo "  --uplog    JUST upload former log file without building."
    echo "  --         Options after this will be passed to makepkg."
    exit 1
fi

export LC_ALL=en_US.UTF-8

PKGBASE=$1
shift

TESTING="-local" # use extra-local-loong64-build by default
PKGVER=""
CLEAN=""
BUILDER="localhost"
BUILDPATH="/home/arch/repos"
DEBUG=""
UPLOG=""

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
        --uplog)
            UPLOG="only"
            shift
            ;;
        --builder)
            shift
            BUILDER=${1%:*}
            BUILDPATH=${1#*:}
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
        if [[ ! -z $NOKEEP ]]; then
            rm $WORKDIR/$PKGBASE -rf
        fi
        cp $LOONGREPO/$PKGBASE $WORKDIR/ -a
    else
        # clone arch package repo
        if [[ -d $WORKDIR/$PKGBASE ]]; then
            cd $WORKDIR/$PKGBASE
            pkgctl repo switch main -f
            git pull || exit 1
            if [[ ! -z $NOKEEP ]]; then
                # delete all untracked files
                git clean -fdx
            fi
        else
            cd $WORKDIR || exit 1
            pkgctl repo clone --protocol=https $PKGBASE || exit 1
            cd $PKGBASE
        fi

        if [[ -z "$PKGVER" ]]; then
            # get the release tag from x86_64's repo
            PKGVER=`$SCRIPTSPATH/compare86.py -Sp $PKGBASE |grep x86_64|awk -F= '{print $2}'`
        fi

        # switch to the current release tag
        if [[ ! -z "$PKGVER" ]]; then
            if ! pkgctl repo switch ${PKGVER//:/-}; then
                error "Release tag could not be found."
                exit 1
            fi
        fi
        # apply patch
        if [[ -d "$LOONGREPO/$PKGBASE" ]]; then
            if ! patch -Np1 -i $LOONGREPO/$PKGBASE/loong.patch; then
                error "Fail to apply loong's patch."
                exit 1
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
    _PKGVER=$(ssh $TIER0 -t "findpkg.py $PKGNAME" 2>/dev/null | tr -d '\r')
    if [[ ! -z "$_PKGVER" ]] && [[ "$_PKGVER" == "$PKGVERREL"* ]]; then
        # Same package found in server. Incrementing point pkgrel...
        PKGREL=${_PKGVER#*-}
        PKGREL=$(echo $PKGREL + .1 | bc)
        sed -i "s/^pkgrel=.*/pkgrel=$PKGREL/" PKGBUILD
        PKGVERREL=${PKGVERREL%-*}-$PKGREL
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
    if [[ "$BUILDER" == "localhost" ]]; then
        PACKAGER="$PACKAGER" extra$TESTING-loong64-build $CLEAN -- -- -A -L $EXTRAARG
        EXITCODE=$?
    else
        rsync -avzP $WORKDIR/$PKGBASE/ $BUILDER:$BUILDPATH/$PKGBASE/ $NOKEEP --exclude=.*
        if [[ ! $? -eq 0 ]]; then
            error "Can't copy PKGBUILD to builder."
            exit 1
        fi
        ssh -t $BUILDER "cd /home/arch/repos/$PKGBASE; PACKAGER=\"$PACKAGER\" extra$TESTING-loong64-build -- -- -A -L $EXTRAARG" 2>/dev/null
        EXITCODE=$?

        # sync back generated zst files
        rsync -avzP $BUILDER:$BUILDPATH/$PKGBASE/*.zst $WORKDIR/$PKGBASE/
    fi
    ENDTIME=$SECONDS
    TIMECOST=$((ENDTIME - STARTTIME))

    # add the zst file to the local-repo
    if [[ -z "$DEBUG"  ]]; then
        (source PKGBUILD;
        if [[ "$arch" == "any" ]]; then
            ARCH="any"
        else
            ARCH="loong64"
        fi
        for pkg in ${pkgname[@]}; do
            if [[ "$BUILDER" == "localhost" ]]; then
                cp $pkg-$PKGVERREL-$ARCH.pkg.tar.zst $LOCALREPO/os/loong64/
                repo-add -R $LOCALREPO/os/loong64/local-repo.db.tar.gz $pkg-$PKGVERREL-$ARCH.pkg.tar.zst
            else
                scp "./$pkg-$PKGVERREL-$ARCH.pkg.tar.zst" $BUILDER:$LOCALREPO/os/loong64/
                ssh -t $BUILDER "cd $LOCALREPO/os/loong64; repo-add -R local-repo.db.tar.gz $pkg-$PKGVERREL-$ARCH.pkg.tar.zst"
            fi
        done)
    fi
    if [[ "$BUILDER" == "localhost" ]]; then
        BUILDER=$(hostname) # save the hostname in log
    fi
    if [[ $EXITCODE -eq 0 ]]; then
        msg "$PKGBASE-$PKGVERREL built on $BUILDER, time cost: $TIMECOST"
    else
        msg2 "$PKGBASE-$PKGVERREL failed on $BUILDER, time cost: $TIMECOST"
    fi
}

# after debuging, maybe you just want to upload the log without rebuilding.
if [[ ! -z "UPLOG" ]]; then
    build_package | tee all.log
fi

if [[ "$DEBUG" == "yes" ]]; then
    exit 1
else
    LOGPATH=/home/arch/loong-status/build_logs

    # 1. mkdir for log. 2. upload. 3. parse the log
    ssh -t $TIER0 "mkdir -p $LOGPATH/$PKGBASE" && scp all.log $TIER0:$LOGPATH/$PKGBASE/ && ssh -t $TIER0 "parselog.py $PKGBASE"
    # rename the log and move to the working directory
    LOGNAME=$(tail -1 all.log | awk '{print $2}')
    mv all.log $WORKDIR/$PKGBASE/"$LOGNAME.log"
fi
