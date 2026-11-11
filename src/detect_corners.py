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
SB_FLAGS = cv2.CALIB_CB_EXHAUSTIVE | cv2.CALIB_CB_ACCURACY


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_image(path: Path, mode: int) -> np.ndarray | None:
    """使用字节解码，支持 Windows 上含中文的路径。"""
    try:
        encoded = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    return cv2.imdecode(encoded, mode) if encoded.size else None


def order_grid(corners: np.ndarray, pattern: tuple[int, int]) -> np.ndarray:
    """保留棋盘格拓扑，统一网格的起点和方向，然后按行展开。"""
    cols, rows = pattern
    grid = np.asarray(corners, dtype=np.float32).reshape(rows, cols, 2)
    across = (grid[:, -1] - grid[:, 0]).mean(axis=0)
    down = (grid[-1] - grid[0]).mean(axis=0)
    if cols == rows and abs(across[0]) < abs(down[0]):
        grid = grid.transpose(1, 0, 2)
        across, down = down, across
    # 竖放的非正方形标定板仍沿物理上的列方向取满 cols 个点。
    horizontal = abs(across[0]) >= abs(across[1])
    if across[0 if horizontal else 1] < 0:
        grid = grid[:, ::-1]
    if down[1 if horizontal else 0] < 0:
        grid = grid[::-1]
    return np.ascontiguousarray(grid.reshape(-1, 2))


def find_sb(gray: np.ndarray, pattern: tuple[int, int]):
    return cv2.findChessboardCornersSB(gray, pattern, flags=SB_FLAGS)


def detect_grid(gray: np.ndarray, pattern: tuple[int, int], detector=find_sb, *, source_pattern=None):
    """先检测完整棋盘，必要时均衡化重试，再取固定的连续网格。"""
    full_pattern = source_pattern if source_pattern is not None else pattern
    cols, rows = pattern
    full_cols, full_rows = full_pattern
    if full_cols < cols or full_rows < rows:
        raise ValueError("输出网格尺寸不能大于完整棋盘")
    ok, corners = detector(gray, full_pattern)
    method = "original"
    if not ok:
        ok, corners = detector(cv2.equalizeHist(gray), full_pattern)
        method = "equalized"
    if not ok:
        return None, "not_found"
    grid = order_grid(corners, full_pattern).reshape(full_rows, full_cols, 2)
    x0, y0 = (full_cols - cols) // 2, (full_rows - rows) // 2
    region = grid[y0:y0+rows, x0:x0+cols]
    return np.ascontiguousarray(region.reshape(-1, 2)), method


def detect_one(image_path: Path, pattern: tuple[int, int], *,
               source_pattern: tuple[int, int] | None = None) -> tuple[bool, np.ndarray | None]:
    """返回是否成功以及行优先的 (列数×行数, 2) 原图像素坐标。"""
    image = read_image(image_path, cv2.IMREAD_COLOR)
    if image is None:
        return False, None
    directory = image_path.resolve().parent
    if source_pattern is None and directory.parent == DATA:
        board = load_manifest(DATA / "manifest.json")["boards"].get(directory.name, {})
        if tuple(board.get("pattern") or ()) == pattern:
            source_pattern = tuple(board.get("source_pattern", pattern))
    corners, _ = detect_grid(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), pattern,
                             source_pattern=source_pattern)
    return corners is not None, corners


def draw_detection(image, pattern, corners, label: str, path: Path) -> None:
    """输出便于报告使用的角点叠加图，标出网格起止编号。"""
    height, width = image.shape[:2]
    scale = min(1.0, 1400 / max(height, width))
    if scale < 1:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    else:
        image = image.copy()
    if corners is not None:
        points = (corners * scale).astype(np.float32)
        cv2.drawChessboardCorners(image, pattern, points.reshape(-1, 1, 2), True)
        for point, number in ((points[0], "1"), (points[-1], str(len(points)))):
            x, y = np.rint(point).astype(int)
            origin = (max(3, min(x + 8, image.shape[1] - 35)), max(20, y - 9))
            cv2.putText(image, number, origin, cv2.FONT_HERSHEY_SIMPLEX, .62, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(image, number, origin, cv2.FONT_HERSHEY_SIMPLEX, .62, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.rectangle(image, (0, 0), (image.shape[1], 38), (25, 34, 49), -1)
    cv2.putText(image, label, (12, 25), cv2.FONT_HERSHEY_SIMPLEX, .62, (255, 255, 255), 1, cv2.LINE_AA)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded, png = cv2.imencode(".png", image)
    if not encoded:
        raise OSError(f"无法生成角点图: {path}")
    png.tofile(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True, choices=["board1", "board2"])
    ap.add_argument("--manifest", type=Path, default=DATA / "manifest.json")
    ap.add_argument("--out", type=Path, default=OUTPUTS / "corners.json")
    args = ap.parse_args()
    cv2.setNumThreads(2)

    manifest = load_manifest(args.manifest)
    board = manifest["boards"][args.board]
    pattern = board["pattern"]
    if pattern is None:
        raise SystemExit(f"{args.board} 的内角点数还没确认，先更新 data/manifest.json")

    pattern = (int(pattern[0]), int(pattern[1]))
    source_pattern = tuple(board.get("source_pattern", pattern))
    records = []
    for camera, files in board["cameras"].items():
        for name in files:
            path = DATA / args.board / name
            img = read_image(path, cv2.IMREAD_COLOR)
            corners = None
            h, w = 0, 0
            stage = "unreadable"
            if img is not None:
                h, w = img.shape[:2]
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                corners, stage = detect_grid(gray, pattern, source_pattern=source_pattern)
                status = f"SB {stage}" if corners is not None else "FAIL: grid not found"
                label = f"{args.board} / {camera} / {name} / {pattern[0]}x{pattern[1]} / {status}"
                figure = OUTPUTS / "figures" / f"corners_{args.board}_{camera}_{path.stem}.png"
                draw_detection(img, pattern, corners, label, figure)
            ok = corners is not None
            records.append({
                "file": path.relative_to(ROOT).as_posix(),
                "camera": camera,
                "image_size": [int(w), int(h)],
                "corners": corners.tolist() if ok else [],
                "detector": "SB",
                "ok": bool(ok),
            })
            print(f"[{'OK' if ok else 'FAIL'}] {camera:6s} {name}: {stage}")

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
