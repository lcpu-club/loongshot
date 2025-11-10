#!/bin/bash
PAGER=cat psql -U pguser -d archdb -c "select name from packages where x86_version is Null and x86_testing_version is Null and x86_staging_version is Null" | sed 's/^ //;s/\r$//;1,2d;$d' | sed '$d' > /tmp/missing.lst
# don't remove the pacakges uniqe to loong
sed -i '/loong/d;/x86_64-linux/d;/lcpu/d;/yt6801/d;/linux-4k/d;/edk2-loongarch/d;' /tmp/missing.lst

BACKUP=$(mktemp -d)
REPODIR=/srv/http/loongarch/archlinux
echo "Backup dir is $BACKUP"

cd $REPODIR/extra/os/loong64

repo-remove extra.db.tar.gz `cat /tmp/missing.lst` | tee remove.log
about_to_delete=()
for pkg in $(grep -oP "Removing existing entry '\K[^']*(?=')" remove.log); do
    about_to_delete+=($pkg)
done
if [ ! "${#about_to_delete[@]}" -eq 0 ]; then
    for file in "${about_to_delete[@]}"; do
        rm $file*.zst
        rm $file*.sig
        mv $REPODIR/pool/packages/$file*.zst $BACKUP
        mv $REPODIR/pool/packages/$file*.sig $BACKUP
    done
fi
rm remove.log
