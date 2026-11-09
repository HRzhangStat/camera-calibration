#!/usr/bin/env python3
"""C 负责：标定精度评估。

输入  outputs/calib.json + outputs/corners.json
输出  outputs/figures/eval_<camera>_errors.png
      outputs/figures/eval_<camera>_reprojection.png
      outputs/tables/eval_summary.csv

用法:
    python src/evaluate.py --calib outputs/calib.json
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = ROOT / "outputs"


def per_image_rms(corners: np.ndarray, projected: np.ndarray) -> float:
    """单张图的重投影误差（RMS，像素）。"""
    raise NotImplementedError("C 同学实现：逐图误差计算")


def plot_error_bars(camera: str, per_image: list[dict], out: Path) -> None:
    """逐图误差柱状图。TODO(C): 用 matplotlib 画。"""
    raise NotImplementedError("C 同学实现：误差柱状图")


def plot_reprojection(camera: str, image_path: Path, detected, projected, out: Path) -> None:
    """把检测到的角点与重投影点画在同一张图上。

    建议：检测点用红圈，重投影点用蓝十字，肉眼看偏移。
    """
    raise NotImplementedError("C 同学实现：重投影叠加图")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--calib", type=Path, default=OUTPUTS / "calib.json")
    ap.add_argument("--corners", type=Path, default=OUTPUTS / "corners.json")
    args = ap.parse_args()

    calib = json.loads(args.calib.read_text(encoding="utf-8"))
    corners = json.loads(args.corners.read_text(encoding="utf-8"))
    (OUTPUTS / "figures").mkdir(parents=True, exist_ok=True)
    (OUTPUTS / "tables").mkdir(parents=True, exist_ok=True)

    rows = []
    for camera, info in calib["cameras"].items():
        print(f"[{camera}] 整体 RMS = {info['rms']:.4f} px")
        # TODO(C): 读 corners，按相机筛出图，算逐图误差、出图、填 rows
        plot_error_bars(camera, info["per_image"], OUTPUTS / "figures" / f"eval_{camera}_errors.png")

    with open(OUTPUTS / "tables" / "eval_summary.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["camera", "file", "rms_px"])
        writer.writerows(rows)
    print("-> outputs/tables/eval_summary.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())