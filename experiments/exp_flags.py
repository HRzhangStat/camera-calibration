#!/usr/bin/env python3
"""B 负责：标定参数（flags）对比实验。

对比以下几组 cv2.calibrateCamera 的 flags：
  A. 默认（解 k1 k2 p1 p2 k3）
  B. cv2.CALIB_FIX_K3        （只解 k1 k2）
  C. cv2.CALIB_ZERO_TANGENT_DIST（假设无切向畸变）
  D. B + C 组合

输出  outputs/experiments/flags_<board>.csv
      outputs/experiments/flags_<board>.md   （可直接贴进报告）

用法:
    python experiments/exp_flags.py --corners outputs/corners.json
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "experiments"

VARIANTS = {
    "default": 0,
    "fix_k3": cv2.CALIB_FIX_K3,
    "zero_tangent": cv2.CALIB_ZERO_TANGENT_DIST,
    "fix_k3+zero_tangent": cv2.CALIB_FIX_K3 | cv2.CALIB_ZERO_TANGENT_DIST,
}


def calibrate_variant(objpoints, imgpoints, size, flags):
    """调用 calibrateCamera。TODO(B): 实现。"""
    raise NotImplementedError


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corners", type=Path, default=ROOT / "outputs" / "corners.json")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    # TODO(B):
    #   1. 读 corners.json，按相机分组
    #   2. 对每组、每个 VARIANTS 跑一次标定
    #   3. 记录 fx/fy/cx/cy/rms，写 csv
    #   4. 生成 md 表，并在报告里说明"我们为什么选这一组"
    print("TODO(B): flags 对比实验")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())