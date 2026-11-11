# B 标定交接（谢云洁）

## 版本与输入

当前交付为 PR #1（https://github.com/HRzhangStat/camera-calibration/pull/1），源分支 `xieyunjie-b`，基于 main `d739926`。已按审查意见将 B 实现与产物从嵌套目录移到仓库根目录，只覆盖 B 的两个空壳源码文件，移除重复副本和 11 个缓存文件，算法代码未修改。

两份输入 `outputs/corners.json`、`outputs/corners_board1.json` 是 A 的真实交接成果，本次按组长要求原样补齐，归属 A。A 已独立提交 PR #3（https://github.com/HRzhangStat/camera-calibration/pull/3），检测代码和清单仍由 A 的 PR 交付，本 PR 不复制它们；仅运行 B 不依赖 A PR 合入。不要运行 main 的检测空壳脚本来覆盖已提供的角点。文件哈希见 `b_input_provenance.json` 和 `calib*.audit.json`。

对照结果：交接包与 main 的 README、CONTRIBUTING、requirements 内容相同（换行符不同）；A 实现了 detect_corners.py、exp_detector.py 并更新 manifest。15 张原图逐文件 SHA256 与 main 一致。A 还提供角点叠加图与检测器对比，均由 A 的 PR 交付，不作为 B 算法成果。

## 如何配对

每张图独立建立物体坐标：第 r 行、第 c 列对应 `(c*square_mm, r*square_mm, 0)`，先走列再换行，与 A 的行优先数组逐个配对。板 2 为 7 列×6 行、30 mm、42 点，板 1 为 9×9、50 mm、81 点。板 2 是完整 11×7 网格中固定截出的子网格；其左上点定义为本次局部原点。平移 tvec 的单位为 mm，rvec 为 Rodrigues 旋转向量（弧度）。这些是逐图板坐标到相机坐标的外参，不是双目左右相机之间的外参。

每台相机独立估计参数，不把不同相机或不同板的分组当同一设备。逐图 RMS = sqrt(mean(dx²+dy²))，整体 RMS 对所有点统一计算，不是 x/y 两分量分别取均方根。

## 实际使用图像与正式结果

|板/相机|采用图片|尺寸（宽×高）|RMS px|fx / fy（px）|cx / cy（px）|
|---|---|---|---:|---|---|
|board2/left|Im_L_1.png, Im_L_2.png, Im_L_3.png, Im_L_4.png|1024×576|0.096986|260.818 / 264.016|517.689 / 300.023|
|board2/right|Im_R_1.png, Im_R_2.png, Im_R_3.png, Im_R_4.png|1024×576|0.119219|78.295 / 79.327|479.691 / 279.507|
|board1/camA|2.jpg, 3.jpg, 4.jpg|1080×1440|0.796437|1034.302 / 1036.229|539.590 / 711.058|
|board1/camB|11.jpg, 12.jpg, 18.jpg|1440×1080|0.910601|1083.914 / 1079.001|729.953 / 537.493|

camA 排除 `data/board1/1.jpg`（3456×4608），保留 2/3/4.jpg（1080×1440）。1.jpg 的 EXIF 有 vivo X9 和拍摄时间，另外三张没有相关 EXIF；相同宽高比与 3.2 的分辨率比例不能证明只是缩放。交接说明也未提供这项证据。因此没有缩放原图或坐标，参数不能直接用于 1.jpg。camA 只有三个视图，作为受限子集的暂定结果；不能宣称代表全部分辨率。

## 四种设置与选型

完整对比见 `experiments/flags_board1.md`、`flags_board2.md`，CSV 有全部内参、五个畸变系数、逐图 RMS 另表，`*_all.json` 有每种模型的全部外参。各相机组四种设置的图集完全相同。

正式配置暂用 `fix_k3`（k3=0，保留 k1/k2/p1/p2）。板 1 相比默认模型，camA RMS 增加约 0.0173 px，camB 增加约 0.0057 px；在三个视图上选择较低阶模型作为保守折中，不把这点训练误差收益当成高阶模型的独立验证。camA 跨四设置的焦距仍有约 4% 差异，需补图；camB 参数较稳定。保留切向项是为了不凭空假设镜头完全对称，不代表已经证明其真实值。

