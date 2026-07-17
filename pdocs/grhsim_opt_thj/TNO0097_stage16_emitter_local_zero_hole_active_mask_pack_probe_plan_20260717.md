# TNO0097 Stage 16 emitter-local zero-hole active-mask pack probe plan

记录日期：2026-07-17

状态：计划。Stage 15 production exact sibling fusion selection 为 `0`，不再通过 schedule mutation 追逐 raw BAE；Stage 16 转到 GrhSIM emitter 的实际 activation lowering cost，新增 C++ native default `active_mask_gap_pack_policy=off`，首阶段只实现 `off/probe`。probe 在 local/global split 和 global byte-entry merge 后离线比较 baseline contiguous pack 与允许零洞的 `1/2/4/8`-byte chunk，不发 candidate，不改变 schedule、topo、active ID、batch、value slot 或 generated source layout。初步静态量化显示 direct write sites 可由 `819,225` 降至 `785,991`（`-4.057%`），table entry 的 gap-pack proxy 相对 contiguous greedy 再降 `11.374%`；但 table 可能主要位于 reset/cold path，最终 strict 仍须另立 targeted 阶段并由 current native-hybrid SimTop 50k 裁决。

## 1. 为什么从 raw BAE 转向 emitter lowering

[TNO0095](./TNO0095_stage15_sibling_fusion_probe_implementation_and_production_result_20260717.md) 的 exact production 漏斗为 `7,234 -> 7 -> 0`，放宽 min-gain 后 raw BAE 收益上界仍 `<0.0011%`。这关闭了 activation-equivalent sibling fusion strict 路径，也说明继续为很小的 schedule 边数变化承担 active-ID/batch/layout 稳定成本不合算。

[TNO0094](./TNO0094_stage14_native_hybrid_commit_cap_fresh_gate_20260717.md) 进一步证明 raw BAE 与最终 emitter work 不单调。一个 source value 到 target supernode 的 BAE 在 emitter 中会先转成 active ID，再按每 8 个 ID 合并成 byte mask；同 byte 多个 target 只需一个 OR bitmask，连续 byte 还可由 `8/4/2/1`-byte helper 合并。删除一条 BAE 可能只清掉 mask 中一 bit，未必减少任何 write；反过来，改变 target 分布也可能破坏 chunk packing。

因此 Stage 16 直接优化现有 active byte-mask map 的物化方式，同时冻结所有上游结构：

```text
GRH / schedule partition / topo       unchanged
supernode active ID                   unchanged
sched batch and file/function order   unchanged
typed value-slot mapping              unchanged
source layout skeleton                unchanged
only active-mask statement/table encoding may change in a future strict stage
```

首轮 probe 连 statement encoding 都不改变，只报告等价 candidate cost。这样机会量来自实际 lowering 形状，不再把 raw BAE 当作机器 work。

## 2. 唯一 C++ 默认与 sparse plumbing

新增 emitter option：

```text
active_mask_gap_pack_policy = off
```

首阶段只接受 `off/probe`；不暴露尚未实现的 `strict`。配置优先级与 current native defaults 一致：

```text
emitter attribute
  > WOLVRIX_GRHSIM_ACTIVE_MASK_GAP_PACK_POLICY
  > C++ native default off
```

Python/native binding 使用 `str | None`：显式字符串写 emitter attribute，`None` 不写，由低层环境或 C++ default 决定。XS 高层入口为：

```text
WOLVRIX_XS_GRHSIM_ACTIVE_MASK_GAP_PACK_POLICY
```

XS 未设置时保持 sparse，不注入 `off`、不写回低层 `WOLVRIX_GRHSIM_*`，日志显示 `cpp-default`；显式高层值才作为 attribute override 透传。由此直接调用 emitter、Python 与 XS 都共享同一个 C++ 默认源。

`off` 不构造 probe-only production scratch，也不新增默认 emit stats 字段。`probe` 只做计数和 validator，最终 generated C++/headers 必须与 `off` byte-exact；任何 source 差异都说明 probe 越过了 no-mutation 边界。

## 3. Baseline lowering 模型

