#!/bin/bash

cd "$(dirname "$0")"
rm -rf dist
python setup.py sdist
cp -r dist ../dist
