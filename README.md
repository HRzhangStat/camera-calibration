# PJ1 相机标定

课程项目：用 OpenCV 对给定的棋盘格图像做单目相机标定，输出内参矩阵、畸变系数与精度评估，并撰写报告。

- 截止时间：**11 月 18 日 23:59**
- 提交物：报告（`组号-相机标定.docx`）+ 代码打包
- 讲解：用报告讲，**每位组员都要讲**

---

## 目录结构

```
camera-calibration/
├── data/
│   ├── manifest.json          # 数据清单：哪张图属于哪块板、哪台相机
│   ├── board1/                # 标定板1：方格 50mm
│   └── board2/                # 标定板2：方格 30mm，7×6 内角点
├── src/
│   ├── detect_corners.py      # A：角点检测      → outputs/corners.json
│   ├── calibrate.py           # B：相机标定      → outputs/calib.json
│   ├── evaluate.py            # C：精度评估      → outputs/figures/eval_*.png
│   ├── undistort.py           # D：畸变校正      → outputs/figures/undistort_*.png
│   ├── report_tables.py       # E：生成报告表格  → outputs/tables/tables.md
│   └── pipeline.py            # 组长：一键跑全流程
├── experiments/               # 对比实验（每人一个）
│   ├── exp_detector.py        # A
│   ├── exp_flags.py           # B
│   ├── exp_views.py           # C
│   └── exp_boards.py          # D
├── tests/
│   └── test_contract.py       # 组长：接口契约测试
├── outputs/                   # 所有脚本产物（不要手改）
├── report/
│   ├── 00-封面与分工.md
│   ├── 01-原理.md             # E
│   ├── 02-方法.md             # E
│   ├── 03a-精度评估.md        # C
│   ├── 03b-畸变校正.md        # D
│   └── 04-结论.md             # 组长
├── scripts/
│   ├── setup_env.sh           # 建 conda 环境
│   └── build_report.sh        # Markdown → docx
├── requirements.txt
└── CONTRIBUTING.md            # 协作规范（先读这个）
```

---

## 快速开始

```bash
# 1. 建环境
bash scripts/setup_env.sh
conda activate calib

# 2. 角点检测
python src/detect_corners.py --board board2

# 3. 标定
python src/calibrate.py --corners outputs/corners.json

# 4. 评估 / 校正
python src/evaluate.py --calib outputs/calib.json
python src/undistort.py --calib outputs/calib.json

# 5. 出报告
bash scripts/build_report.sh
```

---

## 数据说明

### 标定板1（`data/board1/`，方格 **50mm**）

| 相机 | 图片 | 分辨率 |
|---|---|---|
| camA | `1.jpg` `2.jpg` `3.jpg` `4.jpg` | 3456×4608 / 1080×1440 |
| camB | `11.jpg` `12.jpg` `18.jpg` | 1440×1080 |

> ⚠️ **内角点数待确认**。自动检测结果不一致（9×6 最多，另出现 10×8、7×6），说明检测到的是子网格。
> 需要人工数一遍并更新 `data/manifest.json` 里的 `pattern` 字段。

### 标定板2（`data/board2/`，方格 **30mm**，内角点 **7×6**）

| 相机 | 图片 | 分辨率 |
|---|---|---|
| left | `Im_L_1.png` ~ `Im_L_4.png` | 1024×576 |
| right | `Im_R_1.png` ~ `Im_R_4.png` | 1024×576 |

> 7×6 在 8 张图上检测结果完全一致，可信。

---

## 接口约定（重要）

**并行开发的前提是接口先冻结。四个脚本之间只通过文件通信，不能互相 import。**

### `outputs/corners.json` — A 产出，B/C/D 消费

```json
{
  "board": "board2",
  "pattern": [7, 6],
  "square_mm": 30.0,
  "images": [
    {
      "file": "data/board2/Im_L_1.png",
      "camera": "left",
      "image_size": [1024, 576],
      "corners": [[151.2, 123.4], [192.8, 124.1], "..."],
      "detector": "SB",
      "ok": true
    }
  ]
}
```

- `corners`：长度必须等于 `pattern[0] * pattern[1] = 42`，**行优先**（先第一行从左到右，再第二行）
- 顺序必须与 `calibrate.py` 里生成的三维点顺序一致
- 检测失败的图像 `ok: false`，`corners` 为空数组

### `outputs/calib.json` — B 产出，C/D 消费

```json
{
  "board": "board2",
  "pattern": [7, 6],
  "square_mm": 30.0,
  "cameras": {
    "left": {
      "image_size": [1024, 576],
      "K": [[1200.0, 0.0, 512.0], [0.0, 1200.0, 288.0], [0.0, 0.0, 1.0]],
      "dist": [0.12, -0.05, 0.001, 0.002, 0.0],
      "rms": 0.34,
      "per_image": [
        {"file": "data/board2/Im_L_1.png", "rms": 0.31, "rvec": [0.1, 0.2, 0.3], "tvec": [0.0, 0.0, 500.0]}
      ]
    }
  }
}
```

- `K`：3×3 内参矩阵（行优先）
- `dist`：畸变系数 `[k1, k2, p1, p2, k3]`
- `rms`：该相机所有图像的整体重投影误差（像素）
- `per_image`：逐图的误差与外参

### 图表产物

| 脚本 | 输出 |
|---|---|
| `evaluate.py` | `outputs/figures/eval_<camera>_errors.png`（逐图误差柱状图）<br>`outputs/figures/eval_<camera>_reprojection.png`（重投影叠加图）<br>`outputs/tables/eval_summary.csv` |
| `undistort.py` | `outputs/figures/undistort_<camera>_<file>_compare.png`（去畸变前后对比） |

---

## 协作流程

**分工与排期见 [docs/分工说明.md](docs/分工说明.md)。**

协作规范见 [CONTRIBUTING.md](CONTRIBUTING.md)。简述：

```bash
git clone <主仓库地址>
git checkout -b feature/<你的名字>-<任务>
# 只改自己负责的文件
git add . && git commit -m "feat(<模块>): 说明"
git push -u origin feature/<你的名字>-<任务>
# 在 GitHub 上发起 Pull Request 到 main
```

**不要 fork**。所有人直接 clone 主仓库、在分支上工作、提 PR。