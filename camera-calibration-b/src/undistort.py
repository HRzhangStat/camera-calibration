#!/usr/bin/env python3
"""D 负责：畸变校正与对比实验。

输入  outputs/calib.json
输出  outputs/figures/undistort_<camera>_<file>_compare.png
      outputs/undistorted/<camera>/<file>

用法:
    python src/undistort.py --calib outputs/calib.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = ROOT / "outputs"


def make_compare(original: np.ndarray, undistorted: np.ndarray, out: Path) -> None:
    """左右拼接去畸变前后对比图，中间画分界线。

    TODO(D): 建议在图上叠加几条直线（比如背景里的桌子边缘、天花板格线），
             让"直线变直"的效果一眼可见。
    """
    raise NotImplementedError("D 同学实现：前后对比图")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--calib", type=Path, default=OUTPUTS / "calib.json")
    args = ap.parse_args()

    calib = json.loads(args.calib.read_text(encoding="utf-8"))
    (OUTPUTS / "figures").mkdir(parents=True, exist_ok=True)

    for camera, info in calib["cameras"].items():
        K = np.asarray(info["K"], dtype=np.float64)
        dist = np.asarray(info["dist"], dtype=np.float64)
        h, w = info["image_size"][1], info["image_size"][0]
        # 更推荐用 getOptimalNewCameraMatrix 保留更多视野
        new_K, roi = cv2.getOptimalNewCameraMatrix(K, dist, (w, h), alpha=1.0)
        print(f"[{camera}] new_K 已计算, roi={roi}")

        # TODO(D): 遍历该相机的图像，undistort 后出对比图
        #         同时实现 experiment: 标定板1 vs 标定板2 的参数对比表

    print("-> outputs/figures/undistort_*_compare.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())