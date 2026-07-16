# TNO0093 Stage 15 activation-equivalent sibling fusion probe plan

记录日期：2026-07-17

状态：计划。基于 current native hybrid default，先增加默认关闭、完全不修改 schedule 的 activation-equivalent sibling fusion probe。production exact bucket 只接受 state-free、event-free、unclassified-free compute supernode；完整 signature 由 final level、schedule incoming `ValueId` 集合和 graph input/inout `ValueId` 集合共同组成。主 probe 允许 pair 在 topo/storage order 中不相邻，并按距离分布与稳定 nearest-pair selection 报告机会；combined raw ops 不超过 current `maxOpInComputeSupernode`（production `108`）。graph input/inout 只用于证明 activation equivalence，projected raw BAE gain 仍只计算 schedule incoming `Vin`。baseline DP 理论上已经自动合并 exact adjacent + cap-legal pair，因此 production `adjacent_cap_eligible` 预期必须为 `0`；现有 `2,416` pairs / `13,291` gain 只是 predecessor-level DAG proxy 上界。strict mutation 必须等 canonical active ID、batch 与 layout 前置层闭合后另行实施。

## 1. 动机与当前基线

[TNO0092](./TNO0092_stage14_native_hybrid_default_adoption_decision_20260717.md) 已将 direct single-writer state read 与 pure-event compute-word bypass 成对采用为 C++ native defaults。Stage 15 的唯一 runtime control 因而是 current native hybrid default；不再回到旧 NO0300 emitter 形状，也不在 XS 脚本中补默认值。activity-schedule 的其它实验 policy、pure-event profile 和 word packing 继续保持关闭。

此前的 local move、clone、penalty 与 fanin pullback 表明，只降低少量 BAE 不一定改善 frontend；大范围 active-ID 或 batch 重排反而可能压过结构收益。因此本阶段不再移动单个 op/cone，而是检查一种更严格的形状：两个没有 state/event/unclassified activation source、且以相同 schedule 与 graph input/inout ValueId 被激活的同 level sibling supernode，是否可以共享一次 activation target 与函数调度。

既有 baseline DP/coarsen 已有 sibling merge：若两个 exact-equivalent sibling 在 final order 中相邻、combined raw ops 不超过 current compute-supernode cap，理论上它们应已被自动合并。production 的该 cap 为 `108`，与既有 `maxOpInComputeSupernode` 共用，不新增独立常量。因此 Stage 15 不能把“相邻 exact pair”当成新的主候选；production 中该数量应为 `0`，否则优先说明 baseline DP 性质、signature 定义或 probe 位置存在偏差。真正需要量化的是被其它节点隔开的 non-adjacent sibling：它们满足 activation equivalence，但既有局部 DP 无法跨越中间 storage/topo 项完成融合。

设两个 compute supernode 为 `A/B`，并定义带类别的完整 signature：

```text
signature(S) = (
    finalLevel(S),
    sortedUnique(scheduleIncomingValueIds(S)),
    sortedUnique(graphInputInoutValueIds(S)))
```

schedule 与 graph 两组 `ValueId` 不做无标签 union；同一个 ID 出现在不同来源类别时仍保留类别。令共同的 schedule incoming 集合为 `Vin`，共同的 graph input/inout 集合为 `Vio`。`Vio` 只用于证明两边 activation input 完全相同，不计入 raw BAE。融合前每个 `v in Vin` 分别激活 `A` 和 `B`，共有 `2 * |Vin|` 个对应 BAE；融合后每个 `v` 只激活合并节点一次，因此该 pair 的 projected raw BAE gain 为：

```text
projectedRawBAEGain(A, B) = 2 * |Vin| - |Vin| = |Vin|
```

两个节点处于同一 Kahn level，彼此之间不存在依赖边；融合只把各自原有 raw ops 按稳定顺序放进同一 supernode，输出 `ValueId` 和外部 consumer 不变。在 state/event/unclassified source 均为空且上述完整 signature 相同的前提下，任何一方执行时另一方原本也会执行，所以融合不会把原本 inactive 的 raw op 带入新的动态轮次。该结论不能用相同 predecessor supernode、symbol 或不分来源类别的 value 集合近似替代；non-adjacent fusion 还会接触 active-ID、batch 和 source layout，因此只读 probe 成立也不等于可以立即 strict。

