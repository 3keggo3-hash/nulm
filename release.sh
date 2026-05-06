#!/bin/bash
set -e

ruff check .
mypy src
pytest
python -m build
twine check dist/*
echo "Ready: twine upload dist/*"
