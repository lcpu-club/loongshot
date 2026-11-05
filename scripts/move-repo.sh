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

FROM=$(basename "$(pwd | sed 's/\/os\/loong64$//g')")
TO=$1

# destination
if [[ "$TO" == *"/"* ]]; then
    # with full path
    NEWPATH=$TO/os/loong64
    TO=$(basename "$TO")
    NEWREPO=$NEWPATH
else
    NEWREPO=$REPODIR/archlinux/$TO/os/loong64
    NEWPATH=$REPODIR/archlinux/pool/packages
fi

# NEWREPO and NEWPATH are different directories when a repo name is given:
# packages are copied into the pool and only symlinked into the repo, while
# repo-add writes into NEWREPO.  Both have to exist, checking NEWPATH alone
# lets a bogus repo name through.
if [[ ! -d $NEWPATH ]]; then
    echo "Destination path don't exist!"
    exit 1
fi

if [[ ! -d $NEWREPO ]]; then
    echo "Destination repo path don't exist!"
    exit 1
fi

if [[ "$(realpath -m "$NEWPATH")" == "$(realpath -m "$(pwd)")" ]] ||
   [[ "$(realpath -m "$NEWREPO")" == "$(realpath -m "$(pwd)")" ]]; then
    echo "The paths refer to the same directory."
    exit 1
fi

if [[ $# -gt 1 ]]; then
    shift
    ALLFILES=("$@")
else
    shopt -s nullglob
    ALLFILES=(*.zst)
    shopt -u nullglob
fi

if [[ ${#ALLFILES[@]} -eq 0 ]]; then
    echo "No *.zst file to move."
    exit 1
fi

# arrary of packages
ALLPKG=()
ALLZST=()
fcount=1

# keep track of the destination files this run creates, so that a failure
# halfway through can be undone and the staging dir stays re-runnable
CREATED=()

record_created(){
    local f
    for f in "$@"; do
        [[ -e $f ]] || CREATED+=("$f")
    done
}

rollback(){
    local f
    for f in "${CREATED[@]}"; do
        # -L matters: the repo symlinks dangle as soon as their pool file is
        # removed above, and -e is false for a dangling symlink.
        [[ -e $f || -L $f ]] || continue
        echo "Rolling back $f ..."
        rm -f "$f"
    done
    CREATED=()
}

do_move(){
    if [ "${#ALLZST[@]}" -eq 0 ]; then
        return
    fi

    # Copy first, touch the databases afterwards: failing halfway must not
    # leave the source repository without the packages it still holds.
    MOVED=()
    for i in "${!ALLZST[@]}"; do
        zst=${ALLZST[$i]}
        echo "Copying file: $zst ..."
        if [[ -L $zst ]]; then
            record_created "$NEWREPO/$zst" "$NEWREPO/$zst.sig"
            if ! cp -a "$zst"{,.sig} "$NEWREPO"; then
                rollback
                error "Failed to copy $zst to $NEWREPO"
                exit 1
            fi
        elif [[ -f $NEWPATH/$zst ]]; then
            error "$zst already there, ignore it."
            continue
        else
            record_created "$NEWPATH/$zst" "$NEWPATH/$zst.sig"
            if ! cp "$zst"{,.sig} "$NEWPATH"; then
                rollback
                error "Failed to copy $zst to $NEWPATH"
                exit 1
            fi
            if [[ $NEWPATH != "$NEWREPO" ]]; then
                record_created "$NEWREPO/$zst" "$NEWREPO/$zst.sig"
                if ! ln -sf ../../../pool/packages/"$zst"{,.sig} "$NEWREPO"; then
                    rollback
                    error "Failed to link $zst into $NEWREPO"
                    exit 1
                fi
            fi
        fi
        MOVED+=("$zst")
    done

    if [ "${#MOVED[@]}" -gt 0 ]; then
        LC_ALL=C repo-add --include-sigs -R -w "$NEWREPO/$TO.db.tar.gz" "${MOVED[@]}" | tee add.log
        exit_code=${PIPESTATUS[0]}
        if [[ ! $exit_code -eq 0 ]]; then
            rm -f add.log
            # repo-remove and repo-add don't modify the db on error, so the
            # copies can go away and the next run simply tries again.
            rollback
            echo "Error: Failed to update the repository database."
            exit 2
        fi

        about_to_delete=()
        for pkg in $(grep -oP "Removing old package file '\K[^']*(?=')" add.log); do
            about_to_delete+=("$pkg")
        done
        if [ ! "${#about_to_delete[@]}" -eq 0 ]; then
            for file in "${about_to_delete[@]}"; do
                echo "Deleting $file ..."
                # https://gitlab.archlinux.org/pacman/pacman/-/work_items/335
                rm -f "$NEWREPO/$file"{,.sig}
                rm -f "$NEWPATH/$file"{,.sig}
            done
        fi
        rm -f add.log
    fi
    CREATED=()

    if [[ -f $FROM.db.tar.gz ]]; then
        if ! repo-remove "$FROM.db.tar.gz" "${ALLPKG[@]}"; then
            warning "Failed to remove packages from $FROM.db.tar.gz."
        fi
    fi

    for zst in "${MOVED[@]}"; do
        echo "Deleting file: $zst ..."
        rm -f "$zst"{,.sig}
    done

    fcount=1
    ALLZST=()
    ALLPKG=()
}

for pkg in "${ALLFILES[@]}"; do
    if [[ ! -f $pkg ]]; then
        error "$pkg not found."
        exit 1
    fi
    ((fcount++))
    if [[ ! -f $pkg.sig ]]; then
        echo "Signing $pkg ..."
        gpg --detach-sign "$pkg" || exit 1
    fi
    if ! chmod 664 "$pkg"{,.sig}; then
        error "Failed to chmod $pkg"
        exit 1
    fi
    ALLZST+=("$pkg")
    j=${pkg%-*}
    k=${j%-*}
    ALLPKG+=("${k%-*}")
    if [[ $fcount -gt 100 ]]; then
        do_move
    fi
done
do_move