这一保守边界来自 current native hybrid 的实际 lowering：direct single-writer state read 会重写 state-read frontier；memory row readers 会在后续 lowering 中细化到 graph input/inout value；pure-event 即使关联同一 symbol/value，posedge 与 negedge 的触发语义也不同。仅比较 scheduler incoming symbol/value 或要求两边 state signature 相同，都不足以证明 emitter activation equivalence。因此首轮 exact bucket 直接拒绝任何 state/event/unclassified source，并把 graph input/inout `ValueId` 作为独立 signature 分量。

## 2. 现有只读代理量化

对当前 production schedule 的只读扫描得到以下漏斗：

| 代理层 | 数量 | 代理收益 |
| --- | ---: | ---: |
| 相同 predecessor signature | `4,533` groups / `22,401` supernodes | 未做 conflict/cap 选择 |
| coarse predecessor 桶内的 topo/storage adjacent run | `4,076` runs / `18,790` supernodes | 邻接关系仍可互相重叠 |
| earlier loose proxy cap `combined raw ops <=128` 的邻接 pair | `8,558` pairs | projected DAG-edge gain `66,143` |
| coarse proxy 再要求 state signature 相同 | `2,416` pairs | projected DAG-edge gain `13,291` |

这些数字只证明机会规模值得实现正式 probe，不能作为 strict 的结构结果：

- 当前分组使用 predecessor-level signature，尚未逐 pair 验证完整 incoming `ValueId` signature；同一 predecessor 可以提供不同 value，正是这些 false-equivalent pair 让 coarse adjacent proxy 可以非零。
- 代理的“state signature 相同”仍允许 non-empty state；production exact bucket 会进一步收紧为 state-free，并同时排除 event/unclassified source。
- 一个长度大于 2 的 adjacent run 会产生重叠 pair；`2,416` 不是 conflict-free selection 数量。
- `66,143/13,291` 是按 predecessor edge 计算的 DAG proxy，不是 exact BAE recount，也没有应用 `finalSiblingFusionMinGain/MaxPairs/MaxFusedOpPpm` 预算。
- 代理没有解决融合后的 active-ID 稳定性；若 dense renumber 导致后续全部 active word/bit 漂移，局部收益会再次被全局 layout 变化污染。

因此 `2,416 pairs / 13,291 gain` 明确记为 upper bound/proxy，且该早期代理使用的 loose `128` cap 不是正式实现配置，不能与 production exact candidate 数直接比较。正式 probe 必须重新从 canonical final schedule 构造 state/event/unclassified-free 的完整 `(level, schedule Vin, graph Vio)` signature，在 signature 桶内扫描包括 non-adjacent 在内的 pair，报告 topo/storage distance 分布并做稳定无冲突选择。另设 `adjacent_cap_eligible` 精确计数 safe exact-signature、combined raw ops 不超过 current `maxOpInComputeSupernode` 且双 order 相邻的 pair；该值预期为 `0`，用于验证既有 DP sibling merge 性质，并在 min-gain 前独立计算。

## 3. Probe policy 与预算

计划新增以下 activity-schedule 配置，首阶段只接受 `off/probe`：

```text
finalSiblingFusionPolicy        = off
finalSiblingFusionMinGain       = 4
finalSiblingFusionMaxPairs      = 256
finalSiblingFusionMaxFusedOpPpm = 5000
```

CLI、Python 与 XS 分层分别使用统一的 `final-sibling-fusion-*`、`final_sibling_fusion_*` 和 `WOLVRIX_XS_GRHSIM_FINAL_SIBLING_FUSION_*` 命名。C++ `finalSiblingFusion*` 是唯一默认源；Python/XS 未显式设置时不注入属性，不在脚本中复制默认，XS 日志显示 `cpp-default`。

`finalSiblingFusionMaxFusedOpPpm=5000` 表示 selected pairs 覆盖的 combined raw ops 不超过 production raw-op 总数的 `0.5%`。每 pair 的 combined raw-op cap 直接复用 `maxOpInComputeSupernode`，production 为 `108`；`finalSiblingFusionMinGain=4` 按 schedule `Vin` 的 projected raw BAE gain 判断，而不是按 graph `Vio`、predecessor 数或 DAG proxy 判断。`finalSiblingFusionMaxPairs=256` 与 PPM budget 任一先到即停止选择。

