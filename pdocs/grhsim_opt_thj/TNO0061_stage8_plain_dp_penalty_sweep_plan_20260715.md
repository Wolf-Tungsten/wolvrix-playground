# TNO0061 Stage 8 plain-DP segment-penalty sweep plan

日期：2026-07-15

状态：计划 current-default NO0300 plain activity-schedule DP 的固定 segment penalty 双向扫描；本文只定义对象、门禁和停止条件，不预写结构或 runtime 结论。

## 1. 基线与问题

[TNO0060](./TNO0060_stage7_cross_socket_runtime_and_default_decision_20260715.md) 已恢复仓库默认生成配置：NO0300、ASLR 关闭、direct state-read/pure-event bypass/profile/packing 均关闭。Stage 8 的唯一基线继续使用该配置及 canonical pre-reg-to-mem checkpoint。

当前 plain DP 的目标为：

```text
sum(incoming unique boundary values per segment)
+ segment_penalty * compute segment count
```

调用点把 `segment_penalty` 硬编码为 `1.0`。它同时约束 compute BAE 与 compute-supernode 数，却没有在当前 NO0300 plain 图上做过独立双向扫描。历史 probability-DP 的 `mixed-pi` penalty 和旧 activation-cost DP 使用不同 partition/weight/coarsen 对象，不能替代本轮实验。

用户已明确 BAE/DAG/SN 不必作为绝对不退化的硬门禁。因此本轮同时检查：降低 penalty 是否以温和 SN 增量换取 BAE 下降，以及提高 penalty 是否以温和 BAE 增量换取更少的函数/dispatch work；最终仍只由 SimTop 50k 裁决。

## 2. 实现边界

新增默认值 `1000000` 的整数 PPM option，运行时换算成 `1.0`：

```text
ActivityScheduleOptions::dpSegmentPenaltyPpm
-dp-segment-penalty-ppm
WOLVRIX_XS_GRHSIM_DP_SEGMENT_PENALTY_PPM
```

约束如下：

- 默认值必须逐字保持现有 `1.0` 行为，不改变 NO0300；
- 只参数化 plain DP 的固定 penalty，不引入 probability/profile 权重；
- PPM 使用无符号整数，拒绝溢出或非法文本；
- 不改 coarsen、topo order、commit partition、Kahn pack 策略、post-DP refine 和 emitter；Kahn candidate 内部若重跑同一 DP，必须复用 resolved penalty；
- native 与 XS config log 必须记录 resolved PPM，支持 fresh 产物审计；不向默认 stats JSON 增字段，以便继续做 raw identity 比较。

## 3. 结构扫描

首轮在同一 canonical checkpoint 上扫描：

```text
0.5 / 1.0 / 1.5 / 2.0
= 500000 / 1000000 / 1500000 / 2000000 ppm
```

每组记录 compute/commit SN、DAG、boundary values、BAE、compute-compute/compute-commit pairs、生成耗时和 option 日志。`1.0` 必须与 fresh explicit-default stats 完全一致。

只有结构实际变化的点才进入 full emit/build。优先各选一个代表点：低 penalty 侧看 BAE 收益，高 penalty 侧看 SN/代码体积收益。若某一侧相对基线所有核心结构量都不足 `0.05%`，该侧停止，不继续细扫。

## 4. Runtime 门禁

代表候选依次执行：

1. fresh emit 与 O3 build；
2. fixed-ASLR 100/10k/50k 功能门禁，检查 guest 终点与负向日志；
3. quiet A/B/A SimTop 50k，记录 host、cycles、instructions、frontend empty/cmask6 与 backend stalls；
4. 若结果受硬件位置影响或接近 `1%`，至少跨 NUMA0/NUMA1 各补一组，不用跨 socket 平均值掩盖最坏组。

BAE、DAG 或 SN 的小幅退化不阻止第 3 步。明显代码膨胀、功能失败、拓扑/commit 不变量失败，或结构变化方向完全不符合该侧目标时才提前停止。

## 5. 已排除的相邻 contraction

本阶段启动审计还检查了“跨 baseline DP 边界的 topo-adjacent direct-edge contraction”。canonical final topo 中只有 `1716` 个相邻 pair 的合计 op 不超过 `108`，这些 pair 的内部 compute edge/BAE 下界均为 `0`；它们是独立活动域，强行合并只会减少 flag/SN，却可能扩大互相唤醒的 payload。因此该候选没有进入实现，避免重复历史上的盲目 larger-supernode 路线。

## 6. 提交边界

实现与 focused tests 先提交 `wolvrix` 子模块；父仓库随后提交 submodule pointer、XS 配置接线、结构/runtime 文档和 README 索引。若扫描证明 knob 没有 runtime 收益，默认仍保持 `1000000`，实现可作为显式实验入口保留，但文档必须记录停止结论。
