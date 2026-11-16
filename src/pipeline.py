#!/usr/bin/env python3
"""组长负责：一键跑完整标定流程。

依次调用：detect_corners → calibrate → evaluate → undistort → report_tables

设计原则：只通过命令行调用其它脚本，不 import 它们的内部函数。
这样任何一个人改自己的模块，都不会影响这里。

用法:
    python src/pipeline.py --board board2
    python src/pipeline.py --board board2 --skip undistort
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

BOARD_FILES = {
    "board2": {"corners": "outputs/corners.json", "calib": "outputs/calib.json"},
    "board1": {"corners": "outputs/corners_board1.json", "calib": "outputs/calib_board1.json"},
}

STEPS = {
    "detect": ["src/detect_corners.py", "--board", "{board}", "--out", "{corners}"],
    "calibrate": ["src/calibrate.py", "--corners", "{corners}", "--out", "{calib}"],
    "evaluate": ["src/evaluate.py", "--all"],
    "undistort": ["src/undistort.py", "--calib", "{calib}"],
    "tables": ["src/report_tables.py"],
}


def run_step(name: str, board: str) -> bool:
    """跑一步，返回是否成功。"""
    fmt = {"board": board, **BOARD_FILES[board]}
    cmd = [PY] + [a.format(**fmt) for a in STEPS[name]]
    print(f"\n=== [{name}] {' '.join(cmd)}")
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=ROOT)
    dt = time.time() - t0
    status = "OK" if proc.returncode == 0 else f"FAIL({proc.returncode})"
    print(f"=== [{name}] {status}  {dt:.1f}s")
    return proc.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", default="board2", choices=["board1", "board2"])
    ap.add_argument("--skip", nargs="*", default=[], choices=list(STEPS))
    args = ap.parse_args()

    failed = []
    for name in STEPS:
        if name in args.skip:
            print(f"=== [{name}] skipped")
            continue
        if not run_step(name, args.board):
            failed.append(name)
            if name in ("detect", "calibrate"):
                print(f"\n{name} 失败，后续步骤依赖它，终止。")
                break

    print("\n" + "=" * 40)
    if failed:
        print("失败步骤:", ", ".join(failed))
        return 1
    print("全部完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())