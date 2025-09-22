#!/bin/bash

# ===== Variables you should check ======
TEMP=$HOME
LOONGREPO=${LOONGREPO:=$TEMP/loongarch-packages}
WORKDIR=${WORKDIR:=$TEMP/repos}
ZSTLOGDIR=${ZSTLOGDIR:=$TEMP/logs}
PACKAGER=${PACKAGER:="LCPU <lcpu@pku.edu.cn>"}
SCRIPTSPATH=${SCRIPTSPATH:=$TEMP/loongshot/scripts}
LOGPATH=/home/arch/loong-status/build_logs # This is for webserver
# LOCALREPO=/srv/http/build-repo
LOCALREPO=/var/tmp/build-repo

if [[ $# -lt 1 ]]; then
    echo "Usage: ${0##*/} <pkgbase> [option]"
    echo "Option:"
    echo "  --stag     Use staging repo."
    echo "  --test     Use testing repo."
    echo "  --ver      Build a specific version."
    echo "  --repo     core or extra."
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
PKGVERREL=""
CLEAN=""
BUILDER="localhost"
# workdir for the builder
BUILDPATH=/var/tmp/build-loong64-pkgs
DEBUG=""

source /usr/share/makepkg/util/message.sh
colorize

if [ ! -d "$LOONGREPO" ] || [ ! -d "$WORKDIR" ]; then
    error "Please set LOONGREPO and WORKDIR in the source code..."
    exit 1
    # mkdir -p "$LOONGREPO"
    # mkdir -p "$WORKDIR"
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
            PKGVERREL=$1
            shift
            ;;
        --repo)
            shift
            BUILDREPO=$1
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
    # packages belong only to loong
    if [[ -f $LOONGREPO/$PKGBASE/PKGBUILD ]]; then
        cp $LOONGREPO/$PKGBASE $WORKDIR/ -a
        cd $WORKDIR/$PKGBASE
        PKGNAME=$(. PKGBUILD; echo $pkgname)
    else
        # clone arch package repo
        if [[ -d $WORKDIR/$PKGBASE ]]; then
            cd $WORKDIR/$PKGBASE
            pkgctl repo switch main -f
            git pull 2>&1 || return
        else
            cd $WORKDIR 2>&1 || return
	    get-loong64-pkg $PKGBASE
            # pkgctl repo clone --protocol=https $PKGBASE 2>&1 || return
            cd $PKGBASE
        fi

        # switch to the current release tag
        PKGVER=$(echo "$PKGVERREL" | sed 's/^\(.*-[0-9]\+\)\..*$/\1/')

        if [[ ! -z "$PKGVERREL" ]]; then
            if ! pkgctl repo switch $PKGVER; then
                msg "Release tag could not be found."
                return 1
            fi
        fi
        # if [[ ! -z "$PKGVER" ]]; then
        #     if ! pkgctl repo switch ${PKGVER//:/-}; then
        #         msg "Release tag could not be found."
        #         return
        #     fi
        # fi
        # apply patch
        if [[ -d "$LOONGREPO/$PKGBASE" ]]; then
            if ! patch -Np1 -i $LOONGREPO/$PKGBASE/loong.patch; then
                msg "Fail to apply loong's patch."
                return 1
            fi
            # copy additional files
            find $LOONGREPO/$PKGBASE -type f -name "*" ! -name "loong.patch" -exec cp {} . \;
            msg "Loong's patch applied."
        fi
    fi

    echo "Checking package repo"
    if [[ -z "$BUILDREPO" ]]; then
        # BUILDREPO="extra"  # default to extra
        echo "Build repo not specified!"
	    return 1
    fi

    echo "Running pre-built fix"

    # for rust packages, $CARCH need to change to `uname -m`=loongarch64
    sed -i '/cargo fetch/s/\$CARCH\|\${CARCH}\|x86_64/`uname -m`/' PKGBUILD

    # When use cpython, $CARCH also need to chage to `uname -m`
    sed -i 's/lib\.linux-\$CARCH-\|lib\.linux-\${CARCH}-/lib.linux-`uname -m`-/g; s/lib\.linux-x86_64-cpython/lib.linux-`uname -m`-cpython/' PKGBUILD

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

    # Transferring PKGBUILD to builder machine
    STARTTIME=$SECONDS
    rsync -avzP --mkpath $WORKDIR/$PKGBASE/ $BUILDER:$BUILDPATH/$PKGBASE/ $NOKEEP --exclude=.*
    if [[ ! $? -eq 0 ]]; then
        msg "Can't copy PKGBUILD to builder."
        return 1
    fi
    
    # Start to build package
    echo "Sending build command"
    ssh $BUILDER "cd $BUILDPATH/$PKGBASE; PACKAGER=\"$PACKAGER\" extra$TESTING-loong64-build $CLEAN -- -- -A -L $EXTRAARG"
    EXITCODE=$?

    ENDTIME=$SECONDS
    TIMECOST=$((ENDTIME - STARTTIME))

    # add the zst file to the local-repo
    if [[ "$EXITCODE" -eq 0 ]] && [[ ! "$DEBUG" == "yes" ]]; then
        (source PKGBUILD;
        if [[ "$arch" == "any" ]]; then
            ARCH="any"
        else
            ARCH="loong64"
        fi

        mkdir -p $LOCALREPO/$BUILDREPO/debug-pool
        cd $LOCALREPO/$BUILDREPO

        # All packages
    	FILENAME="*.pkg.tar.zst"
        # Only debug packages
        DEBUGPKG=$PKGBASE-debug-$PKGVERREL-loong64.pkg.tar.zst
	    if [ "$BUILDER" = "loong1" ]; then
            echo "Signing package on loong1"
            ssh -t $BUILDER "cd $BUILDPATH/$PKGBASE && \
                for file in *.pkg.tar.zst; do \
                    rm -f \"\$file.sig\"; \
                    gpg --detach-sign \"\$file\" && echo \"\$file.sig created\" || echo \"\$file signing failed\"; \
                done"            
            scp loong1:/tmp/"$FILENAME" loong1:/tmp/"${FILENAME}.sig" .
        else # Only loong1 has the signing key
            echo "Sending package to loong1 for signing"
            scp "$BUILDER:$BUILDPATH/$PKGBASE/$FILENAME" . || echo "File copy failed";
            scp $FILENAME "loong1:/tmp/" || echo "File copy failed to loong1";
            ssh -t loong1 "cd /tmp && \
            for file in *.pkg.tar.zst; do \
                rm -f \"\$file.sig\"; \
                gpg --detach-sign \"\$file\" && echo \"\$file.sig created\" || echo \"\$file signing failed\"; \
            done"
            scp loong1:/tmp/"${FILENAME}.sig" .
            ssh -t loong1 "rm /tmp/$FILENAME{,.sig} -f"
        fi
        chmod 664 $FILENAME{,.sig}
	    mv $DEBUGPKG{,.sig} $LOCALREPO/$BUILDREPO/debug-pool
        repo-add -R $LOCALREPO/$BUILDREPO/temp-$BUILDREPO$TESTING.db.tar.gz $FILENAME
    	)

        msg "$PKGBASE-$PKGVERREL built on $BUILDER, time cost: $TIMECOST"
	else
        msg "$PKGBASE-$PKGVERREL failed on $BUILDER, time cost: $TIMECOST, exit code: $EXITCODE"
    fi
    return $EXITCODE
}