**板 2 内参不可可靠识别，正式文件仅保留可复现的暂定解**。fix_k3 的 200 次/2000 次迭代结果：

|相机|200 次 fx / fy|2000 次 fx / fy|RMS 改变（px）|
|---|---|---|---:|
|left|637.026 / 645.001|260.818 / 264.016|-0.000060|
|right|240.034 / 243.216|78.295 / 79.327|-0.000038|

低 RMS 伴随大幅焦距漂移，轻微 0.05 px 角点扰动也会显著改变焦距，说明现有图像几何约束不足。不能把输出 K 当作可靠物理内参；增加迭代预算也不能解决数据可辨识性。需增加倾斜方向、距离和图像边缘覆盖，再由 C 验证。四种设置都没能解决板 2 的限制，不能宣称 fix_k3 已使它可靠。敏感度实验是 10 次固定随机种子的数值试验，不是实际置信区间。个别默认模型 RMS 略高于受限模型是非凸求解现象，不是自由参数更多反而理论拟合能力更差。

## C / D / E 拿什么

- C：板 2 用 `outputs/calib.json` 加 A 的 `corners.json`；板 1 用 `outputs/calib_board1.json` 加 A 的 `corners_board1.json`。必须按 `per_image.file` 选择实际采用图，再匹配角点，不要把 A 的所有图全拿来评估。JSON 中已有每张图的 RMS/rvec/tvec。只允许相同 board/camera/image_size 的配对。
- D：同样两份 calib JSON，按 `image_size` 和 `per_image.file` 读取图像；K/dist 不可跨相机复用，camA 的 1.jpg 不适用。板 2 仅供效果探索，不能宣称实现准确测量。没有对整幅画面外推质量作保证。
- E：`outputs/experiments/flags_board1.md`、`flags_board2.md` 可直接取表，CSV 与 PNG 用于排版；本说明提供设置、单位与局限。不要把训练 RMS 当作泛化精度。

## 从 B 仓库复现

从小组仓库检出 `xieyunjie-b`，在仓库根目录运行。两份真实角点已包含在 outputs/ 中，无需本机交接包路径。正式结果沿用已核查的同次求解，不因目录整理重新标定。

```bash
git clone --branch xieyunjie-b https://github.com/HRzhangStat/camera-calibration.git
cd camera-calibration
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
# 先跑板 2 左相机（临时结果放仓库外）
python src/calibrate.py --corners outputs/corners.json --camera left --out /tmp/pj1-left.json
# 独立标定入口示例（与后续实验是独立运行）：默认 --model fix_k3
python src/calibrate.py --corners outputs/corners.json
python src/calibrate.py --corners outputs/corners_board1.json --out outputs/calib_board1.json
# 最终交付以实验运行同步生成的正式 JSON 和表格为准，不要再单独覆盖正式 JSON
python experiments/exp_flags.py --corners outputs/corners.json
python experiments/exp_flags.py --corners outputs/corners_board1.json
PYTHON=.venv/bin/python bash scripts/check.sh
```

本次环境：Python 3.11.5、OpenCV 5.0.0、NumPy 2.4.6（精确版本以 audit 为准）；标准求解设置 MAX_ITER=2000、EPS=1e-10。不同 OpenCV 或迭代设置可能改变板 2 的弱约束解，这本身属于已记录的局限。

## 验收状态

仓库语法、所有 CLI --help、calib.json 接口检查通过；本次两份角点均已入库，默认 corners 接口检查不再跳过；两份真实角点 JSON 和两份 calib JSON 的显式接口检查也均通过。独立重算每张图及整体 RMS，与输出一致；四组均已用真实原图调用 cv2.undistort 检查数组尺寸。另验证错误点数、NaN、错误尺寸、错误相机、重复文件、乱序网格六类错误，两块板均拒绝。

C 的 evaluate.py 能读取 JSON 并打印整体 RMS，但在尚未实现的 plot_error_bars 抛出 NotImplementedError；没有修改 C 文件。D 的 undistort.py 能读取两份 JSON、计算 new_K/ROI，但实际出图仍是 TODO，本次没有声称 D 全流程完成。组长报告构建脚本因环境未安装 pandoc 无法生成 docx；保留其原文件，不扩大 B 的修改范围。

