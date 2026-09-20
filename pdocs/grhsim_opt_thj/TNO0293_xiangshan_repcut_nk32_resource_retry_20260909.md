# TNO0293: XiangShan RepCut N=K=32 resource retry

日期：2026-09-09

状态：`PRE-RUNTIME RESOURCE RETRY RECORDED; NODE041/NODE032 PROBES LAUNCHED NO MODEL`。

前置：[TNO0280](./TNO0280_xiangshan_repcut_nk32_four_stage_experiment_plan_20260907.md)、
[TNO0286](./TNO0286_xiangshan_repcut_nk32_resource_blocker_20260907.md)。

## 1. 重试范围与冻结输入

本轮响应用户要求，在允许节点 `node029-node034,node036-node042` 内重新寻找可用
CCD，目标为 N=K=32 的阶段一 C=100 admission，随后才进入 C=10000 AB/BA。
继续使用 runtime-v1、closure-aware K=32、32 个物理 worker；生产源码、默认配置、
冻结 assignment 和模型 ELF 均未修改。阶段一 runner 目录为
`build/repcut_nk32_opt_20260907/runs/stage1-dispatch-retry20260909-ab/`。

本轮冻结 ELF SHA-256 为
`1f57c1e00d6e8339ba0b6eade021cfd463f21baa39b0f6fd64d3949a4de20e94`，assignment
SHA-256 仍为 `ffefbb1d1373cb30290e6725479d339b87e637f3db32132dcbe416fd2c52d589`。
runner 的 staging.json SHA-256 为
`b4c3396d4e2d0ed80a2354a9f3471b1a092750cace0f37de6ce40caec854856a`，
attempts.jsonl SHA-256 为
`771df951af1fd0efd829a4e224ab39e38a50eac5f97bcaa68deb493e12da49f3`。

## 2. 资源扫描与 admission 时间线

资源扫描使用三段约三秒窗口（quick probe 另有单段三秒记录），正式 admission 使用
三段一秒窗口；两者均保持 mean idle >=98%、minimum idle >=95%。扫描只提名候选，
不预约资源。`retry_20260909_resource/found.json` 在约 14:32 UTC+8 提名
node041 NUMA0 的四个 CCD bases `[0,24,40,80]`，其最新窗口最差 mean idle
98.313%、最差 minimum idle 96.345%，monitor CPU 191。该 found.json SHA-256 为
`b4a9ed14b9787c0addd819eabf46f0b17612f59e311a61cea77b4ab5417a71ec`。

阶段一随后在约 14:33:45 于 node041 NUMA0 运行 A arm C=100 admission。由于扫描与
启动存在时间差，CPU 资源已改变；12 次 admission 全部 `admission_not_quiet`，
model launch=0，未产生 B arm、C=10000、BA 或性能 timing。每次 aggregate mean idle
为 85.787%--87.495%，minimum idle 均为 0%。这不是仿真功能失败，也不能解释为
调度优化无效。

额外检查显示扫描后资源变化很快。node041 在约 14:36 对 base0 的再次三窗口扫描
已经看到 CPU0--7 与 CPU16--23 被占满，CCD mean idle 约 74.922%、minimum idle 0%；
该扫描 JSON SHA-256 为
`2eaeb9838d2eec296adc3576e1bb5abdaf7be3267721986167fb3a73cd53490b`。

node032 NUMA0 的直接 admission probe（记录内 `created_at=2026-09-09T06:52:00Z`）选择
CCD bases `[32,64,72,80]`。原始 probe JSON 同时写入 physical `32-39,64-95` 与
SMT `224-231,256-287`；后者与四个 base 对应的 32 物理核范围并不一致，因此该
probe 不能作为有效的 32-core admission，只保留其资源阻断证据。三段一秒门禁 aggregate
mean idle 为 96.500436%、minimum idle 为 0%；blocking CPU 32 的 idle 为 0%、
busy ticks 为 300，model launch=0。该 JSON 的 SHA-256 为
`013365c831780b40262aea323c4e1c299f12086da8fa620d82863872b604ed7c`。

node033 NUMA1 的同轮快速筛查（约 14:44，只有一个三秒窗口）没有稳定四 CCD 候选，
因此没有启动模型；其 `best_n32_ccd_bases` 为 null。该 quick-scan JSON SHA-256 为
`7decdbc79c6ed6bcf7ced7cec7f1cad3623f68f216757023caf86223af79b919`。单窗口快扫
不满足正式三窗口提名条件，不能当作性能 admission 或有效样本。

## 3. 资源阶段结论与后续边界

上述 node041 阶段一 A C=100 admission 12 次，全部在模型启动前被资源门拒绝；
node032 直接 admission probe 也未启动模型。这些资源筛选尝试的 launch 数为 0，
没有产生 C=100 功能结果或 C=10000 性能结果，不能据此选择 pipeline-workers、
pipeline-host 或后续 CCD/pull/refinement 方案。所有拒绝与扫描原始 JSON 均保留；
node041 runner 已退出，未终止任何外部任务。

失败原因是扫描候选到实际 admission 之间的资源竞争和时间窗口，而不是降低门槛、
放宽审计或修改仿真代码即可解决的问题。下一轮应把候选扫描和首次 C=100 admission
放入同一远程会话、同一 CPU mask，扫描通过后立即 admission；仍沿用原门槛并记录
扫描结束到 admission 开始的时间差。只有 admission 和后续功能/身份/页面/线程门
完整通过，才可进入每臂一次的 C=10000 AB/BA。

随后在 node031 NUMA1 成功启动的阶段一 runtime 记录属于独立议题，另行归档；
因此本篇的零 launch 仅描述上述资源筛选尝试，不代表整个 2026-09-09 重试最终仍为零。
本记录不改变生产默认值，不把未启动的尝试计为性能样本，也不据此停止四项实验。
