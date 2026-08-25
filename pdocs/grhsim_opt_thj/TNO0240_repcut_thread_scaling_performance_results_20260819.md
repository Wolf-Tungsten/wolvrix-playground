# RepCut 1/2/4/8 线程性能结果与证据边界

日期：2026-08-19

状态：`BLOCKED — NO VALID FORMAL MATRIX`。

## 1. 直接回答

本轮没有可发布的 `run_xs_repcut` 与 `run_xs_repcut_verilator` 线程缩放性能表。原因不是机器资源不足，而是同一份冻结 RepCut RTL 在正确的 `difftest-config G` profile 下仍于 guest cycle 605 触发 `csr_dbltrp_inMN` assertion。功能不通过时，失败前的 host 时间不能当作仿真吞吐量，也不能跨线程或跨后端比较。

因此，本轮正式 headline `Host time spent` 的状态如下：

| 入口 | N=1 | N=2 | N=4 | N=8 |
| --- | --- | --- | --- | --- |
| `run_xs_repcut`（native） | `N/A — gate blocked` | `N/A — gate blocked` | `N/A — gate blocked` | `N/A — gate blocked` |
| `run_xs_repcut_verilator`（partitioned） | `N/A — gate blocked` | `N/A — gate blocked` | `N/A — gate blocked` | `N/A — gate blocked` |

预注册的正式样本数是 `2 backends × 4 thread counts × 4 samples = 32`；正式 runner 在功能门之前停止，实际“启动/接受”均为 `0/32`，不是 32 个失败样本。没有计算 speedup、并行效率或 partitioned/native 比值，避免从不等价运行中推导结论。

## 2. 已获得但不构成正式结果的数字

### 2.1 失败 probe

正确 G profile 的 partitioned `-C 1000 --no-diff` probe：

```text
exit=1, ABORT, cycleCnt=605, guest=609, Host time spent=5425ms,
assertion=ExuBlock.sv:908, critical error=csr_dbltrp_inMN
```

`5425 ms` 是到 assertion 的失败耗时；它不是完成 1000 cycles 的耗时，也不是可与 native 对照的运行样本。完整日志见 [TNO0239](./TNO0239_repcut_thread_scaling_build_and_functional_gates_20260819.md)。

### 2.2 初轮错误 profile 构建与 canary

初轮 native `t1/t2/t4/t8` 和 partitioned 构建均返回 `rc=0`，但使用 `CPU_XIANGSHAN`/79263 接口的普通 profile，不匹配冻结 RTL 的 `CPU_DEMO`/45871 G profile；因此它们不进入本表。100-cycle launcher smoke 的 `EXCEEDING CYCLE/INSTR LIMIT` 也只说明程序可启动，严格功能 gate 当时被跳过。

### 2.3 历史文档中的 RepCut timing

仓库仍保留 2026-03-24/25 的 partitioned timing 分析文档，例如：

- [`../draft/xs-repcut-timing-compare-20260324.md`](../draft/xs-repcut-timing-compare-20260324.md)：记录 60,102 steps 的平均 step `3601.299 us`、`5887.360 us` 两个版本，以及 `63.479%` 的版本间退化。
- [`../draft/xs-repcut-timing-compare-20260325.md`](../draft/xs-repcut-timing-compare-20260325.md)：记录另一次版本对比的 `5887.360 us -> 3584.439 us`、`39.116%` 改善。
- [`../draft/xs-repcut-regression-cause-analysis-20260324.md`](../draft/xs-repcut-regression-cause-analysis-20260324.md)：分析 `debug_scatter`、`part_eval`、`writeback` 的 phase 变化。

这些数字回答“历史上是否存在 RepCut timing 数据”：答案是存在；但它们不是当前冻结输入、不是 native/partitioned 各自 1/2/4/8 的矩阵，原始日志路径也不在当前 `build/repcut_thread_scaling_20260819/results` 中。因此只能作为历史背景，不能拼接进本轮正式结果。

## 3. 为什么不以失败时间做比较

正式协议要求每个样本同时满足退出状态、terminal signature、guest/cycle/instruction 一致、无 assertion/fatal/error，以及唯一正的 `Host time spent`。当前 probe 在 cycle 605 发生 assertion 并 `ABORT`，违反多个硬条件。

即使两个后端都在同一 cycle 失败，失败时间仍可能由 assertion 触发前的调度、日志输出和线程同步决定；它测量的是“到共同错误点的代价”，不是完成相同 workload 的仿真性能。故本记录不报告伪 speedup。

## 4. 可恢复的正式实验入口

修复 RepCut 功能后，应保留以下冻结输入并重新执行完整流程：

