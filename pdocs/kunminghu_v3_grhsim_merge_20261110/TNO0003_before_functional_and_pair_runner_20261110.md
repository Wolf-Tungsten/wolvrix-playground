# TNO0003 合并前功能门与配对 runner

## 功能结果

合并前 native GrhSIM 已完成构建（binary SHA256 `54d08d3930f65aa7cb88eade13ab11d270640cec1cb9b3675aa0fd272380ad71`），完整 DiffTest 的 10,000 / 100,000 周期功能运行均通过。

合并前 32 线程 RepCut 的初始分区已编译并通过 100,000 周期 DiffTest；performance pipeline 的后续重复运行、trace 与自动迁移仍在进行中，尚未冻结最终 retained 版本。

两种 simulator 的 100,000 周期结果一致：

| 字段 | native / RepCut |
| --- | --- |
| PC | `0x80000cde` |
| instrCnt | 238535 |
| cycleCnt | 99996 |
| Guest cycle spent | 100001 |
| 终止状态 | cycle-limit |
| UART | `Running CoreMark for 2 iterations` |

原始日志与解析：[before-functional.json](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/before-functional.json)。这些运行与其他构建并行，只用于功能门，不进入正式前后配对统计。

## Harness 修改

- native 和 RepCut 明确传递 `CONFIG=DefaultConfig`；hardware-only 不传研究行为模型参数，接受上游没有 simulation_models manifest 的情形。
- 单核比较新增显式 `--allow-schema-change`：各自使用匹配的 schema 检查原始 trace 记录完整性，保留完整 NEMU 功能门。按版本检查重复运行的 PC/指令数/周期数/UART 输出一致，并记录跨版本进度差异。不同微架构在固定周期数内的提交进度不要求相同。
- 新增 [grhsim32_pair_compare.py](../../scripts/grhsim32_pair_compare.py)，复用 performance 模式的环境与启动命令；只接受完成的 performance 构建和相同的 32 CPU、NUMA、code-page 配置。每个版本运行 10k smoke、100k verify、warmup，然后 8 对 AB/BA。
- 配对 runner 复制和预触页 binary/NEMU/依赖库/workload，监控线程 affinity、NUMA 页面、ASLR 和 code-page 状态。仅通过这些门的样本进入内部 Host time 与外部 walltime 的配对 bootstrap 统计。
- Workload 与 NEMU 已复制到 `inputs/` 并记录 SHA，避免 ready-to-run 子模块更新改变测量输入。

## 检查记录

`PYTHONPATH=scripts python3 -m unittest scripts.test_grhsim32_pair_compare scripts.test_grhsim_single_compare scripts.test_grhsim_single_baseline scripts.test_grhsim32`：45 项通过。涵盖默认/性能流程隔离、CPU/config gate、pair 顺序与统计、功能签名和 trace 检查。后续 runner 增量变更仍需最终检查。

前置构建发现当前 XiangShan 的 Constantin 输出依赖 source 下 `build/` 目录；已在统一 harness 创建目录，before 重新构建成功。首次失败日志保留，未复用失败 binary。

## 后续入口

完整原始构建树通过 [builds](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/builds) 指向独立 before/after 输出；适配过程见 [TNO0002](./TNO0002_difftest_merge_port_20261110.md)。本记录没有合并后的功能或性能结论。

## 增量：配对 runner 实机 gate

新增 runner 使用 before 初始 binary 完成 10,000 周期实机验证，完整 DiffTest、32 线程、CPU0–31、ASLR disabled、code-page PASS、NUMA 本地页面门均通过。使用独立复制并预触页的 binary/NEMU/依赖库/workload。此运行只验证 runner，不进入正式统计。结果见 [pair-runner-smoke/result.json](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/pair-runner-smoke/result.json)。
