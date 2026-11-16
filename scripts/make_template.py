#!/usr/bin/env python3
"""生成报告用的 docx 模板：把表格单元格字号降到 9pt，并收紧单元格间距。

pandoc 会给表格单元格套用 "Compact" 段落样式，因此只改这一个样式即可。

用法：
    python3 scripts/make_template.py
输出：
    report/template.docx（build_report.sh 会自动使用）
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "report" / "template.docx"
TMP = ROOT / "report" / ".reference.docx"


def main() -> int:
    subprocess.run(["pandoc", "-o", str(TMP), "--print-default-data-file",
                    "reference.docx"], check=True)

    with zipfile.ZipFile(TMP) as zin:
        items = [(info, zin.read(info.filename)) for info in zin.infolist()]

    out = []
    for info, data in items:
        if info.filename == "word/styles.xml":
            xml = data.decode("utf-8")
            m = re.search(r'<w:style [^>]*w:styleId="Compact"[^>]*>.*?</w:style>',
                          xml, re.S)
            if not m:
                print("未找到 Compact 样式", file=sys.stderr)
                return 1
            style = m.group(0)
            style_new = style.replace(
                '<w:spacing w:before="36" w:after="36" />',
                '<w:spacing w:before="0" w:after="0" />')
            style_new = style_new.replace(
                "</w:style>",
                '<w:rPr><w:sz w:val="18" /><w:szCs w:val="18" /></w:rPr></w:style>')
            xml = xml.replace(style, style_new)
            data = xml.encode("utf-8")
        out.append((info, data))

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zout:
        for info, data in out:
            zout.writestr(info, data)
    TMP.unlink(missing_ok=True)
    print(f"已生成模板: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())