#!/bin/bash

PAGER=cat psql -U pguser -d archdb -c "select name from packages where x86_version is Null" | sed 's/^ //;s/\r$//;1,2d;$d' | sed '$d' > /tmp/missing.lst

# don't remove the pacakges uniqe to loong
sed -i '/loong/d;/x86_64-linux/d;/lcpu/d;/yt6801/d' /tmp/missing.lst

BACKUP=$(mktemp -d)
echo "Backup dir is $BACKUP"

cd /srv/http/loongarch/archlinux/extra/os/loong64

for i in `cat /tmp/missing.lst`; do
    FILE=$(repo-remove extra.db.tar.gz $i | grep Removing | sed -n "s/.*'\(.*\)'.*/\1/p")
    if [[ ! -z "$FILE" ]]; then
        mv $FILE*.zst $BACKUP
        mv $FILE*.sig $BACKUP
    fi
done
