# TNO0303: XiangShan RepCut N=K=32 stage-1 fresh retest plan

日期：2026-09-14

状态：`PLAN REGISTERED; RESOURCE SCAN AND FROZEN IDENTITY CHECK IN PROGRESS`。

## 1. 范围与前置

用户同意继续阶段一有效复测。前置为
[TNO0280 四阶段计划](./TNO0280_xiangshan_repcut_nk32_four_stage_experiment_plan_20260907.md)、
[TNO0282 测量协议](./TNO0282_xiangshan_repcut_nk32_measurement_protocol_gate_20260907.md) 和
[TNO0294 上轮诊断](./TNO0294_xiangshan_repcut_nk32_stage1_scheduler_ab_ba_20260909.md)。
固定 N=K=32；A=legacy，B=pipeline-workers，使用同一 runtime-v1 ELF、identity 映射和 push。
不拆 ASC，不修改生产默认，不原地改冻结 runner 或放宽页面、worker、CPU audit 门槛。

## 2. 执行约束

- 只轮询 node029-node034、node036-node042；同 NUMA 四个完整 CCD，每核一个 SMT thread，monitor 位于目标 CCD 外。
- 扫描仅提供候选，不能代表独占预约。正式 runner 在每次 launch 前执行原 admission，运行期保留全部审计。
- AB 与 BA 使用同一 pair-id、host、CPU mask、NUMA、monitor、spec、工具与原默认 retry/timeout 配置，输出目录分别独立。
- 每个 order 自动执行两臂 C=100，然后两臂 C=10000；每个 slot 仅 admission 未启动时允许最多 4 次尝试，间隔 5 秒。
- 已启动的长样本不按快慢或审计结果单独重抽；完整 pair 证据全部保留。功能失败停止，资源失败与诊断结果另篇归档。

## 3. 原协议核对与本次决策

沿用 TNO0280：AB、BA 的 Host 都缩短且两序中心改善至少 2%，才可暂选新实验 control；不是要求每序各提升 2%。
TNO0280/TNO0282 及 analyzer 没有预注册 order gap <=0.25 pp 硬门槛，不再把它当本实验拒绝条件。
先确认功能、身份、页归属、线程绑定与运行期证据，再比较 Host、step wall、phase/worker timing 及 PMU。
未达选择条件保留 legacy；若 CPU accounting 仍不闭合，先定位计量/资源来源，不把差值直接当外来进程时间。
本轮不从无效 pair 选 pipeline-workers，也不据它进入 pipeline-host、映射、pull 或 solver 后处理。
已知上轮约 10.6% 回退仅为诊断线索，不能预先写成确认结果。

## 4. 产物约定

继续使用 `build/repcut_nk32_opt_20260907/`；本日扫描目录为
`measurement/scans/retry_20260914_resource/`。新 launch tag 和 pair-id 含 `retry20260914`，不覆盖历史产物。
运行/诊断结果及后续工具修正按独立 TNO 递增记录，同步 README，旧记录只追加勘误。
