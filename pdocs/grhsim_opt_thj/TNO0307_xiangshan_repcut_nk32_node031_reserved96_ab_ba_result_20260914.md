# TNO0307: XiangShan RepCut N=K=32 node031 reserved96 AB/BA result

日期：2026-09-14

状态：`COMPLETE BALANCED DIAGNOSTIC PAIR; PIPELINE-WORKERS NOT SELECTED; LEGACY RETAINED; NOT ALL-STRICT ACCEPTANCE`。

前置：[TNO0306 资源与运行计划](./TNO0306_xiangshan_repcut_nk32_node031_reserved96_run_plan_20260914.md)、
[TNO0303 复测及选择口径](./TNO0303_xiangshan_repcut_nk32_stage1_fresh_retest_plan_20260914.md)。

## 1. 执行与身份

在 node031 NUMA1、物理 CPU96-127、SMT guard288-319 上完成固定 AB/BA，monitor CPU35。
同一 runtime-v1 ELF、N=K=32、连续 partition 映射、push update；A=legacy，B=pipeline-workers。
两序运行时间约为本日 12:52-12:53（UTC+08:00），每序 C100/C10000 按预定 AB 或 BA 顺序执行。
8 个预定 slot 全部首次 admission 通过并启动，每次 admission mean/min idle 为 100%。
没有重抽或替换已启动样本；没有额外性能 launch。

冻结 runner、analyzer、ELF 和 spec 身份不变，各 arm 11 个源码身份通过。
两序 host/boot/kernel/NUMA/CPU mask/monitor/工具/环境/映射一致，12 个 staged 输入 inode
彼此独立，结束后的 staging 和来源复核通过。四次 C100 均通过；四次 C10000 均通过
功能、运行配置与 timing 完整性检查，共 20,102 steps，各含预期 36 条 timing records。
长样本签名一致：guest cycles=10001、cycle_count=9996、guest instr_count=458、
terminal PC=`0x800027c6`，终止原因为预期 cycle/instruction limit。

## 2. 证据质量与 CPU accounting 边界

| 长样本 | page / worker 有效快照 | guard mean/min idle | 已观察 foreign ticks | 原 diagnostic verdict |
| --- | --- | --- | ---: | --- |
| AB/A legacy | 3 / 3 | 100% / 100% | 6 | pass |
| AB/B pipeline-workers | 3 / 3 | 100% / 100% | 6 | pass |
| BA/B pipeline-workers | 3 / 3 | 100% / 100% | 5 | pass |
| BA/A legacy | 3 / 3 | 100% / 100% | 5 | unexplained target busy |

EMU resident pages A/B 为 63,169/63,089，executable coverage 为 98.799%/98.674%；
NEMU 为 71 pages、coverage95.946%。两者所有 qualifying snapshots 的 local fraction
均为 100%，没有观察到 remote bytes；无 affinity violation、未知 worker 配置或 audit error。
31 个 Verilator 备用线程均被识别，已观察 lifetime/delta CPU ticks 为 0；不据此保证退出尾部
绝对无消耗。foreign task 仅见 `rcu_preempt` 与少量 kworker，未超过原阈值，没有观察到
其它用户任务污染。任务快照不是对短命/迁移线程的逐时刻完整追踪。

CPU 计量仍有已知不闭合，保留正负残差如下（单位均为 CPU 秒）：

| 样本 | raw target busy | perf task-clock | busy−task-clock | raw target total−32×workload wall |
| --- | ---: | ---: | ---: | ---: |
| AB/A | 125.230 | 128.41623 | −3.18623 | −20.48550 |
| AB/B | 150.620 | 154.87846 | −4.25846 | −25.09238 |
| BA/B | 149.050 | 153.71835 | −4.66835 | −26.11539 |
| BA/A | 139.130 | 129.13086 | +9.99914 | −7.18849 |

BA/A 的原门阈值为 0.052387 CPU s，故其 runtime reason 保留。该样本某 CPU 的 total
增量 10.72 s 大于原始 snapshot 最大窗口约10.48115 s；结合其他样本负残差及 raw total
不闭合，不能将 +9.99914 CPU s 全部解释成实际 foreign work，也不能因用户隔离就豁免原门。
边界延续 [TNO0278](./TNO0278_xiangshan_repcut_parallel_cpu_audit_capture_protocol_20260907.md)。

冻结 analyzer 分类为 `balanced_diagnostic`，`formal_acceptance=false`。这与上一轮
TNO0294 的 page/worker 不足导致 `invalid_evidence_retained_without_selection` 不同：
本轮具有完整对称诊断证据，但仍不是四条全部 strict 通过或正式生产性能认定。

## 3. Host 结果与选择

| 顺序 | legacy A / s | pipeline-workers B / s | B 相对 A |
| --- | ---: | ---: | ---: |
| AB | 10.281 | 11.547 | +12.314% |
| BA | 10.251 | 11.524 | +12.418% |
| pooled | 10.2660 | 11.5355 | +12.366% |

