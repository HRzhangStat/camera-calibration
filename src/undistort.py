#!/usr/bin/env python3
"""D：按相机独立完成畸变校正，并生成可复现的视觉对比。

输入  outputs/calib.json（也可显式传入 calib_board1.json）
输出  outputs/figures/undistort_<camera>_<file>_compare.png
      outputs/figures/undistort_<camera>_<file>_alpha_compare.png
      outputs/undistorted/<camera>/<file>
      outputs/undistorted/undistort_<board>_summary.json

用法:
    python src/undistort.py --calib outputs/calib.json
    python src/undistort.py --calib outputs/calib_board1.json --alpha 0
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import re
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = ROOT / "outputs"
DEFAULT_ALPHAS = (0.0, 0.5, 1.0)


def read_image(path: Path) -> np.ndarray:
    """用字节解码读取图像，兼容路径中的非 ASCII 字符。"""
    try:
        encoded = np.fromfile(path, dtype=np.uint8)
    except OSError as exc:
        raise ValueError(f"无法读取图像: {path}") from exc
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR) if encoded.size else None
    if image is None:
        raise ValueError(f"无法解码图像: {path}")
    return image


def write_image(path: Path, image: np.ndarray) -> None:
    """按扩展名编码并写入图像，失败时给出明确错误。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower() or ".png"
    params: list[int] = []
    if suffix in (".jpg", ".jpeg"):
        params = [cv2.IMWRITE_JPEG_QUALITY, 95]
    elif suffix == ".png":
        params = [cv2.IMWRITE_PNG_COMPRESSION, 6]
    ok, encoded = cv2.imencode(suffix, image, params)
    if not ok:
        raise OSError(f"图像编码失败: {path}")
    encoded.tofile(path)


def _safe_component(text: str) -> str:
    value = re.sub(r"[^0-9A-Za-z_.-]+", "_", text).strip("._")
    if not value:
        raise ValueError(f"无法用于文件名的名称: {text!r}")
    return value


def _resolve_input(image_root: Path, relative_file: str) -> Path:
    """解析标定文件中的相对路径，并拒绝越出 image_root 的路径。"""
    path = (image_root / relative_file).resolve()
    try:
        path.relative_to(image_root.resolve())
    except ValueError as exc:
        raise ValueError(f"图像路径越出 image_root: {relative_file}") from exc
    return path


def _validated_camera(camera: str, info: dict) -> tuple[tuple[int, int], np.ndarray, np.ndarray, list[dict]]:
    required = ("image_size", "K", "dist", "per_image")
    missing = [key for key in required if key not in info]
    if missing:
        raise ValueError(f"{camera} 缺少字段: {', '.join(missing)}")

    size_raw = info["image_size"]
    if not (isinstance(size_raw, list) and len(size_raw) == 2):
        raise ValueError(f"{camera}.image_size 应为 [width, height]")
    size = (int(size_raw[0]), int(size_raw[1]))
    if size[0] <= 0 or size[1] <= 0:
        raise ValueError(f"{camera}.image_size 非法: {size}")

    K = np.asarray(info["K"], dtype=np.float64)
    dist = np.asarray(info["dist"], dtype=np.float64).reshape(-1)
    if K.shape != (3, 3) or dist.shape != (5,):
        raise ValueError(f"{camera} 的 K 应为 3x3、dist 应含 5 个系数")
    if not np.isfinite(K).all() or not np.isfinite(dist).all():
        raise ValueError(f"{camera} 的 K/dist 含非有限数值")
    if K[0, 0] <= 0 or K[1, 1] <= 0 or not np.isclose(K[2, 2], 1.0):
        raise ValueError(f"{camera} 的内参矩阵不合理")

    records = info["per_image"]
    if not isinstance(records, list) or not records:
        raise ValueError(f"{camera}.per_image 不能为空")
    seen: set[str] = set()
    for record in records:
        file = record.get("file") if isinstance(record, dict) else None
        if not isinstance(file, str) or not file or file in seen:
            raise ValueError(f"{camera}.per_image 含空路径或重复路径")
        seen.add(file)
    return size, K, dist, records


