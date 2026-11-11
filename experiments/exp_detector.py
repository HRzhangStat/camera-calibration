#!/usr/bin/env python3
"""比较传统角点、SB 以及 SB 后再做 cornerSubPix。

用法: python experiments/exp_detector.py --board board2
输出: outputs/experiments/detector_<board>{.csv,_summary.csv,.png}
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter

import cv2
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "outputs" / "experiments"
# 这两个脚本同属 A。其他角色只通过文件读取 A 的产物。
sys.path.insert(0, str(ROOT))
from src.detect_corners import detect_grid, find_sb, load_manifest, read_image

METHODS = ("Classic", "SB", "SB + SubPix")
REPEATS = 3
VARIANTS = ("dark", "blur")


def detect_classic(gray, pattern):
    flags = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE
    return cv2.findChessboardCorners(gray, pattern, flags=flags)


def detect(method, gray, pattern, source_pattern):
    detector = detect_classic if method == "Classic" else find_sb
    corners, stage = detect_grid(gray, pattern, detector, source_pattern=source_pattern)
    if method == "SB + SubPix" and corners is not None:
        criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 30, .001)
        points = corners.reshape(-1, 1, 2).copy()
        corners = cv2.cornerSubPix(gray, points, (5, 5), (-1, -1), criteria).reshape(-1, 2)
    return corners, stage


def point_rms(delta):
    return float(np.sqrt(np.mean(np.sum(delta ** 2, axis=-1))))


def measure(gray, perturbed, pattern, source_pattern, method):
    result = {
        "ok": False, "raw_ok": False, "preprocessing": "unreadable",
        "median_ms": None, "repeats_ok": 0, "repeatability_px": None,
        "dark_rms_px": None, "blur_rms_px": None, "corners_json": "[]",
    }
    if gray is None:
        return result

    samples, timings = [], []
    for _ in range(REPEATS):
        start = perf_counter()
        samples.append(detect(method, gray, pattern, source_pattern))
        timings.append((perf_counter() - start) * 1000)
    baseline, stage = samples[0]
    repeats = [points for points, _ in samples if points is not None]
    result.update(ok=baseline is not None, raw_ok=stage == "original", preprocessing=stage,
                  median_ms=median(timings), repeats_ok=len(repeats))
    if len(repeats) == REPEATS:
        stack = np.asarray(repeats, dtype=np.float64)
        result["repeatability_px"] = point_rms(stack - stack.mean(axis=0))
    if baseline is not None:
        result["corners_json"] = json.dumps(baseline.tolist())
        for name, image in perturbed.items():
            points, _ = detect(method, image, pattern, source_pattern)
            if points is not None:
                result[f"{name}_rms_px"] = point_rms(points - baseline)
    return result


def summarize(records):
    # 三种方法在原图和两种扰动下都检出的图，才进入同口径稳定性对比。
    complete = {}
    for row in records:
        if all(row[f"{variant}_rms_px"] is not None for variant in VARIANTS):
            complete.setdefault(row["file"], set()).add(row["method"])
    common = {file for file, methods in complete.items() if len(methods) == len(METHODS)}
    summary = []
    for method in METHODS:
        rows = [row for row in records if row["method"] == method]
        timing = [row["median_ms"] for row in rows if row["median_ms"] is not None]
        repeatability = [row["repeatability_px"] for row in rows if row["repeatability_px"] is not None]
        drift = [row[f"{v}_rms_px"] for row in rows if row["file"] in common for v in VARIANTS]
        summary.append({
            "method": method,
            "total_images": len(rows),
            "raw_success": sum(row["raw_ok"] for row in rows),
            "success_after_retry": sum(row["ok"] for row in rows),
            "median_ms": median(timing) if timing else None,
            "repeatability_images": len(repeatability),
            "median_repeatability_px": median(repeatability) if repeatability else None,
            "dark_success": sum(row["dark_rms_px"] is not None for row in rows),
            "blur_success": sum(row["blur_rms_px"] is not None for row in rows),
            "common_images": len(common),
            "median_perturbation_rms_px": median(drift) if drift else None,
        })
    return summary


def write_csv(path, records):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)


def plot_summary(summary, board, path):
    x = np.arange(len(METHODS))
    colors = ("#67798A", "#245B87", "#007D7A")
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.7), layout="constrained")
    total = summary[0]["total_images"]
    axes[0].bar(x-.18, [row["raw_success"] for row in summary], .36, color="#8BA5B7", label="Original")
    axes[0].bar(x+.18, [row["success_after_retry"] for row in summary], .36, color="#245B87", label="With retry")
    axes[0].set(ylim=(0, total+1.6), title=f"Detection success (out of {total})", ylabel="Images")
    axes[0].set_yticks(range(total+1))
    axes[0].legend(frameon=False, fontsize=8, loc="upper center", ncol=2)
    for ax, key, title, unit in (
        (axes[1], "median_ms", "Median detection time", "ms"),
        (axes[2], "median_perturbation_rms_px", f"Median drift (common n={summary[0]['common_images']})", "px"),
    ):
        values = [row[key] for row in summary]
        ax.bar(x, [value or 0 for value in values], color=colors, width=.52)
        for index, value in enumerate(values):
            ax.annotate("N/A" if value is None else f"{value:.3g}", (index, value or 0),
                        xytext=(0, 3), textcoords="offset points", ha="center", fontsize=8)
        ax.set(title=title, ylabel=unit)
        ax.margins(y=.2)
    for ax in axes:
        ax.set_xticks(x, METHODS)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=.2)
        ax.set_axisbelow(True)
    fig.suptitle(f"{board}: chessboard corner detector comparison", fontweight="bold")
    fig.savefig(path, dpi=170)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", default="board2", choices=("board1", "board2"))
    args = ap.parse_args()
    cv2.setNumThreads(2)
    OUT.mkdir(parents=True, exist_ok=True)

    board = load_manifest(DATA / "manifest.json")["boards"][args.board]
    if board["pattern"] is None:
        raise SystemExit(f"{args.board} 的内角点数尚未确认")
    pattern = tuple(board["pattern"])
    source_pattern = tuple(board.get("source_pattern", pattern))
    records = []
    for camera, names in board["cameras"].items():
        for name in names:
            path = DATA / args.board / name
            image = read_image(path, cv2.IMREAD_COLOR)
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image is not None else None
            perturbed = {} if gray is None else {
                "dark": np.clip(.78 * gray.astype(np.float32) + 10, 0, 255).astype(np.uint8),
                "blur": cv2.GaussianBlur(gray, (5, 5), .9),
            }
            for method in METHODS:
                records.append({
                    "board": args.board, "file": path.relative_to(ROOT).as_posix(),
                    "camera": camera, "method": method,
                    **measure(gray, perturbed, pattern, source_pattern, method),
                })
            print(f"[{args.board}] {camera:6s} {name}", flush=True)
    prefix = OUT / f"detector_{args.board}"
    summary = summarize(records)
    write_csv(prefix.with_suffix(".csv"), records)
    write_csv(OUT / f"detector_{args.board}_summary.csv", summary)
    plot_summary(summary, args.board, prefix.with_suffix(".png"))
    for row in summary:
        print(f"{row['method']}: {row['raw_success']} original, "
              f"{row['success_after_retry']}/{row['total_images']} with retry")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
