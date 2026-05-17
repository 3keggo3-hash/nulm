#!/bin/bash
set -e

ruff check .
mypy src
pytest
rm -rf dist/
python -m build
twine check dist/*
echo "Ready: twine upload dist/*"
