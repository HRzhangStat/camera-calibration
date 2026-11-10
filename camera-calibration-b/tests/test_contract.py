#!/usr/bin/env python3
"""组长负责：接口契约测试。

验证 A/B 产出的 json 是否符合 README 里约定的格式。
这是并行开发的保险丝——谁改了字段名，这里会立刻报错。

可以直接运行，也可以被 pytest 收集：
    python tests/test_contract.py
    pytest tests/
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = ROOT / "outputs"


def _load(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def check_corners(data: dict) -> list[str]:
    errs: list[str] = []
    for key in ("board", "pattern", "square_mm", "images"):
        if key not in data:
            errs.append(f"corners.json 缺少字段: {key}")
    pattern = data.get("pattern")
    n = pattern[0] * pattern[1] if pattern else None
    for i, rec in enumerate(data.get("images", [])):
        for key in ("file", "camera", "image_size", "corners", "ok"):
            if key not in rec:
                errs.append(f"images[{i}] 缺少字段: {key}")
        if rec.get("ok") and n is not None and len(rec.get("corners", [])) != n:
            errs.append(
                f"images[{i}] {rec.get('file')} 角点数 {len(rec.get('corners', []))} != {n}"
            )
        if rec.get("corners"):
            pt = rec["corners"][0]
            if not (isinstance(pt, list) and len(pt) == 2):
                errs.append(f"images[{i}] corners 元素应为 [x, y]")
    return errs


def check_calib(data: dict) -> list[str]:
    errs: list[str] = []
    for key in ("board", "pattern", "square_mm", "cameras"):
        if key not in data:
            errs.append(f"calib.json 缺少字段: {key}")
    for camera, info in data.get("cameras", {}).items():
        for key in ("image_size", "K", "dist", "rms", "per_image"):
            if key not in info:
                errs.append(f"cameras[{camera}] 缺少字段: {key}")
        K = info.get("K")
        if K is not None and (len(K) != 3 or any(len(row) != 3 for row in K)):
            errs.append(f"cameras[{camera}].K 应为 3x3")
        dist = info.get("dist")
        if dist is not None and len(dist) != 5:
            errs.append(f"cameras[{camera}].dist 长度应为 5")
        if info.get("rms") is not None and not (0 <= info["rms"] < 100):
            errs.append(f"cameras[{camera}].rms 数值异常: {info['rms']}")
    return errs


def test_corners_contract() -> None:
    data = _load(OUTPUTS / "corners.json")
    if data is None:
        print("[skip] outputs/corners.json 不存在")
        return
    errs = check_corners(data)
    assert not errs, "\n".join(errs)


def test_calib_contract() -> None:
    data = _load(OUTPUTS / "calib.json")
    if data is None:
        print("[skip] outputs/calib.json 不存在")
        return
    errs = check_calib(data)
    assert not errs, "\n".join(errs)


def main() -> int:
    failed = 0
    for fn in (test_corners_contract, test_calib_contract):
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"[FAIL] {fn.__name__}\n{exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())