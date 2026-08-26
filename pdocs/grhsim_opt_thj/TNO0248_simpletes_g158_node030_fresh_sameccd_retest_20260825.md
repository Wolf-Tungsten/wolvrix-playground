# TNO0248: SimpleTES g158 node030 fresh same-CCD retest

日期：2026-08-25

状态：`FRESH BUILD/FUNCTION PASS; FORMAL 50K POSITIVE; HISTORICAL MAGNITUDE CORRECTED; NOT LANDED`。

关联记录：[TNO0247](./TNO0247_simpletes_typed_state_budget512_valid128_node030_resume_launch_20260824.md) 记录了包含 g158 的上一段搜索结果及后续扩容。本记录只冻结 g158 本身，并在 node030 重新构建、复测其 SimTop 50k walltime。

## 1. 结论

g158 的正收益可以复现，但原搜索结果中的 `4.566244%` 明显高估了幅度。fresh 正式同 CCD `ABBA+BAAB` 结果为：

| arm | pooled walltime | 相对 control |
| --- | ---: | ---: |
| current default control | `43,223.00 ms` | baseline |
| g158 | `42,491.25 ms` | `-731.75 ms / +1.692964%` |

两个顺序分别改善 `1.735496%` 和 `1.650505%`，方向一致，order gap 为 `0.084992 pp`，满足预注册的 `<0.25 pp` 门槛。因此 g158 是可信的正收益候选，但本轮只完成独立复测，未将 patch 落入 Wolvrix、未改变默认选项。

## 2. 候选身份与机制

g158 是搜索树 `chain 1 / generation 158` 的节点 `621109d489774ae2b6361cc30c8dffdc`，冻结身份为：

```text
parent commit:    0dc48d4aa6dd508812d3226221e7c7a594ff3e7b
wolvrix commit:   79ec2037b00f2d4894d72785277ebe3f5d37782d
candidate mode:   default-path
enable options:   {}
candidate digest: 7715a2ea459f1d6da8c7e535525aa905e8714164e32e869498e3174cc968c01e
patch SHA-256:    cf29862adc2441aed4f72d446295fa5e60557872e7b2c59fa7641608371f72a5
program SHA-256:  4419814848287a43d93fccb26ccd05cc0042b0985b2c0447a2098de413337416
```

patch 只修改 `wolvrix/lib/emit/grhsim_cpp.cpp`。它在 final schedule 已固定后统计普通 persistent state 的静态引用需求：direct/raw read 计 1，write destination 计 2，并保留 compute supernode 与 commit batch 的 phase-tagged execution signature。随后按非空 signature、2 的幂需求等级、精确需求和原图顺序确定稳定顺序；每个需求层内仍按 wide/u64、u32、u16、bool/u8 的自然对齐组发射现有 typed fields。

该变换只改变 C++ persistent-state 成员的物理声明顺序，不改变字段名、字段类型、`logicSlotIndex`、legacy `slotIndex`、materialized-value 顺序、schedule、guard、event 或 operation。其目标是把同一执行单元经常共同访问的跨类型状态放得更近，减少热工作集和后端停顿；它不匹配 SimTop 名称、信号名或 benchmark 名称。

## 3. Fresh build 与功能门禁

复测根目录：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/
  g158_retest_node030_20260825_144807/
