#!/usr/bin/env python3
"""E 负责：把 calib.json 整理成报告用的 CSV 表格。

输入  outputs/calib.json、outputs/calib_board1.json
输出  outputs/tables/intrinsics.csv   内参（对应报告表 2-1）
      outputs/tables/distortion.csv   畸变（表 2-2）
      outputs/tables/sanity.csv       参数合理性（表 2-3）

报告里的这三张表与该目录下的 CSV 同源；calib.json 更新后重跑脚本即可核对。
CSV 为 UTF-8 带 BOM，双击可直接用 Excel 打开。

用法:
    python src/report_tables.py
    python src/report_tables.py --calib outputs/calib.json --table-dir /tmp
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = ROOT / "outputs"
DEFAULT_CALIBS = (OUTPUTS / "calib.json", OUTPUTS / "calib_board1.json")
TABLE_DIR = OUTPUTS / "tables"

# 判定门槛：只用于提示"该不该把数值当物理内参"，不是精度验收标准。
FX_FY_WARN_PCT = 2.0      # fx 与 fy 的相对差超过 2% 提示焦距两轴不一致
PP_WARN_FRAC = 0.05       # 主点偏离图像中心超过 5% 提示
F_OVER_W_WARN = 0.30      # fx/W 低于 0.30 ⇒ 水平视场角超过约 118°，普通镜头不合理


# --------------------------------------------------------------------------
# calib.json → 行
# --------------------------------------------------------------------------
def load_calibs(paths) -> list[dict]:
    calibs = []
    for path in paths:
        path = Path(path)
        if not path.exists():
            print(f"[skip] {path} 不存在")
            continue
        calibs.append(json.loads(path.read_text(encoding="utf-8")))
    if not calibs:
        raise SystemExit("没有可用的 calib JSON，先跑 src/calibrate.py")
    calibs.sort(key=lambda d: str(d.get("board")))
    return calibs


def board_tag(calib: dict) -> str:
    """结果表统一用英文板号（board1/board2），与 3.1、3.2 节一致。"""
    return str(calib.get("board"))


def camera_rows(calibs: list[dict]):
    for calib in calibs:
        for camera, info in calib["cameras"].items():
            yield calib, camera, info


def intrinsic_rows(calibs: list[dict]) -> list[dict]:
    rows = []
    for calib, camera, info in camera_rows(calibs):
        K = info["K"]
        width, height = info["image_size"]
        rows.append({
            "board": board_tag(calib), "camera": camera,
            "width_px": width, "height_px": height,
            "fx_px": round(float(K[0][0]), 6), "fy_px": round(float(K[1][1]), 6),
            "cx_px": round(float(K[0][2]), 6), "cy_px": round(float(K[1][2]), 6),
            "rms_px": round(float(info["rms"]), 9),
        })
    return rows


def distortion_rows(calibs: list[dict]) -> list[dict]:
    rows = []
    for calib, camera, info in camera_rows(calibs):
        dist = [float(v) for v in info["dist"]] + [0.0] * (5 - len(info["dist"]))
        rows.append({
            "board": board_tag(calib), "camera": camera,
            "k1": round(dist[0], 12), "k2": round(dist[1], 12),
            "p1": round(dist[2], 12), "p2": round(dist[3], 12), "k3": round(dist[4], 12),
        })
    return rows


def corner_stats(info: dict) -> dict:
    """把内参与畸变换算成"在图像四角处会有多大"的可核对数字。"""
    K, dist = info["K"], list(info["dist"]) + [0.0] * 5
    width, height = info["image_size"]
    fx, fy = K[0][0], K[1][1]
    cx, cy = K[0][2], K[1][2]
    k1, k2, p1, p2, k3 = dist[:5]
    corners = [((u - cx) / fx, (v - cy) / fy)
               for u in (0.0, float(width)) for v in (0.0, float(height))]
    x, y = max(corners, key=lambda p: math.hypot(*p))
    r = math.hypot(x, y)
    radial = 1.0 + k1 * r**2 + k2 * r**4 + k3 * r**6
    tangential_x = 2 * p1 * x * y + p2 * (r**2 + 2 * x**2)
    tangential_y = p1 * (r**2 + 2 * y**2) + 2 * p2 * x * y
    return {
        "corner_r": round(r, 6),
        "radial_ratio": round(radial, 6),
        "radial_shift_px": round(abs(radial - 1.0) * r * fx, 4),
        "tangential_shift_px": round(math.hypot(tangential_x, tangential_y) * fx, 4),
        "fov_deg": round(math.degrees(2 * math.atan(width / (2 * fx))), 3) if fx > 0 else "",
        "fx_fy_diff_pct": round(abs(fx - fy) / ((fx + fy) / 2) * 100, 4),
        "pp_offset_x_px": round(cx - width / 2, 4),
        "pp_offset_y_px": round(cy - height / 2, 4),
        "fx_over_w": round(fx / width, 6) if width else "",
    }


def sanity_rows(calibs: list[dict]) -> list[dict]:
    rows = []
    for calib, camera, info in camera_rows(calibs):
        stats = corner_stats(info)
        width, height = info["image_size"]
        flags = []
        if stats["fx_fy_diff_pct"] > FX_FY_WARN_PCT:
            flags.append("焦距两轴不一致")
        if abs(stats["pp_offset_x_px"]) > PP_WARN_FRAC * width or \
           abs(stats["pp_offset_y_px"]) > PP_WARN_FRAC * height:
            flags.append("主点偏离图像中心过大")
        if stats["fx_over_w"] < F_OVER_W_WARN:
            flags.append("焦距过小/视场角不合理")
        rows.append({
            "board": board_tag(calib), "camera": camera,
            "fx_px": round(float(info["K"][0][0]), 6),
            "fy_px": round(float(info["K"][1][1]), 6),
            "rms_px": round(float(info["rms"]), 9),
            **stats,
            "verdict": "通过" if not flags else "、".join(flags),
        })
    return rows


# --------------------------------------------------------------------------
# 表格定义与 CSV 写出
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Column:
    header: str
    get: Callable[[dict], object]


@dataclass(frozen=True)
class Table:
    filename: str
    title: str
    columns: tuple[Column, ...]


def c(header: str, key: str) -> Column:
    return Column(header, lambda r: r[key])


TABLES = (
    Table("intrinsics.csv", "表 2-1 内参矩阵", (
        c("标定板", "board"), c("相机", "camera"),
        c("图像宽度 (px)", "width_px"), c("图像高度 (px)", "height_px"),
        c("fx (px)", "fx_px"), c("fy (px)", "fy_px"),
        c("cx (px)", "cx_px"), c("cy (px)", "cy_px"),
        c("整体 RMS (px)", "rms_px"),
    )),
    Table("distortion.csv", "表 2-2 畸变系数", (
        c("标定板", "board"), c("相机", "camera"),
        c("k1", "k1"), c("k2", "k2"), c("p1", "p1"), c("p2", "p2"), c("k3", "k3"),
    )),
    Table("sanity.csv", "表 2-3 参数合理性", (
        c("标定板", "board"), c("相机", "camera"),
        c("fx (px)", "fx_px"), c("fy (px)", "fy_px"), c("整体 RMS (px)", "rms_px"),
        c("fx/fy 相对差 (%)", "fx_fy_diff_pct"),
        c("主点偏移 dx (px)", "pp_offset_x_px"), c("主点偏移 dy (px)", "pp_offset_y_px"),
        c("fx/W", "fx_over_w"), c("水平视场角 (°)", "fov_deg"),
        c("角点处 r", "corner_r"), c("角点径向缩放比", "radial_ratio"),
        c("角点径向位移 (px)", "radial_shift_px"), c("角点切向位移 (px)", "tangential_shift_px"),
        c("判定", "verdict"),
    )),
)


def build_rows(calibs: list[dict]) -> list[tuple[Table, list[dict]]]:
    return [(TABLES[0], intrinsic_rows(calibs)),
            (TABLES[1], distortion_rows(calibs)),
            (TABLES[2], sanity_rows(calibs))]


def write_csv(table: Table, rows: list[dict], directory: Path) -> Path:
    path = directory / table.filename
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([column.header for column in table.columns])
        for row in rows:
            writer.writerow([column.get(row) for column in table.columns])
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--calib", type=Path, nargs="*", default=list(DEFAULT_CALIBS),
                    help="calib JSON 路径，可给多份；默认读两块板的正式结果")
    ap.add_argument("--table-dir", type=Path, default=TABLE_DIR, help="CSV 输出目录")
    args = ap.parse_args()

    calibs = load_calibs(args.calib)
    args.table_dir.mkdir(parents=True, exist_ok=True)
    for table, rows in build_rows(calibs):
        path = write_csv(table, rows, args.table_dir)
        shown = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path
        print(f"-> {shown}（{table.title}，{len(rows)} 行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
