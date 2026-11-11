# TNO0027 当前 before 的独立 8-seed 分区重试

## 实验控制

目的：在源图不变的条件下，检查标准 8 次并行分区选择的随机性是否能解释当前 before 的较慢 walltime。输入直接复用 before 的冻结 `memory.json`、完整/缩减 HGR，重新启动 seeds 0–7 的八个 Mt-KaHyPar 进程；不重新 elaboration、frontend 或 memory lowering。

参数沿用原 before：32 partitions，隔离 oversized 节点 `[5]` 后求解 31 partitions，epsilon=0.05，6 维容量约束，`km1` 目标，8 个 seed 各 48 solver threads。选择完整图容量可行且 `km1` 最小者；这不等于实测八个 binary 后取最快者。

编译使用原 before 的 `/usr/bin/clang++` 19.1.1、`-std=c++20 -O3 -march=native -pthread` 与 64-byte 对象代码节对齐。GrhSIM emission 配置、冻结 DiffTest generated headers、XiangShan `77ed568fc` / DiffTest `26af3a5e` harness、CoreMark 和 NEMU 相同。工具和输入 SHA256 见 [provenance](../../build/xs/repcut-before-retry-20261111/provenance.json)，[构建入口](../../build/artifacts/repcut-before-retry-20261111/retry.py) 记录每条生成/编译命令。

本轮专门隔离分区变化，**不执行自动 atom migration**。保留两种对照：原始 seed3 initial 与新 seed2 initial，用于分区重试的直接比较；此前保留的迁移 candidate 与新 seed2 initial，用于回答是否比当前实际使用的 before 更快。

## 分区结果

| seed | 原 before 完整图 km1 | 本轮完整图 km1 |
| ---: | ---: | ---: |
| 0 | 29,502,926 | 29,435,550 |
| 1 | 30,326,621 | 30,237,990 |
| 2 | 30,348,582 | **27,714,651** |
| 3 | **27,756,977** | 29,968,368 |
| 4 | 30,206,289 | 33,246,094 |
| 5 | 30,312,636 | 28,629,322 |
| 6 | 34,289,997 | 28,177,808 |
| 7 | 30,338,875 | 28,109,605 |

八个新结果均通过六维容量约束；相同 seed 的 assignment SHA256 全部不同。选中 seed2，最小 `km1` 比原 seed3 下降约 **0.15249%**。这确认并行求解存在随机性，但不能从 `km1` 直接推断 walltime 改善幅度。[selection.json](../../build/xs/repcut-before-retry-20261111/selection.json) 保留八个结果、原/新 assignment 哈希和选择依据。

## 运行口径

所有实测在 node030，CPU96–127、NUMA1 strict membind、ASLR disabled，保持 performance 模式、thread pinning 和原 code-page/preload 设置；不执行外部 CPU 空闲准入检查。

[测量入口](../../build/artifacts/repcut-before-retry-20261111/measure.py) 复用现有 `grhsim32_pair_compare.Runner`，逐样本检查真实 32 个 singleton affinity、ASLR personality、NUMA mappings、codepage PASS、完整 DiffTest 和冻结 binary/dependency 哈希。旧构建时的 CPU0–31/NUMA0 元数据如实保留；实际测量统一覆盖为 CPU96–127/NUMA1。

每个 binary 先做 10k smoke、100k verification、100k warmup。由于本轮固定相同 before RTL，额外要求三个 binary 的 PC、提交指令数、周期数、终止条件和 workload 输出完全相同。随后两种对照分别执行 8 对 AB/BA，使用固定 seed 20261102 的 10,000 次 paired bootstrap，同时报告 Host time 和外部 walltime。功能或 placement 门拒绝的样本不得纳入统计。

此段记录于分区完成、模型生成期间；实际功能门和 walltime 结果完成后追加于本文后部。

## 完成后的功能与性能结果

三份 binary 均通过 10k smoke、100k 完整 DiffTest 和预热，100k 签名完全一致：PC `0x80000cde`，提交指令数 238,535，cycle_count 99,996，guest_cycles 100,001，cycle-limit 终止，UART 输出 `Running CoreMark for 2 iterations`。全部 **41 次运行**（含 3 次 smoke、验证/预热和两组各 16 个计时样本）通过功能及 CPU/NUMA/ASLR/code-page 门，拒绝样本为 0。[功能记录](../../build/xs/repcut-before-retry-20261111/measurements/functional.json) 和 [运行 manifest](../../build/xs/repcut-before-retry-20261111/measurements/manifest.json) 包含完整证据。