对一次 activation target list，保持现有顺序执行：

1. **Local 先 split**：若 target 位于当前 active byte 且 bit 在当前执行 bit 之后，合并进 local byte mask；这些 target 不再进入 global pack。
2. **Global entry merge**：其余 active ID 先映射为 `byteIndex=activeId/8`、`bit=activeId%8`；相同 byte 的 bit OR 成唯一 `ActiveMaskEntry(byteIndex, mask)`，并按 byteIndex 排序。
3. **冻结 baseline table 判定**：以 global merged entry 数 `n` 判断；`n>=32` 使用 per-entry `kActivationMasks` table loop，否则进入 direct chunk path。
4. **Baseline contiguous greedy**：direct path 从第一个未消费 entry 开始，只在后续 byteIndex 严格连续时按 `8/4/2/1` 最大宽度贪心；不连续位置拆成新的 chunk。

conditional lowering 同样冻结：condition expression、direct/deferred owner、local/global split 与 baseline table/direct 分支均先按现有实现决定。probe 不能因为 zero-hole 后 chunk 数变少，就把 baseline table 改判为 direct，也不能合并不同 condition 的 target list。

这里的 `n>=32` 是 baseline merged byte-entry 数，不是 BAE、active ID 数或 candidate chunk 数。

## 4. Zero-hole candidate 的精确模型

candidate 只重编码已经冻结的 global byte-entry map。合法 chunk 定义为：

```text
width in {1, 2, 4, 8}
startByte <= real entry byteIndex < startByte + width
startByte + width <= activeByteCount
floor(startByte / 64) == floor((startByte + width - 1) / 64)
```

即 chunk 必须在 active byte array bounds 内，且新增 gap chunk 不跨 logical 64-byte lane。这里的 `index % 64` 只是基于数组下标的 logical-lane proxy；当前 active byte array 没有 `alignas(64)`，因此它不等于实际 cache-line 边界。chunk 覆盖区间内存在的 entry mask 放到对应 byte；没有 entry 的洞填 `UINT8_C(0)`。对 OR lowering，向洞 byte OR 零不改变 active state。

probe 将有序 nonzero entries 分区为合法 `1/2/4/8`-byte chunks，优化顺序为：

1. 最少 chunk/write 数；
2. 同 write 数下最少 zero-hole bytes；
3. 再按 start byte、width 的稳定顺序打破平局。

如果 power-of-two chunk 所需的 trailing zero 能减少总 write 数，则允许在最后一个真实 entry 之后填充；在 write 数相同的方案之间仍选择 hole 最少者。所有 trailing hole 同样必须满足 array bounds 与 logical-lane 约束，不能只为扩大 width 任意越界填充。baseline contiguous 和 candidate gap pack 都必须通过逐 byte validator：

```text
expand(chunks)[byte] == mergedEntries[byte]  for every byte
```

validator 同时检查：

- 每个原始 nonzero mask 恰好出现一次；
- 每个缺失 byte 的 candidate mask 精确为 0；
- 没有 overlap、越界、跨 lane、missing 或 extra nonzero byte；
- 将 chunks 展开后与 baseline merged map byte-exact。

任何 validator 失败只报告 probe invalid，不导出 candidate cost。

## 5. 分类边界

首轮 headline 只覆盖两类已经明确的 global lowering：

- **direct**：baseline `n<32`、现有 contiguous `8/4/2/1` helper path；
- **table**：baseline `n>=32` 的 `kActivationMasks` entries；table/direct 分类保持冻结，但同时报告把同一 entry map 重编码成 contiguous chunks 和 gap chunks 的 write proxy。

其它类别单列，不夸大覆盖：

- **local** 已在 global merge 前形成单 byte mask，当前 production 只有 `34` 个 site，首轮只统计、不重打包；
- **deferred** 同时受 condition group、direct-vs-accumulator cost model、temp updates 和 final flush 影响；离线量化虽显示 `2,210 -> 1,478 -> 1,167`，首轮明确排除，不计入 headline gain；
- **memory-row readers** 会在 emitter 中细化 reader/row activation，必须独立确认 owner 与执行频率，不能默认并入 direct；
- **seed/reset/initial** activation 可能属于冷路径，必须单独分类；即使静态 table entry 很多，也不能宣称为 50k hot work。

