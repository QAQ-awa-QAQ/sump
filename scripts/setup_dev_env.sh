#!/bin/bash
# 一键搭建开发环境

set -e

echo "正在搭建 SUMP 开发环境..."

python -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"
pre-commit install

echo "完成！运行: source .venv/bin/activate"
