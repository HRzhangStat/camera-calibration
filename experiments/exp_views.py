#!/usr/bin/env python3
"""C 负责：图像数量对精度的影响（留一法）。

思路：
  用 N-1 张图标定，用被留出的那 1 张做验证，算它的重投影误差。
  轮流把每一张留出来，得到 N 个"没见过"的误差。
  再对比"全部 N 张一起标定"的 RMS。

这个实验能直接回答报告里最容易被问的问题：
  "只有 3~4 张图，够不够？"

输出  outputs/experiments/views_<board>.csv
      outputs/experiments/views_<board>.png

用法:
    python experiments/exp_views.py --corners outputs/corners.json
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "experiments"


def calibrate(objpoints, imgpoints, size, flags=0):
    """TODO(C): 实现。"""
    raise NotImplementedError


def reprojection_rms(K, dist, rvec, tvec, objp, imgp):
    """TODO(C): 用 projectPoints 算单张图误差。"""
    raise NotImplementedError


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corners", type=Path, default=ROOT / "outputs" / "corners.json")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    # TODO(C):
    #   for 每台相机:
    #       for 每张被留出的图:
    #           用其余图标定 -> 在留出图上算误差
    #       对比 "全量标定 RMS" vs "留一验证 RMS"
    #   画图：横轴=留出的图，纵轴=误差；再画一条全量 RMS 的参考线
    print("TODO(C): 留一法实验")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())