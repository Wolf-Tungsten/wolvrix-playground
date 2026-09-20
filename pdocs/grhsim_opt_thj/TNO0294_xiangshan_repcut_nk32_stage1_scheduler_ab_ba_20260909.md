# TNO0294: XiangShan RepCut N=K=32 stage-1 scheduler AB/BA

日期：2026-09-09

状态：`RUNTIME DIAGNOSTIC COMPLETE; EVIDENCE INVALID FOR FORMAL PERFORMANCE SELECTION`。

前置：[TNO0280](./TNO0280_xiangshan_repcut_nk32_four_stage_experiment_plan_20260907.md)、
[TNO0281](./TNO0281_xiangshan_repcut_nk32_scheduler_build_gate_20260907.md)、
[TNO0293](./TNO0293_xiangshan_repcut_nk32_resource_retry_20260909.md)。

## 1. 对照定义与身份

本阶段只测试阶段一调度封装：A 为原 `legacy` 调度，B 为 `pipeline-workers`，
N=K=32、32 个物理计算 lane、连续 partition 映射、push update。AB/BA 使用同一
pair-id；A 变体和 B 变体的 ELF、assignment、输入、工具链及 runtime 配置通过
身份核对。node031 NUMA1 使用四个完整 CCD，worker 物理 CPU 为
`96-103,112-119,152-159,160-167`，SMT siblings 为 `288-295,304-311,344-351,352-359`，
monitor CPU 为 0。

分析汇总文件为
`build/repcut_nk32_opt_20260907/measurement/stage1-dispatch-retry20260909-node031-ab2-ba3-analysis/summary.json`（SHA-256
`ced413303db67a9830ea3b4e7c8f06b891ef677bc357adba4af2ba4c820fb4cd`）。AB 原始目录为
`build/repcut_nk32_opt_20260907/runs/stage1-dispatch-retry20260909-node031-ab2/`，
BA 原始目录为
`build/repcut_nk32_opt_20260907/runs/stage1-dispatch-retry20260909-node031-ba3/`。

## 2. C=100 功能与 C=10000 运行

AB 顺序中，A C=100 首次通过；B C=100 首次 admission 被拒后第二次通过。两臂
功能签名、runtime-config、输入身份和页面/worker 配置核对通过。A C=10000 已启动，
但 diagnostic runtime gate 报 `runtime_unexplained_target_busy`；B C=10000 启动并通过
对应 gate。BA 顺序中 B C=100 与 A C=100 均在第 4 次 admission 后启动，B C=10000
通过，A C=10000 同样因运行期目标核忙而未通过。因此两序均有 launch，但 A 的长样本
均未满足完整运行期门禁，不能作为正式对照组。所有已启动样本和失败原因均
保留，不拼接 partial sample，也不按性能数值择优。

## 3. 保留的诊断数值

汇总器将四个已启动的 C=10000 launch 全部保留，但状态为
`invalid_evidence_retained_without_selection`，`formal_acceptance=false`。
Host wall（秒）如下：

| 顺序 | legacy A | pipeline-workers B | B 相对 A |
| --- | ---: | ---: | ---: |
| AB | 10.476 | 11.635 | +11.063% |
| BA | 10.751 | 11.848 | +10.204% |
| pooled | 10.6135 | 11.7415 | +10.628% |

诊断中 A 的 `eval_part_max` 为 281.950 us、B 为 282.541 us（B 高 0.210%）；
`global_update_critical_mean_us` 为 112.370 us 对 115.828 us（B 高 3.077%）；
但 A 的 aggregate IPC 为 1.4993、B 为 1.3424，且 order gap 为 1.006 pp，超过
预设的 0.25 pp。A 的 pooled update step-wall fraction 为 34.155%，B 为 38.591%。
这些数值仅用于定位调度行为，不能升级为正式性能收益。

## 4. 解释与阶段决策

两种顺序的 Host 数值都显示 legacy A 比 pipeline-workers B 快约 10%，方向一致；然而 A 的 C=10000
runtime gate 失败，BA 没有完整有效配对，order gap 也超限。因此本次不能证明
`pipeline-workers` 已满足阶段选择规则，不能把它作为下一阶段 CCD 映射的正式 control，
也不能宣布对生产默认有收益。调度改进的静态/小规模 build gate 仍有效，但 runtime
证据只保留为诊断。

下一步如继续阶段一，应在同一 pair-id 和同一 fresh resource window 中完成完整
AB/BA，并先解决 `runtime_unexplained_target_busy` 的来源或取得可解释的 balanced
diagnostic 证据；在此之前不进入 pipeline-host、CCD 映射、pull update 或通信后处理
的正式比较。生产源码、默认调度和搜索状态均未修改。

## 5. 勘误 2026-09-14：选择规则与失败样本边界

重新核对 TNO0280/TNO0282 与冻结 analyzer：本实验没有预注册 `order gap <=0.25 pp`
硬门槛。上文“超过预设的 0.25 pp”缺乏本协议依据，不能作为拒绝本 pair 的独立原因。
Host order gap 是 `0.859681 pp`，`1.006027 pp` 是 aggregate IPC 的 order gap。
原选择规则是 AB、BA 均缩短 Host，且两序中心改善至少 2%，并非每序各改善至少 2%。

AB/A 的长样本 page/worker 各有 3 个有效快照，均通过；其唯一 diagnostic 拒绝是
`runtime_unexplained_target_busy`。BA/A 才同时存在 page/worker 各仅 2 个快照、SMT guard
mean/min idle `96.452%/94.886%` 不足，以及 unexplained busy。两臂功能与身份核验通过。
因此不要将“legacy 长样本 page/worker 失败”外推到 AB/A。

AB/A 的 raw busy 减 task-clock 为 `+36.66679 CPU s`，raw total 减 32 倍 workload wall
为 `+19.91144 CPU s`；某 CPU total 增量 `12.30 s` 大于整个 snapshot 窗口约 `10.62260 s`。
两次 B 的 raw busy 减 task-clock 则为 `-4.57987/-4.43277 CPU s`。毫秒级读取窗口差
不能解释这些不闭合量，符合 [TNO0278](./TNO0278_xiangshan_repcut_parallel_cpu_audit_capture_protocol_20260907.md)
已记录的单边 residual 门方向性风险，不能把所有差额称为真实 foreign CPU 时间，也不能
重抽直到 residual 恰好通过。BA/A 的 foreign task 与 guard 扰动则是独立资源污染证据。

原 Host 数值、原始 verdict 和“不选择 pipeline-workers”结论保留；本次勘误不将旧 pair
升级为有效或正式 clean evidence。后续复测方案见
[TNO0303](./TNO0303_xiangshan_repcut_nk32_stage1_fresh_retest_plan_20260914.md)。
