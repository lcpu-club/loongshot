#!/bin/bash
#
# Initialize the build_staus's table with arch repo.

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <directory> <url>"
    exit 1
fi

# directory of the arch repo
REPO=$1
# build_status's url
URL=$2

if [ ! -d "$REPO" ]; then
    echo "Error: $REPO is not a directory."
    exit 1
fi

for repo in core extra;
do
    for pkg in $REPO/$repo/*;
    do
        echo $pkg
        name=${pkg##*/}
        data=$(. $pkg/PKGBUILD; echo "version=$pkgver&release=$pkgrel")
        curl -X POST $URL/add -d "name=$name&$data&repo=$repo&build_status=void"
    done
done
