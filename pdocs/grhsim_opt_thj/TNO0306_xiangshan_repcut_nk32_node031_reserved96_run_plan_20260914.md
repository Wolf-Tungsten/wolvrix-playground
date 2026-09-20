# TNO0306: XiangShan RepCut N=K=32 node031 reserved96 run plan

日期：2026-09-14

状态：`FIXED PAIR REGISTERED; RUNNER STARTED; NO RUNTIME CONCLUSION YET`。

前置：[TNO0303 固定复测计划](./TNO0303_xiangshan_repcut_nk32_stage1_fresh_retest_plan_20260914.md)、
[TNO0304 资源阻断](./TNO0304_xiangshan_repcut_nk32_stage1_fresh_resource_result_20260914.md)。

## 1. 用户指定资源与核验

用户指定 node031 的 CPU96-127，并说明已排除其他用户。只使用该范围执行 32 个计算 lane，
不调整其它任务的 affinity、不修改节点管理配置。sysfs 确认 NUMA1 四个完整 CCD：
`96-103/104-111/112-119/120-127`，对应 SMT siblings 为 `288-319`。
三个 1 秒初扫窗口中，四 CCD 所有目标核和 siblings mean/min idle 均为 100%。

初扫原始文件为实验根目录下
`measurement/scans/retry_20260914_node031_reserved96_scan1.json`。
初始 observer CPU0 idle 只有 `0.000/0.990/4.124%`。按同一原始快照比较目标 CCD 外
CPU 及其 sibling 的最差 idle，选择 CPU35 为正式 monitor（最差 99%）；它位于 NUMA0，
不占用目标 CCD。此选择在任何模型 launch 前作出，AB/BA 保持相同。

用户的隔离说明和初扫不取代正式 admission/运行期审计。尤其保留目标 SMT siblings、
page/worker 样本完整性及 CPU accounting 原判定。

## 2. 固定 pair 和执行入口

实验根仍为 `build/repcut_nk32_opt_20260907/`；`measurement/run_pair.py`、
`measurement/analyze_pair.py` 和 `builds/runtime-v1/emu` 保持 TNO0304 冻结身份。
spec 为 `specs/stage1_dispatch.json`（SHA-256
`084a98f96ca1809b56b56843f6fd4c999e6337ac0b92ef1a1f70882b364b9fae`）。
同 ELF A=legacy/B=pipeline-workers、N=K=32、连续映射、push，不改变 partition model。

```text
pair-id: stage1-dispatch-retry20260914-node031-reserved96-pair1
AB tag: stage1-dispatch-retry20260914-node031-reserved96-ab1
BA tag: stage1-dispatch-retry20260914-node031-reserved96-ba1
--expected-host node031 --cpus 96-127 --numa-node 1 --monitor-cpu 35
--policy diagnostic --max-attempts 4 --retry-delay-seconds 5 --timeout-seconds 600
```

每序自动先两臂 C=100，再两臂 C=10000；AB 成功退出后同 SSH 命令顺序进入 BA。
每个性能 slot 一旦启动即保留，不按速度或 runtime verdict 重抽。独立 staging inode、
输入/ELF/工具/SHA、运行配置、页归属和线程绑定由冻结入口复核。
若 AB 功能/结构失败或资源耗尽退出，BA 不自行跳过前置启动。

## 3. 判定与后续

严格沿用 TNO0303，不增加 0.25 pp order-gap 硬门槛，不把 accounting residual 直接
等同外来工作，不根据共享节点偶然单臂通过筛选性能样本。AB/BA 都缩短 Host 且 pooled
改善至少 2%，并有完整可解释证据，才可暂选实验 control；否则保留 legacy。
若无法达到 page/worker 三次要求，保留失败证据并另行记录采样工具问题，不能回填。
本 pair 结果另建增量记录；此计划不代表已完成性能测量，也不修改生产默认。