负数表示新 seed2 更快；各行使用自己相邻配对的 8 对样本：

| 对照 | 原版本 Host 均值 / 中位数 | 新 seed2 Host 均值 / 中位数 | 配对均值 / 中位数 delta | bootstrap 95% CI | 新版更快 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 原 seed3 initial → 新 seed2 initial | 18.159125 / 18.1385 s | 16.618500 / 16.5965 s | −8.4786% / −8.7629% | [−9.1293%, −7.7684%] | 8/8 |
| 原 retained candidate → 新 seed2 initial | 17.881375 / 17.9375 s | 16.350875 / 16.3925 s | −8.5480% / −8.4983% | [−9.4328%, −7.6584%] | 8/8 |

| 对照 | 原版本外部 walltime 均值 / 中位数 | 新 seed2 外部 walltime 均值 / 中位数 | 配对均值 delta | bootstrap 95% CI |
| --- | ---: | ---: | ---: | ---: |
| initial → retry | 18.252180 / 18.234459 s | 16.709355 / 16.688717 s | −8.4474% | [−9.0870%, −7.7477%] |
| retained → retry | 17.971143 / 18.026705 s | 16.439386 / 16.479482 s | −8.5123% | [−9.3808%, −7.6209%] |

两组顺序执行，第二组的新 seed2 绝对时间比第一组略低；因此不跨组拼接样本，只分别报告配对差异。两组内部均 8/8 同向，置信区间均低于零。

retained 对照的阶段耗时中位数：input load 459.501 → 454.744 ms，part eval 15,315.172 → 14,023.289 ms，global update 1,772.625 → 1,524.814 ms。收益主要落在分区计算和更新阶段；这些阶段包含调度/同步，不能当作纯算术执行耗时。

## 结论与归档

**重新跑同一 before 的八次分区，确实找到了约快 8.5% 的新方案。** 同图、同 seeds、同配置的不同 assignment 能带来可测差异；`km1` 只降低 0.15%，实际 Host time 降低约 8.5%，说明静态 cut 目标对动态仿真时间的预测有限。只生成最小 `km1` 的一个方案，无法保证得到八个候选中 walltime 最快者。

这只是一次新的 8-seed portfolio，不能估计完整的分区性能分布。新方案仍约 16–17 秒；未在本轮复现历史 10–12 秒水平。结合 [TNO0026](./TNO0026_historical_before_verilog_content_20261111.md) 证实的 RTL 差异和历史 Clang 23 / 当前 Clang 19 差异，不能把历史与当前的全部差距归因于 solver 随机性。

新 binary：100,630,944 B，SHA256 `079da8ac24e10bb16025ce820f3379024a3323d144442f35056e64d7231abc5d`，位于 [retry emulator](../../build/xs/repcut-before-retry-20261111/initial/harness/grhsim-compile/emu)。保留原 before 的 initial/retained 产物与全部旧报告，本轮没有替换默认配置或历史基线。

产物入口：

- [综合机器可读报告](../../build/artifacts/repcut-before-retry-20261111/report.json)、[汇总脚本](../../build/artifacts/repcut-before-retry-20261111/report.py)。
- [initial 配对 CSV](../../build/xs/repcut-before-retry-20261111/measurements/initial-vs-retry/pairs.csv)、[initial summary](../../build/xs/repcut-before-retry-20261111/measurements/initial-vs-retry/summary.json)。
- [retained 配对 CSV](../../build/xs/repcut-before-retry-20261111/measurements/retained-vs-retry/pairs.csv)、[retained summary](../../build/xs/repcut-before-retry-20261111/measurements/retained-vs-retry/summary.json)。
- [原始运行与 placement 日志](../../build/xs/repcut-before-retry-20261111/measurements/)、[构建日志](../../build/artifacts/repcut-before-retry-20261111/build.log)、[测量日志](../../build/artifacts/repcut-before-retry-20261111/measurement.log)。

构建、输入/工具哈希复核、Python 编译检查、文档相对链接及 `git diff --check` 通过；没有修改通用 pipeline/emitter 源码。实验复用现有严格 runner，额外收紧为同 revision 的完整功能签名一致。