`probe` 只读 final schedule，不修改 supernode partition、op owner、DAG、topo、storage order、active ID、batch 或任何 emitter metadata。probe summary 写入独立日志/可选统计，不向默认 raw activity stats 注入字段；`off` 不扫描、不分配 production-sized scratch，也不产生日志噪声。

## 4. Exact candidate、距离与稳定选择

probe 先拒绝有 state/event/unclassified source 的节点，再按 `(final level, schedule incoming ValueIds, graph input/inout ValueIds)` 完整 signature 建桶，并在桶内扫描 pair `A/B`；相邻不是 selected eligible 的硬条件。每个 pair 逐项要求：

1. `A/B` 为不同、非空的 compute supernode；commit、oversize split 或无法分类的节点拒绝。
2. 两边 state-read/frontier source 都为空；“相同且非空的 state signature”也不放行。
3. 两边 posedge/negedge/其它 pure-event source 都为空，且没有 unclassified activation source。
4. final Kahn level、去重排序后的 schedule incoming `ValueId` 集合和带独立类别的 graph input/inout `ValueId` 集合分别 byte-exact。只比较 predecessor SN ID、symbol 或不分来源类别的 value union 不足以通过。
5. `rawOps(A) + rawOps(B) <= maxOpInComputeSupernode`（production `108`）。进入 selection 时另要求 projected `|Vin| >= finalSiblingFusionMinGain`；graph input/inout `Vio` 不加入这个 gain。
6. 同 level 与完整 signature 检查确认 `A/B` 之间没有隐式或显式依赖；融合后所有 output value、consumer、commit use 与全局 state/event use 保持原样。

对每个 exact signature bucket，定义：

```text
topoDistance(A, B)    = abs(topoPos(A) - topoPos(B))
storageDistance(A, B) = abs(storagePos(A) - storagePos(B))
pairKey               = (topoDistance, storageDistance,
                         min(supernodeId), max(supernodeId))
```

桶内按 `pairKey` 升序贪心选择未冲突 pair；先取 topo/storage 距离最小者，距离相同才由 canonical supernode ID 决定。bucket 之间按 projected raw BAE gain 降序、规范化 signature byte order 升序处理，再依次应用 `finalSiblingFusionMaxPairs` 与 `finalSiblingFusionMaxFusedOpPpm` 预算。这样 selection 不依赖容器插入顺序，也不会把所有两两组合简单相加。

summary 记录 compute SN、signature group/node、empty/input/state/event/unclassified/singleton、raw/cap/exact/selected、projected raw BAE、fused-op limit、adjacent scan 与各 reject 数。distribution 使用已实现的 capped count maps：eligible/selected 分别按 gain、fused ops、storage distance 和 topo distance 计数；不承诺 DAG projection、distance quantile 或 topo/storage 联合分桶。每个 selected pair 行输出 `lhs_supernode_id/rhs_supernode_id`、对应 `lhs_active_id/rhs_active_id`、gain、fused ops 和两种 distance，供后续 rtprof 对照和 canonical packing/layout 处理。

`adjacent_cap_eligible` 单独统计 `topoDistance==1 && storageDistance==1` 的 safe exact-signature、cap-legal pair，并在应用 `finalSiblingFusionMinGain` 前计算；即使 `|Vin| < 4` 也进入该性质计数。production 预期必须为 `0`；若非零，先诊断 baseline DP sibling merge，不进入 strict 设计。重复运行要求结构 count maps 与逐 selected-pair 行稳定；full summary 含天然变化的 `elapsed_ms`，不要求 byte identity。

首轮 probe 不把 selected pair 应用到副本，也不把代理收益写成 actual delta。若完整 ValueId 分类、state/event/unclassified、conflict 与预算漏斗后没有足够候选，直接归档并停止，不为凑 50k 放宽 activation-equivalent 条件。

## 5. Canonical active ID、batch 与 layout 前置门禁

