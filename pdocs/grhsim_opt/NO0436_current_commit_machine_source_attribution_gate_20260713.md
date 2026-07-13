# NO0436 Current commit machine/source attribution gate

日期：2026-07-13

## 1. Input and exact-code gate

按 [NO0435](./NO0435_current_commit_machine_source_attribution_plan_20260713.md)，复用
[NO0388](./NO0388_direct_state_read_instruction_profile_gate_20260712.md) 的 25M-period、0-lost、fixed-ASLR
exact-entry direct profile，没有重跑仿真或修改 emitter。

profile 中共有 6,675 个 samples，其中 868 个落在 42 个 commit batches；829 个 `(batch, IP)` 唯一。对这 42 个
sampled TUs 使用 NO0357 同源 PCH、Clang/C++20/O3，只增加 line table：

```text
debug objects                 42/42
objects with line table       42/42
nonempty compiler diagnostics  0
production/debug .text        42/42 byte-identical
sample offsets on instruction 868/868
source/runtime resolution     868/868
```

批量编译墙钟 41.28 秒；最大 TU commit115 单独为 65.85 秒、1,367,968 KiB RSS。分析器 8.64 秒完成，所有归因都在
与 production machine code 相同的 `.text` 上进行。

## 2. Machine/source decomposition

| Class | Samples | Commit share | Direct-total share | Approx instructions |
| --- | ---: | ---: | ---: | ---: |
| changed compare | 305 | 35.138% | 4.569% | 7.625B |
| event/write guard | 283 | 32.604% | 4.240% | 7.075B |
| reader activation | 138 | 15.899% | 2.067% | 3.450B |
| data/mask preparation | 137 | 15.783% | 2.052% | 3.425B |
| runtime/dispatch/memory residual | 5 | 0.576% | 0.075% | 0.125B |

824/868 samples (`94.93%`) 属于 `kRegisterWritePort`，memory/latch 分别只有 26/4。opcode 头部为 `je=277`、
`jne=239`、`cmp=83`、`movb=81`：当前 commit 热路径主要是 `write-enable -> je` 和
`state != next -> jne/cold update`，不是实际 state store。

热点仍集中在 commit115/105：

| Batch | Total | Changed compare | Data/mask | Reader activation |
| --- | ---: | ---: | ---: | ---: |
| commit115 | 253 | 172 | 36 | 45 |
| commit105 | 163 | 98 | 37 | 28 |

两者合计 416 samples，占 commit `47.93%`。模块族则较分散：`backend.inner_ctrlBlock=185`、
`logEndpoint=170`、`memBlock=151`，三者合计 `58.29%`，没有单一状态族覆盖大多数 commit。

## 3. GSim comparison correction

same-FIR GSim 对应状态更新并未消失。代表状态 `valid_numsNSamples`、ROB writeback time 和 LQ index 都生成：

```cpp
auto old = state;
state = next;
bool changed = state != old;
activeFlags[...] |= changed << bit;
```

production-identical GSim machine code使用 `cmp/setne/cmove/or` 和局部寄存器聚合，不是 GrhSIM 的逐 state
`jne cold_update`。NO0403 的 GSim profile 中 old snapshot / persistent writeback / changed compare / activation 共
`176/310/137/315 = 938` samples，约 23.450B instructions；entry active scan 另有 332 samples。

这些 GSim classes 同时覆盖 persistent combinational values，不能与 GrhSIM commit 做逐样本语义相减；但足以修正
“21.700B commit 都是 GSim 不做的额外工作”。event/write guard 283 也与 GSim entry scan 332 同量级，不能把 guard
本身当作可删除开销。

直接把 GrhSIM 改成全局 branchless 也不成立：NO0287 已证明 current changed branch 的 cold layout 有正收益，历史全局
branchless 和 commit activation grouping 分别出现 instruction/runtime 回退。GSim 的 branchless 形态依赖其 aggregate/local
布局，不能脱离该上下文移植。

## 4. Sampled-state crosswalk

