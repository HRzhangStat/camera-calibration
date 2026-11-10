#!/usr/bin/env python3
"""A 负责：棋盘格内角点检测。

输入  data/manifest.json + data/<board>/ 下的图像
输出  outputs/corners.json

接口见 README「接口约定」一节。字段名不要私自改。

用法:
    python src/detect_corners.py --board board2
    python src/detect_corners.py --board board1 --out outputs/corners_board1.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUTPUTS = ROOT / "outputs"


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def detect_one(image_path: Path, pattern: tuple[int, int]) -> tuple[bool, np.ndarray | None]:
    """对单张图做角点检测。

    TODO(A): 用 cv2.findChessboardCornersSB 实现，建议开启
             cv2.CALIB_CB_EXHAUSTIVE | cv2.CALIB_CB_ACCURACY
             再配合 cv2.cornerSubPix 做亚像素精化。

    返回 (是否成功, 形状为 (pattern[0]*pattern[1], 2) 的 float32 数组)
    顺序必须是行优先：先第一行从左到右，再第二行……
    """
    raise NotImplementedError("A 同学实现：角点检测")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True, choices=["board1", "board2"])
    ap.add_argument("--manifest", type=Path, default=DATA / "manifest.json")
    ap.add_argument("--out", type=Path, default=OUTPUTS / "corners.json")
    args = ap.parse_args()

    manifest = load_manifest(args.manifest)
    board = manifest["boards"][args.board]
    pattern = board["pattern"]
    if pattern is None:
        raise SystemExit(f"{args.board} 的内角点数还没确认，先更新 data/manifest.json")

    pattern = (int(pattern[0]), int(pattern[1]))
    records = []
    for camera, files in board["cameras"].items():
        for name in files:
            path = DATA / args.board / name
            img = cv2.imread(str(path))
            if img is None:
                raise SystemExit(f"读不到图像: {path}")
            ok, corners = detect_one(path, pattern)
            h, w = img.shape[:2]
            records.append({
                "file": str(path.relative_to(ROOT)),
                "camera": camera,
                "image_size": [int(w), int(h)],
                "corners": corners.reshape(-1, 2).tolist() if ok else [],
                "detector": "SB",
                "ok": bool(ok),
            })
            print(f"[{'OK ' if ok else 'FAIL'}] {camera:6s} {name}")

    result = {
        "board": args.board,
        "pattern": list(pattern),
        "square_mm": board["square_mm"],
        "images": records,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    ok_n = sum(r["ok"] for r in records)
    print(f"\n成功 {ok_n}/{len(records)} 张 -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())