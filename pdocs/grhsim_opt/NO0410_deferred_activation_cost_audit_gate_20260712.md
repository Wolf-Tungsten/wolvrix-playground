# NO0410 Deferred activation cost audit gate

日期：2026-07-12

## 1. Source and fire closure

按 [NO0409](./NO0409_deferred_activation_cost_audit_plan_20260712.md)，解析 NO0357 direct-state 的 66 个 production
compute sources，并连接 [NO0399](./NO0399_direct_scalar_locality_runtime_profile_50k_gate_20260712.md) 的 direct 50k
fire。所有 `grhsim_any_changed` declaration 和 source update 均闭合：

| Metric | Value |
| --- | ---: |
| Deferred groups | 136,969 |
| Source-to-group updates | 952,261 |
| Named `grhsim_changed` updates | 859,573 |
| Branch-contained `true` updates | 92,688 |
| Unique emitted sources | 589,559 |
| Sources updating multiple groups | 217,406 |
| Maximum groups per source | 16 |

有 1,855 个 declaration 在实际 generated body 中没有 source update，另有 666 个只剩一个 source；这是构组时按
静态 result/fanout 建组、后续专用 emit path 未实际使用全部 source 的 over-approximation。production O3 会 DCE 掉
无输入的 flags，本轮 fixed-period samples 中没有形成可单独优化的热点。

按 direct fire 加权，source-to-group updates 为 `7.676B`。若每个 source 在多个 group 中只保留一份更新，源码级重复
上界为 `3.191B`，即 direct compute `139.750B` instructions 的 `2.283%`；该值尚未扣除替代表示自身的更新成本。

## 2. Machine sample split

复用 [NO0404](./NO0404_global_compute_machine_source_attribution_gate_20260712.md) 的 5,590 个 byte-identical O3
compute samples：

| Shape | Samples | Interpretation |
| --- | ---: | --- |
| Source -> group accumulate | 158 | `group |= changed` |
| Group -> deferred active word | 1 | 多 group mask 汇聚 |
| Group-based final activation | 107 | 304 activation samples 的子集 |
| Multi-group source updates | 81 | 同一 source 更新 2..8 个 sampled groups |

81 是把 multi-group 更新全部删除的错误上界。每个 source 至少仍需一次 packed/exact update；按 sampled source
multiplicity 折算，理想净省只有 `47.449` samples，即 direct compute `0.849%`、GrhSIM-vs-GSim change-tracking
净超额 290 samples 的 `16.36%`。两项均低于 NO0409 的 `1% / 20%` 双门槛。

## 3. Subset and exact-fanout gates

source-set subset factoring 找到 25,487 条可复用 parent edges，最理想源码减少 120,126 updates；direct-fire 加权为
`1.183B / 0.847%` compute。但 production samples 中只有 11 个 source updates 真正落在该候选，machine 上界仅
`0.197%` compute。

进一步把每个 named changed source 的 group targets 与即时 direct targets 合并，重建旧版 exact-fanout key。8,724 个
source 因 table/deferred final shape 保持 unresolved，不进入 exact 结论；其余 source 中 450,501 个属于至少二 source
共享的 exact key。159 个 accumulate samples 中 119 个落在 exact-grouped source，但扣除每个 source 必须保留的一次
update 后，理想净省只有 `30.207` samples：

```text
direct compute share                 0.540%
change-tracking excess coverage     10.416%
```

因此恢复旧版 exact-fanout grouping 也不能通过实现门槛。

## 4. Packed-mask O3 probe

为排除 bool flags 的额外 spill 被 sample-equivalent 低估，在 ignored generated copies 中把同一 source 的多 group updates
压成一个 16-bit mask update。选择 duplicate samples 最多的 compute batches 0/1/14/20，分别测试 multiplicity >=2 和
>=3；使用 production PCH 和相同 `clang++ -std=c++20 -O3` 编译完整 compute functions。

四个 symbol 合计：

| Variant | Symbol bytes | Static instructions | Stack operands | OR instructions | AND instructions |
| --- | ---: | ---: | ---: | ---: | ---: |
| Production | 5,660,685 | 1,133,147 | 147,496 | 185,340 | 83,577 |
| Packed >=2 | +2.745% | +3.136% | +0.824% | -22,256 | +22,948 |
| Packed >=3 | +1.087% | +1.523% | -3.349% | -14,322 | +14,405 |

packed >=3 虽减少 4,939 个 stack operands，仍新增 17,260 条 static instructions 和 61,554 bytes；省下的 bool OR 被
mask AND、搬运和 final bit extraction 反超。batch20 >=3 单独为 `-0.490%` instructions，但 >=3 全模型 machine-equivalent
上界只有 21.449 samples，且其余三个代表 batch 全部增加 instructions，不能据此做 batch-specific 默认优化。

## 5. No-deferred O3 probe

最后对 final activation 可直接解析的 groups 做语义等价 no-deferred probe：把每条 source update 替换为该 group 的即时
activation，并删除组尾 activation。四个 batch 分别覆盖 97.7%、96.4%、99.8%、98.5% declarations；table 与
deferred-word aggregate shape 保留 current 路径。

| Metric | Production | No-deferred | Delta |
| --- | ---: | ---: | ---: |
| Symbol bytes | 5,660,685 | 6,362,636 | +12.400% |
| Static instructions | 1,133,147 | 1,284,185 | +13.329% |
| Stack operands | 147,496 | 48,356 | -67.215% |
| Memory operands | 526,082 | 567,391 | +7.852% |
| MOV instructions | 367,163 | 401,373 | +9.317% |
| OR instructions | 185,340 | 219,898 | +18.646% |

四个 batch 的 static instructions 分别增加 `17.03% / 13.78% / 7.40% / 17.00%`，不是单一布局异常。减少局部 bool
live ranges 确实回收了 stack slots，但逐 source 写 global active masks 产生更多 MOV/OR、memory operands和 text，违反
NO0409 的 machine、activation 和 footprint gates，因此不进入 SimTop runtime A/B。

## 6. Decision

保留 current partial-overlap deferred grouping，不修改 emitter。change tracking 的 159 accumulate samples 是真实成本，
但三条可实现路径均失败：

- subset / exact reuse 的 production machine coverage不足；
- packed mask 在 O3 后增加 instructions 和 text；
- no-deferred 把局部累加转移为更昂贵的 global activation，四个代表 batch 全面回退。

本轮没有跑 wall-time benchmark；所有拒绝均发生在预声明 O3 gate，机器负载不参与结论。下一步不再围绕
`grhsim_any_changed` 改写，转向 NO0404 中尚未归名的 147 个 runtime-helper samples；它们单独约占 direct compute
`2.63% / 3.675B` instructions，仍超过 1% gate。

产物：

```text
build/logs/xs_perf/no0409/analyze_deferred_activation.py
build/logs/xs_perf/no0409/{summary,group_rows,source_multiplicity,sample_candidate_rows}.tsv
build/logs/xs_perf/no0409/{make_packed_group_probe,make_no_deferred_probe,
    compare_packed_probe_objects}.py
build/logs/xs_perf/no0409/packed_object_{compare,aggregate}.tsv
```

