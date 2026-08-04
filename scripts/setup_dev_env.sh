#!/bin/bash
# 涓€閿惌寤哄紑鍙戠幆澧?

set -e

echo "Setting up SUMP development environment..."

python -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"
pre-commit install

echo "Done! Run: source .venv/bin/activate"