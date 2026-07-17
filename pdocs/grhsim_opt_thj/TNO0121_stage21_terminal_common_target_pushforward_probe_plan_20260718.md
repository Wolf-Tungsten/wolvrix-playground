# TNO0121 Stage 21 terminal common-target pushforward probe plan

记录日期：2026-07-18

状态：计划。Stage 20 table lowering walltime 中性、Stage 7+ corrected runtime 持续补测的同时，下一条 activity-schedule 主线转向 terminal common-target pushforward。首阶段只做 default-off/no-mutation 结构 probe，寻找可将完整小型纯 compute node 从 source supernode 推入唯一 consumer supernode 的候选；只有 exact BAE 与 boundary materialization 同时下降，并通过后续动态额外执行 gate，才进入 strict mutation。

## 1. 当前基线与 GSIM 对照

唯一基线仍是当前仓库默认 NO0300：C++ native hybrid 开启、commit cap4096、其它 schedule 实验项关闭、ASLR 关闭。current GrhSIM absolute stats：

```text
supernodes                         63,726
compute supernodes                 63,241
commit supernodes                     485
DAG edges                         528,622
boundary activation edges       1,983,923
boundary values                 1,000,463
other-compute activation edges  1,805,435
other-compute unique SN pairs     518,558
other-compute duplicate edges   1,286,877
```

same-FIR GSIM/GrhSIM 结构对照：

| metric | GSIM | GrhSIM | GrhSIM difference |
| --- | ---: | ---: | ---: |
| supernodes | `84,713` | `63,726` | `-20,987` (`-24.774%`) |
| DAG edges | `645,827` | `528,622` | `-117,205` (`-18.148%`) |
| BAE | `1,367,271` | `1,983,923` | `+616,652` (`+45.101%`) |
| BAE / DAG edge | `2.117` | `3.753` | `1.773x` |

因此当前差距不是 supernode 或 unique dependency 数过多，而是每个 supernode pair 携带的不同 boundary values 过多。GrhSIM 的 `other_compute_duplicate_activation_edges` 定义为：

```text
1,805,435 value->target edges - 518,558 unique (sourceSN,targetSN) pairs
= 1,286,877
```

它占 other-compute BAE `71.277947%`，但这些 value 各有独立 changed predicate，不能按 pair 直接语义删除。

BAE 最大来源为：

| kind | edges | source values | edge/value | all-BAE share |
| --- | ---: | ---: | ---: | ---: |
| `kAnd` | `445,774` | `186,589` | `2.389` | `22.469%` |
| `kLogicAnd` | `202,280` | `89,362` | `2.264` | `10.196%` |
| `kAssign` | `191,620` | `73,644` | `2.602` | `9.659%` |
| `kSliceStatic` | `187,986` | `85,130` | `2.208` | `9.475%` |
| `kMux` | `174,748` | `143,770` | `1.215` | `8.808%` |
| `kEq` | `126,283` | `44,940` | `2.810` | `6.365%` |
| `kOr` | `115,911` | `59,095` | `1.961` | `5.843%` |

前七项合计 `1,444,602` BAE，占全部 `72.815%`。

## 2. 为什么不做 fanout free-dedup

emitter 已按 source supernode 内相同 changed-source set 构建 deferred activation group，把多个 changed predicate 先聚合为 local bool，再对 target active mask 做一次最终写。current cap4096 lowering 的绝对静态计数为：

```text
raw BAE                         1,983,923
one-byte OR                       790,475
chunk OR                           28,750
table loop body                       613
deferred final writes              19,044
deferred temporary updates          4,730
table entries                      92,384
static final sites                838,916
runtime-write proxy               930,687
```

历史 machine attribution 也排除了该方向：activation propagation 为 GrhSIM `304` samples、GSIM `315` samples，GrhSIM 并不更高；compute excess `60.50B` instructions 中 direct payload/generic helpers 解释 `50.075B`（`82.769%`），change tracking 另约 `7.25B`。deferred duplicate ideal machine 上界仅 `47.449` samples，约占 direct compute `0.849%`；packed/no-deferred variants 还会膨胀 O3 code 或 memory operands。Stage 20 进一步证明 instructions `-1.434620%` 也可能只对应 wall `-0.010753%`。

所以 Stage21 不把 raw duplicate count 当作可免费 collapse 的 active writes，也不再尝试简单整 supernode merge。Stage15 exact activation-equivalent sibling 在 `7,234` raw pairs 中只有 `7` 个 capacity eligible，gain>=4 后为 `0`；放宽后的总 gain也低于 `21` BAE。

