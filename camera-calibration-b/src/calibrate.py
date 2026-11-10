#!/usr/bin/env python3
"""B: validated monocular calibration. Files communicate through the frozen JSON API.

Use --corners /path/to/A/outputs/corners.json. No automatic rescaling is performed.
An audit sidecar records input hashes, exclusions and the selected model.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import uuid
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = ROOT / 'outputs'
VARIANTS = {
    'default': 0,
    'fix_k3': cv2.CALIB_FIX_K3,
    'zero_tangent': cv2.CALIB_ZERO_TANGENT_DIST,
    'fix_k3+zero_tangent': cv2.CALIB_FIX_K3 | cv2.CALIB_ZERO_TANGENT_DIST,
}


def build_object_points(pattern, square_mm):
    cols, rows = pattern
    obj = np.zeros((cols * rows, 3), np.float32)
    obj[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2) * square_mm
    return obj


def calibrate_camera(objpoints, imgpoints, image_size, flags=0):
    rms, K, dist, rv, tv = cv2.calibrateCamera(
        objpoints, imgpoints, tuple(image_size), None, None, flags=flags,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 2000, 1e-10))
    if not all(np.isfinite(v).all() for v in (K, dist, np.array([rms]))):
        raise ValueError('Nonfinite calibration result')
    if K[0, 0] <= 0 or K[1, 1] <= 0:
        raise ValueError('Nonpositive focal length')
    return K, dist.ravel(), float(rms), rv, tv


def prepare(data, image_root, cameras=None):
    """Validate every record against original images and the repository camera manifest."""
    expected = {'board1': ([9, 9], 50.0), 'board2': ([7, 6], 30.0)}
    board = data['board']
    if board not in expected or (data['pattern'], data['square_mm']) != expected[board]:
        raise ValueError('Unexpected board pattern or square_mm; check A handoff')
    manifest = json.loads((ROOT / 'data/manifest.json').read_text())['boards'][board]
    allowed = {f'data/{board}/{name}': cam for cam, files in manifest['cameras'].items() for name in files}
    groups, audit, seen = {}, [], set()
    for rec in data['images']:
        file, cam = rec['file'], rec['camera']
        if file in seen or allowed.get(file) != cam:
            raise ValueError(f'Duplicate or wrong camera: {file} / {cam}')
        seen.add(file)
        if type(rec['ok']) is not bool:
            raise ValueError(f'Invalid ok: {file}')
        if not rec['ok']:
            audit.append({'file': file, 'camera': cam, 'reason': 'A detection failed'})
            continue
        size = rec['image_size']
        if len(size) != 2 or any(type(v) is not int or v <= 0 for v in size):
            raise ValueError(f'Invalid image_size: {file}')
        path = image_root / file
        raw = path.read_bytes()
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
        if image is None or list(image.shape[::-1]) != size:
            raise ValueError(f'Original image size mismatch: {file}')
        pts = np.asarray(rec['corners'], np.float32)
        if pts.shape != (np.prod(data['pattern']), 2) or not np.isfinite(pts).all():
            raise ValueError(f'Invalid point count/coordinates: {file}')
        if np.any(pts < 0) or np.any(pts >= np.asarray(size)) or len(np.unique(pts, axis=0)) != len(pts):
            raise ValueError(f'Outside/duplicate corners: {file}')
        # A ordering is a regular topological grid, not a global sort of pixel x/y.
        cols, rows = data['pattern']
        grid = pts.reshape(rows, cols, 2)
        dx, dy = np.diff(grid, axis=1), np.diff(grid, axis=0)
        cross = dx[:-1, :, 0] * dy[:, :-1, 1] - dx[:-1, :, 1] * dy[:, :-1, 0]
        if not (np.all(cross > 0) or np.all(cross < 0)):
            raise ValueError(f'Folded grid / wrong ordering: {file}')
        groups.setdefault(cam, []).append(rec)
        audit.append({'file': file, 'camera': cam, 'image_size': size,
                      'sha256': hashlib.sha256(raw).hexdigest(), 'reason': 'candidate'})
    if cameras:
        if set(cameras) - groups.keys():
            raise ValueError('Requested camera not present')
        groups = {cam: groups[cam] for cam in cameras}
    selected = {}
    for cam, records in groups.items():
        counts = Counter(tuple(r['image_size']) for r in records)
        max_count = max(counts.values())
        winners = [size for size, n in counts.items() if n == max_count]
        if len(winners) != 1:
            raise ValueError(f'{cam}: ambiguous resolution subset; no rescaling evidence')
        size = winners[0]
        records = [r for r in records if tuple(r['image_size']) == size]
        if len(records) < 3:
            raise ValueError(f'{cam}: fewer than 3 same-resolution views; group is limited')
        selected[cam] = records
    used = {r['file'] for records in selected.values() for r in records}
    for item in audit:
        if item['reason'] == 'candidate':
            item['reason'] = ('used' if item['file'] in used else
                              'camera not selected' if item['camera'] not in selected else
                              'excluded: different resolution, scaling unproven')
    if not selected:
        raise ValueError('No usable camera groups')
    return selected, audit


def fit_records(records, obj, flags):
    points = [np.asarray(r['corners'], np.float32).reshape(-1, 1, 2) for r in records]
    K, dist, rms, rvecs, tvecs = calibrate_camera([obj] * len(records), points, records[0]['image_size'], flags)
    per_image = []
    for r, points2d, rv, tv in zip(records, points, rvecs, tvecs):
        projected = cv2.projectPoints(obj, rv, tv, K, dist)[0]
        error = projected.astype(np.float64) - points2d
        error_rms = float(np.sqrt(np.mean(np.sum(error.reshape(-1, 2)**2, axis=1))))
        R = cv2.Rodrigues(rv)[0]
        if np.any((obj @ R.T + tv.reshape(1, 3))[:, 2] <= 0):
            raise ValueError(f'Board behind camera: {r["file"]}')
        per_image.append({'file': r['file'], 'rms': error_rms,
                          'rvec': rv.ravel().tolist(), 'tvec': tv.ravel().tolist()})
    if not np.isclose(rms, np.sqrt(np.mean([p['rms']**2 for p in per_image])), atol=2e-4):
        raise ValueError('Global and per-image RMS disagree')
    return {'image_size': records[0]['image_size'], 'K': K.tolist(), 'dist': dist.tolist(),
            'rms': rms, 'per_image': per_image}


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--corners', type=Path, default=OUTPUTS / 'corners.json')
    ap.add_argument('--out', type=Path, default=OUTPUTS / 'calib.json')
    ap.add_argument('--image-root', type=Path, default=ROOT)
    ap.add_argument('--camera', action='append', help='Optional camera filter (repeatable)')
    ap.add_argument('--model', choices=VARIANTS, default='fix_k3', help='Conservative small-view default; compare with exp_flags.py')
    args = ap.parse_args()
    raw = args.corners.read_bytes()
    data = json.loads(raw)
    groups, audit = prepare(data, args.image_root, args.camera)
    obj = build_object_points(data['pattern'], data['square_mm'])
    result = {k: data[k] for k in ('board', 'pattern', 'square_mm')}
    result['cameras'] = {}
    for cam, records in groups.items():
        result['cameras'][cam] = fit_records(records, obj, VARIANTS[args.model])
        print(f"[{cam}] {len(records)} views, RMS={result['cameras'][cam]['rms']:.6f} px")
    write_json(args.out, result)
    write_json(args.out.with_suffix('.audit.json'), {
        'run_id': str(uuid.uuid4()),
        'result_sha256': hashlib.sha256(args.out.read_bytes()).hexdigest(),
        'initialization': {'cameraMatrix': None, 'distCoeffs': None, 'use_intrinsic_guess': False},
        'object_points_sha256': hashlib.sha256(obj.tobytes()).hexdigest(),
        'opencv_build_sha256': hashlib.sha256(cv2.getBuildInformation().encode()).hexdigest(),
        'opencv_threads': cv2.getNumThreads(),
        'corners_file': args.corners.name, 'corners_sha256': hashlib.sha256(raw).hexdigest(),
        'model': args.model, 'flags': VARIANTS[args.model], 'opencv': cv2.__version__,
        'numpy': np.__version__, 'python': platform.python_version(), 'images': audit,
        'solver': {'max_iterations': 2000, 'epsilon': 1e-10},
        'status': ('limited_intrinsic_unidentifiable' if data['board'] == 'board2' else 'provisional_small_view_subset'),
        'resolution_policy': 'Unique largest same-resolution subset; no pixel scaling',
        'limitations': 'Only 3-4 views per camera. Provisional parameters, no held-out accuracy claim. '
                        'Use only listed files/resolution; do not transfer between camera groups.'})
    print(f'-> {args.out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
