#!/usr/bin/env python3
"""B 负责：单目相机标定。

输入  outputs/corners.json
输出  outputs/calib.json

接口见 README「接口约定」一节。字段名不要私自改。

用法:
    python src/calibrate.py --corners outputs/corners.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = ROOT / "outputs"


def build_object_points(pattern: tuple[int, int], square_mm: float) -> np.ndarray:
    """生成棋盘格的三维点，形状 (N, 3)，Z 全为 0。

    顺序必须和 corners.json 里的角点顺序一致：行优先。
    """
    cols, rows = pattern
    objp = np.zeros((cols * rows, 3), np.float32)
    grid = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2)
    objp[:, :2] = grid * square_mm
    return objp


def calibrate_camera(objpoints, imgpoints, image_size):
    """调用 cv2.calibrateCamera。

    TODO(B): 实现标定，返回 (K, dist, rms, rvecs, tvecs)。
             注意 experiment：试试不同的 flags，例如
             cv2.CALIB_FIX_K3 / cv2.CALIB_ZERO_TANGENT_DIST，
             并在报告里说明选择理由。
    """
    raise NotImplementedError("B 同学实现：标定")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corners", type=Path, default=OUTPUTS / "corners.json")
    ap.add_argument("--out", type=Path, default=OUTPUTS / "calib.json")
    args = ap.parse_args()

    data = json.loads(args.corners.read_text(encoding="utf-8"))
    pattern = tuple(data["pattern"])
    square_mm = float(data["square_mm"])
    objp = build_object_points(pattern, square_mm)

    # 按相机分组
    by_camera: dict[str, list[dict]] = {}
    for rec in data["images"]:
        if rec["ok"]:
            by_camera.setdefault(rec["camera"], []).append(rec)

    cameras = {}
    for camera, records in by_camera.items():
        image_size = tuple(records[0]["image_size"])
        objpoints = [objp for _ in records]
        imgpoints = [np.asarray(r["corners"], dtype=np.float32).reshape(-1, 1, 2)
                     for r in records]
        K, dist, rms, rvecs, tvecs = calibrate_camera(objpoints, imgpoints, image_size)
        cameras[camera] = {
            "image_size": list(image_size),
            "K": np.asarray(K).tolist(),
            "dist": np.asarray(dist).ravel().tolist(),
            "rms": float(rms),
            "per_image": [
                {
                    "file": r["file"],
                    "rms": None,  # TODO(B): 逐图重投影误差
                    "rvec": np.asarray(rv).ravel().tolist(),
                    "tvec": np.asarray(tv).ravel().tolist(),
                }
                for r, rv, tv in zip(records, rvecs, tvecs)
            ],
        }
        print(f"[{camera}] RMS = {rms:.4f} px  ({len(records)} 张)")

    result = {
        "board": data["board"],
        "pattern": list(pattern),
        "square_mm": square_mm,
        "cameras": cameras,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())