868 个 commit samples 中 828 个能归到具体 state，共 761 个 unique names；其余 40 个是无 state 属性的入口/guard。
对 GSim 的 488,167 个声明执行三层严格 crosswalk：

| Match | Unique states | Samples | Rule |
| --- | ---: | ---: | --- |
| exact | 406 | 449 | 直接 `$ -> __DOT__` 后同名 |
| canonical | 131 | 150 | 仅结构分隔符差异，如 `ftqPtr_value` / `ftqPtr.value` |
| aggregate array | 140 | 143 | GSim 声明确为数组，GrhSIM 只多出数字 index tokens |
| unmatched | 84 | 86 | 不作猜测 |

总覆盖为 `742/828 = 89.614%` samples。aggregate-array 规则不会按任意前缀模糊匹配；GSim base tokens 必须保持
顺序，GrhSIM 多出的 tokens 必须全是数字，且目标声明必须有数组维度。

143 个 aggregate samples 分布在 79 个 base groups，互斥 class 为 changed compare 66、event/write guard 53、data/mask
21、reader activation 3。头部包括：

| GSim aggregate base | Flattened states | Samples |
| --- | ---: | ---: |
| PTW `l0BitmapReg[64][4][8]` | 13 | 14 |
| L2 bus PMU `latencyRecord.valid[]` | 11 | 11 |
| DCache `accessArray.meta_array[]` | 8 | 8 |
| FTQ `perfQueue.isCfi[]` | 7 | 7 |
| uTage `MicroTageTable*.entries.valid[]` | 7 | 8 |

GSim header/source 直接确认这些是 array declarations，并以 loop/indexed update 处理；默认 lowered-SV GrhSIM 对应项是
逐元素 scalar register write。该 aggregate signal 为 `143/868 = 16.475%` commit、`143/6675 = 2.142%` direct total，
约 3.575B instructions，同时通过 NO0435 的 `>=10% commit` 和 `>=1% direct total` 门槛。

## 5. Decision

本轮不实现 branchless 或 commit flag aggregation。`commit_activated_readers_ = true` 虽有 81 samples、约占 direct
`1.213%`，但只占 commit `9.332% < 10%`，未通过预声明双门槛；其余 reader mask OR 又是语义必要工作。

唯一通过全部门槛的方向是 scalar-to-array re-aggregation。它与历史结论一致但提供了 latest direct profile 的新量化：

- preserve-aggregate 仍是独立正确性路径，不能直接切换；
- current true-merge 已覆盖 TAGE/PHR/ROB/RAT 等严格闭包族，但 79 个 GSim array bases 仍出现在最新 commit samples；
- 单个 base 最大只有 14 samples，下一步必须做通用 eligibility/rejection 诊断，不能再为单一状态名写特例。

下一 gate 将 140 个 flattened states 连接到当前 reg-to-mem intent/true-merge discovery，逐组拆分已合并、读闭包、写口、
reset/fill、shared-view 和 name-only re-aggregation 拒绝原因。只有可证明安全的共同 rejection class 仍覆盖 direct total
至少 1%，才设计 lowering；本篇没有形成 runtime 收益结论。

## 6. Artifacts

```text
build/logs/xs_perf/no0435/commit_debug_objects/
build/logs/xs_perf/no0435/commit_text_identity_manifest.tsv
build/logs/xs_perf/no0435/commit_sample_rows.tsv
build/logs/xs_perf/no0435/commit_{class,batch,batch_class,opcode,operation,
    operation_class,state_family,state_family_class}_summary.tsv
build/logs/xs_perf/no0435/commit_attribution_summary.txt
build/logs/xs_perf/no0435/gsim_state_crosswalk.tsv
build/logs/xs_perf/no0435/gsim_state_crosswalk_summary.txt
build/logs/xs_perf/no0435/gsim_state_crosswalk_family_summary.tsv
build/logs/xs_perf/no0435/gsim_aggregate_base_summary.tsv
```
