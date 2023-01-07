#!/bin/bash
set -e
git push
rm -rf dist

poetry build

if [[ -z $1 ]]; then
    echo "doing test release (pass a version to do official release)"
    poetry publish -r testpypi
else
    echo "doing official release"
    poetry publish
    git tag "$1"
    git push --tags
fi
