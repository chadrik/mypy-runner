#!/bin/bash
set -e
rm -rf dist
python3 setup.py sdist bdist_wheel

if [[ -z $1 ]]; then
    echo "doing test release (pass any arg to do official release)"
    twine upload --repository-url https://test.pypi.org/legacy/ dist/*
else
    echo "doing official release"
    twine upload dist/*
fi
