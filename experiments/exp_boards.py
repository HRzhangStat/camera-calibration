#!/usr/bin/env python3
"""D 负责：标定板1 vs 标定板2 对比实验。

对比维度：
  - 图像数量、分辨率
  - 棋盘占画面比例、单格像素数
  - fx、fy、cx、cy
  - RMS 重投影误差

输出  outputs/experiments/boards_compare.csv
      outputs/experiments/boards_compare.md   （可直接贴进报告）

用法:
    python experiments/exp_boards.py
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "experiments"
OUTPUTS = ROOT / "outputs"


def board_stats(calib_path: Path, corners_path: Path) -> dict:
    """汇总一块板的统计量。TODO(D): 实现。"""
    raise NotImplementedError


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board2-calib", type=Path, default=OUTPUTS / "calib.json")
    ap.add_argument("--board1-calib", type=Path, default=OUTPUTS / "calib_board1.json")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    # TODO(D):
    #   1. 两块板各自跑一次标定（板1 需要先确认角点数）
    #   2. 汇总统计量，写 csv
    #   3. 生成 md 表 + 一段差异分析文字
    #   4. 加分项：用同样的去畸变参数对比两块板的校正效果
    print("TODO(D): 板1 vs 板2 对比实验")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())