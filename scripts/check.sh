#!/usr/bin/env bash
# 本地检查：等价于 CI 做的事，提交前跑一遍
#
# 默认自动寻找装了 opencv 的 python。也可以手动指定：
#     PYTHON=~/miniforge3/envs/calib/bin/python bash scripts/check.sh
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

pick_python() {
  local cands=()
  [ -n "${PYTHON:-}" ] && cands+=("$PYTHON")
  cands+=("python3" "python" "$HOME/miniforge3/envs/calib/bin/python" "$HOME/miniforge3/bin/python")
  for c in "${cands[@]}"; do
    command -v "$c" >/dev/null 2>&1 || continue
    if "$c" -c "import cv2" >/dev/null 2>&1; then
      echo "$c"; return 0
    fi
  done
  return 1
}

PY="$(pick_python)" || {
  echo "找不到装了 opencv 的 Python。先执行："
  echo "    bash scripts/setup_env.sh && conda activate calib"
  exit 1
}
echo "使用解释器: $PY"

FAIL=0

echo "== 1. 语法检查"
if ! "$PY" -m py_compile src/*.py experiments/*.py tests/*.py; then
  echo "  语法错误"; FAIL=1
else
  echo "  OK"
fi

echo "== 2. 脚本入口检查"
ENTRY_FAIL=0
for f in src/*.py experiments/*.py; do
  if ! "$PY" "$f" --help >/dev/null 2>&1; then
    echo "  FAIL: $f --help"
    ENTRY_FAIL=1; FAIL=1
  fi
done
[ $ENTRY_FAIL -eq 0 ] && echo "  OK"

echo "== 3. 接口契约测试"
if ! "$PY" tests/test_contract.py; then
  FAIL=1
fi

echo
if [ $FAIL -ne 0 ]; then
  echo "检查未通过"
  exit 1
fi
echo "全部通过"