# 协作规范

## 一、分支与提交

### 每人一个分支

| 成员 | 分支名 | 负责文件 |
|---|---|---|
| 组长 | `feature/<名字>-repo` | `README.md` `CONTRIBUTING.md` `scripts/` `src/pipeline.py` `tests/` `.github/` `report/00-*.md` `report/04-*.md` |
| A | `feature/<名字>-detect` | `src/detect_corners.py` `experiments/exp_detector.py` `data/manifest.json` |
| B | `feature/<名字>-calibrate` | `src/calibrate.py` `experiments/exp_flags.py` |
| C | `feature/<名字>-evaluate` | `src/evaluate.py` `experiments/exp_views.py` `report/03a-*.md` |
| D | `feature/<名字>-undistort` | `src/undistort.py` `experiments/exp_boards.py` `report/03b-*.md` |
| E | `feature/<名字>-report` | `src/report_tables.py` `report/01-*.md` `report/02-*.md` |

> **只改自己那一列的文件。** 需要改别人的文件时，先在群里说，或者在自己的 PR 里留言让对方改。

### 提交信息格式

```
feat(detect): 完成 7×6 角点检测
fix(calibrate): 修正畸变系数顺序
docs(report): 补充单应矩阵推导
```

类型：`feat` / `fix` / `docs` / `chore`

---

## 二、日常流程

```bash
# 第一次
git clone https://github.com/<组长>/camera-calibration.git
cd camera-calibration
git checkout -b feature/<名字>-<任务>

# 每天开始前：同步主分支
git checkout main
git pull origin main
git checkout feature/<名字>-<任务>
git merge main            # 有冲突就在这一步解决

# 干活、提交
git add <你改的文件>
git commit -m "feat(detect): ..."
git push origin feature/<名字>-<任务>

# 完成后：在 GitHub 上提 Pull Request → main
```

---

## 三、合并规则

- PR 标题写清楚做了什么，例如 `[A] 角点检测完成，7×6，8 张全部成功`
- PR 描述里贴一张产物截图（角点图 / 误差图 / 对比图）
- **组长负责 review 和 merge**，其他人不要自己合并
- 合并后立刻删掉远程分支

---

## 四、不能提交的东西

`.gitignore` 已经配好，但仍然强调：

- ❌ 原始 `.rar` 压缩包
- ❌ 虚拟环境目录 `.venv/` `env/`
- ❌ 编辑器临时文件 `.vscode/` `.idea/` `.DS_Store`
- ❌ 大模型权重、临时实验文件

✅ `outputs/` 里的图**要提交**，因为报告要引用。

---

## 五、并行开发的约定

1. **接口以 README 为准**，不要私自改 `corners.json` / `calib.json` 的字段。要改先在群里讨论并更新 README。
2. **拿不到上游数据时用假数据先跑通**。比如 B 还没拿到 A 的 `corners.json`，可以自己手写一个只有 2 张图的小 json 调试流程。
3. **每天至少 push 一次**，避免最后一天集中合并。
4. **报告用 Markdown 写**，不要直接改 docx（二进制无法合并）。

---

## 六、提交前检查

```bash
python -m py_compile src/*.py     # 语法检查
bash scripts/build_report.sh      # 报告能否正常生成
```

确认生成的 docx 命名为 `组X-相机标定.docx`。