# NO0447 Assign-boundary machine/source gate

日期：2026-07-13

## 1. Corrected sample gate

按 [NO0445](./NO0445_assign_boundary_forwarding_audit_plan_20260713.md) 和
[NO0446](./NO0446_assign_sample_ownership_correction_20260713.md)，本轮只重放 existing-artifact analyzer；没有重新编译、
运行仿真或采集 perf。117 个 NO0357 sched sources 中的 73,644 个 static `kAssign` blocks 全解析，395/395 profile rows 的
batch 和实际 source text 一致，374/374 recorded operation symbols 都能定位。

修正 supernode scope 后，旧 `kAssign=395` 口径拆为：

| Actual ownership | Samples | Direct total share |
| --- | ---: | ---: |
| Exact assign value body | 291 | 4.360% |
| Shared deferred supernode tail | 51 | 0.764% |
| Next-supernode prelude payload | 31 | 0.464% |
| Next-supernode dispatch | 22 | 0.330% |

后 104 个 samples 都不能归为独立 assign body。其中 53 个是 NO0446 已定位的跨 supernode label inheritance；51 个是最后
一条 op 后的共享聚合 tail。NO0403 的 operation-kind summary 因而只能用作初筛，不能继续直接当成 source ownership。

## 2. Exact-body classes

291 个 exact-body samples 互斥分类如下：

| Class | Samples | Direct total share | Decision |
| --- | ---: | ---: | --- |
| Fused/multi-operand RHS | 94 | 1.408% | real payload，不是透传 |
| Direct scalar source + deferred changed boundary | 69 | 1.034% | 唯一进入 GSim gate |
| Event/clock protected result | 50 | 0.749% | 需要独立 edge/history |
| Direct scalar source + direct tracked boundary | 38 | 0.569% | 低于门槛 |
| Typed-local result boundary | 15 | 0.225% | 低于门槛 |
| Constant result boundary | 13 | 0.195% | 低于门槛 |
| Direct scalar source + plain write | 8 | 0.120% | 低于门槛 |
| Wide result | 4 | 0.060% | 低于门槛 |

唯一通过 67-sample source gate 的 69-sample class 合并同一 scalar direct-source 语义下的 slot/state RHS，包含 68 个 unique
operations；机器角色为 RHS/load 29、changed compare 24、slot writeback 9、changed accumulate 7。它不是 69 条纯 copy，
但若整层都能安全 bypass，理论上限仍为 direct `1.034%`，所以按 NO0445 继续做 same-FIR GSim 差异校正。

## 3. GSim crosscheck

该 class 最大的 result family 是 `logEndpoint`，17 samples 对应 17 个不同的 `...Next_T` values。把 `$` 精确映射为 GSim
的 `__DOT__` 后，一次扫描全部 same-FIR `SimTop*.cpp`；17/17 values 均同时找到：

1. `$old` snapshot；
2. result/member assignment；
3. `bool cond_*` old/new compare；
4. `activeFlags` propagation。

例如 `prefetch_queue_fullNext_T` 在 `SimTop106.cpp:16375/16382/16400/16401`，
`sms_train_filter_deqNext_T` 在 `SimTop118.cpp:24010/24018/24057/24058`。完整 17 项位置在：

```text
build/logs/xs_perf/no0445/gsim_assign_crosscheck.txt
```

因此这 17 samples 是两边共同的 declared value/change boundary，不能计入“GSim 没有、GrhSIM 可 forwarding”的差异层。
69 减 17 后，剩余最宽松上界为 52 samples/direct `0.779%`，已低于预声明 1% 门槛。

## 4. Decision

停止 assign-boundary forwarding，不进入 NO0445 Phase B：不增加 emitter structural diagnostic，不做 O3 patch，也不跑低上界
runtime。当前 `redundant-elim` 保持不变，event/clock 和 shared deferred tail 均不放宽。

本轮同时暴露了后续热点选择的前置问题：NO0403 的 operation-kind 标签会跨 supernode preamble 继承，并把共享 tail 归给最后
一条 op。下一步应先对全量 5,590 compute samples 重建 scope-aware ownership，再从 corrected profile 选新候选，避免重复按虚高
operation count 开题。

产物：

```text
build/logs/xs_perf/no0445/analyze_assign_boundaries.py
build/logs/xs_perf/no0445/assign_sample_rows.tsv
build/logs/xs_perf/no0445/{ownership,source_shape,effect,preclass,candidate_class}_summary.tsv
build/logs/xs_perf/no0445/candidate_class_{mechanism,line_role,family}_summary.tsv
build/logs/xs_perf/no0445/analysis_summary.txt
build/logs/xs_perf/no0445/gsim_assign_crosscheck.txt
```