```

control 与 g158 都从冻结 commit fresh 构建，使用相同 build/toolchain fingerprint：

```text
build config: 920b5c7f1e32e61e7ad363145521736e9a10a68d0e0d112ce7b4406f00e820b3
toolchain:    6aa94991d9b49260ca9450d85ddbc1bad83ae9431c5ff1064110ed00498b6063
control generated fingerprint: ddbcab05a1b54f010a0358b6b376a311ef314fe594a796fe56442f03469bd6d9
g158 generated fingerprint:    eada87782a205e0853bc858918458241f5a98bdcd602d4d481d0b5ed469338a9
```

两边均为 `97` 个 schedule translation units，activity schedule 结构一致：`1,092,530` compute nodes、`468` commit supernodes、`63,709` final supernodes。focused tests 两边均为 `29/29 PASS`；100-cycle 和 10k-cycle 功能门禁两边均通过，10k 的 guest 结果一致为 `instrCnt=458, cycleCnt=9996, Guest cycle spent=10001`。

二进制绝对身份如下：

| arm | ELF size | ELF SHA-256 | snapshot manifest SHA-256 |
| --- | ---: | --- | --- |
| control | `83,705,920 B` | `376d87ee2f55e542f7761def9aacadc488702afffb07b2989696382439affeac` | `069a74270077ac6549ba7390b75a22186e5e4943dcc0d7b599c8c3ac5872e4e8` |
| g158 | `83,517,504 B` | `beed9657a6314079255c4f53627dee296edff0cff2c593269943f0e2b11d7c62` | `13c7755eb99cb99ed1026f242aea84b1b1399ce1e2e864ee8b91d9c8708444c0` |

g158 ELF 减少 `188,416 B / 0.225093%`。candidate proof ID 为 `62036c2f93bc4432b20b5e62e4011580`，proof SHA-256 为 `f61c6f846fb6e692f992f01bcb8d6ea933dc08155c458aeb6caff4f14b3f3296`。

本次 fresh control 的 generated fingerprint 与历史搜索 evaluator 不同，因此不能把两个批次的绝对 walltime 混池。正式 A/B 的两边始终来自同一次 fresh control 输入和相同工具链，故本轮内部比较仍是严格配对的。

## 4. 正式 SimTop 50k 结果

最终选中 `round 3 / pair attempt 4`，两个顺序固定在同一 placement：

```text
CCD:        node0:72-79,264-271
target CPU: 75
sibling:    267
helper CPU: 96
NUMA node:  0
```

八个正式样本为：

| order | index | role | walltime |
| --- | ---: | --- | ---: |
| ABBA | 1 | control | `43,201 ms` |
| ABBA | 2 | g158 | `42,255 ms` |
| ABBA | 3 | g158 | `42,619 ms` |
| ABBA | 4 | control | `43,172 ms` |
| BAAB | 1 | g158 | `42,648 ms` |
| BAAB | 2 | control | `43,491 ms` |
| BAAB | 3 | control | `43,028 ms` |
| BAAB | 4 | g158 | `42,443 ms` |

分 order 与 pooled 计算：

| aggregation | control | g158 | 绝对变化 | 相对提升 |
| --- | ---: | ---: | ---: | ---: |
| ABBA | `43,186.50 ms` | `42,437.00 ms` | `-749.50 ms` | `1.735496%` |
| BAAB | `43,259.50 ms` | `42,545.50 ms` | `-714.00 ms` | `1.650505%` |
| pooled | `43,223.00 ms` | `42,491.25 ms` | `-731.75 ms` | `1.692964%` |

八个样本均满足：

- 固定同一 CCD/CPU，affinity 正确，CPU migration 为 `0`；
- personality 均为 `00040000`，即地址随机化关闭；
- guest signature、cycle、terminal PC 和唯一 walltime 字段均通过；
- binary/NEMU NUMA local ratio 均为 `1.0`；
- perf events 与 task-clock scheduled percent 均为 `100%`；
- 连续监控 mean idle 为 `98.481%..99.739%`、min idle 为 `97.500%..99.310%`，均通过门禁。

同一批正式样本的主要 PMU 均值也与 walltime 方向一致：

| metric | control | g158 | delta |
| --- | ---: | ---: | ---: |
| cycles | `154,454,061,575.75` | `151,822,457,367.75` | `-1.703810%` |
| instructions | `149,144,195,899.25` | `148,670,704,550.25` | `-0.317472%` |
| backend stalls | `53,673,798,649.00` | `49,536,166,353.00` | `-7.708849%` |

## 5. 与历史 g158 分数的关系

搜索 checkpoint 曾记录：

```text
pooled: 43,564.25 -> 41,575.00 ms, +4.566244%
ABBA:   42,545.50 -> 41,668.00 ms, +2.062498%
BAAB:   44,583.00 -> 41,482.00 ms, +6.955566%
gap:    4.893068 pp
```

历史 BAAB control 中出现单个 `47,206 ms`，使两个 order 的改善相差 `4.893068 pp`，远超 `0.25 pp` 稳定门槛。因此历史结果只证明当时 evaluator 将 g158 选为 best，不能作为可信的提升幅度。fresh 复测把结论修正为：方向仍为正，但正式幅度是 `1.692964%`，比历史数值低 `2.873280 pp`。

## 6. 基础设施过程与证据

production evaluator 已完成 fresh build、focused/function gate 和 artifact proof，但其 9 次 runtime attempt 全部因 quiet/pre/continuous-load gate 作废，返回 retryable infrastructure outcome，没有产生可用 candidate walltime。随后将已证明的 immutable control/g158 artifacts 冻结后运行独立配对 runner。

前两个 detached runner 受 node030 后台任务策略影响实际为 `nice=5`，且只产生基础设施无效轮次，均已正常停止且未入选。最终通过 user systemd unit 保证 runner 及其子进程为 `nice=0`；正式 runner 的前两轮各 9 次仍因外部负载作废，第 3 轮第 4 次收敛并以 status 0 正常退出。用户允许与现有任务并行，所有碰撞均由 quiet/continuous-load gate 判无效，没有把受污染样本计入结果。

最终证据：

```text
summary:
  SimpleTES/checkpoints/grhsim_simtop_50k/g158_retest_node030_20260825_144807/
    formal_sameccd_gap_lt_0p25_nice0_systemd/summary.json
  SHA-256 c0ac53318230b2d175d0631f897855ab30e0d51bc931e32e455fcc1911ed6977

selected result:
  .../formal_sameccd_gap_lt_0p25_nice0_systemd/round-3/result.json
  SHA-256 dbc5c68294e86f2d3081f66c06eea53ec79983047b0f574d36b32153b8d49184
```

并行的 SimpleTES `512 attempts / 128 valid` auto research launcher 与 main process 在复测结束时仍存活；本轮没有停止、重启或修改它。

## 7. 决策边界

- g158 的独立正收益已通过正式端到端 walltime 门禁，值得进入后续消融、原则化审查和 landing 回归。
- 本轮不能把 `4.566244%` 继续作为 g158 的可信收益；后续规划应使用 fresh `1.692964%`。
- 本轮没有证明该布局策略在其他 workload 上同样获益，也没有授权默认开启；是否落地需单独任务决定。