echo "Running 1build.sh"

mkdir -p $LOGPATH/$PKGBASE
build_package | tee $PKGBASE-$PKGVERREL.log
EXITCODE=${PIPESTATUS[0]}

if [[ -f $LOGPATH/$PKGBASE/$PKGBASE-$PKGVERREL.log ]]; then
    rm $LOGPATH/$PKGBASE/$PKGBASE-$PKGVERREL.log
fi
cp $PKGBASE-$PKGVERREL.log $LOGPATH/$PKGBASE/$PKGBASE-$PKGVERREL.log

if [[ "$EXITCODE" -ne 0 ]]; then
   msg "Triggering faulty, exit code: $EXITCODE"
   exit $EXITCODE
fi
# if [[ ${PIPESTATUS[0]} -eq 2 ]] || [[ "$DEBUG" == "yes" ]]; then
#     exit 1
# else
#     # 1. mkdir for log. 2. upload. 3. parse the log
#     mkdir -p $LOGPATH/$PKGBASE
#     cp all.log.$BUILDER $LOGPATH/$PKGBASE/all.log
#     parselog.py $PKGBASE
#     if [[ -f $WORKDIR/$PKGBASE/PKGBUILD ]]; then
#         PKGVERREL=$(source $WORKDIR/$PKGBASE/PKGBUILD; echo $epoch${epoch:+:}$pkgver-$pkgrel)
#         mkdir -p $ZSTLOGDIR/$PKGBASE
#         mv all.log.$BUILDER $ZSTLOGDIR/$PKGBASE/$PKGBASE-$PKGVERREL.log
#     fi
# fi
