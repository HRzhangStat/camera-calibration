#!/usr/bin/env python3
"""B: flags comparison via the calibration CLI, plus controlled coordinate sensitivity.

No imports from src. All variants consume the same validated image subset.
Sensitivity uses 10 seeded 0.05 px Gaussian perturbations, not a confidence interval.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'outputs/experiments'
VARIANTS = {'default': 0, 'fix_k3': cv2.CALIB_FIX_K3,
            'zero_tangent': cv2.CALIB_ZERO_TANGENT_DIST,
            'fix_k3+zero_tangent': cv2.CALIB_FIX_K3 | cv2.CALIB_ZERO_TANGENT_DIST}


def calibrate_variant(objpoints, imgpoints, size, flags, iterations=2000):
    return cv2.calibrateCamera(objpoints, imgpoints, tuple(size), None, None, flags=flags,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, iterations, 1e-10))


def save_csv(path, rows):
    with path.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--corners', type=Path, default=ROOT/'outputs/corners.json')
    ap.add_argument('--selected-out', type=Path, help='Publish fix_k3 from this exact experiment run (default: outputs/calib[_board1].json)')
    ap.add_argument('--image-root', type=Path, default=ROOT)
    args = ap.parse_args()
    data = json.loads(args.corners.read_text())
    board = data['board']
    OUT.mkdir(parents=True, exist_ok=True)
    prefix = OUT / f'flags_{board}'
    cols, rows = data['pattern']
    obj = np.zeros((cols*rows, 3), np.float32)
    obj[:, :2] = np.mgrid[:cols, :rows].T.reshape(-1, 2)*data['square_mm']
    summary, per_image, fits, audits = [], [], {}, {}
    with tempfile.TemporaryDirectory() as tmp:
        for model, flags in VARIANTS.items():
            target = Path(tmp)/'calib.json'
            subprocess.run([sys.executable, str(ROOT/'src/calibrate.py'), '--corners', str(args.corners.resolve()),
                            '--image-root', str(args.image_root.resolve()), '--model', model, '--out', str(target)], check=True)
            result = json.loads(target.read_text())
            fits[model] = result
            audits[model] = json.loads(target.with_suffix('.audit.json').read_text())
            for cam, info in result['cameras'].items():
                names = [p['file'] for p in info['per_image']]
                records = {r['file']: r for r in data['images']}
                points = [np.asarray(records[n]['corners'], np.float32).reshape(-1, 1, 2) for n in names]
                rng = np.random.default_rng(20261110)  # paired perturbations for every model
                params = []
                for _ in range(10):
                    jittered = [(p + rng.normal(0, .05, p.shape)).astype(np.float32) for p in points]
                    _, K, dist, _, _ = calibrate_variant([obj]*len(points), jittered, info['image_size'], flags)
                    params.append([K[0,0], K[1,1], K[0,2], K[1,2], *dist.ravel()])
                std = np.std(params, axis=0, ddof=1)
                rms200, K200, _, _, _ = calibrate_variant([obj]*len(points), points, info['image_size'], flags, 200)
                K = np.array(info['K'])
                row = dict(board=board, camera=cam, model=model, flags=flags, n_images=len(names),
                           files=';'.join(names), rms_px=info['rms'], fx=K[0,0], fy=K[1,1], cx=K[0,2], cy=K[1,2])
                row.update(rms_200_iter=rms200, fx_200_iter=float(K200[0,0]), fy_200_iter=float(K200[1,1]))
                row.update(zip(('k1','k2','p1','p2','k3'), info['dist']))
                row.update(zip(('noise_std_fx','noise_std_fy','noise_std_cx','noise_std_cy',
                                'noise_std_k1','noise_std_k2','noise_std_p1','noise_std_p2','noise_std_k3'), std.tolist()))
                summary.append(row)
                for p in info['per_image']:
                    per_image.append(dict(board=board, camera=cam, model=model, file=p['file'], rms_px=p['rms']))
    # Publish the exact same fit used below; never recalibrate the selected model here.
    selected_out = args.selected_out or ROOT / 'outputs' / ('calib.json' if board == 'board2' else 'calib_board1.json')
    selected_out.parent.mkdir(parents=True, exist_ok=True)
    selected_out.write_text(json.dumps(fits['fix_k3'], ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    assert hashlib.sha256(selected_out.read_bytes()).hexdigest() == audits['fix_k3']['result_sha256']
    selected_out.with_suffix('.audit.json').write_text(json.dumps(audits['fix_k3'], ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (OUT/f'flags_{board}_audit.json').write_text(json.dumps(audits, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    save_csv(prefix.with_suffix('.csv'), summary)
    save_csv(OUT/f'flags_{board}_per_image.csv', per_image)
    (OUT/f'flags_{board}_all.json').write_text(json.dumps(fits, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    lines = [f'# {board}：B 的设置对比', '',
             f"正式 JSON 与本表 fix_k3 由同一份结果生成，运行标识 `{audits['fix_k3']['run_id']}`；完整来源见 flags_{board}_audit.json。", '',
             '四种设置使用相同原图坐标和同一批图。k3 固定为 0；固定切向指 p1=p2=0，fix_k3 仍估计 p1/p2。', '',
             '|相机|设置|图数|RMS (px)|fx|fy|cx|cy|k1|k2|p1|p2|k3|噪声敏感度 fx/fy (px)|',
             '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|']
    for r in summary:
        vals = [r['camera'], r['model'], str(r['n_images'])] + [f'{r[k]:.6g}' for k in ('rms_px','fx','fy','cx','cy','k1','k2','p1','p2','k3')]
        vals.append(f"{r['noise_std_fx']:.3g} / {r['noise_std_fy']:.3g}")
        lines.append('|'+'|'.join(vals)+'|')
    lines += ['', '敏感度：固定输入图集，对全部像素点加入独立 σ=0.05 px 高斯噪声，随机种子 20261110，重复 10 次；报告参数样本标准差。',
              '这是数值敏感性实验，不能作为实际参数置信区间，也不能代替 C 的独立视图评估。CSV 另含 200 次迭代结果供与主结果 2000 次迭代比较，并包含全部参数的敏感度；all.json 包含四种设置的完整外参。', '']
    for cam in fits['default']['cameras']:
        subset = [r for r in summary if r['camera']==cam]
        default, fixed = subset[0], subset[1]
        lines += [f"- {cam}：fix_k3 相对默认 RMS 增加 {fixed['rms_px']-default['rms_px']:.6f} px；"
                  f"默认 k3={default['k3']:.6g}，其噪声标准差={default['noise_std_k3']:.6g}。"
                  f"四设置 fx 范围 {min(r['fx'] for r in subset):.3f}–{max(r['fx'] for r in subset):.3f} px，"
                  f"fy 范围 {min(r['fy'] for r in subset):.3f}–{max(r['fy'] for r in subset):.3f} px。"]
    if board == 'board2':
        lines += ['', '**板 2 内参受限**：焦距随设置、像素扰动和迭代预算显著变化，低训练 RMS 未能确定唯一可靠内参；K/dist 仅供复现分析，不能用于可信测量。建议补拍不同倾角、距离和边缘覆盖的图像。',
                  '默认模型是非凸优化；若其 RMS 略高于受限模型，表示优化未找到一致的最小值，不能据此声称受限模型具有更好的训练拟合能力。']
    lines += ['', '正式配置暂用 fix_k3：视图少且高阶径向项约束弱，限制高阶自由度，同时保留切向畸变以免无依据强设对称。',
              '选型须结合上表 RMS 代价、内参跨设置变化与噪声敏感度审查；全部结果为受限数据上的暂定估计，不能仅因训练 RMS 小就称为高精度。',
              '板 1 camA 只使用 2/3/4.jpg；1.jpg 分辨率不同且没有仅缩放证据，未做任何换算。',
              '方法依据：[OpenCV calibrateCamera / projectPoints](https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html)。', '']
    prefix.with_suffix('.md').write_text('\n'.join(lines), encoding='utf-8')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout='constrained')
    for cam in fits['default']['cameras']:
        rs = [r for r in summary if r['camera']==cam]
        axes[0].plot(range(4), [r['rms_px'] for r in rs], 'o-', label=cam)
        axes[1].plot(range(4), [r['noise_std_fx'] for r in rs], 'o-', label=cam)
    for ax, title, unit in zip(axes, ('Training reprojection RMS', 'fx sensitivity to 0.05 px noise'), ('RMS (px)', 'Sample std (px)')):
        ax.set_xticks(range(4), ['default','fix k3','zero tangent','both'], rotation=15)
        ax.set_title(f'{board}: {title}')
        ax.set_ylabel(unit)
        ax.legend()
        ax.grid(alpha=.25)
    fig.savefig(prefix.with_suffix('.png'), dpi=160)
    plt.close(fig)
    print(f'-> {prefix}.*')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