## 3. Terminal common-target candidate

在 final materialization 后，令 `C` 为 source compute supernode `S` 中的一个完整 compute node/cone，`T` 为唯一 external consumer compute supernode。probe 只接受：

1. `C` 非空且不超过 `8` ops；所有 op 为 cheap pure allowlist，禁止 state/memory/event/intent/side effect、declared/port、clone-forbidden 和 split-sensitive path；
2. `C` 的所有 external output values 只被 `T` 中的 op 使用，无 commit 或第三 supernode consumer；
3. `C` 的所有 external input values 都由 `S` 中不属于 `C` 的 remaining ops 定义；输入、输出各不超过 `16`，所有 logic width 不超过 `64`；
4. move 后 `S` 和 `T` 均非空，`T ops + C ops <= 108`；
5. `S -> T` dependency 在 move 前由 outputs 存在，move 后由 inputs 保持；rebuild 后 DAG/topo/compute-commit/commit partition 必须 exact-valid；
6. touched supernodes 不冲突，最多选择 `128` moves。

对每个候选机械重算：

```text
removed BAE = C outputs whose S->T edge disappears
added BAE   = C inputs that did not already fan out to T
net BAE     = removed BAE - added BAE

removed boundary values = outputs that cease to have any external fanout
added boundary values   = inputs that become external for the first time
net boundary values     = removed - added
```

只有 `net BAE >= 1` 且 `net boundary values >= 1` 才进入 exact candidate。另报告 removed/added materialized bytes、kind/width、source/target op headroom、topo/storage distance 和 pair multiplicity。

首版预算的绝对上界：moved ops `<=1,024`，只占 current compute ops `5,625,117` 的 `0.018204%`；touched compute SN `<=256`，占 `63,241` 的 `0.404801%`。若每个 input/output 上限均为16，理论 net BAE 与 boundary-value gain 各不超过 `2,048`，分别为 current `0.103230%/0.204705%`。该窄预算明确不同于 Stage1 的 `4,096` moves、`51,569` moved ops 和大范围 layout 改写。

## 4. 动态风险与 profile gate

结构正收益不保证 runtime 正收益。原始路径只有 `C` 的 outputs 真变化才激活 `T`；pushforward 后，任一 input 变化会激活 `T` 并在 `T` 中执行 `C`，即使 outputs 最终不变。strict 前必须用不改 schedule 的 runtime profile 统计：

```text
source_dispatch
target_dispatch
input_changed_any
would_add_target = input_changed_any && target_active_bit_was_clear
```

估算：

```text
candidate_cone_evals = target_dispatch + would_add_target
cone op delta = |C| * (candidate_cone_evals - source_dispatch)
target extra op work = |T remaining ops| * would_add_target
```

优先只接受两项动态 delta `<=0` 的候选；轻微正值也必须由明显的 materialization/weighted BAE 收益覆盖。profile binary 只用于计数，不用于 walltime A/B。

## 5. 实现、identity 与 stop gate

首阶段新增 C++ native default `off` 的 `final-terminal-pushforward-policy=off/probe`，以及 max node/input/output/width、max moves 选项。Python/native/XS 只做显式 sparse override，不在 XS 脚本重复默认值。probe：

- 不修改 graph、schedule、active-ID、batch、slot、source 或 session payload；
- default/off/probe raw stats 与 generated artifacts byte-exact；
- focused fixture 覆盖 positive、third consumer、input not in source remainder、capacity、restricted op、boundary-value non-gain 和 deterministic selection；
- production 输出完整 reject funnel、candidate 明细和绝对 gain distribution。

若 `selected=0`、net boundary materialization 为0，或 relaxed total net BAE 仅为 Stage15 的几十条量级，则停止，不实现 runtime profile/strict。若 structural gain 足够，先增加 candidate-specific runtime counter；只有额外执行 gate 通过，才在下一阶段实现 strict move，并尽量限制 `S/T` 位于同一 baseline compute batch，避免重切全局 batch/layout。

最终 strict candidate 仍需 fresh emit/O3、100/10k/50k 功能、完整回归和正确 page-local 双 NUMA ABBA+BAAB；唯一 headline 是未插桩 SimTop 50k `Host time spent` walltime，cycles/instructions/BAE/slot bytes 只作诊断。