日志中的 `a_succ` 按 activation-producing op/check 机会计数：每个具有 nonempty `boundaryFanout` 的 result 加一，每个具有 reader head 的 write op 加一。它既不是 schedule BAE/graph edge 数，也不是 active byte/chunk write 数；`a_succ -X%` 只能描述这类 producer/check 机会的变化，不能写成“边数减少”“write 数减少”或“动态执行减少 X%”。

## 6. 初步静态量化

对 current native hybrid/cap4096 generated source 的离线模型得到：

### Direct global path

| metric | baseline contiguous | zero-hole candidate | delta |
| --- | ---: | ---: | ---: |
| write sites | `819,225` | `785,991` | `-33,234` (`-4.057%`) |
| inserted zero-hole bytes | `0` | `96,772` | candidate covered bytes 的 `11.3%` |

`819,225` 对应实际 direct one-byte/chunk write site 口径，不是 raw BAE。约 4.1% 的 write-site 上界足以支持正式 no-mutation probe，但 `96,772` 个零洞会增加写宽度和 touched bytes，必须在 strict O3/PMU 中同时检查 store/load lowering、code size 和 cache 行为。

### Baseline table path

| metric | current per-entry | contiguous chunk proxy | zero-hole chunk proxy |
| --- | ---: | ---: | ---: |
| writes/chunks | `92,384` | `21,373` | `18,942` |
| vs contiguous greedy | - | control | `-2,431` (`-11.374%`) |
| vs current per-entry | control | `-71,011` | `-73,442` |
| zero-hole ratio | `0` | `0` | `7.93%` |

table 静态 proxy 比 direct 更大，但不能直接推断性能收益：现有 loop body 很小，`92,384` 是所有 table entries 的潜在 per-entry writes；其中一部分可能只在 reset/initial 或其它冷 condition 下执行。probe 必须按 owner/path 分类，后续 strict 前还要有 runtime evidence，不能用静态 entry 总数乘成动态收益。

### Excluded categories

```text
deferred: current 2,210 -> contiguous 1,478 -> zero-hole 1,167
local:    34 sites, report-only
```

deferred 数字只作为后续方向，不进入 Stage 16 首轮 selected gain；memory-row 与 seed/reset 也必须分别报告 covered/excluded 数，不能静默落入 direct/table 总数。

## 7. Probe 统计与 focused gate

probe 至少输出每类：

- activation lists、local targets、global active IDs、merged byte entries；
- baseline table/direct lists、baseline writes/chunks；
- contiguous chunks、gap chunks、write delta；
- real covered bytes、zero-hole bytes/ratio；
- rejected bounds/lane/validator 数和 invalid lists；
- conditional、table、direct、local、deferred、memory-row、seed/initial 与 unclassified owner counts。

所有 headline delta 都必须可由分类计数重算；elapsed time 单列，不参与 deterministic identity。

Focused tests 至少覆盖：

- native default、显式 `off` 与 `probe` generated source byte-exact；
- attribute > low-level env > C++ default，Python `None` 省略、XS unset sparse/`cpp-default` 与显式 override；
- 多 active ID 合并成同一 byte entry，local target 在 global pack 前移除；
- baseline contiguous `8/4/2/1` 与当前 emitter helper 选择完全一致；
- 单洞/多洞正例、width `1/2/4/8`、能减少 write 的合法 trailing zero、array 尾部 bounds、logical 64-byte lane 边界；
- hole mask 必须为 0，逐 byte expansion validator 的 missing/extra/overlap/跨 lane 反例；
- baseline entry `31/32` 固定 direct/table，candidate cost 不反向改变分类；
- 不同 condition 不合并，deferred/memory-row/seed 明确落入 excluded/report-only bucket；
- 非法 policy 明确失败，重复 probe 的结构计数稳定。

## 8. Production probe gate

production control 使用当前 C++ native hybrid、commit cap4096 和 fixed schedule checkpoint；activity-schedule 及其它实验 policy 全部关闭。生成 `off/probe` 两套 fresh output，要求：

