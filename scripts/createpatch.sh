#!/bin/bash
#
# Create patch based on current edition
#
# Sanity checks before writing $LOONGREPO/$PKG/loong.patch:
#   1. PKGBUILD must exist in the current directory.
#   2. pkgrel must not be modified, the build scripts bump it themselves.
#   3. Files added to the source arrays must be remote URLs, otherwise
#      they have to exist in $LOONGREPO/$PKG so the build can copy them in.

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

OLDPKGBUILD=$(mktemp) || die "cannot create a temporary file."
trap 'rm -f "$OLDPKGBUILD"' EXIT
git show HEAD:./PKGBUILD >"$OLDPKGBUILD" 2>/dev/null || : >"$OLDPKGBUILD"

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

mkdir -p $LOONGREPO/$PKG

# 3. New source files must be shipped in $LOONGREPO/$PKG.
ADDED=$(comm -13 \
    <(list_sources "$OLDPKGBUILD") \
    <(list_sources "$PWD/PKGBUILD"))
MISSING=()
while IFS= read -r entry; do
    [[ -n $entry ]] || continue
    is_remote "$entry" && continue
    # Strip the "name::" prefix and the file:// scheme of local paths.
    entry=${entry##*::}
    entry=${entry#file://}
    [[ -f $LOONGREPO/$PKG/$entry ]] || MISSING+=("$entry")
done <<<"$ADDED"

if (( ${#MISSING[@]} )); then
    echo "These files added to source are missing in $LOONGREPO/$PKG:" >&2
    printf '  %s\n' "${MISSING[@]}" >&2
    die "copy them into $LOONGREPO/$PKG before creating the patch."
fi

git diff | tail -n +3 > $LOONGREPO/$PKG/loong.patch
