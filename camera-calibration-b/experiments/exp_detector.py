#!/usr/bin/env python3
"""A 负责：角点检测方式对比实验。

对比三种配置：
  1. cv2.findChessboardCorners（传统）
  2. cv2.findChessboardCornersSB（sector-based）
  3. SB + cv2.cornerSubPix 亚像素精化

输出  outputs/experiments/detector_<board>.csv
      outputs/experiments/detector_<board>.png

用法:
    python experiments/exp_detector.py --board board2
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "outputs" / "experiments"


def detect_classic(gray, pattern):
    """传统检测器。TODO(A): 实现。"""
    raise NotImplementedError


def detect_sb(gray, pattern):
    """SB 检测器。TODO(A): 实现。"""
    raise NotImplementedError


def refine_subpix(gray, corners):
    """亚像素精化。TODO(A): cv2.cornerSubPix。"""
    raise NotImplementedError


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", default="board2")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    # TODO(A):
    #   1. 遍历 data/<board>/ 下的每张图
    #   2. 三种方式各跑一遍，记录 成功/失败、耗时、角点坐标
    #   3. 三次重复检测同一张图，比较角点的重复性（标准差），衡量稳定性
    #   4. 写 csv + 画柱状图
    print("TODO(A): 检测器对比实验")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())