1. 复用当前 `xs_wolf_repcut.json`、split SV、32-part package 和 CoreMark/NEMU SHA。
2. 继续使用 `difftest-src-fresh` 的 G profile，不再使用普通 `CPU_XIANGSHAN` generated-src。
3. 完成 native `--threads 1/2/4/8` 四个 ELF，partitioned 完成一个可复用 ELF。
4. 八个配置均通过 100-cycle 与 10k canary、whole-CCD quiet admission 和 runtime audit。
5. 按 [TNO0238](./TNO0238_repcut_thread_scaling_experiment_protocol_20260819.md) 的 ABBA/BAAB 顺序采集 32 个有效样本，再报告均值、median、spread、speedup、效率和同 N 跨后端差异。

当前正式结果的唯一正确结论是：`run_xs_repcut` 与 `run_xs_repcut_verilator` 的 1/2/4/8 线程性能比较尚未完成，阻断点为冻结 RepCut RTL 的功能 assertion，而不是缺少 CPU/内存资源。

## 5. 增量更新（2026-08-19 19:45）

五个正确 G profile ELF 已全部构建完成，但短 probe 的终点分叉：native `t1`/partitioned 在 cycle 605 assertion，native `t2/t4/t8` 在 PC `0x0`、仅 3 条指令处触发 cycle limit。故“0/32”应理解为正式矩阵尚未启动，而不是可从失败样本计算统计量；完整构建和 probe 证据见 [TNO0239](./TNO0239_repcut_thread_scaling_build_and_functional_gates_20260819.md)。

## 6. profile 身份增量勘误（2026-08-19）

上一节及第 1 节中的“正确 G profile/CPU_DEMO/45871”表述需要更正：冻结 `SimTop.sv` 所对应的是 `CPU_XIANGSHAN`、interface width `79263` 的 generated-src；初轮五个 ELF 正是使用这组匹配 profile 构建。通用 `difftest_verilog CONFIG=G` 产生的 `CPU_DEMO`/45871 fresh-G ELF 与该 RTL 不匹配，已从所有 headline 和正式样本候选中排除。详细身份表、SHA 和匹配 profile probe 见 [TNO0239](./TNO0239_repcut_thread_scaling_build_and_functional_gates_20260819.md) 第 7 节。

更正后，阻断结论仍然成立但原因更精确：matching-profile native `t1` 以及 partitioned `N=1/2/4/8` 在 cycle 605 触发 `csr_dbltrp_inMN` assertion；matching-profile native `t2/t4/t8` 至少能通过 10k 启动/短程诊断（native t2 已做 difftest，t4/t8 记录为 no-diff 诊断），但八个配置并未全部通过功能门。因此 N=1/2/4/8 的完整双后端性能表仍全部为 `N/A`，不是因为把错误 profile 的失败时间当成了正式结果。

## 7. 最终执行口径（2026-08-19）

本节覆盖前文恢复步骤中关于 generated-src 的旧表述。后续恢复实验必须使用与冻结 `GatewayEndpoint.sv` 相匹配的工作区 generated-src：`CPU_XIANGSHAN`、interface width `79263`，以及 `build/repcut_thread_scaling_20260819/build` 下的五个 ELF。通用 `difftest.DifftestMain CONFIG=G` 生成的 `CPU_DEMO`/45871 fresh-G 目录和 ELF 已排除，不得用于性能或功能结论。

因此第 4 节第 2 条“继续使用 `difftest-src-fresh` 的 G profile”正式废止；恢复时应改为使用工作区 `testcase/xiangshan/build/generated-src`，并先核验 `DifftestMacros.svh` 的 `CPU_XIANGSHAN`/79263 与冻结 RTL 的端口宽度一致。

匹配 profile 的短程诊断数字如下；它们没有进入 headline 表：

| 入口 | N=1 | N=2 | N=4 | N=8 |
| --- | --- | --- | --- | --- |
| `run_xs_repcut`（native） | `ABORT@605, 1956 ms` | `cycle-limit@9996, 14730 ms`（`--diff`） | `cycle-limit@9996, 8869 ms`（`--no-diff`） | `cycle-limit@9996, 5946 ms`（`--no-diff`） |
| `run_xs_repcut_verilator`（partitioned） | `ABORT@605, 6063 ms` | `ABORT@605, 3512 ms` | `ABORT@605, 2258 ms` | `ABORT@605, 1371 ms` |

这里的 `ms` 是到错误终点或人为 cycle limit 的耗时；native 与 partitioned 的终点、选项和功能状态不一致，不能由此计算 speedup、效率或跨后端比值。正式统计仍为 `0/32` 已启动/接受、16 个配置 headline 全部 `N/A`。

恢复顺序固定为：修复 RepCut 变换并重新生成冻结 JSON/SV/package；使用匹配 XiangShan generated-src 重建五个 ELF；八个配置通过 100-cycle、10k、静默/NUMA 和 runtime audit；最后按 [TNO0238](./TNO0238_repcut_thread_scaling_experiment_protocol_20260819.md) 采集 32 个 ABBA/BAAB 样本。历史 2026-03 timing 仍只作背景，不与本轮结果合并。
