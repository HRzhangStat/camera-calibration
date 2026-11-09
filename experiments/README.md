# 对比实验

每个实验是一个**独立的可执行脚本**，只读 `outputs/` 里的数据，输出自己的图表到 `outputs/experiments/`。

| 脚本 | 负责人 | 做什么 | 输出 |
|---|---|---|---|
| `exp_detector.py` | A | 对比三种角点检测方式：传统 `findChessboardCorners`、`findChessboardCornersSB`、以及是否加亚像素精化 | `outputs/experiments/detector_*.csv/.png` |
| `exp_flags.py` | B | 对比不同 `calibrateCamera` flags 对内参与误差的影响 | `outputs/experiments/flags_*.csv` |
| `exp_views.py` | C | 留一法：用 N-1 张标定、留 1 张验证，看图像数量对精度的影响 | `outputs/experiments/views_*.png` |
| `exp_boards.py` | D | 标定板1 vs 标定板2 的全面对比 | `outputs/experiments/boards_*.csv/.png` |

## 约定

1. **只读 `outputs/corners.json` / `outputs/calib.json`**，不要直接 import 别人模块的内部函数
2. 输出统一放在 `outputs/experiments/`
3. 每个实验在报告里对应一小节，结论要写清楚"这说明什么"
4. 没有真数据时，**先用手写的假 json 跑通流程**，不要等

## 为什么单独放 experiments/

主流程 `src/` 是要交上去的"正经代码"，实验脚本是报告里的论证材料。分开之后：

- 实验脚本可以写得随意一点，不影响主流程可读性
- 每个人可以独立改自己的实验，不会碰到别人的文件
- 报告里"我们做了哪些对比实验"会显得工作量很足