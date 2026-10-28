# TNO0342：自动迁移验收与 Verilog 到 emu 流程收束

日期：2026-10-27。本轮完整流程已完成，机器可读结果为 [result.json](../../build/grhsim_auto_flow_20261027_allcores/result.json)。

## 自动候选的完整构建与检查

候选来源和规则见 [TNO0341](./TNO0341_grhsim_automatic_migration_selection_20261027.md)：工具从 72 个提案中选择 `piece_957948_p4_to_7`，迁移 1925 个完整 ASC。全流程没有人工提供 memory 名称或迁移源/目的分区。

候选含 7534 个 C++ 对象；32 分区、10 表执行计划分析通过，耗时 819.12 s。与初解的计划身份、完整后端选项一致。编译使用相同的 Clang23/O3/native/no-SLP，保持自身 Makefile 成员顺序，耗时 193.14 s；6934 个 compute 入口全部 64B 对齐。代码生成完成后，计划核验与编译独立并行；全部退出后才开始正式测试。

初解与候选均使用通用编译兼容规则，不含诊断时的强制激活或单分区编译补丁。候选 executable SHA256：`1872cdad8f470cdabab23022566bd80bfea6c34a4ea9bed11c43152e4e3b06e7`。

## Fresh AB/BA 与取舍

node030 CPU96–127、32 线程、C100000、preferred NUMA1、all-spin、ASLR off、代码 THP，8 对 AB/BA。正式 16 次与 2 次 C100 smoke 的功能、THP 和输入身份全部通过。

| 指标 | 自动初解 | 自动迁移 | 配对变化中位数 | 候选更快 |
|---|---:|---:|---:|---:|
| 进程 walltime (s) | 14.7900 | 14.7300 | -0.136% | 5/8 |
| Host (s) | 14.7000 | 14.6420 | -0.160% | 5/8 |
| global eval (µs) | 59.4690 | 59.2370 | +0.061% | 3/8 |
| global update (µs) | 9.4150 | 9.3850 | -0.604% | 5/8 |
| max part eval (µs) | 38.7145 | 38.7030 | +0.114% | 4/8 |
| sum part eval (µs) | 645.5575 | 647.0875 | +0.403% | 2/8 |

候选的 walltime 配对中位改善 0.136%，但只有 5/8 对更快，没有满足预先固定的“负变化且至少 6/8 更快”的第一轮门槛。因此不进入第二轮、不保留迁移；保留自动初解作为本轮完整自动生成路线的产物。这里不是宣称已证明候选绝无收益，而是按本轮预先约定的有限搜索和接受规则停止。

[AB/BA 汇总](../../build/grhsim_auto_flow_20261027_allcores/automatic_candidate/ab_ba_r1/summary.json)、[THP 核验](../../build/grhsim_auto_flow_20261027_allcores/automatic_candidate/ab_ba_r1/thp_verification.json)、[最终取舍](../../build/grhsim_auto_flow_20261027_allcores/automatic_migration/result.json)。

## 最终交付与性能边界

- Verilog 重新 ingest → 结构 memory 筛选 → mem-to-reg → 从头 32 分区 → 完整 preset 生成/编译 → 功能与 walltime → 新 profile 自动提出并验证一次迁移，已经完整跑通。
- 自动筛选 206 个 memory 切集并接受 3 个 memory；名单和预算来自工具。恢复版只提供后端选项和性能参考，没有作为新 assignment 起点。
- 全自动保留 binary：`build/grhsim_auto_flow_20261027_allcores/initial/harness/grhsim-compile/emu`，SHA256 `ea5aad2a0552d73ad1bad7e9a4328304201ffda5a47020e98ebe190c19890ed8`。
- 与恢复版直接对照的独立窗口为 walltime **11.015 → 14.725 s，配对 +34.107%，0/8 更快**，见 [TNO0340](./TNO0340_grhsim_automatic_initial_runtime_20261027.md)。自动路线尚未追平最佳恢复版；该比较包含编译兼容策略的差异，不能全部归因为划分。
- 本轮完成 32 次正式 C100000 和 4 次正式前 C100 smoke，另有 4 次完整 trace 和 2 次 trace smoke。插桩数据只用于提出候选，不作为普通 walltime。
- 26 项相关 Python 测试、GCC/Clang 编译兼容回归及 Python 编译、diff 空白检查通过。原功能失败已用独立 fixture 定位并加入通用兼容处理，见 [TNO0339](./TNO0339_grhsim_clang23_change_reduction_20261027.md)。

复现入口为 [run.sh](../../build/grhsim_auto_flow_20261027_allcores/run.sh)，实现为 [repcut_grhsim_auto_flow.py](../../scripts/repcut_grhsim_auto_flow.py)。`--output` 使用新目录即可重新开始；原目录支持通过身份核验的断点续跑。直接生成的包也附有同一编译兼容规则，避免绕过驱动重编时漏掉保护。

CPU 口径：生成/分析/编译允许全部 0–383；正式 walltime 固定 96–127。ingest 启动时遗漏两个 CPU 范围，已在运行中修正，原始启动记录与 [修正记录](../../build/grhsim_auto_flow_20261027_allcores/generation_affinity_correction.json) 均保留。后续求解和编译均记录为 384 个 CPU。

完整参数、规则预算、输入/工具/二进制身份及未接受候选的结果均保留在本轮目录中；未将这条较慢的自动路线替换为生产默认，也未覆盖恢复版。
