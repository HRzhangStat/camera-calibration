#!/usr/bin/env python3
"""C 负责：图像数量对精度的影响（留一法）。

思路：
  用 N-1 张图标定，用被留出的那 1 张做验证，算它的重投影误差。
  轮流把每一张留出来，得到 N 个"没见过"的误差。
  每折固定训练得到的 K/dist，用 solvePnP 估计留出图姿态，再计算 RMS。
  同时记录内参变化，对比"全部 N 张一起标定"的 RMS。

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
import json
import re
from pathlib import Path

import cv2
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent


def calibrate(objpoints, imgpoints, size, flags=0, max_iter=100, epsilon=1e-9):
    """各折独立标定，至少保留 3 张训练视图；返回 OpenCV 原生元组。"""
    if len(imgpoints) < 3:
        raise ValueError("至少需要 3 张训练图；留一法至少需要每台相机 4 张有效图")
    if len(objpoints) != len(imgpoints):
        raise ValueError("三维点和二维点的视图数不一致")
    supported = cv2.CALIB_FIX_K1 | cv2.CALIB_FIX_K2 | cv2.CALIB_FIX_K3 | cv2.CALIB_ZERO_TANGENT_DIST
    if flags < 0 or flags & ~supported:
        raise ValueError("仅支持标准五参数模型的 FIX_K1/K2/K3、ZERO_TANGENT_DIST 及其组合")
    if max_iter < 1 or not np.isfinite(epsilon) or epsilon <= 0:
        raise ValueError("max_iter 和 epsilon 必须为正数")
    result = cv2.calibrateCamera(
        objpoints, imgpoints, size, None, None, flags=flags,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, max_iter, epsilon))
    rms, K, dist, rvecs, tvecs = result
    if (not np.isfinite(rms) or not np.isfinite(K).all() or not np.isfinite(dist).all()
            or K[0, 0] <= 0 or K[1, 1] <= 0
            or any(not np.isfinite(v).all() for v in (*rvecs, *tvecs))):
        raise ValueError("标定返回非有限数值或非正焦距")
    return result


def reprojection_rms(K, dist, rvec, tvec, objp, imgp):
    """按角点二维距离计算 RMS，单位像素。"""
    projected, _ = cv2.projectPoints(objp, rvec, tvec, K, dist)
    detected = np.asarray(imgp, np.float64).reshape(-1, 2)
    projected = projected.reshape(-1, 2).astype(np.float64)
    if detected.shape != projected.shape or not len(detected):
        raise ValueError("检测角点与重投影角点数量不一致或为空")
    value = float(np.sqrt(np.mean(np.sum((detected - projected) ** 2, axis=1))))
    if not np.isfinite(value):
        raise ValueError("重投影 RMS 不是有限数值")
    return value


def _load_corners(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    pattern = data["pattern"]
    if (not isinstance(pattern, list) or len(pattern) != 2
            or any(type(v) is not int or v < 2 for v in pattern)):
        raise ValueError("pattern 必须为两个至少为 2 的整数 [列数, 行数]")
    square = float(data["square_mm"])
    if not np.isfinite(square) or square <= 0:
        raise ValueError("square_mm 必须为正数")
    if not re.fullmatch(r"[\w.-]+", data["board"]) or data["board"] in (".", ".."):
        raise ValueError("board 不能用于输出文件名")
    cols, rows = pattern
    objp = np.zeros((cols * rows, 3), np.float32)
    objp[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2) * square
    grouped, seen = {}, set()
    for rec in data["images"]:
        key = rec["camera"], rec["file"]
        if key in seen:
            raise ValueError(f"重复的角点记录: {key}")
        seen.add(key)
        if rec["ok"] is not True:
            continue
        points = np.asarray(rec["corners"], np.float32)
        size = rec["image_size"]
        if points.shape != (len(objp), 2) or not np.isfinite(points).all():
            raise ValueError(f"{rec['file']}: 角点必须为 {len(objp)}×2 个有限数值")
        if len(size) != 2 or any(type(v) is not int or v <= 0 for v in size):
            raise ValueError(f"{rec['file']}: image_size 必须为正整数 [宽, 高]")
        records = grouped.setdefault(rec["camera"], [])
        if records and size != records[0]["image_size"]:
            raise ValueError(f"{rec['camera']}: 图像分辨率不一致，不可混合标定")
        records.append(rec)
    if not grouped:
        raise ValueError("没有成功检测的图像")
    return data, objp, grouped


def run_experiment(corners_path: Path, output_dir: Path, flags=0, max_iter=100, epsilon=1e-9):
    data, objp, grouped = _load_corners(corners_path)
    rows = []
    for camera, records in grouped.items():
        image_points = [np.asarray(rec["corners"], np.float32).reshape(-1, 1, 2)
                        for rec in records]
        size = tuple(records[0]["image_size"])
        baseline, baseline_error = None, ""
        try:
            baseline = calibrate([objp] * len(records), image_points, size, flags, max_iter, epsilon)
        except (cv2.error, ValueError) as exc:
            baseline_error = str(exc)
        for index, rec in enumerate(records):
            row = {"camera": camera, "file": rec["file"], "n_total": len(records),
                   "n_train": len(records) - 1, "flags": flags, "max_iter": max_iter,
                   "epsilon": epsilon, "full_rms_px": baseline[0] if baseline else "",
                   "train_rms_px": "", "validation_rms_px": "", "fx": "", "fy": "",
                   "cx": "", "cy": "", "fx_change_pct": "", "fy_change_pct": "",
                   "status": "ok", "error": ""}
            if len(records) < 4:
                row.update(status="insufficient_views", error="留一后少于 3 张训练图，跳过此折")
            elif baseline is None:
                row.update(status="baseline_failed", error=baseline_error)
            else:
                try:
                    training = [points for i, points in enumerate(image_points) if i != index]
                    train_rms, K, dist, _, _ = calibrate(
                        [objp] * len(training), training, size, flags, max_iter, epsilon)
                    # 只拟合留出图的外参，绝不把它加入内参标定。
                    ok, rvec, tvec = cv2.solvePnP(objp, image_points[index], K, dist,
                                                flags=cv2.SOLVEPNP_ITERATIVE)
                    if not ok or not np.isfinite(rvec).all() or not np.isfinite(tvec).all():
                        raise ValueError("留出图 solvePnP 未返回有效姿态")
                    rotation, _ = cv2.Rodrigues(rvec)
                    if np.any((objp @ rotation.T + tvec.reshape(1, 3))[:, 2] <= 0):
                        raise ValueError("留出图姿态将部分棋盘点置于相机后方")
                    value = reprojection_rms(K, dist, rvec, tvec, objp, image_points[index])
                    row.update(train_rms_px=float(train_rms), validation_rms_px=value,
                               fx=float(K[0, 0]), fy=float(K[1, 1]), cx=float(K[0, 2]), cy=float(K[1, 2]),
                               fx_change_pct=float(100 * (K[0, 0] / baseline[1][0, 0] - 1)),
                               fy_change_pct=float(100 * (K[1, 1] / baseline[1][1, 1] - 1)))
                except (cv2.error, ValueError) as exc:
                    row.update(status="fold_failed", error=str(exc))
            rows.append(row)
            if row["status"] != "ok":
                print(f"WARNING {camera}/{Path(rec['file']).name}: {row['status']} {row['error']}")

    output_dir.mkdir(parents=True, exist_ok=True)
    table = output_dir / f"views_{data['board']}.csv"
    with table.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    fig, axes = plt.subplots(len(grouped), 2, figsize=(13, 4 * len(grouped)), squeeze=False)
    for (camera, _), (errors_ax, stability_ax) in zip(grouped.items(), axes):
        camera_rows = [row for row in rows if row["camera"] == camera]
        first_success = True
        for index, row in enumerate(camera_rows):
            if row["status"] == "ok":
                errors_ax.bar(index, row["validation_rms_px"], color="#3b82b4")
                stability_ax.scatter(index, row["fx_change_pct"], c="#3b82b4", marker="o",
                                     label="fx" if first_success else None)
                stability_ax.scatter(index, row["fy_change_pct"], c="#c2410c", marker="x",
                                     label="fy" if first_success else None)
                first_success = False
            else:
                errors_ax.text(index, 0.05, row["status"], rotation=90, ha="center",
                               va="bottom", transform=errors_ax.get_xaxis_transform(), fontsize=8)
        baseline_value = camera_rows[0]["full_rms_px"]
        if baseline_value != "":
            errors_ax.axhline(baseline_value, color="#c2410c", linestyle="--",
                              label="Full-data calibration RMS")
            errors_ax.legend(fontsize=8)
        if any(row["status"] == "ok" for row in camera_rows):
            stability_ax.legend()
        stability_ax.axhline(0, color="gray", linewidth=0.8)
        errors_ax.set(title=f"{camera}: leave-one-view-out (pose fitted)", ylabel="RMS (px)", ylim=(0, None))
        stability_ax.set(title=f"{camera}: focal-length stability", ylabel="Change from full-data fit (%)")
        for ax in (errors_ax, stability_ax):
            ax.set_xticks(range(len(camera_rows)), [Path(row["file"]).name for row in camera_rows],
                          rotation=25, ha="right")
            ax.set_xlabel("Held-out image")
            ax.grid(axis="y", alpha=0.2)
    fig.suptitle(f"{data['board']} | flags={flags}, max_iter={max_iter}, epsilon={epsilon:g}")
    fig.tight_layout()
    fig.savefig(table.with_suffix(".png"), dpi=150)
    plt.close(fig)
    succeeded = sum(row["status"] == "ok" for row in rows)
    print(f"-> {table}\n留一法成功 {succeeded}/{len(rows)} 折；失败/跳过见 CSV 的 status/error")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corners", type=Path, default=ROOT / "outputs" / "corners.json")
    ap.add_argument("--output-dir", type=Path, default=ROOT / "outputs",
                    help="输出根目录，CSV/PNG 写入其中的 experiments/")
    ap.add_argument("--flags", type=lambda value: int(value, 0), default=0,
                    help="与 B 对齐的 OpenCV 标定 flags 整数，可用十六进制")
    ap.add_argument("--max-iter", type=int, default=100)
    ap.add_argument("--epsilon", type=float, default=1e-9)
    args = ap.parse_args()
    cv2.setNumThreads(1)
    try:
        rows = run_experiment(args.corners, args.output_dir / "experiments",
                              args.flags, args.max_iter, args.epsilon)
    except (OSError, ValueError, KeyError, TypeError, cv2.error) as exc:
        ap.exit(2, f"留一法实验失败: {exc}\n")
    return 0 if all(row["status"] == "ok" for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
