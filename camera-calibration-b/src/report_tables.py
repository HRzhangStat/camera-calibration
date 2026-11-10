#!/usr/bin/env python3
"""E 负责：从 calib.json 生成报告用的 Markdown 表格。

输入  outputs/calib.json（可选 outputs/corners.json）
输出  outputs/tables/tables.md

用途：避免手抄数字抄错。报告里的内参表、畸变表、误差表都由本脚本生成，
      calib.json 更新后重跑一次即可。

用法:
    python src/report_tables.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = ROOT / "outputs"


def intrinsic_table(cameras: dict) -> str:
    """生成内参表：相机 | fx | fy | cx | cy | RMS。"""
    raise NotImplementedError("E 同学实现：内参表")


def distortion_table(cameras: dict) -> str:
    """生成畸变系数表：相机 | k1 | k2 | p1 | p2 | k3。"""
    raise NotImplementedError("E 同学实现：畸变表")


def repoint_note(cameras: dict) -> str:
    """生成一段"参数合理性"的文字：fx/fy 比值、主点偏移等。

    这段直接贴进报告 3.1 节，属于加分内容。
    """
    raise NotImplementedError("E 同学实现：合理性描述")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--calib", type=Path, default=OUTPUTS / "calib.json")
    ap.add_argument("--out", type=Path, default=OUTPUTS / "tables" / "tables.md")
    args = ap.parse_args()

    calib = json.loads(args.calib.read_text(encoding="utf-8"))
    cameras = calib["cameras"]
    parts = [
        "## 内参矩阵\n", intrinsic_table(cameras), "",
        "## 畸变系数\n", distortion_table(cameras), "",
        "## 参数合理性\n", repoint_note(cameras), "",
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(parts), encoding="utf-8")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())