strict fusion 会把两个 active target 变成一个。对 non-adjacent pair，还必须把两个相隔的 storage/function 区域收敛到一个 canonical anchor。若沿用当前按 dense final supernode order 重新编号 active ID、再按 actual partition 重建 batch/source layout，删除一个节点会移动其后的 active word/bit、函数表、batch membership 和 propagation mask，形成与历史 Stage 1 类似的全局 code-layout 扰动。因此 Stage 15 strict 的硬前置条件是同时闭合 partition-stable canonical active identity、batch 和 source layout：

- explicit-off/native default 的 active ID、active word/bit、函数顺序和全部 generated source byte-exact；
- strict pair 使用确定的 canonical anchor identity，未参与融合的 supernode active identity 全部不变；
- 被融合 sibling 的 identity 不得被后续节点复用而引发级联改号；若需要 reserved hole 或等价 indirection，必须有完整 bounds/uniqueness validator；
- activation target/mask 只允许在 selected pair 上由两个等价 target 收缩为一个，不能出现 selected set 之外的 changed/missing/extra target；
- 未参与融合的 supernode 必须保持 canonical batch、batch 内顺序、generated function/file 归属和 value-slot layout；non-adjacent pair 的中间节点不能因 anchor 选择整体前移或后移；
- selected pair 的 anchor、合并 op 顺序和 source placement 必须由 baseline canonical metadata 决定，source diff 可局部归因，不能用 actual dense renumber 隐式决定；
- metadata 缺失、重复、越界或顺序不一致时 fail closed 或回退 explicit legacy path，不能静默生成部分 canonical layout。

只有这三层的 focused fixture 和 production identity 都通过，才允许新增 `strict` policy。canonical active ID/batch/layout 本身若造成 off-path source 漂移或明显数据结构膨胀，应先修复或停止，不能带着漂移进入 fusion runtime。

## 6. Focused correctness gate

Probe 阶段至少覆盖：

- native default、显式 `off` 与 `probe` 的 schedule/session/raw stats identity；probe 阶段不要求生成 CPP；
- `probe` 正例包含相同 schedule `Vin`、相同 graph input/inout `Vio`、同 level、state/event/unclassified-free，但在 topo/storage order 中非相邻的 pair；报告 projected raw BAE gain `|Vin|`、正确距离、lhs/rhs SN 与 active ID，同时所有 schedule 字段保持不变；
- predecessor/schedule `Vin` 相同但 graph input/inout `Vio` 不同、graph symbol 相同但 `ValueId` 不同、来源类别不同但无标签 union 相同分别拒绝；
- 任一 state source 都拒绝，包括两边 state signature byte-exact；pure-event 同 value 的 posedge/negedge pair 和任一 unclassified source 也分别拒绝；
- `Vio` 只参与 equivalence：fixture 显式验证 projected raw BAE gain 只等于 `|Vin|`，不加 `|Vio|`；
- level 不同、combined raw ops 为 configured cap `+1`（production `109`）、commit 分别拒绝；topo/storage 任一或全部相邻本身既不构成接受条件，也不构成拒绝条件；
- baseline DP fixture 中 pre-DP safe exact adjacent + cap-legal sibling 被既有 merge 吸收，final probe 的 `adjacent_cap_eligible==0`；另用 `|Vin| < minGain` fixture 证明该计数独立于 `finalSiblingFusionMinGain`；
- 同 signature 长桶的 overlapping pairs 按 topo/storage 最短距离、再按 ID 做稳定 conflict-free selection；gain/fused-op/topo-distance/storage-distance count maps 以及 `finalSiblingFusionMinGain=4`、`finalSiblingFusionMaxPairs=256`、`finalSiblingFusionMaxFusedOpPpm=5000` 边界均有正反例；
- 相同 fixture 重复运行时，忽略 `elapsed_ms` 后的关键 count maps、selection fields 与逐 pair 行相同；非法 policy、负数/溢出 PPM 和 pair budget 明确失败。

进入 strict 后再增加：raw op partition exact、selected union exact、非 selected owner 不变、actual BAE delta 等于 selected `sum(|Vin|)`、DAG recount 与 projected 值一致、graph input/inout、state/event/commit/value-use 不变，以及 canonical active target diff 只覆盖 selected pairs。用 focused activation trace 证明每对 baseline `lhs-only/rhs-only` fire count 为 `0`，并验证融合前后 raw-op execution count 相同；该动态 trace 是静态完整-signature proof 的补充门禁。

