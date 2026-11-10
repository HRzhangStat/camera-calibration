#!/usr/bin/env bash
# 创建并初始化 conda 环境（只需跑一次）
set -euo pipefail

ENV_NAME=calib
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v conda >/dev/null 2>&1; then
  echo "未找到 conda，请先安装 miniforge/miniconda" >&2
  exit 1
fi

if conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  echo "环境 $ENV_NAME 已存在，跳过创建"
else
  conda create -y -n "$ENV_NAME" python=3.10
fi

# shellcheck disable=SC1091
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "$ENV_NAME"
pip install -r "$ROOT/requirements.txt"

echo
echo "完成。使用前先激活："
echo "    conda activate $ENV_NAME"