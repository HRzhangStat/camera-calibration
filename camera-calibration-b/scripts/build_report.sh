#!/usr/bin/env bash
# 把 report/*.md 按文件名顺序合并，生成最终 docx
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GROUP="${GROUP:-组X}"          # 用法: GROUP=组3 bash scripts/build_report.sh
OUT="$ROOT/${GROUP}-相机标定.docx"
TEMPLATE="$ROOT/report/template.docx"

if ! command -v pandoc >/dev/null 2>&1; then
  echo "未安装 pandoc。Ubuntu: sudo apt install pandoc" >&2
  echo "或下载: https://pandoc.org/installing.html" >&2
  exit 1
fi

mapfile -t FILES < <(ls "$ROOT"/report/[0-9]*.md 2>/dev/null | sort)
if [ ${#FILES[@]} -eq 0 ]; then
  echo "report/ 下没有找到 0*.md" >&2
  exit 1
fi

echo "合并以下文件:"
printf '  %s\n' "${FILES[@]##*/}"

ARGS=("${FILES[@]}" -o "$OUT" --toc --toc-depth=2)
if [ -f "$TEMPLATE" ]; then
  ARGS+=(--reference-doc="$TEMPLATE")
  echo "使用模板: report/template.docx"
fi

pandoc "${ARGS[@]}"
echo
echo "已生成: $OUT"