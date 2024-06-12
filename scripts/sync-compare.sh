#!/bin/bash
#
# Copy package database from loong server and compare with the x86_64 repo
# Will change to copy from our TIER0 server when ready.

sudo pacman -Sy

ssh loong "sudo pacman -Sy"
LOONGDB=$(mktemp -d)
scp loong:/var/lib/pacman/sync/core.db $LOONGDB
scp loong:/var/lib/pacman/sync/extra.db $LOONGDB
sudo cp $LOONGDB/core.db /var/lib/pacman/sync/loong64-core.db
sudo cp $LOONGDB/extra.db /var/lib/pacman/sync/loong64-extra.db
sudo chmod go+r /var/lib/pacman/sync/*.db
./compare.py
