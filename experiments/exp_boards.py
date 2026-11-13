#!/usr/bin/env python3
"""D：标定板 1 与标定板 2 的描述性对比实验。

统计口径：
  - 检测网格占比：四个最外层检测角点围成区域 / 图像面积；
  - 单格像素：网格内全部水平、垂直相邻角点距离的平均值；
  - 图像集合：严格采用各 calib 文件中的 per_image.file。

输出  outputs/experiments/boards_compare.csv
      outputs/experiments/boards_compare.md
      outputs/experiments/boards_compare.png
      outputs/experiments/boards_compare.audit.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
from pathlib import Path

import cv2
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "experiments"
OUTPUTS = ROOT / "outputs"


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"JSON 顶层应为对象: {path}")
    return data


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_finite(name: str, values: np.ndarray) -> None:
    if not np.isfinite(values).all():
        raise ValueError(f"{name} 含非有限数值")


def _image_geometry(corners: np.ndarray, pattern: tuple[int, int],
                    image_size: tuple[int, int]) -> dict:
    cols, rows = pattern
    points = np.asarray(corners, dtype=np.float64)
    if points.shape != (cols * rows, 2):
        raise ValueError(f"角点形状 {points.shape} 与 {cols}x{rows} 不一致")
    _require_finite("corners", points)
    grid = points.reshape(rows, cols, 2)
    horizontal = np.linalg.norm(np.diff(grid, axis=1), axis=2).reshape(-1)
    vertical = np.linalg.norm(np.diff(grid, axis=0), axis=2).reshape(-1)
    cell_lengths = np.concatenate((horizontal, vertical))
    if np.any(cell_lengths <= 0):
        raise ValueError("相邻角点距离必须为正")
    polygon = np.asarray((grid[0, 0], grid[0, -1], grid[-1, -1], grid[-1, 0]),
                         dtype=np.float32)
    width, height = image_size
    coverage = float(cv2.contourArea(polygon) / (width * height))
    if not 0 < coverage <= 1:
        raise ValueError(f"检测网格占比异常: {coverage}")
    return {
        "coverage_ratio": coverage,
        "cell_px_mean": float(cell_lengths.mean()),
        "cell_px_std": float(cell_lengths.std()),
        "cell_px_min": float(cell_lengths.min()),
        "cell_px_max": float(cell_lengths.max()),
    }


def board_stats(calib_path: Path, corners_path: Path) -> dict:
    """按 board/camera 汇总几何采样与标定参数，并保留逐图审计数据。"""
    calib = _load(calib_path)
    corners_data = _load(corners_path)
    for key in ("board", "pattern", "square_mm"):
        if calib.get(key) != corners_data.get(key):
            raise ValueError(f"{calib_path.name} 与 {corners_path.name} 的 {key} 不一致")
    board = calib.get("board")
    pattern_raw = calib.get("pattern")
    if not (isinstance(board, str) and isinstance(pattern_raw, list) and len(pattern_raw) == 2):
        raise ValueError(f"{calib_path.name} 缺少有效的 board/pattern")
    pattern = (int(pattern_raw[0]), int(pattern_raw[1]))
    if min(pattern) < 2:
        raise ValueError(f"非法 pattern: {pattern}")
    square_mm = float(calib["square_mm"])
    if not math.isfinite(square_mm) or square_mm <= 0:
        raise ValueError("square_mm 必须为正数")

    records = corners_data.get("images")
    if not isinstance(records, list):
        raise ValueError(f"{corners_path.name} 缺少 images")
    index: dict[str, dict] = {}
    for record in records:
        file = record.get("file") if isinstance(record, dict) else None
        if not isinstance(file, str) or not file or file in index:
            raise ValueError(f"{corners_path.name} 含空路径或重复路径")
        index[file] = record

    cameras = calib.get("cameras")
    if not isinstance(cameras, dict) or not cameras:
        raise ValueError(f"{calib_path.name} 缺少 cameras")
    rows_out: list[dict] = []
    images_out: list[dict] = []
    for camera, info in cameras.items():
        size_raw = info.get("image_size")
        K = np.asarray(info.get("K"), dtype=np.float64)
        dist = np.asarray(info.get("dist"), dtype=np.float64).reshape(-1)
        per_image = info.get("per_image")
        if not (isinstance(size_raw, list) and len(size_raw) == 2 and K.shape == (3, 3)
                and dist.shape == (5,) and isinstance(per_image, list) and per_image):
            raise ValueError(f"{board}/{camera} 标定字段不完整")
        _require_finite(f"{board}/{camera} K", K)
        _require_finite(f"{board}/{camera} dist", dist)
        image_size = (int(size_raw[0]), int(size_raw[1]))
        if min(image_size) <= 0:
            raise ValueError(f"{board}/{camera} 图像尺寸非法")

        metrics: list[dict] = []
        files_seen: set[str] = set()
        for calib_record in per_image:
            file = calib_record.get("file")
            if not isinstance(file, str) or file in files_seen:
                raise ValueError(f"{board}/{camera} per_image 含重复或空路径")
            files_seen.add(file)
            corner_record = index.get(file)
            if corner_record is None:
                raise ValueError(f"{board}/{camera} 在角点文件中找不到 {file}")
            if corner_record.get("camera") != camera or corner_record.get("ok") is not True:
                raise ValueError(f"{file} 的相机或检测状态与标定文件不一致")
            if tuple(corner_record.get("image_size", ())) != image_size:
                raise ValueError(f"{file} 的图像尺寸与标定参数不一致")
            geometry = _image_geometry(corner_record.get("corners"), pattern, image_size)
            item = {
                "board": board,
                "camera": camera,
                "file": file,
                "image_size": list(image_size),
                **geometry,
                "per_image_rms_px": float(calib_record.get("rms")),
            }
            if not math.isfinite(item["per_image_rms_px"]):
                raise ValueError(f"{file} 的 per-image RMS 非法")
            metrics.append(item)
            images_out.append(item)

        coverages = np.asarray([item["coverage_ratio"] for item in metrics])
        cells = np.asarray([item["cell_px_mean"] for item in metrics])
        rms = float(info.get("rms"))
        if not math.isfinite(rms) or rms < 0:
            raise ValueError(f"{board}/{camera} RMS 非法")
        row = {
            "board": board,
            "camera": camera,
            "pattern": f"{pattern[0]}x{pattern[1]}",
            "square_mm": square_mm,
            "image_count": len(metrics),
            "image_width": image_size[0],
            "image_height": image_size[1],
            "corners_per_image": pattern[0] * pattern[1],
            "coverage_mean_pct": float(coverages.mean() * 100),
            "coverage_std_pct": float(coverages.std() * 100),
            "coverage_min_pct": float(coverages.min() * 100),
            "coverage_max_pct": float(coverages.max() * 100),
            "cell_px_mean": float(cells.mean()),
            "cell_px_std_between_images": float(cells.std()),
            "rms_px": rms,
            "fx_px": float(K[0, 0]),
            "fy_px": float(K[1, 1]),
            "cx_px": float(K[0, 2]),
            "cy_px": float(K[1, 2]),
            "fx_over_width": float(K[0, 0] / image_size[0]),
            "fy_over_height": float(K[1, 1] / image_size[1]),
            "k1": float(dist[0]),
            "k2": float(dist[1]),
            "p1": float(dist[2]),
            "p2": float(dist[3]),
            "k3": float(dist[4]),
        }
        rows_out.append(row)
    return {
        "board": board,
        "pattern": list(pattern),
        "square_mm": square_mm,
        "calib": str(calib_path),
        "calib_sha256": _sha256(calib_path),
        "corners": str(corners_path),
        "corners_sha256": _sha256(corners_path),
        "rows": rows_out,
        "images": images_out,
    }


CSV_FIELDS = (
    "board", "camera", "pattern", "square_mm", "image_count", "image_width",
    "image_height", "corners_per_image", "coverage_mean_pct", "coverage_std_pct",
    "coverage_min_pct", "coverage_max_pct", "cell_px_mean", "cell_px_std_between_images",
    "rms_px", "fx_px", "fy_px", "cx_px", "cy_px", "fx_over_width", "fy_over_height",
    "k1", "k2", "p1", "p2", "k3",
)


def _write_csv(rows: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            formatted = {}
            for key in CSV_FIELDS:
                value = row[key]
                formatted[key] = f"{value:.9g}" if isinstance(value, float) else value
            writer.writerow(formatted)


def _board_summary(results: list[dict], board: str) -> dict:
    result = next(item for item in results if item["board"] == board)
    coverages = np.asarray([item["coverage_ratio"] for item in result["images"]]) * 100
    cells = np.asarray([item["cell_px_mean"] for item in result["images"]])
    rms = np.asarray([item["rms_px"] for item in result["rows"]])
    return {
        "image_count": len(result["images"]),
        "coverage_mean_pct": float(coverages.mean()),
        "coverage_range_pct": (float(coverages.min()), float(coverages.max())),
        "cell_mean_px": float(cells.mean()),
        "cell_range_px": (float(cells.min()), float(cells.max())),
        "rms_range_px": (float(rms.min()), float(rms.max())),
    }


def _write_markdown(results: list[dict], rows: list[dict], path: Path) -> None:
    b1 = _board_summary(results, "board1")
    b2 = _board_summary(results, "board2")
    lines = [
        "# 标定板 1 与标定板 2 描述性对比", "",
        "> 统计仅采用各标定文件 `per_image.file` 中的图像。检测网格占比为四个外层检测角点围成区域除以图像面积；单格像素为全部水平、垂直相邻角点距离的平均值。", "",
        "**表 D-1　图像采样与网格成像尺度**", "",
        "| 标定板/相机 | 图像数 | 分辨率 | 检测网格 | 网格占比（均值±标准差） | 单格像素（均值±图间标准差） |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['board']} / {row['camera']} | {row['image_count']} | "
            f"{row['image_width']}×{row['image_height']} | {row['pattern']} | "
            f"{row['coverage_mean_pct']:.2f}% ± {row['coverage_std_pct']:.2f}% | "
            f"{row['cell_px_mean']:.2f} ± {row['cell_px_std_between_images']:.2f} px |"
        )
    lines.extend([
        "", "**表 D-2　标定结果与分辨率归一化焦距**", "",
        "| 标定板/相机 | RMS ↓ (px) | $f_x$ / $f_y$ (px) | $c_x$ / $c_y$ (px) | $f_x/W$ / $f_y/H$ |",
        "|---|---:|---:|---:|---:|",
    ])
    for row in rows:
        lines.append(
            f"| {row['board']} / {row['camera']} | {row['rms_px']:.6f} | "
            f"{row['fx_px']:.3f} / {row['fy_px']:.3f} | "
            f"{row['cx_px']:.3f} / {row['cy_px']:.3f} | "
            f"{row['fx_over_width']:.4f} / {row['fy_over_height']:.4f} |"
        )
    lines.extend([
        "", "## 差异分析", "",
        f"板 1 的 6 张采用图像中，检测网格平均占画面 {b1['coverage_mean_pct']:.2f}%（逐图范围 "
        f"{b1['coverage_range_pct'][0]:.2f}%～{b1['coverage_range_pct'][1]:.2f}%），平均单格边长 "
        f"{b1['cell_mean_px']:.2f} px。板 2 的 8 张采用图像对应数值为 "
        f"{b2['coverage_mean_pct']:.2f}%（{b2['coverage_range_pct'][0]:.2f}%～{b2['coverage_range_pct'][1]:.2f}%）和 "
        f"{b2['cell_mean_px']:.2f} px。这里的板 2 占比只描述下游使用的 7×6 子网格，不代表完整 11×7 内角点区域。", "",
        f"板 1 两个相机组的训练 RMS 为 {b1['rms_range_px'][0]:.6f}～{b1['rms_range_px'][1]:.6f} px，"
        f"板 2 为 {b2['rms_range_px'][0]:.6f}～{b2['rms_range_px'][1]:.6f} px。该差异同时混入了相机、分辨率、"
        "拍摄距离、姿态、板面平整度和角点质量等因素，因此只能作描述性比较，不能据此建立“方格尺寸导致 RMS 变化”的因果结论。", "",
        "板 2 虽有更低的训练重投影误差，但 B/C 的迭代与留一结果显示其焦距对求解设置和视图选择敏感；"
        "低 RMS 因而不能证明物理内参可靠。板 1 每个相机组只有 3 张同分辨率图像，也不足以支持强泛化结论。", "",
        "## 输出说明", "",
        "- 完整精度数据：`outputs/experiments/boards_compare.csv`",
        "- 可视化：`outputs/experiments/boards_compare.png`",
        "- 逐图几何统计与输入路径：`outputs/experiments/boards_compare.audit.json`", "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def _plot(rows: list[dict], path: Path) -> None:
    labels = [f"{row['board']}\n{row['camera']}" for row in rows]
    colors = ["#c96b4b" if row["board"] == "board1" else "#3d84a8" for row in rows]
    x = np.arange(len(rows))
    fig, axes = plt.subplots(2, 2, figsize=(11, 7.5))
    specs = (
        (axes[0, 0], "coverage_mean_pct", "Detected-grid coverage (%)", "%.1f"),
        (axes[0, 1], "cell_px_mean", "Mean cell size (px)", "%.1f"),
        (axes[1, 0], "rms_px", "Training reprojection RMS (px)", "%.3f"),
    )
    for ax, key, ylabel, fmt in specs:
        values = [row[key] for row in rows]
        bars = ax.bar(x, values, color=colors)
        ax.bar_label(bars, fmt=fmt, padding=3, fontsize=9)
        ax.set_ylabel(ylabel)
        ax.set_xticks(x, labels)
        ax.grid(axis="y", alpha=0.22)
        ax.set_ylim(0, max(values) * 1.22 if max(values) else 1)
    width = 0.34
    fx = [row["fx_over_width"] for row in rows]
    fy = [row["fy_over_height"] for row in rows]
    axes[1, 1].bar(x - width / 2, fx, width, label="fx / width", color="#5b6fa8")
    axes[1, 1].bar(x + width / 2, fy, width, label="fy / height", color="#67a96b")
    axes[1, 1].set_ylabel("Normalized focal length")
    axes[1, 1].set_xticks(x, labels)
    axes[1, 1].legend()
    axes[1, 1].grid(axis="y", alpha=0.22)
    fig.suptitle("Board/camera-group comparison (descriptive; cameras are not controlled)", fontsize=13)
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--board2-calib", type=Path, default=OUTPUTS / "calib.json")
    ap.add_argument("--board2-corners", type=Path, default=OUTPUTS / "corners.json")
    ap.add_argument("--board1-calib", type=Path, default=OUTPUTS / "calib_board1.json")
    ap.add_argument("--board1-corners", type=Path, default=OUTPUTS / "corners_board1.json")
    ap.add_argument("--out-dir", type=Path, default=OUT)
    args = ap.parse_args()

    try:
        results = [
            board_stats(args.board1_calib, args.board1_corners),
            board_stats(args.board2_calib, args.board2_corners),
        ]
        rows = [row for result in results for row in result["rows"]]
        args.out_dir.mkdir(parents=True, exist_ok=True)
        csv_path = args.out_dir / "boards_compare.csv"
        md_path = args.out_dir / "boards_compare.md"
        png_path = args.out_dir / "boards_compare.png"
        audit_path = args.out_dir / "boards_compare.audit.json"
        _write_csv(rows, csv_path)
        _write_markdown(results, rows, md_path)
        _plot(rows, png_path)
        audit = {
            "schema_version": 1,
            "environment": {
                "python": platform.python_version(),
                "opencv": cv2.__version__,
                "numpy": np.__version__,
                "matplotlib": matplotlib.__version__,
            },
            "definitions": {
                "coverage_ratio": "Area of quadrilateral formed by outer detected corners / image area.",
                "cell_px": "Mean Euclidean distance over horizontal and vertical adjacent detected corners.",
                "selection": "Only calib.cameras[*].per_image.file records are included.",
            },
            "limitations": [
                "Board groups use different cameras/resolutions and are not a controlled causal experiment.",
                "board2 coverage describes the delivered 7x6 subgrid, not the full physical board.",
                "Training RMS does not establish held-out accuracy or intrinsic identifiability.",
            ],
            "results": results,
        }
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                              encoding="utf-8")
        for path in (csv_path, md_path, png_path, audit_path):
            print(f"-> {path}")
    except (OSError, ValueError, KeyError, TypeError, cv2.error) as exc:
        ap.exit(2, f"标定板对比失败: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
