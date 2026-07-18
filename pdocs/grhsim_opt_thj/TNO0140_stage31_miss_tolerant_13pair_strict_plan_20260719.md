# TNO0140 Stage 31 miss-tolerant 13-pair deferred-activation strict plan

日期：2026-07-19

状态：计划在保留 Stage30 `cofire-strict` 12-pair 行为不变的前提下，新增独立显式
default-off `cofire-strict-extended`，只额外加入 Stage29 已测的第 13 对
`35026 -> 38043`。该 pair 有 141 次 leader fire 未触发 baseline follower，但这是额外
纯 compute 执行的性能成本，不是功能错误；本阶段按“轻微退化也实际跑 SimTop”的原则
直接生成 strict candidate，最终仍只以 50k `Host time spent` walltime 裁决。

## 1. Pair13 的原始证据

Stage28 exact row：

```text
source=35026 target=38043
source_active_id=25864 target_active_id=27857
source_batch=28 target_batch=30
source_ops=92 target_ops=86
shared_values=43
value_fingerprint=91cd730c99b00052
source_fire=3220 target_fire=3649
control_work_units=263 candidate_work_units=176 static_saved_units=87
control_deferred_direct=14 candidate_deferred_direct=13
control_branchless=18 candidate_branchless=17
control_entries=19 candidate_entries=19
control_lines=19 candidate_lines=21
```

Stage29 50k no-mutation raw counters：

```text
leader_fire=3220
follower_fire=3649
before_pending=706
after_pending=follower_pending=3079
baseline_flush_added=2373
leader_without_follower=141
forward_would_add=2514
```

若把每个 source fire 的 static saved `87` 当作上界，原值为
`87 * 3220 = 280,140` work proxy。按真实 141 次额外 target fire、每次最保守计入全部
86 ops，修正后为 `280,140 - 141 * 86 = 268,014`，仍保留上界的约 `95.67%`。
即使错误地假设 3,220 次 source fire 都额外执行 target，Stage28 lower 仍为
`(87 - 86) * 3,220 = 3,220 > 0`。这些只是选候 proxy，不替代 walltime。

target 38043 的 86 个 op 全为纯 `kLogicAnd`；没有 side effect、commit、memory、event、
div/mul、wide 或 dynamic-slice。source active/batch 均早于 target，额外 bit 会在同一 eval
round 的后续 target 位置被消费，不要求新增 settle round。输入未变的额外执行由 target
输出的既有 changed checks 阻止继续传播。

## 2. 独立 policy 与 fail-closed 契约

- 保持 `cofire-strict` 精确等于 Stage30 的 12 对，避免历史结果漂移；新增
  `cofire-strict-extended` 精确等于前 12 对加 pair13。两者 C++ 默认都不启用，XS 只
  转发显式环境变量。
- extended 必须固定 13 对的 source/target、active ID、batch、op counts、50k fire、
  value count/fingerprint、cross-word、source-before-target、互不 overlap 和 pure compute；
  任一 profile/schedule/value set 改变时 fail-closed。
- 复用 Stage30 private ordinary-compute fanout overlay；不修改 baseline graph、schedule、
  active IDs、batch、slots、materialization、fullpass、commit、seed 或 session。
- pair13 和前 12 对一样，删除 source 对 43 个 target-only values 的 changed/deferred
  lowering，并在 source baseline deferred flush 后无条件置 target bit。允许已知的
  141 次额外 target fire；功能等价性由 purity gate 和 100/10k/50k difftest 验证。
- extended 使用独立 13-pair accounting gate，至少固定 local work
  `3,525 -> 2,129`、estimated lines `442 -> 466`、forward groups=`13`；其它字段以
  production raw accounting 核对后记录，不从 Stage28 broad 128-pair accounting 反推。

## 3. 静态预期与验证阶梯

相对 baseline control，13-pair 的已知静态上界为：

```text
selected values:             691
local work:                  3525 -> 2129 (-1396)
deferred direct groups:       101 -> 89
branchless groups:            440 -> 425
active entries:               523 -> 521
planned chunks:               442 -> 440
global RMW:                   442 -> 440
estimated activation lines:   442 -> 466 (+24)
forward groups:                 0 -> 13
global work:              2417244 -> 2415848 (-1396)
```

验证顺序：

1. focused emitter/Python/XS tests；确认 default/off 与既有 Stage30 policy 不变，extended
   在 invalid profile/pair/fingerprint/accounting 上 fail-closed。
2. fresh production emit，记录 13 个指纹、local/global accounting、改变的 CPP、source
   bytes 和 identity SHA；不得把 Stage28 broad candidate 当作实际 extended accounting。
3. O3/archive/link，随后 fixed-ASLR 100/10k/50k difftest；保存绝对 endpoint、raw log
   SHA 和大小。任何功能差异立即停止。
4. 功能通过后，control/Stage30-12/Stage31-13 使用独立 fresh page-local inode，按
   `taskset + numactl --physcpubind/--membind` first-touch、`setarch -R`、whole-node
   pre/runtime gate、`numa_maps`、ABBA/BAAB 和双 NUMA测量。
5. 最终 headline 只用 SimTop `Host time spent` walltime。若机器持续无 quiet window，
   记录 gate block 并保持 extended/default off；不以 N0 单组、cycles、instructions 或
   static work 晋升默认。

若 13-pair strict 在有效 walltime 中中性或正向，下一阶段再对 7 个低 fire-gap pair 做
独立 no-mutation cofire probe；不在本阶段同时扩大 profile 和 strict 集合。

