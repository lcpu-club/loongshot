#!/bin/bash
#
# Create patch based on current edition
#
# Sanity checks before writing $LOONGREPO/$PKG/loong.patch:
#   1. PKGBUILD must exist in the current directory.
#   2. pkgrel must not be modified, the build scripts bump it themselves.
#   3. Local files in the source arrays (patches and friends) are synced into
#      $LOONGREPO/$PKG: missing ones are copied in, and files no longer
#      referenced by the source arrays are removed, so the build copies
#      exactly what the PKGBUILD asks for.

LOONGREPO=${LOONGREPO:=$HOME/loongarch-packages}
PKG=$(basename "$PWD")

die() {
    echo "${0##*/}: error: $*" >&2
    exit 1
}

# 1. PKGBUILD must be here.
[[ -f PKGBUILD ]] || die "no PKGBUILD found in $PWD."

# The patch is a git diff, so PKGBUILD must be tracked and HEAD is the base.
git rev-parse --is-inside-work-tree >/dev/null 2>&1 ||
    die "not a git repository, nothing to create a patch from."
git ls-files --error-unmatch -- PKGBUILD >/dev/null 2>&1 ||
    die "PKGBUILD is not tracked by git, nothing to create a patch from."

# 2. pkgrel belongs to the build scripts, it must not be part of the patch.
PKGRELDIFF=$(git diff -U0 HEAD -- PKGBUILD | grep -E '^[+-][[:space:]]*pkgrel=')
if [[ -n $PKGRELDIFF ]]; then
    echo "$PKGRELDIFF" >&2
    die "pkgrel must not be modified, revert it before creating the patch."
fi

# Print every entry of the source arrays (source, source_x86_64, ...) of a
# PKGBUILD.  The file is sourced in a subshell so that variable references
# such as ${pkgname} or ${pkgver} are expanded.
list_sources() {
    (
        set +u
        source "$1" >/dev/null 2>&1 || exit 0
        local var
        for var in $(compgen -A variable); do
            [[ $var == source || $var == source_* ]] || continue
            [[ $(declare -p "$var" 2>/dev/null) == "declare -a"* ]] || continue
            eval "for e in \"\${$var[@]}\"; do printf '%s\n' \"\$e\"; done"
        done
    ) | sort -u
}

# Return true if the source entry is downloaded by makepkg.
is_remote() {
    local scheme=${1%%://*}
    case $1 in
        *://*)
            scheme=${scheme##*+}
            [[ ${scheme,,} == file ]] && return 1
            return 0
            ;;
        git+*|svn+*|hg+*|bzr+*) return 0 ;;
    esac
    return 1
}

mkdir -p "$LOONGREPO/$PKG"

# 3. Local source files (patches and friends) live in $LOONGREPO/$PKG.
LOCAL=()
while IFS= read -r entry; do
    [[ -n $entry ]] || continue
    is_remote "$entry" && continue
    # Strip the "name::" prefix and the file:// scheme of local paths.
    entry=${entry##*::}
    entry=${entry#file://}
    entry=${entry#./}
    LOCAL+=("$entry")
done < <(list_sources "$PWD/PKGBUILD")

# Copy in what the PKGBUILD asks for but the target directory lacks.
COPIED=()
for entry in ${LOCAL[@]+"${LOCAL[@]}"}; do
    [[ -e $LOONGREPO/$PKG/$entry ]] && continue
    [[ -f $entry ]] || die "$entry is in source but neither here nor in $LOONGREPO/$PKG."
    cp -- "$entry" "$LOONGREPO/$PKG/$entry" || die "cannot copy $entry into $LOONGREPO/$PKG."
    COPIED+=("$entry")
done

# Drop everything the PKGBUILD no longer references, loong.patch aside.
REMOVED=()
while IFS= read -r file; do
    rel=${file#"$LOONGREPO/$PKG/"}
    [[ $rel == loong.patch ]] && continue
    printf '%s\n' ${LOCAL[@]+"${LOCAL[@]}"} | grep -Fxq -- "$rel" || REMOVED+=("$rel")
done < <(find "$LOONGREPO/$PKG" -type f)
for rel in ${REMOVED[@]+"${REMOVED[@]}"}; do
    rm -f -- "$LOONGREPO/$PKG/$rel" || die "cannot remove $LOONGREPO/$PKG/$rel."
done

if (( ${#COPIED[@]} )); then
    echo "Copied into $LOONGREPO/$PKG:"
    printf '  %s\n' "${COPIED[@]}"
fi
if (( ${#REMOVED[@]} )); then
    echo "Removed from $LOONGREPO/$PKG:"
    printf '  %s\n' "${REMOVED[@]}"
fi

git diff | tail -n +3 > $LOONGREPO/$PKG/loong.patch