```text
activity-schedule stats SHA identity
topo / active-ID map identity
batch/file/function membership identity
typed value-slot identity
all generated C++/headers byte identity
ELF not required for no-mutation probe
```

probe 只归档 direct/table headline、holes、owner/path 分类和 validator。若 direct 收益不能复现约 `4%`，或收益主要来自 excluded/cold path，则停止；若机会仍成立，也只进入单独的 targeted strict 设计，不在 probe commit 中直接发 candidate。

## 9. Targeted strict 与最终性能边界

strict 必须另立阶段，并只采用 probe 已验证的类别。实现时保持 schedule、topo、active IDs、batch membership、value slots 和 source file/function order 不变；允许的 source diff 仅为 selected active-mask statement/table encoding。conditional/table baseline 判定继续冻结，不能为了扩大收益顺带重写 deferred strategy、memory-row ownership 或 seed scheduling。

targeted candidate 至少完成：

- focused/full regression 与 source-diff validator；
- fresh O3/link，记录 `.text/.data/.eh_frame`、函数/statement 数及相关汇编；
- 对 active byte array 增加明确的 64-byte 对齐，或用地址/汇编实测验证 candidate chunk 的实际 cache-line 边界；不能把 `index % 64` proxy 直接当作物理 cache-line 证明；
- fixed-ASLR 100/10k/50k 功能终点与负向扫描；
- 如果 table 是主要收益，增加 category runtime counter，确认并非仅 reset/cold path；
- current native-hybrid control/candidate 的 page-local 双 NUMA 50k。

正式性能继续使用 [TNO0085](./TNO0085_numa_file_page_locality_diagnosis_and_protocol_20260716.md) 与 [TNO0089](./TNO0089_page_local_stage12_stage13_interim_runtime_and_strict_numa_protocol_20260717.md) 的 node-local `/dev/shm` inode、镜像核、`taskset + numactl --physcpubind/--membind`、fixed-ASLR、whole-node pre/run monitor、page placement、PMU/scheduler 和平衡 ABBA/BAAB。最终口径是 SimTop 50k cycles，同时解释 instructions、frontend/backend 和 memory/cache 事件；静态 `a_succ`、hole ratio 或 `.text` 都不能单独触发默认采用。

Stage 16 初始默认保持 `off`。只有 targeted strict 在双 node 上形成方向一致、超过 control noise 的正收益且无功能/回归问题，才另立 adoption 记录讨论 C++ native default。

## 10. 提交边界

Stage 16 probe option、plumbing、focused tests、production no-mutation result 和对应 TNO 作为一个任务粒度：先提交 `wolvrix` 子模块，再提交父仓 submodule pointer、XS sparse plumbing 与文档。targeted strict、O3/function、功能和 50k 属于后续独立阶段；生成目录与 perf 日志不提交。

## 11. 增量勘误 2026-07-17：DP start 与 logical-lane 契约

第 4 节对 candidate chunk 合法性的表述需要补充两个实现契约；保留上文作为最初计划，后续实现、validator 与测试统一以下述定义为准：

1. gap DP 每一步的 `startByte` 必须精确等于当前首个尚未覆盖的 real entry 的 `byteIndex`。不允许把 chunk 起点前移并在首个 real entry 之前制造 leading hole；允许的 hole 只能位于 chunk 已锚定的首个 real entry 之后。
2. logical 64-byte lane 限制只作用于真正引入 hole 的 chunk，即 `holeBytes > 0` 时才要求 chunk 不跨 `floor(byteIndex / 64)` 边界。`holeBytes == 0` 的连续无洞 chunk 必须保留现有 contiguous lowering 的合法能力，即使它跨越 logical 64-byte lane 也不应被拒绝或拆分。

因此 validator 也应独立检查：所有 chunk 均由首个未覆盖 real entry 锚定；仅对 `holeBytes > 0` 的 chunk 执行 logical-lane no-cross gate。这个 logical lane 仍只是数组下标 proxy，不构成实际 cache-line 对齐证明。