pooled 为两序 primitive totals 算术平均后计算比值。Host 增加 1.2695 s，两个顺序
方向一致；Host order-effect gap 为 0.104323 pp，仅作描述，不新增阈值或统计显著性结论。
原选择规则要求两序均缩短且中心改善至少2%，本候选显然不满足。

决策：**当前 condition-variable pipeline-workers 不采用，保留 legacy control**。
不继续重抽到某个有利性能值或 residual 恰好通过，也不把此结果外推为所有 pipeline
或所有减少 host 往返的设计均无效。尚未测试 pipeline-host，本轮不混入映射、pull 或新划分。

## 4. 回退集中位置与机制线索

下表为 pooled；phase 和 per-part 数值单位是 us/step，task-clock 是累计 CPU 秒。

| 指标 | legacy | pipeline-workers | 相对变化 |
| --- | ---: | ---: | ---: |
| total step wall | 506.149 | 566.520 | +11.927% |
| input-load wall | 12.584 | 16.732 | +32.966% |
| part-eval wall | 321.141 | 330.132 | +2.800% |
| eval max（max of per-part means） | 279.519 | 281.090 | +0.562% |
| global-update wall | 172.424 | 219.656 | +27.393% |
| update critical（max of worker means） | 117.076 | 118.901 | +1.559% |
| update wall−critical 混合剩余量 | 55.348 | 100.755 | +82.038% |
| instructions / billion | 303.433 | 305.821 | +0.787% |
| cycles / billion | 202.533 | 230.685 | +13.900% |
| task-clock / CPU s | 128.774 | 154.298 | +19.822% |
| aggregate IPC | 1.49819 | 1.32571 | −11.513% |
| context switches | 1,392,963.5 | 1,660,736.5 | +19.223% |
| CPU migrations | 13,123.0 | 396.5 | −96.979% |

step 增加 60.370 us，其中当前计时边界下 global-update 增加47.232 us；两个 runtime
phase 边界实现不同，不能把该份额当作与实现无关的精确通信归因。关键 eval/update 本体
计时变化小，指令增幅也小，但整个阶段墙钟、CPU 时间及上下文切换明显增加，支持优先
调查调度/同步实现，而不是这次固定不变的分区逻辑规模。

源码对照（实验根下）`runtime/generated-v1/wolvi_repcut_verilator_sim_common.cpp`：
legacy 每个 worker 各有独立 mutex/cv，host 逐 worker 派发和等待；
`runtime/generated-v1/step_pipeline.h` 则以同一 mutex 保护 step epoch、eval 到达计数和
update 完成计数，eval 完成后 `notify_all`，等待者唤醒后需要重新获得共享 mutex。
这是共享锁竞争/集中唤醒的明确候选机制，与新增 context switches 相符，但本轮没有
futex/调度事件 profile，尚不能给出各项的因果占比或把全部剩余量称为纯 barrier。

per-part timer 是重叠的局部墙钟，不是 worker CPU 时间；phase wall 减聚合 max 包含
派发、等待、封装间隙与 step 间变化。task-clock/cycles 比值仅为聚合观测量，也不能单独
证明硬件降频因果。migration 下降而 Host 变慢，不能将本次回退归因于迁核增多。
audit finalization 不含在 Host 和 workload wall 内，本轮 B 的约1.37 s 收尾等待不能
解释 Host 的1.27 s 回退；两个计时区间明确独立。

## 5. 产物、复核与后续

实验根 `build/repcut_nk32_opt_20260907/` 下：

- AB：`runs/stage1-dispatch-retry20260914-node031-reserved96-ab1/captured.json`。
- BA：`runs/stage1-dispatch-retry20260914-node031-reserved96-ba1/captured.json`。
- 汇总：`measurement/stage1-dispatch-retry20260914-node031-reserved96-pair1-analysis/summary.json` 及 `comparisons.csv`。
- 各 run 同目录保存原始 attempts、log、perf、timing、page-placement、staging 与最终核验。

| 文件 | SHA-256 |
| --- | --- |
| AB captured.json | `b605ac256bba3fba4565825152915c9743ed5ac9577f34ca5fc4f8a9aa881099` |
| BA captured.json | `36b42fb85751099f173308a00fa2c3f950f7daa6f91f491abe1c929c5d081dbd` |
| summary.json | `11eb8786414b5f4a6f83884f30b8adce0153ed41dc75a3928fb08cd0284e974d` |

47 项 measurement/calibration 单测通过；独立复核原始样本和再次执行 `summarize()`，
与保存 summary 完全一致。源码、冻结门槛、生产默认均未修改，全部预定进程已完成。
下一步按阶段一回退分支，应保留 legacy 并定位共享同步路径；如继续评估 host 参与，
须独立固定对照，不把本次未采用 pipeline-workers 当作已选的新 control。
