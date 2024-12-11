#!/bin/bash

SCRIPTSPATH=${SCRIPTSPATH:-$HOME/loongshot/scripts}
TIER0=${TIER0:-""}

if [[ ! -z "$TIER0" ]]; then
    echo $TIER0
    ssh -t $TIER0 "$SCRIPTSPATH/dbcmd.py $@"
else
    $SCRIPTSPATH/dbcmd.py $@
fi
