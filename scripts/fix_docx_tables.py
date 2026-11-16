#!/usr/bin/env python3
"""给 docx 的所有表格行加 <w:cantSplit/>，避免一行被分页从中间截断。

用法：python3 scripts/fix_docx_tables.py 组X-相机标定.docx
"""
from __future__ import annotations

import os
import re
import sys
import zipfile


def _fix_row(match: re.Match) -> str:
    row = match.group(0)
    if "<w:cantSplit" in row:
        return row
    if "<w:trPr>" in row:
        # cantSplit 在 schema 中位于 trHeight / tblHeader 之前
        return row.replace("<w:trPr>", "<w:trPr><w:cantSplit/>", 1)
    return row.replace("<w:tr>", "<w:tr><w:trPr><w:cantSplit/></w:trPr>", 1)


def fix(path: str) -> None:
    tmp = path + ".tmp"
    with zipfile.ZipFile(path) as zin:
        items = [(info, zin.read(info.filename)) for info in zin.infolist()]
    out = []
    for info, data in items:
        if info.filename == "word/document.xml":
            xml = data.decode("utf-8")
            xml, n = re.subn(r"<w:tr\b.*?</w:tr>", _fix_row, xml, flags=re.S)
            data = xml.encode("utf-8")
            print(f"  已处理表格行: {n}")
        out.append((info, data))
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for info, data in out:
            zout.writestr(info, data)
    os.replace(tmp, path)


if __name__ == "__main__":
    for target in sys.argv[1:]:
        fix(target)
        print(f"  -> {target}")
