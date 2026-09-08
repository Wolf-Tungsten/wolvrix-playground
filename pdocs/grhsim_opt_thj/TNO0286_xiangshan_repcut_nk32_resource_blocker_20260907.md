# TNO0286: XiangShan RepCut N=K=32 resource blocker

日期：2026-09-07

状态：`RESOURCE BLOCKED BEFORE MODEL LAUNCH; 40 ADMISSION REJECTIONS; NO PERFORMANCE SAMPLES`。

前置：[TNO0280](./TNO0280_xiangshan_repcut_nk32_four_stage_experiment_plan_20260907.md)、
[TNO0282](./TNO0282_xiangshan_repcut_nk32_measurement_protocol_gate_20260907.md)。

## 1. 四组实际 admission

本篇从四个 `attempts.jsonl` 重新按 JSON 记录核算，排除 experiment header。
机器可读统计、每次 aggregate、来源文件 SHA 和扫描覆盖见
[resource-blocker-summary-v1.json](../../build/repcut_nk32_opt_20260907/measurement/resource-blocker-summary-v1.json)。

| AB run | 节点 | 32 个物理 CPU | NUMA / monitor CPU | attempts | model launches | 各次 aggregate min idle 的最大值 |
| --- | --- | --- | --- | ---: | ---: | ---: |
| v1 | node030 | `0-23,88-95` | 0 / 191 | 4 | 0 | 89.701% |
| v2 | node030 | `8-23,40-47,88-95` | 0 / 191 | 12 | 0 | 92.027% |
| v3 | node032 | `112-119,152-159,168-175,184-191` | 1 / 0 | 12 | 0 | 0.000% |
| v4 | node030 | `0-15,80-95` | 0 / 191 | 12 | 0 | 0.662% |
| 合计 | | | | **40** | **0** | |

四组原始目录均为 `build/repcut_nk32_opt_20260907/runs/stage1-dispatch-ab-v{1,2,3,4}/`。
全部 40 条均是 A/C=100、`launched=false`、`accepted=false`，唯一拒绝原因
`admission_not_quiet`；没有进入 B/C=100，更没有启动 C=10000。各目录只有
`attempts.jsonl` 与 `staging.json`，没有 BA、captured.json、timing/perf 产物或性能 summary。
表中最大值仅描述拒绝样本的资源状态，不是选择可用性能样本。

## 2. 门槛与身份未变

冻结 runner SHA：`7b50e6d9d7780ecc1785f0ceeedfbc8edb7d6732b94431a1f5a316ff2dad9c48`。
stage1 spec SHA：`084a98f96ca1809b56b56843f6fd4c999e6337ac0b92ef1a1f70882b364b9fae`。
四组 header 均与这两个现有文件 SHA 一致；A/B 使用同一个 runtime-v1 ELF，
只切换 `legacy` 与 `pipeline-workers`，仍为连续映射、push 更新、N=K=32。

启动前检查所选 32 个物理 CPU 及其完整 SMT siblings。代码记录 3 个约 1 秒子窗口，
但实际 pass 判断使用整段约 3 秒 aggregate：mean idle >=98%，min idle >=95%；
不是每个子窗口独立通过。实现见
[run_matrix_v6.py](../../build/repcut_fix_20260825/run_matrix_v6.py) 的 `run_admission()`。
`diagnostic` 策略没有豁免此启动前门槛。v1 显式 `max_attempts=4`，后续显式增至 12；
这只增加未 launch 的 admission 重试预算，没有修改冻结代码、默认值或通过阈值。
运行期、页面、绑定、功能等门没有得到执行，不能写成已经通过。

## 3. 全节点覆盖与时间差

独立资源轮询约在北京时间 17:53:13 至 18:06:30，共 13 分 17 秒。
`measurement/scans/` 保存 71 份扫描 JSON，覆盖 `node029-node034,node036-node042`
全部 13 个允许节点的 NUMA0/NUMA1，共 26 个 host/NUMA 组合；物理范围分别为
`0-95`、`96-191`，同时检查完整 SMT siblings。每份 JSON 保留实际窗口时长与数量；
1 窗口短扫不能称为 3 窗口稳定通过。

曾经合格的候选不等于后来 admission 通过。例如
[node032 round8](../../build/repcut_nk32_opt_20260907/mapping/scans/bounded_runtime_rescan_20260907/round8_node032_numa1.json)
在 17:46:46.783 的 3×3 秒扫描中，CCD bases `112,152,168,184` 均合格，
各 CCD 最差 min idle 为 97.667%-98.671%。v3 的 run header 时间为 17:50:17，
已相隔 210.218 秒；随后 12 次实际 admission 全部失败。扫描只提名候选，不预约资源，
也不是与实际 admission 同一时间段的测量。

末轮扫描另外 12 节点的双 NUMA，共 24 份记录，没有一个组合达到 4 个合格 CCD。
node029 此时已有本工程单线程完整 GRH 导入/导出构建，故主动避开；它的双 NUMA
此前已覆盖。末轮 node030 使用 3×1 秒，其他节点为 1×1 秒，结论仅限这些观测时段，
不能外推为节点永久不可用。

## 4. 外部任务与停止边界

[只读进程快照](../../build/repcut_nk32_opt_20260907/mapping/scans/bounded_runtime_rescan_20260907/top-processes.json)
保留 17:41 左右的 `uptime`、`ps`：node030 有约 799%/767% CPU 的 emu，
node032 有约 1494% firtool、797% emu 和多个 Java 任务；node033 有多个约
1571%-1584% emu，load average 为 264.28/257.01/255.25。
这些是共享节点有外部工作负载的上下文证据；`ps %CPU` 不是 admission 同窗口指标，
不能把具体失败 CPU tick 全部归因到某个 PID。没有修改或终止任何外部任务。

本轮资源扫描及四组性能 runner 会话均已退出，没有遗留本轮 benchmark 进程。
由于模型完全未启动，这不是功能失败，也不是优化无收益；stage1 AB/BA 尚未完成，
后续阶段不得把它当作可用性能 control。保留全部拒绝证据，没有降低门槛换取样本。
资源轮询结束时，另一路完整图 emit/构建准备仍在进行，它不属于性能运行；
主线程随后确认完整复现、dry run 和回归已结束，相关结果由独立记录承载。
