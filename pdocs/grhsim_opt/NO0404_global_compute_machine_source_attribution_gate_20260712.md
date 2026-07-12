# NO0404 Global compute machine/source attribution gate

日期：2026-07-12

## 1. Exact sample and machine-code gates

按 [NO0403](./NO0403_compute1_machine_source_attribution_plan_20260712.md)，先复用 NO0388 direct fixed-ASLR
`instructions:u` profile 分析 compute1，再扩展到全部 compute；为避免局部热点与 GSim 全模型错配，同时对 NO0345 same-FIR
GSim 全部 sampled subSteps 做相同 line mapping。本轮没有重跑仿真或采集新的性能数。

| Side | Profile leaf samples | Debug objects | `.text` identical | Aggregate `.text` |
| --- | ---: | ---: | ---: | ---: |
| GrhSIM direct compute | 5,590 | 66 | 66/66 | 70,924,958 bytes |
| GSim subStep | 3,170 | 284 | 284/284 | 43,620,240 bytes |

两边都只在 production O3 编译口径上增加 line table，逐 object `.text` SHA256 完全相同。GrhSIM 映射 5,395、未解析
195 个 samples；GSim 映射 2,996、未解析 174 个 samples，未解析率分别为 `3.49%/5.49%`。所有 perf event 仍为相同
25M period、0 lost 的既有样本。

## 2. Compute1 local gate

compute1 的 243 个 leaf samples 全量提取，batch1 debug/production `.text` SHA 为相同的 `9feda6f3...`。238 个 samples
直接映射 generated line，5 个保持 unresolved；242 个 unique IP 分散到 179 个 supernodes，最高单 supernode 只有 4 个
samples，不能通过单点 patch 解释。

| Class | Samples | Share |
| --- | ---: | ---: |
| Payload compute | 80 | 32.92% |
| Changed compare | 46 | 18.93% |
| Activation propagation | 42 | 17.28% |
| Slot writeback | 25 | 10.29% |
| Operand/state read | 23 | 9.47% |
| Changed accumulate | 16 | 6.58% |
| Dispatch + unresolved | 11 | 4.53% |

最大单一 framework class 为 changed compare，`18.93% < 20%`，未通过 NO0403 预声明实现门槛。四类 changed /
activation / writeback 合计虽为 `53.09%`，但 GSim source 对照纠正了“这些都是 GrhSIM 独有”的假设：GSim 同样生成
`$old` snapshot、`cond` compare、`activeFlags |=` 和 persistent member writeback。

## 3. Global normalized comparison

为避免 compute1 的 ROB-heavy 形态代表全模型，把 5,590/3,170 samples 按可验证的 generated-code role 归一化：

| Normalized class | GrhSIM samples | GSim samples | Approx instruction delta | Share of 60.50B compute excess |
| --- | ---: | ---: | ---: | ---: |
| Direct payload | 2,822 | 1,726 | +27.400B | 45.29% |
| Generic runtime helper | 907 | 0 | +22.675B | 37.48% |
| Change tracking | 603 | 313 | +7.250B | 11.98% |
| Activation propagation | 304 | 315 | -0.275B | -0.45% |
| Persistent writeback | 313 | 310 | +0.075B | 0.12% |
| Dispatch | 413 | 332 | +2.025B | 3.35% |
| Other / unresolved | 228 | 174 | +1.350B | 2.23% |

`direct payload + generic runtime helper` 合计解释 `50.075B`，即 compute excess 的 `82.7686%`。changed / activation /
writeback 三类增量框架合计只解释 `7.050B/11.6529%`；其中 activation 在 GSim 反而略多，persistent writeback 几乎
相同，额外框架成本主要来自 GrhSIM 更细粒度的 changed compare/accumulate。此前把主要差距归为 successor activation
并不成立。

这里的 `generic runtime helper=0` 不表示 GSim 没有对应逻辑，而是 GSim 把选择、位运算和 typed local 直接展开在
subStep payload 中。因此可靠结论是合并后的 payload 实现/粒度差，而不是把 22.675B 全部视为可删除 helper overhead。

## 4. GrhSIM helper shape

按 runtime header line 归属，在重新分类 active/writeback/ref helper 后，剩余 907 个 generic helper samples 的头部为：

| Helper | Samples | All compute share | Approx instructions |
| --- | ---: | ---: | ---: |
| `grhsim_mux_u64` | 450 | 8.05% | 11.250B |
| unresolved helper line | 147 | 2.63% | 3.675B |
| `grhsim_or_words_full` | 117 | 2.09% | 2.925B |
| `grhsim_and_words_full` | 83 | 1.48% | 2.075B |
| `grhsim_reduce_or_u64` | 31 | 0.55% | 0.775B |
| `grhsim_udiv_u64` | 26 | 0.47% | 0.650B |

`grhsim_mux_u64` 覆盖 58/66 compute batches，但不能把 11.250B 直接当成 overhead：采样指令含 `test/cmove/cmovne` 和
operand loads，是 mux 的真实数据选择。历史 [NO0090](./NO0090_grhsim_branchless_mux_select_coremark50k_20260511.md)
已证明 branchless mux 虽增加 instructions，仍通过减少 branch miss 提升 50k wall time `3.05%`；
[NO0129](./NO0129_scalar_mux_ternary_negative_smoke_20260521.md) 的 ternary 回退 `8.1%`，因此不重复全局 ternary 实验。

当前代码与 generated source 中已经没有 NO0091 的 same-condition `mux_mask/grhsim_select_u64` 路径，66 个 compute files
仍有 642,023 个 `grhsim_mux_u64` calls。历史该窄路径曾提升 `1.84%`，但 current schedule/compiler 是否仍有同样 run 和
机器冗余尚未验证，应另起 current-data 诊断，不能直接按旧结果恢复。

## 5. Decision

NO0403 的 compute1 单类实现门槛未通过，本篇不修改 emitter。全量 GSim 对照把主因收敛为：GrhSIM 对 payload 使用更细的
IR/value 粒度、generic helper 和持久 materialization，合计解释约 83% compute excess；changed framework 是第二级问题，
activation/slot writeback 本身不是主差值。

下一步不再做全局 typed-local、ternary mux 或 supernode-size 调参。优先对 current same-condition scalar mux runs 做静态、
direct-fire 和 production O3 冗余门禁；只有当前覆盖与机器码都成立，才恢复 NO0091 的 threshold>=8 mask reuse。若该门禁
不足，则继续按 helper 头部检查 full-width OR/AND 的 current machine realization。

产物：

```text
build/logs/xs_perf/no0403/compute1_{sample_rows,class_summary,supernode_summary}.*
build/logs/xs_perf/no0403/grhsim_all_compute_{sample_rows,class_summary,
    batch_class_summary,operation_summary,helper_summary,text_identity_manifest}.tsv
build/logs/xs_perf/no0403/gsim_all_{sample_rows,class_summary,
    substep_class_summary,text_identity_manifest}.tsv
build/logs/xs_perf/no0403/grhsim_runtime_helper_summary.tsv
build/logs/xs_perf/no0403/global_normalized_category_{compare,summary}.*
```
