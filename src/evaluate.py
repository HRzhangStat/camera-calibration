#!/usr/bin/env python3
"""C 负责：标定精度评估。

输入  outputs/calib.json + outputs/corners.json
输出  outputs/figures/eval_<camera>_errors.png
      outputs/figures/eval_<camera>_reprojection.png
      outputs/tables/eval_summary.csv

用法（在仓库根目录运行）:
    python src/evaluate.py --calib outputs/calib.json
    python src/evaluate.py --demo  # 显式生成模拟输入，输出到 outputs/demo/
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
OUTPUTS = ROOT / "outputs"


def per_image_rms(corners: np.ndarray, projected: np.ndarray) -> float:
    """sqrt(mean(dx**2 + dy**2))；兼容 (N, 2) 和 OpenCV 的 (N, 1, 2)。"""
    detected = np.asarray(corners, dtype=np.float64)
    estimated = np.asarray(projected, dtype=np.float64)
    for points in (detected, estimated):
        if points.ndim not in (2, 3) or points.shape[-1] != 2:
            raise ValueError("角点形状必须为 (N, 2) 或 (N, 1, 2)")
        if points.ndim == 3 and points.shape[1] != 1:
            raise ValueError("三维角点数组形状必须为 (N, 1, 2)")
        if not points.size or not np.isfinite(points).all():
            raise ValueError("角点必须非空且全部为有限数值")
    detected, estimated = detected.reshape(-1, 2), estimated.reshape(-1, 2)
    if detected.shape != estimated.shape:
        raise ValueError("检测点与重投影点的数量不一致")
    return float(np.sqrt(np.mean(np.sum((detected - estimated) ** 2, axis=1))))


def plot_error_bars(camera: str, per_image: list[dict], out: Path) -> None:
    """展示 C 重新计算的逐图 RMS；同一棋盘每图角点数相同。"""
    values = [rec["rms"] for rec in per_image]
    fig, ax = plt.subplots(figsize=(max(7, len(values) * 1.4), 4))
    bars = ax.bar(range(len(values)), values, color="#3b82b4")
    ax.bar_label(bars, fmt="%.4f", padding=3, fontsize=9)
    ax.axhline(np.sqrt(np.mean(np.square(values))), color="#c2410c",
               linestyle="--", label="Overall RMS (recomputed)")
    ax.set_xticks(range(len(values)), [Path(rec["file"]).name for rec in per_image],
                  rotation=25, ha="right")
    ax.set(title=f"{camera}: per-image reprojection error", ylabel="RMS (px)")
    ax.set_ylim(0, max(max(values) * 1.3, 0.01))
    ax.legend()
    ax.grid(axis="y", alpha=0.2)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def plot_reprojection(camera: str, image_path: Path, detected, projected, out: Path) -> None:
    """保留单图入口；主流程使用同一相机全部图像的拼图。"""
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError(f"无法读取图像: {image_path}")
    _plot_reprojections(camera, [{"file": str(image_path), "image": image,
                                "detected": detected, "projected": projected,
                                "rms": per_image_rms(detected, projected)}], out)


def _plot_reprojections(camera: str, records: list[dict], out: Path) -> None:
    cols = min(2, len(records))
    rows = (len(records) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(6 * cols, 3.8 * rows), squeeze=False)
    for ax, rec in zip(axes.flat, records):
        detected = np.asarray(rec["detected"]).reshape(-1, 2)
        projected = np.asarray(rec["projected"]).reshape(-1, 2)
        ax.imshow(cv2.cvtColor(rec["image"], cv2.COLOR_BGR2RGB))
        ax.scatter(detected[:, 0], detected[:, 1], s=32, facecolors="none",
                   edgecolors="red", linewidths=0.8, label="Detected")
        ax.scatter(projected[:, 0], projected[:, 1], s=24, marker="+",
                   c="blue", linewidths=0.8, label="Reprojected")
        ax.set_title(f"{Path(rec['file']).name} | RMS={rec['rms']:.4f} px", fontsize=10)
        ax.legend(loc="upper right", fontsize=8)
        ax.set_axis_off()
    for ax in axes.flat[len(records):]:
        ax.set_axis_off()
    fig.suptitle(f"{camera}: detected vs. reprojected corners")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def _object_points(data: dict) -> np.ndarray:
    pattern = data["pattern"]
    if (not isinstance(pattern, list) or len(pattern) != 2
            or any(type(v) is not int or v < 2 for v in pattern)):
        raise ValueError("pattern 必须为 [列数, 行数]，且两者均为至少 2 的整数")
    square = float(data["square_mm"])
    if not np.isfinite(square) or square <= 0:
        raise ValueError("square_mm 必须为正数")
    cols, rows = pattern
    objp = np.zeros((cols * rows, 3), np.float32)
    objp[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2) * square
    return objp


def evaluate(calib_path: Path, corners_path: Path, output_dir: Path) -> list[list]:
    """仅通过 README 约定的 JSON 交接，不 import A/B 的模块。"""
    calib = json.loads(calib_path.read_text(encoding="utf-8"))
    corners = json.loads(corners_path.read_text(encoding="utf-8"))
    objp = _object_points(corners)
    if (calib["board"] != corners["board"] or calib["pattern"] != corners["pattern"]
            or not np.isclose(float(calib["square_mm"]), float(corners["square_mm"]))):
        raise ValueError("calib.json 与 corners.json 的标定板参数不一致")
    if not calib["cameras"]:
        raise ValueError("calib.json 没有相机结果")
    detected_by_key = {}
    for rec in corners["images"]:
        key = (rec["camera"], rec["file"])
        if key in detected_by_key:
            raise ValueError(f"重复的角点记录: {key}")
        detected_by_key[key] = rec

    # 先核验所有输入，避免输入不完整时留下看似完成的图表。
    by_camera = {}
    for camera, info in calib["cameras"].items():
        if not re.fullmatch(r"[\w.-]+", camera) or camera in (".", ".."):
            raise ValueError(f"相机编号不能用于输出文件名: {camera!r}")
        K = np.asarray(info["K"], dtype=np.float64)
        dist = np.asarray(info["dist"], dtype=np.float64).reshape(-1)
        if (K.shape != (3, 3) or dist.shape != (5,) or not np.isfinite(K).all()
                or not np.isfinite(dist).all() or K[0, 0] <= 0 or K[1, 1] <= 0):
            raise ValueError(f"{camera}: K 必须为有效 3×3 矩阵，dist 必须含 5 个有限数值")
        if not info["per_image"]:
            raise ValueError(f"{camera}: per_image 为空")
        records, seen = [], set()
        for pose in info["per_image"]:
            filename = pose["file"]
            if filename in seen:
                raise ValueError(f"{camera}: 重复的外参记录 {filename}")
            seen.add(filename)
            rec = detected_by_key.get((camera, filename))
            if rec is None or rec["ok"] is not True:
                raise ValueError(f"{camera}/{filename}: 缺少成功检测的角点记录")
            points = np.asarray(rec["corners"], dtype=np.float64)
            if points.shape != (len(objp), 2) or not np.isfinite(points).all():
                raise ValueError(f"{filename}: 角点必须为 {len(objp)}×2 个有限数值")
            rvec = np.asarray(pose["rvec"], dtype=np.float64).reshape(-1)
            tvec = np.asarray(pose["tvec"], dtype=np.float64).reshape(-1)
            if (rvec.size != 3 or tvec.size != 3 or not np.isfinite(rvec).all()
                    or not np.isfinite(tvec).all()):
                raise ValueError(f"{filename}: 缺少有效 rvec/tvec，需 B 提供逐图外参")
            image = cv2.imread(str(ROOT / filename))
            if image is None:
                raise ValueError(f"无法读取原图: {filename}")
            size = list(image.shape[1::-1])
            if rec["image_size"] != size or info["image_size"] != size:
                raise ValueError(f"{filename}: 原图尺寸与 A/B 的 image_size 不一致")
            projected, _ = cv2.projectPoints(objp, rvec, tvec, K, dist)
            rms = per_image_rms(points, projected)
            records.append({"file": filename, "image": image, "detected": points,
                            "projected": projected, "rms": rms})
            supplied = pose.get("rms")
            if supplied is not None and not np.isclose(float(supplied), rms, atol=1e-3, rtol=1e-3):
                print(f"WARNING {camera}/{filename}: B 的 RMS={supplied}，C 重算={rms:.6f}")
        by_camera[camera] = records

    rows = []
    for camera, records in by_camera.items():
        overall = float(np.sqrt(np.mean([rec["rms"] ** 2 for rec in records])))
        supplied = calib["cameras"][camera]["rms"]
        print(f"[{camera}] C 重算整体 RMS={overall:.6f} px；B 提供 RMS={supplied}")
        if supplied is not None and not np.isclose(float(supplied), overall, atol=1e-3, rtol=1e-3):
            print(f"WARNING {camera}: 整体 RMS 不一致，请核对上游误差定义与图像集合")
        plot_error_bars(camera, records, output_dir / "figures" / f"eval_{camera}_errors.png")
        _plot_reprojections(camera, records,
                            output_dir / "figures" / f"eval_{camera}_reprojection.png")
        rows.extend([camera, rec["file"], rec["rms"]] for rec in records)
    table = output_dir / "tables" / "eval_summary.csv"
    table.parent.mkdir(parents=True, exist_ok=True)
    with table.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["camera", "file", "rms_px"])
        writer.writerows(rows)
    print(f"-> {table.relative_to(ROOT) if table.is_relative_to(ROOT) else table}")
    return rows


def make_demo(output_dir: Path) -> tuple[Path, Path]:
    """固定种子生成虚拟棋盘、含噪角点和模拟 B 标定结果；不调用 A/B 代码。"""
    corners_path, calib_path = output_dir / "corners.json", output_dir / "calib.json"
    if corners_path.exists() or calib_path.exists():
        raise FileExistsError("模拟输入已存在；请用 --corners/--calib 重新评估，或选择新的 --output-dir")
    output_dir = output_dir.resolve()
    if not output_dir.is_relative_to(ROOT):
        raise ValueError("模拟数据目录必须在仓库内")
    rng = np.random.default_rng(20261110)
    data = {"board": "demo_board", "pattern": [7, 6], "square_mm": 30.0, "images": []}
    objp = _object_points(data)
    size, cameras, truth = (1024, 576), {}, {}
    poses = [([-0.25, 0.20, -0.08], [-105, -80, 600]),
             ([0.30, -0.20, 0.10], [-75, -95, 680]),
             ([-0.15, -0.35, 0.06], [-115, -45, 560]),
             ([0.35, 0.25, -0.15], [-70, -60, 640])]
    image_dir = output_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    for index, camera in enumerate(("demo_left", "demo_right")):
        K = np.array([[800.0 + index * 35, 0, 512], [0, 805.0 + index * 35, 288], [0, 0, 1]])
        dist = np.array([-0.12, 0.025, 0.001, -0.0005, 0.0])
        records = []
        for i, (rotation, translation) in enumerate(poses, 1):
            rvec, tvec = np.array(rotation, dtype=float), np.array(translation, dtype=float)
            clean, _ = cv2.projectPoints(objp, rvec, tvec, K, dist)
            points = clean.reshape(-1, 2) + rng.normal(0, 0.12, (len(objp), 2))
            image = np.full((size[1], size[0], 3), 210, dtype=np.uint8)
            for row in range(-1, data["pattern"][1]):
                for col in range(-1, data["pattern"][0]):
                    square = np.array([[col, row, 0], [col + 1, row, 0],
                                       [col + 1, row + 1, 0], [col, row + 1, 0]], dtype=float) * 30
                    polygon, _ = cv2.projectPoints(square, rvec, tvec, K, dist)
                    shade = 245 if (row + col) % 2 else 35
                    cv2.fillConvexPoly(image, np.rint(polygon).astype(np.int32), (shade,) * 3)
            cv2.putText(image, "SYNTHETIC DEMO - NOT COURSE DATA", (20, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 180), 2, cv2.LINE_AA)
            path = image_dir / f"{camera}_{i}.png"
            if not cv2.imwrite(str(path), image):
                raise OSError(f"无法写入模拟图像: {path}")
            records.append({"file": path.relative_to(ROOT).as_posix(), "camera": camera,
                            "image_size": list(size), "corners": points.tolist(),
                            "detector": "synthetic", "ok": True})
        imgpoints = [np.asarray(rec["corners"], np.float32).reshape(-1, 1, 2) for rec in records]
        rms, fitted_K, fitted_dist, rvecs, tvecs = cv2.calibrateCamera(
            [objp] * len(records), imgpoints, size, None, None,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-9))
        per_image = []
        for rec, rvec, tvec in zip(records, rvecs, tvecs):
            projected, _ = cv2.projectPoints(objp, rvec, tvec, fitted_K, fitted_dist)
            per_image.append({"file": rec["file"], "rms": per_image_rms(rec["corners"], projected),
                              "rvec": rvec.ravel().tolist(), "tvec": tvec.ravel().tolist()})
        cameras[camera] = {"image_size": list(size), "K": fitted_K.tolist(),
                           "dist": fitted_dist.ravel().tolist(), "rms": float(rms),
                           "per_image": per_image}
        truth[camera] = {"K": K.tolist(), "dist": dist.tolist()}
        data["images"].extend(records)
    calib = {key: data[key] for key in ("board", "pattern", "square_mm")}
    calib["cameras"] = cameras
    metadata = {"purpose": "SYNTHETIC DEMO ONLY; not course results", "seed": 20261110,
                "noise_sigma_px": 0.12, "flags": 0, "max_iter": 100, "epsilon": 1e-9,
                "ground_truth": truth, "opencv_version": cv2.__version__}
    for path, content in ((corners_path, data), (calib_path, calib),
                          (output_dir / "demo_metadata.json", metadata)):
        path.write_text(json.dumps(content, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                        encoding="utf-8")
    print("DEMO: 已生成模拟数据；所有数值仅用于验证 C 的流程。")
    return corners_path, calib_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--calib", type=Path, help="B 的 calib.json，默认 outputs/calib.json")
    ap.add_argument("--corners", type=Path, help="A 的 corners.json，默认 outputs/corners.json")
    ap.add_argument("--output-dir", type=Path, help="输出根目录；正常为 outputs，模拟为 outputs/demo")
    ap.add_argument("--demo", action="store_true", help="生成明确标记的模拟输入并运行评估")
    args = ap.parse_args()
    if args.demo and (args.corners or args.calib):
        ap.error("--demo 不能与 --corners/--calib 同时使用")
    output_dir = (args.output_dir or (OUTPUTS / "demo" if args.demo else OUTPUTS)).resolve()
    cv2.setNumThreads(1)
    try:
        if args.demo:
            corners_path, calib_path = make_demo(output_dir)
        else:
            corners_path = args.corners or OUTPUTS / "corners.json"
            calib_path = args.calib or OUTPUTS / "calib.json"
        evaluate(calib_path, corners_path, output_dir)
    except (OSError, ValueError, KeyError, TypeError, cv2.error) as exc:
        ap.exit(2, f"评估失败: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