方法依据：[OpenCV 相机标定文档](https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html)。

## GitHub 交付状态

现有 PR #1 的源分支为 `xieyunjie-b`，继续更新同一 PR，由组长审查合并。早期 `feature/xieyunjie-calibrate` 推送失败是历史状态，当前以本 PR 为交付入口。

## 板 2 right 的 fx 差异核查与修复

旧版 `calib.json` 的 fx=83.33292443633762，而旧版 `flags_board2.md` 显示 80.6221（其完整实验 JSON 为 80.62214479430229），差约 3.25%。对应 RMS 分别为 0.11921932461112252 和 0.1192190303222905 px，差仅约 2.94e-7 px。不是舍入误差。旧数值、完整 right 外参、正式审计与旧产物哈希已保存在 `experiments/reconciliation_board2.json`，不再冒充本次结果。

来源核查：正式 JSON 来自直接执行 calibrate.py；实验表来自 exp_flags.py 再次通过 subprocess 启动 calibrate.py。它们是两个独立求解，虽然按用途应是同一正式配置。执行记录与代码均指向相同交接包 `outputs/corners.json`，当前角点文件 SHA256 与旧正式 audit 一致，为 `3f35b59043ab5af00f1711520438adf356183ec454df47f3c935e643ed213a55`。right 都是按 Im_R_1、2、3、4 的顺序使用 4 张 1024×576 原图，每张 42 点，7×6、30mm、float32，无坐标缩放。

两条代码路径的 flags 都是 `CALIB_FIX_K3=128`，没有 `CALIB_USE_INTRINSIC_GUESS`；传入 cameraMatrix=None、distCoeffs=None，由 OpenCV 自动初始化，并非显式提供不同焦距。终止条件均为 `(EPS|MAX_ITER, 2000, 1e-10)`，是最多 2000 次而非已证明收敛。旧正式审计与当前环境均为 OpenCV 5.0.0、NumPy 2.4.6、Python 3.11.5。旧实验临时 audit 被删除，因此没有保留下当时子进程版本、构建、线程数与有效初始化矩阵的独立证据，不能断言已经查明差异的底层数值原因。数据与迭代敏感性说明弱约束问题，但不应把某个未验证的线程或随机因素当作已证实原因。

修复：exp_flags.py 现在将其同一次 fix_k3 求解的结果同时写入正式 JSON、CSV、Markdown 和 all.json，不再额外重算正式配置。板 1 同样采用这条路径。正式 audit 与 `flags_<board>_audit.json` 保留相同 run_id、结果 SHA256、输入 SHA256、flags、初始化方式、终止条件、运行版本、OpenCV 构建哈希及线程数。运行后若单独覆盖 calib.json，它就不再是这份对比表的对应产物，应重跑实验统一生成。

本次板 2 right 的正式 fx=78.295364537751，表中按 6 位有效数字显示 `78.2954`；运行标识 `3ba1e1d7-2dce-420d-af64-08afcbf899b7`。完整参数逐字段一致，不是只手改 fx。板 2 内参受限的结论保持。

本次修复验收：两块板正式 JSON 均与实验 all.json 的 fix_k3 完整字典相等；各设置 CSV 内参/畸变/RMS、逐图 CSV 误差与源结果逐项一致，Markdown fx 按相同格式舍入，运行 ID 与结果哈希对应。仓库 check.sh、两份真实角点及两份 calib 契约、独立重投影 RMS 复算、真实图像 undistort 和六类异常输入检查全部通过。目录整理后再次执行默认 corners 接口测试，不再跳过。


## 给组长的技术答复

`fx≈78.3` 是当前数据与求解配置下的暂定数值，不是已验证的真实焦距。迭代预算、模型设置和微小角点扰动使焦距明显变化而 RMS 几乎不变，这支持数据约束不足、内参估计病态的判断。点数/顺序、单位、图像分组、尺寸、输入哈希和误差复算检查未发现实现错误；现有检查不能绝对排除所有 bug，也没有证明具体底层数值差异的原因。报告可将“低重投影 RMS 不保证内参可靠”作为主要发现。约 160° 是把不可靠内参代入理想针孔公式得到的估算，不能当作相机真实视场角。
