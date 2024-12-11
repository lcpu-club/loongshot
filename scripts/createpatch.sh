#!/bin/bash
#
# Create patch based on current edition

LOONGREPO=${LOONGREPO:=$HOME/loongarch-packages}
PKG=$(basename $PWD)

mkdir -p $LOONGREPO/$PKG
git diff | tail -n +3 > $LOONGREPO/$PKG/loong.patch
