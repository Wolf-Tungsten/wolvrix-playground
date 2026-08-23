# A0083 run-summary：r003 收口与停止 restart 建议（2026-08-23）

对应 `next` = `run-summary`（全部 2 条轨迹已达 L=8 步）。本 action 无评估开销。

## 做了什么

汇总 r003 台账 e00051-e00084、16 个 step 与 7 个 round-summary，写
[runs/r003/summary.md](../runs/r003/summary.md)（分数曲线、机制族裁决、测量风险和
restart 建议），并更新 insights.md 与两处 README。随后仅执行本 action 的
`close-run`、`action-done` 和 playground 提交，不启动新的 run。

## 量化结果

- C=2/L=8/K=2，16/16 步走满；候选 32/32，总 eval 34（含双基线）。29 个候选
  `ok`、3 个 `ctest_fail`；全部 ok 候选过 17/17 ctest、3 rep difftest 与编译门，
  其中 2 个 noisy。另有 4 个 ok 结果经 correction 判为表型无效测量。
- AM y0 e00051 = **363.995s**，gsim e00052 = **45.864s**，起跑差距 7.936x。
- best_overall = t0/e00057 **229.429s**，commit `1563c3d837fc`；较 AM 基线名义
  -36.97%，但仍为 gsim 的 **5.002x**，目标未达成。t1 best e00056 =
  **241.956s**（5.276x gsim）。
- 两条 best 均在前两轮产生；第 3-8 轮没有刷新任一轨迹历史 best。机械 tips 为
  t0/e00082 327.672s、t1/e00084 378.064s，不取代历史 best。

## 裁决与机制分析

- t0 保留 `sys-task-body-outline + scan-branch-hints`；scan hints 有 r002 同窗证据，
  e00057 又较 e00054 名义 -7.32%。t1 保留 `wide-mux-chain-fuse`，其正向性也由 r002
  同窗互证。r003 的 -31.99%/-33.53% 首轮幅度落进已知进程快慢态混杂，不作净收益。
- active-tile + nonzero-level 只保留方向性证据；scanner 控制派发、task 冷体精修、
  wide-mux helper/cache/store 微结构均已关闭，或要求动态 Host 权重/变化率后重开。
- e00073/e00074 与 e00075/e00076 的开关或硬依赖漏传使 4 个 ok 分数机制无效；
  `result.json.emit_args` 逐项审计继续作为硬前置。
- 跨进程约 1.3-1.4x 快慢态、loadavg 差异和 2 个 noisy 候选说明批内 CV=0 仍不足以
  支持跨窗相减；229.429s/5.002x 只作 ledger/看板口径。

## restart 裁决

**当前不建议 restart。** `restart.max=2` 已耗尽、`auto=false`，后六轮无新 best，
当前机制池也都要求先补动态证据和测量协议修复。run 收口后停止，等待用户另行裁决。

若用户之后明确扩预算，候选 y0 = `r003/e00057`，commit
`1563c3d837fcfe9db28fc36901531a70b59fd790`，完整表型为冻结 10 开关加
`--sys-task-body-outline --scan-branch-hints`；建议 C/L/K 从 2/8/2 缩为
**2/4/2（N=16）**。前置条件是解决 rep 级进程态分簇/同窗锚定，并以非计时 profiling
给出新候选的动态热点证据。本 action 不执行 `init-run`。