def _fit_panel(image: np.ndarray, max_panel: int) -> np.ndarray:
    """限制报告图尺寸，同时保持原始宽高比。"""
    h, w = image.shape[:2]
    scale = min(1.0, max_panel / max(h, w))
    if scale == 1.0:
        return image.copy()
    return cv2.resize(image, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)


def _dashed_line(image: np.ndarray, p1: tuple[int, int], p2: tuple[int, int],
                 color: tuple[int, int, int], thickness: int = 1, dash: int = 10) -> None:
    """画不遮挡主体的虚线参考线。"""
    start = np.asarray(p1, dtype=np.float64)
    end = np.asarray(p2, dtype=np.float64)
    length = float(np.linalg.norm(end - start))
    if length == 0:
        return
    direction = (end - start) / length
    for offset in np.arange(0.0, length, dash * 2):
        a = start + direction * offset
        b = start + direction * min(offset + dash, length)
        cv2.line(image, tuple(np.rint(a).astype(int)), tuple(np.rint(b).astype(int)),
                 color, thickness, cv2.LINE_AA)


def _mark_long_edges(image: np.ndarray, max_lines: int = 5) -> None:
    """用 Hough 线段标出少量长边，帮助定位板框、桌沿或天花板格线。"""
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 60, 160)
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=max(35, min(h, w) // 10),
        minLineLength=max(60, round(min(h, w) * 0.28)),
        maxLineGap=max(8, round(min(h, w) * 0.025)),
    )
    if lines is None:
        return
    candidates = []
    for x1, y1, x2, y2 in lines[:, 0]:
        length = math.hypot(x2 - x1, y2 - y1)
        angle = math.atan2(y2 - y1, x2 - x1) % math.pi
        midpoint = np.asarray(((x1 + x2) / 2, (y1 + y2) / 2))
        candidates.append((length, angle, midpoint, (int(x1), int(y1), int(x2), int(y2))))
    selected = []
    for candidate in sorted(candidates, key=lambda item: item[0], reverse=True):
        _, angle, midpoint, _ = candidate
        duplicate = False
        for _, kept_angle, kept_midpoint, _ in selected:
            angle_delta = abs(angle - kept_angle)
            angle_delta = min(angle_delta, math.pi - angle_delta)
            if angle_delta < math.radians(5) and np.linalg.norm(midpoint - kept_midpoint) < min(h, w) * 0.12:
                duplicate = True
                break
        if not duplicate:
            selected.append(candidate)
        if len(selected) == max_lines:
            break
    for _, _, _, (x1, y1, x2, y2) in selected:
        cv2.line(image, (x1, y1), (x2, y2), (15, 40, 15), 4, cv2.LINE_AA)
        cv2.line(image, (x1, y1), (x2, y2), (70, 235, 90), 2, cv2.LINE_AA)


def _annotate_panel(image: np.ndarray, label: str, *, guides: bool = True,
                    mark_edges: bool = False) -> np.ndarray:
    """增加标题和位置参考线；真实直线仍由图像中的板边/背景边缘提供。"""
    panel = image.copy()
    h, w = panel.shape[:2]
    if mark_edges:
        _mark_long_edges(panel)
    if guides:
        color = (0, 215, 255)
        for fraction in (0.1, 0.5, 0.9):
            x = int(round((w - 1) * fraction))
            y = int(round((h - 1) * fraction))
            _dashed_line(panel, (x, 0), (x, h - 1), color)
            _dashed_line(panel, (0, y), (w - 1, y), color)
    bar_h = max(38, round(h * 0.055))
    overlay = panel.copy()
    cv2.rectangle(overlay, (0, 0), (w, bar_h), (18, 25, 35), -1)
    cv2.addWeighted(overlay, 0.86, panel, 0.14, 0, panel)
    font_scale = max(0.48, min(0.82, w / 1200))
    cv2.putText(panel, label, (12, round(bar_h * 0.7)), cv2.FONT_HERSHEY_SIMPLEX,
                font_scale, (255, 255, 255), 1, cv2.LINE_AA)
    return panel


