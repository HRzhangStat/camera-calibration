#!/usr/bin/env python3
"""C：按 B 的实际图集和审计设置做留一法，保留全量复算作为数值对照。

python experiments/exp_views.py
python experiments/exp_views.py --corners outputs/corners_board1.json --calib outputs/calib_board1.json

留出图只参与 solvePnP 外参拟合，不参与该折内参标定。
每折至少三张训练图；视图不足明确跳过，不伪造验证误差。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
from pathlib import Path

import cv2
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
SUPPORTED_FLAGS = cv2.CALIB_FIX_K1 | cv2.CALIB_FIX_K2 | cv2.CALIB_FIX_K3 | cv2.CALIB_ZERO_TANGENT_DIST


def calibrate(objpoints, imgpoints, size, flags=cv2.CALIB_FIX_K3, max_iter=2000, epsilon=1e-10):
    """与 B 使用相同初始化、float32 点集、flags 和终止条件。"""
    if len(imgpoints) < 3 or len(objpoints) != len(imgpoints):
        raise ValueError("至少需要三张同分辨率训练图，且物体点/图像点视图数一致")
    if flags < 0 or flags & ~SUPPORTED_FLAGS:
        raise ValueError("只支持标准五参数模型的 FIX_K1/K2/K3、ZERO_TANGENT_DIST")
    if max_iter < 1 or not np.isfinite(epsilon) or epsilon <= 0:
        raise ValueError("max_iter 和 epsilon 必须为正数")
    result = cv2.calibrateCamera(
        objpoints, imgpoints, tuple(size), None, None, flags=flags,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, max_iter, epsilon))
    rms, K, dist, rvecs, tvecs = result
    if (not np.isfinite(rms) or not np.isfinite(K).all() or not np.isfinite(dist).all()
            or dist.size != 5 or K[0, 0] <= 0 or K[1, 1] <= 0):
        raise ValueError("标定返回非有限数值、非正焦距或非五参数畸变")
    for rvec, tvec, obj in zip(rvecs, tvecs, objpoints):
        rotation, _ = cv2.Rodrigues(rvec)
        if (not np.isfinite(rvec).all() or not np.isfinite(tvec).all()
                or np.any((obj @ rotation.T + tvec.reshape(1, 3))[:, 2] <= 0)):
            raise ValueError("训练姿态无效或棋盘位于相机后方")
    return result


def reprojection_rms(K, dist, rvec, tvec, objp, imgp):
    """二维点距离的均方根，以像素为单位。"""
    projected, _ = cv2.projectPoints(objp, rvec, tvec, K, dist)
    observed = np.asarray(imgp, np.float64).reshape(-1, 2)
    projected = projected.reshape(-1, 2).astype(np.float64)
    if observed.shape != projected.shape or not len(observed):
        raise ValueError("检测角点和投影角点数量不一致或为空")
    value = float(np.sqrt(np.mean(np.sum((observed - projected) ** 2, axis=1))))
    if not np.isfinite(value):
        raise ValueError("RMS 不是有限数值")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_audit_hash(path: Path, expected: str) -> dict:
    """保留合并后实际字节哈希，同时复现 B 的 LF/CRLF 字节哈希。"""
    raw = path.read_bytes()
    lf = raw.replace(b"\r\n", b"\n")
    for mode, candidate in (("exact", raw), ("LF", lf), ("CRLF", lf.replace(b"\n", b"\r\n"))):
        if hashlib.sha256(candidate).hexdigest() == expected:
            return {"actual_sha256": _sha(path), "B_expected_sha256": expected,
                    "matching_line_endings": mode}
    raise ValueError(f"{path.name}: 内容与 B 审计不同（已排除 LF/CRLF 差异）")


def _load_inputs(corners_path: Path, calib_path: Path):
    data = json.loads(corners_path.read_text(encoding="utf-8"))
    reference = json.loads(calib_path.read_text(encoding="utf-8"))
    pattern = data["pattern"]
    if (not isinstance(pattern, list) or len(pattern) != 2
            or any(type(v) is not int or v < 2 for v in pattern)):
        raise ValueError("pattern 必须为 [列数, 行数]，两者均为至少 2 的整数")
    square = float(data["square_mm"])
    if not np.isfinite(square) or square <= 0:
        raise ValueError("square_mm 必须为正数")
    if any(data[key] != reference[key] for key in ("board", "pattern", "square_mm")):
        raise ValueError("A/B 标定板参数不一致")
    if data["board"] not in ("board1", "board2", "demo_board"):
        raise ValueError("未知标定板")
    objp = np.zeros((pattern[0] * pattern[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:pattern[0], 0:pattern[1]].T.reshape(-1, 2) * square
    audit_path = calib_path.with_suffix(".audit.json")
    audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else None
    hash_verification = {}
    if audit:
        hash_verification = {corners_path.name: _verify_audit_hash(corners_path, audit["corners_sha256"]),
                             calib_path.name: _verify_audit_hash(calib_path, audit["result_sha256"])}
    elif data["board"] != "demo_board":
        raise ValueError("正式留一实验需要 B 的 .audit.json，以确认实际配置与来源")
    records_by_key = {}
    for rec in data["images"]:
        key = (rec["camera"], rec["file"])
        if key in records_by_key:
            raise ValueError(f"重复的 A 角点记录: {key}")
        if type(rec["ok"]) is not bool:
            raise ValueError(f"{rec['file']}: ok 必须为布尔值")
        records_by_key[key] = rec
    grouped, image_hashes, used = {}, {}, set()
    for camera, info in reference["cameras"].items():
        if not info["per_image"]:
            raise ValueError(f"{camera}: B 的 per_image 为空")
        records = []
        for pose in info["per_image"]:
            key = (camera, pose["file"])
            if key in used:
                raise ValueError(f"重复的 B 外参记录: {key}")
            used.add(key)
            rec = records_by_key.get(key)
            if rec is None or rec["ok"] is not True:
                raise ValueError(f"{key}: 缺少 A 成功检测的角点")
            points = np.asarray(rec["corners"], np.float32)
            size = rec["image_size"]
            if points.shape != (len(objp), 2) or not np.isfinite(points).all():
                raise ValueError(f"{key}: 角点数量/数值无效")
            if (size != info["image_size"] or len(size) != 2
                    or any(type(v) is not int or v <= 0 for v in size)):
                raise ValueError(f"{key}: A/B 图像尺寸不一致")
            raw = (ROOT / rec["file"]).read_bytes()
            image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
            if image is None or list(image.shape[::-1]) != size:
                raise ValueError(f"{key}: 原图尺寸与声明不一致")
            if (np.any(points < 0) or np.any(points >= np.asarray(size))
                    or len(np.unique(points, axis=0)) != len(points)):
                raise ValueError(f"{key}: 角点超出图像或重复")
            grid = points.reshape(pattern[1], pattern[0], 2)
            dx, dy = np.diff(grid, axis=1), np.diff(grid, axis=0)
            cross = dx[:-1, :, 0] * dy[:, :-1, 1] - dx[:-1, :, 1] * dy[:, :-1, 0]
            if not (np.all(cross > 0) or np.all(cross < 0)):
                raise ValueError(f"{key}: 网格拓扑或角点顺序无效")
            image_hashes[rec["file"]] = hashlib.sha256(raw).hexdigest()
            records.append(rec)
        grouped[camera] = records
    if not grouped:
        raise ValueError("B 没有相机结果")
    if audit:
        audited = {(item["camera"], item["file"]): item
                   for item in audit["images"] if item["reason"] == "used"}
        if set(audited) != used:
            raise ValueError("B 审计 used 图集与正式结果不一致")
        for key, item in audited.items():
            if item["sha256"] != image_hashes[key[1]]:
                raise ValueError(f"{key}: 原图哈希与 B 审计不一致")
    excluded = [dict(camera=rec["camera"], file=rec["file"], reason="not in B per_image")
                for key, rec in records_by_key.items() if key not in used]
    return data, objp, reference, audit, grouped, excluded, image_hashes, hash_verification


def run_experiment(corners_path: Path, output_dir: Path, calib_path: Path | None = None,
                   flags=None, max_iter=None, epsilon=None):
    if calib_path is None:
        board = json.loads(corners_path.read_text(encoding="utf-8"))["board"]
        calib_path = corners_path.parent / ("calib_board1.json" if board == "board1" else "calib.json")
    data, objp, reference, audit, grouped, excluded, image_hashes, hash_verification = _load_inputs(corners_path, calib_path)
    expected = ((audit["flags"], audit["solver"]["max_iterations"], audit["solver"]["epsilon"])
                if audit else (0, 100, 1e-9))
    settings = tuple(default if supplied is None else supplied
                     for default, supplied in zip(expected, (flags, max_iter, epsilon)))
    if audit and settings != expected:
        raise ValueError("命令行配置与 B 审计不一致；正式实验须使用同一模型与求解设置")
    flags, max_iter, epsilon = settings
    threads = int(audit["opencv_threads"]) if audit else 1
    cv2.setNumThreads(threads)
    rows, controls = [], {}
    for camera, records in grouped.items():
        points = [np.asarray(rec["corners"], np.float32).reshape(-1, 1, 2) for rec in records]
        info = reference["cameras"][camera]
        baseline, baseline_error = None, ""
        try:
            baseline = calibrate([objp] * len(records), points, info["image_size"], *settings)
            controls[camera] = {"rms_px": float(baseline[0]), "K": baseline[1].tolist(),
                                "dist": baseline[2].ravel().tolist(),
                                "B_rms_px": info["rms"], "B_K": info["K"],
                                "fx_difference_from_B_pct": float(100 * (baseline[1][0, 0] / info["K"][0][0] - 1)),
                                "fy_difference_from_B_pct": float(100 * (baseline[1][1, 1] / info["K"][1][1] - 1))}
        except (cv2.error, ValueError) as exc:
            baseline_error = str(exc)
            controls[camera] = {"status": "baseline_failed", "error": baseline_error}
        for index, rec in enumerate(records):
            row = dict(camera=camera, file=rec["file"], n_total=len(records), n_train=len(records) - 1,
                       flags=flags, max_iter=max_iter, epsilon=epsilon, B_rms_px=info["rms"],
                       full_rms_px=float(baseline[0]) if baseline else "", train_rms_px="",
                       validation_rms_px="", fx="", fy="", cx="", cy="",
                       fx_change_pct="", fy_change_pct="", B_fx_change_pct="", B_fy_change_pct="",
                       status="ok", error="")
            if baseline is None:
                row.update(status="baseline_failed", error=baseline_error)
            elif len(records) < 4:
                row.update(status="insufficient_views", error="留一后少于三张训练图；不生成验证误差")
            else:
                try:
                    training = [view for i, view in enumerate(points) if i != index]
                    train_rms, K, dist, _, _ = calibrate(
                        [objp] * len(training), training, info["image_size"], *settings)
                    ok, rvec, tvec = cv2.solvePnP(objp, points[index], K, dist, flags=cv2.SOLVEPNP_ITERATIVE)
                    if not ok or not np.isfinite(rvec).all() or not np.isfinite(tvec).all():
                        raise ValueError("留出图 solvePnP 无有效姿态")
                    rotation, _ = cv2.Rodrigues(rvec)
                    if np.any((objp @ rotation.T + tvec.reshape(1, 3))[:, 2] <= 0):
                        raise ValueError("留出图棋盘位于相机后方")
                    value = reprojection_rms(K, dist, rvec, tvec, objp, points[index])
                    row.update(train_rms_px=float(train_rms), validation_rms_px=value,
                               fx=float(K[0, 0]), fy=float(K[1, 1]), cx=float(K[0, 2]), cy=float(K[1, 2]),
                               fx_change_pct=float(100 * (K[0, 0] / baseline[1][0, 0] - 1)),
                               fy_change_pct=float(100 * (K[1, 1] / baseline[1][1, 1] - 1)),
                               B_fx_change_pct=float(100 * (K[0, 0] / info["K"][0][0] - 1)),
                               B_fy_change_pct=float(100 * (K[1, 1] / info["K"][1][1] - 1)))
                except (cv2.error, ValueError) as exc:
                    row.update(status="fold_failed", error=str(exc))
            rows.append(row)
            if row["status"] != "ok":
                print(f"{camera}/{Path(rec['file']).name}: {row['status']} {row['error']}")
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = output_dir / f"views_{data['board']}"
    with prefix.with_suffix(".csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    metadata = {
        "board": data["board"], "corners_sha256": _sha(corners_path), "calib_sha256": _sha(calib_path),
        "B_run_id": audit.get("run_id") if audit else None,
        "B_status": audit.get("status") if audit else "synthetic",
        "input_hash_verification": hash_verification,
        "settings": {"flags": flags, "max_iterations": max_iter, "epsilon": epsilon,
                     "initial_cameraMatrix": None, "initial_distCoeffs": None, "min_train_views": 3},
        "runtime": {"python": platform.python_version(), "numpy": np.__version__, "opencv": cv2.__version__,
                    "opencv_threads": cv2.getNumThreads(),
                    "opencv_build_sha256": hashlib.sha256(cv2.getBuildInformation().encode()).hexdigest()},
        "B_runtime": {key: audit[key] for key in ("python", "numpy", "opencv", "opencv_threads", "opencv_build_sha256")} if audit else None,
        "files": {camera: [rec["file"] for rec in records] for camera, records in grouped.items()},
        "image_sha256": image_hashes, "excluded": excluded, "full_fit_controls": controls,
        "fold_status_counts": {status: sum(row["status"] == status for row in rows)
                               for status in sorted({row["status"] for row in rows})},
        "interpretation": "Pose-conditioned held-out-view reprojection. Compare focal changes to same-runtime full fit; B comparison exported separately. Not independent 3D measurement accuracy."}
    prefix.with_suffix(".audit.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    _plot(rows, grouped, data["board"], settings, prefix.with_suffix(".png"))
    succeeded = sum(row["status"] == "ok" for row in rows)
    skipped = sum(row["status"] == "insufficient_views" for row in rows)
    print(f"-> {prefix}.*\n成功 {succeeded}/{len(rows)} 折，视图不足跳过 {skipped} 折")
    return rows


def _plot(rows, grouped, board, settings, target):
    fig, axes = plt.subplots(len(grouped), 2, figsize=(13, 4 * len(grouped)), squeeze=False)
    for (camera, _), (errors_ax, stability_ax) in zip(grouped.items(), axes):
        subset = [row for row in rows if row["camera"] == camera]
        valid = [(i, row) for i, row in enumerate(subset) if row["status"] == "ok"]
        if valid:
            errors_ax.bar([i for i, _ in valid], [row["validation_rms_px"] for _, row in valid], color="#3b82b4")
            for field, label, color, marker in [
                    ("fx_change_pct", "fx", "#3b82b4", "o"), ("fy_change_pct", "fy", "#c2410c", "x")]:
                stability_ax.scatter([i for i, _ in valid], [row[field] for _, row in valid],
                                     label=label, c=color, marker=marker)
            stability_ax.legend()
        for index, row in enumerate(subset):
            if row["status"] != "ok":
                errors_ax.text(index, .05, row["status"], rotation=90, ha="center", va="bottom",
                               transform=errors_ax.get_xaxis_transform(), fontsize=8)
        if subset[0]["full_rms_px"] != "":
            errors_ax.axhline(subset[0]["full_rms_px"], color="#c2410c", linestyle="--",
                              label="Same-runtime full-fit RMS")
            errors_ax.legend(fontsize=8)
        stability_ax.axhline(0, color="gray", linewidth=.8)
        errors_ax.set(title=f"{camera}: held-out view (pose fitted)", ylabel="RMS (px)", ylim=(0, None))
        stability_ax.set(title=f"{camera}: focal-length stability",
                         ylabel="Change from same-runtime full fit (%)")
        for ax in (errors_ax, stability_ax):
            ax.set_xticks(range(len(subset)), [Path(row["file"]).name for row in subset],
                          rotation=25, ha="right")
            ax.set_xlabel("Held-out image")
            ax.grid(axis="y", alpha=.2)
    fig.suptitle(f"{board} | flags={settings[0]}, max_iter={settings[1]}, epsilon={settings[2]:g}")
    fig.tight_layout()
    fig.savefig(target, dpi=160)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corners", type=Path, default=ROOT / "outputs/corners.json")
    ap.add_argument("--calib", type=Path, help="B 正式结果；默认取 corners 同目录的对应板结果")
    ap.add_argument("--output-dir", type=Path, default=ROOT / "outputs")
    ap.add_argument("--flags", type=lambda value: int(value, 0), help="可选核对值，须与 B 审计一致")
    ap.add_argument("--max-iter", type=int, help="可选核对值，须与 B 审计一致")
    ap.add_argument("--epsilon", type=float, help="可选核对值，须与 B 审计一致")
    args = ap.parse_args()
    try:
        rows = run_experiment(args.corners, args.output_dir / "experiments", args.calib,
                              args.flags, args.max_iter, args.epsilon)
    except (OSError, ValueError, KeyError, TypeError, cv2.error) as exc:
        ap.exit(2, f"留一实验失败: {exc}\n")
    # 已预期的视图不足由 CSV 清楚标记；求解失败仍返回非零。
    return int(any(row["status"] not in ("ok", "insufficient_views") for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