## 7. Production、build 与功能门禁

Production probe 从 current native hybrid default 的 canonical checkpoint 运行，明确保持：

```text
direct_single_writer_state_reads = native true
pure_event_compute_word_bypass   = native true
pure_event profile / word pack   = off
all other experimental schedule policies = off
Stage 15 policy                  = off or probe
```

`probe` 与 `off` 的 raw activity stats 和 schedule/session metadata 必须 byte-exact；probe summary/pair rows 是唯一允许的差异，首轮不要求生成 CPP。production 首先要求 min-gain 前独立计算的 `adjacent_cap_eligible==0`，确认 safe exact adjacent 机会已被 baseline DP 吸收；随后归档 signature group/count maps、capped topo/storage distance maps、selected lhs/rhs SN+active-ID rows 和 conflict-free selected 上界，再决定是否投入 canonical active-ID/batch/layout 与 strict 实现。

strict 若进入，结构 gate 至少要求：

- supernode count 精确减少 selected pair 数，raw op/value 总数不变，每个 op 恰好出现一次；
- 每个融合节点 raw ops 不超过 current `maxOpInComputeSupernode`（production `108`），非 selected supernode partition/storage order 保持不变；
- actual total/compute BAE 精确下降 `sum(|Vin|)`，DAG edge delta 与 full recount 一致；
- commit partition/order、state-read signature、value users、topological legality和功能语义全部通过；
- 非 selected active ID/word/bit、batch、value slot 与 generated function/file layout 不漂移，source diff 可逐项归因于 selected fusion；
- generated source、O3 ELF `.text/.data/.eh_frame`、activation update sites 和 function-table 数量均记录，但轻微静态退化不直接否决 50k。

随后执行 focused tests、完整 build 与 CTest；只允许保留既有 `transform-comb-lane-pack` 和 `transform-repcut` 两项失败。fresh candidate 完成 fixed-ASLR 100/10k/50k 功能门禁，50k 终点仍要求：

```text
guest/cycleCnt/instrCnt/PC = 50001/49996/73580/0x80001312
```

除明显错误、结构爆炸或功能失败外，即使 BAE/DAG/size 有温和退化也继续一次 SimTop 50k，避免漏掉 active-check/function-dispatch 减少带来的真实收益。

## 8. 50k 性能与默认决策

正式 runtime 以 current native hybrid default + Stage15 `off` 为 control，同一 native hybrid + `strict` 为唯一 candidate。继续执行 [TNO0085](./TNO0085_numa_file_page_locality_diagnosis_and_protocol_20260716.md) 与 [TNO0089](./TNO0089_page_local_stage12_stage13_interim_runtime_and_strict_numa_protocol_20260717.md) 的严格协议：

- N0/N1 使用镜像 physical core，binary/image/NEMU 在各 node 的 `/dev/shm` 独立 inode 预热并验证 file/anon placement；
- workload 同时使用 `taskset`、`numactl --physcpubind/--membind` 和 `setarch x86_64 -R`；
- 整 node 30 秒 pre-run gate、运行期整 node monitor、PMU/scheduler/功能终点全部通过；
- 每个 node 独立执行平衡 AB/BA 重复，污染样本或 control 漂移超限时整组作废重跑，不拼接不同 quiet window；
- 以 cycles 为最终口径，同时记录 instructions、frontend empty、frontend `cmask>=6` 与 backend stalls，不用跨 node 平均掩盖方向反转。

Stage15 policy 初始默认保持 `off`。只有 strict 在 page-local 双 node 上方向一致、超过 control noise 且无功能/回归问题，才另立 adoption 记录讨论 C++ native default；probe proxy、单 node walltime 或高负载样本都不能直接触发默认变更。

## 9. 提交边界

probe option、focused tests、production probe 与结果文档作为一个阶段提交：先提交 `wolvrix` 子模块，再提交父仓 submodule pointer、XS 显式透传和 TNO/README。canonical active-ID/batch/layout 层与 strict fusion 各自形成后续独立阶段，不与 no-mutation probe 混入同一提交；生成目录和 perf 日志不提交。