def make_compare(original: np.ndarray, undistorted: np.ndarray, out: Path, *,
                 alpha: float, roi: tuple[int, int, int, int], max_panel: int = 1000) -> None:
    """生成同尺度左右拼接图，并叠加稀疏参考线辅助观察真实结构边缘。"""
    if original.shape != undistorted.shape:
        raise ValueError("前后图像尺寸不一致，不能直接比较")
    left = _fit_panel(original, max_panel)
    right = _fit_panel(undistorted, max_panel)
    left = _annotate_panel(left, "Original | green=edge, yellow=guide", mark_edges=True)
    right = _annotate_panel(right, f"Undistorted | alpha={alpha:g} | ROI={roi}", mark_edges=True)
    divider = np.full((left.shape[0], 4, 3), (240, 240, 240), dtype=np.uint8)
    write_image(out, np.hstack((left, divider, right)))


def make_alpha_compare(original: np.ndarray, variants: list[tuple[float, np.ndarray, tuple[int, int, int, int]]],
                       out: Path, *, max_panel: int = 1000) -> None:
    """将原图与多个 alpha 的未裁剪结果排成网格，直接展示视野/黑边权衡。"""
    panels = [(_fit_panel(original, max_panel), "Original")]
    panels.extend((_fit_panel(image, max_panel), f"alpha={alpha:g} | ROI={roi}")
                  for alpha, image, roi in variants)
    target_h = max(panel.shape[0] for panel, _ in panels)
    target_w = max(panel.shape[1] for panel, _ in panels)
    rendered: list[np.ndarray] = []
    for panel, label in panels:
        canvas = np.full((target_h, target_w, 3), (245, 245, 245), dtype=np.uint8)
        y0 = (target_h - panel.shape[0]) // 2
        x0 = (target_w - panel.shape[1]) // 2
        canvas[y0:y0 + panel.shape[0], x0:x0 + panel.shape[1]] = panel
        rendered.append(_annotate_panel(canvas, label, guides=False))
    if len(rendered) % 2:
        rendered.append(np.full_like(rendered[0], 245))
    rows = [np.hstack((rendered[i], rendered[i + 1])) for i in range(0, len(rendered), 2)]
    write_image(out, np.vstack(rows))


