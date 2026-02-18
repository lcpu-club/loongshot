#!/bin/bash

REPODIR="/srv/http/loongarch/archlinux"
BACKUP=$(mktemp -d)
REPOS=("core" "extra")

echo "Backup dir is $BACKUP"

for REPO in "${REPOS[@]}"; do
    echo "Processing repository: $REPO"

    # Generate the list of packages to remove for this specific repo
    # Queries packages that exist in our DB for $REPO but have no x86 equivalent
    PAGER=cat psql -U pguser -d archdb -c "select name from packages where x86_version is Null and x86_testing_version is Null and x86_staging_version is Null and repo='$REPO'" \
        | sed 's/^ //;s/\r$//;1,2d;$d' | sed '$d' > /tmp/missing_$REPO.lst

    # Filter out packages that are unique to LoongArch (should not be deleted)
    sed -i '/loong/d;/x86_64-linux/d;/lcpu/d;/yt6801/d;/linux-4k/d;/edk2-loongarch/d;/musl-x86_64/d;' /tmp/missing_$REPO.lst

    # Skip if the list is empty
    if [ ! -s /tmp/missing_$REPO.lst ]; then
        echo "No packages to remove in $REPO."
        rm "/tmp/missing_$REPO.lst"
        continue
    fi

    # Perform removal from the repository database
    pushd "$REPODIR/$REPO/os/loong64" > /dev/null

    repo-remove "$REPO.db.tar.gz" $(cat "/tmp/missing_$REPO.lst") | tee remove_$REPO.log

    # Identify and move the actual files to backup
    about_to_delete=($(grep -oP "Removing existing entry '\K[^']*(?=')" remove_$REPO.log))

    if [ "${#about_to_delete[@]}" -gt 0 ]; then
        for file in "${about_to_delete[@]}"; do
            echo "Moving $file to backup..."
            # Remove from local repo dir (symlinks)
            rm -f "$file"*.zst "$file"*.sig
            # Move actual files from pool to backup
            mv "$REPODIR/pool/packages/$file"*.zst "$BACKUP/" 2>/dev/null
            mv "$REPODIR/pool/packages/$file"*.sig "$BACKUP/" 2>/dev/null
        done
    fi

    # Cleanup temp files for this repo
    rm "remove_$REPO.log" "/tmp/missing_$REPO.lst"
    popd > /dev/null
done