def undistort_variant(image: np.ndarray, K: np.ndarray, dist: np.ndarray,
                      alpha: float) -> tuple[np.ndarray, np.ndarray, tuple[int, int, int, int], dict]:
    """计算指定 alpha 的映射、校正图和可审计的映射统计。"""
    h, w = image.shape[:2]
    new_K, roi_raw = cv2.getOptimalNewCameraMatrix(K, dist, (w, h), alpha, (w, h))
    map_x, map_y = cv2.initUndistortRectifyMap(
        K, dist, None, new_K, (w, h), cv2.CV_32FC1
    )
    corrected = cv2.remap(image, map_x, map_y, cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
    grid_x, grid_y = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    valid = (map_x >= 0) & (map_x <= w - 1) & (map_y >= 0) & (map_y <= h - 1)
    displacement = np.hypot(map_x - grid_x, map_y - grid_y)
    roi = tuple(int(value) for value in roi_raw)
    stats = {
        "alpha": float(alpha),
        "new_K": new_K.tolist(),
        "roi": list(roi),
        "roi_area_ratio": float((roi[2] * roi[3]) / (w * h)),
        "valid_map_ratio": float(valid.mean()),
        "mean_mapping_displacement_px": float(displacement[valid].mean()),
        "max_mapping_displacement_px": float(displacement[valid].max()),
    }
    return corrected, new_K, roi, stats


def _parse_alphas(values: list[float], selected: float) -> list[float]:
    alphas = sorted(set(float(value) for value in (*values, selected)))
    if any(not math.isfinite(value) or value < 0 or value > 1 for value in alphas):
        raise ValueError("alpha 必须位于 [0, 1]")
    return alphas


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--calib", type=Path, default=OUTPUTS / "calib.json")
    ap.add_argument("--image-root", type=Path, default=ROOT)
    ap.add_argument("--output-root", type=Path, default=OUTPUTS)
    ap.add_argument("--alpha", type=float, default=0.0,
                    help="保存到 outputs/undistorted 的主结果 alpha（默认 0，优先保证有效像素）")
    ap.add_argument("--alphas", type=float, nargs="+", default=list(DEFAULT_ALPHAS),
                    help="alpha 对比列表（默认 0 0.5 1）")
    ap.add_argument("--max-panel", type=int, default=800,
                    help="报告对比图中单个面板的最长边像素数")
    args = ap.parse_args()

    try:
        if args.max_panel < 320:
            raise ValueError("--max-panel 至少为 320")
        alphas = _parse_alphas(args.alphas, args.alpha)
        calib = json.loads(args.calib.read_text(encoding="utf-8"))
        board = calib.get("board")
        cameras = calib.get("cameras")
        if not isinstance(board, str) or not isinstance(cameras, dict) or not cameras:
            raise ValueError("标定文件缺少有效的 board/cameras")

        figures_dir = args.output_root / "figures"
        undistorted_dir = args.output_root / "undistorted"
        figures_dir.mkdir(parents=True, exist_ok=True)
        undistorted_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            "schema_version": 1,
            "board": board,
            "calibration_file": str(args.calib),
            "calibration_sha256": hashlib.sha256(args.calib.read_bytes()).hexdigest(),
            "selected_alpha": float(args.alpha),
            "compared_alphas": alphas,
            "note": "Mapping displacement includes the alpha-dependent new-camera-matrix scaling.",
            "environment": {
                "python": platform.python_version(),
                "opencv": cv2.__version__,
                "numpy": np.__version__,
            },
            "cameras": {},
        }

        for camera, info in cameras.items():
            size, K, dist, records = _validated_camera(camera, info)
            camera_summary = {
                "image_size": list(size),
                "dist": dist.tolist(),
                "alphas": [],
                "files": [],
            }
            camera_key = _safe_component(camera)

            for record in records:
                relative_file = record["file"]
                source = _resolve_input(args.image_root, relative_file)
                image = read_image(source)
                actual_size = (image.shape[1], image.shape[0])
                if actual_size != size:
                    raise ValueError(
                        f"{relative_file} 尺寸 {actual_size} 与 {camera} 标定尺寸 {size} 不一致"
                    )

                variants: list[tuple[float, np.ndarray, tuple[int, int, int, int]]] = []
                alpha_stats: list[dict] = []
                for alpha in alphas:
                    corrected, _, roi, stats = undistort_variant(image, K, dist, alpha)
                    variants.append((alpha, corrected, roi))
                    alpha_stats.append(stats)

                selected = next((item for item in variants if math.isclose(item[0], args.alpha,
                                                                            rel_tol=0, abs_tol=1e-12)), None)
                if selected is None:
                    raise RuntimeError("内部错误：未生成 selected alpha")
                _, selected_image, selected_roi = selected

                saved = undistorted_dir / camera_key / source.name
                write_image(saved, selected_image)
                stem = _safe_component(source.stem)
                compare_path = figures_dir / f"undistort_{camera_key}_{stem}_compare.png"
                alpha_path = figures_dir / f"undistort_{camera_key}_{stem}_alpha_compare.png"
                make_compare(image, selected_image, compare_path, alpha=args.alpha,
                             roi=selected_roi, max_panel=args.max_panel)
                make_alpha_compare(image, variants, alpha_path, max_panel=args.max_panel)
                camera_summary["files"].append({
                    "file": relative_file,
                    "saved": saved.relative_to(args.output_root).as_posix(),
                    "compare": compare_path.relative_to(args.output_root).as_posix(),
                    "alpha_compare": alpha_path.relative_to(args.output_root).as_posix(),
                    "alphas": alpha_stats,
                })
                print(f"[{board}/{camera}] {source.name}: alpha={args.alpha:g}, ROI={selected_roi}")

            # 映射只由相机参数和尺寸决定；相机级摘要取第一张图的结果即可。
            camera_summary["alphas"] = camera_summary["files"][0]["alphas"]
            summary["cameras"][camera] = camera_summary

        summary_path = undistorted_dir / f"undistort_{_safe_component(board)}_summary.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                                encoding="utf-8")
        print(f"-> {figures_dir}/undistort_*_compare.png")
        print(f"-> {undistorted_dir}")
        print(f"-> {summary_path}")
    except (OSError, ValueError, KeyError, TypeError, cv2.error, json.JSONDecodeError) as exc:
        ap.exit(2, f"去畸变失败: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
