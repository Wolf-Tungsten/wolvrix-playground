# NO0443 Remaining register-read machine audit plan

日期：2026-07-13

## 1. Objective

[NO0404](./NO0404_global_compute_machine_source_attribution_gate_20260712.md) 的 latest direct profile 中，5,590 个 compute
samples 有 920 个映射到 `kRegisterReadPort`；其中 544 个属于 `operand_or_state_read`，约占 direct total
`8.15%`。direct state-read 已删除 NO0357 的 75,830 个严格 single-writer boundary reads，但所有 read op comments 仍保留，
而 inline state refs 也可能是 consumer 的必要 payload。因此不能把 920 samples 整体当作残余框架开销。

本轮只复用既有 fixed-period profile、byte-identical O3 line mapping 和 NO0352 locality TSV，回答剩余热点是：

1. 仍在写 `value_*_slots_` 的 materialized read；
2. 已直接内联到 consumer 的必要 state load；
3. wide/packed read copy；
4. line attribution 中与 read comment 相邻的 fused payload；
5. 因 multi-writer、protected/local user、fanout 或 unscheduled user 被 direct gate 排除的结构。

## 2. Data validity

输入固定为：

```text
samples: build/logs/xs_perf/no0403/grhsim_all_compute_sample_rows.tsv
locality: build/xs_grhsim_no0352_state_read_locality_20260712/
          grhsim/grhsim_emit/grhsim_state_read_locality.tsv
source:   build/xs_grhsim_no0357_direct_state_read_20260712/
          grhsim/grhsim_emit/grhsim_SimTop_sched_*.cpp
```

NO0404 已证明 66/66 debug objects 与 production `.text` 相同；本轮不重编、不重跑 perf。要求 920/920 sample operation IDs
唯一连接 locality row；缺失、重复或 source line 与 recorded source text 不一致时停止归因。

## 3. Classification

逐 sample 输出 batch/IP/op/state/width/source shape，并按优先顺序互斥分类：

- `slot_materialize_scalar`：`value_{bool,u8,u16,u32,u64}_slots_ = state_ref`；
- `slot_materialize_wide`：array/wide slot copy；
- `inline_state_operand`：state ref 直接进入当前表达式；
- `fused_or_ambiguous`：无法证明采样指令属于独立 read 搬运。

再连接 locality fields：materialized/alias/canonical/tracked-change/boundary fanout、same-supernode/unscheduled users、
unique users/fanout equality。解析 current generated commit comments，按 state symbol 统计 register write-port count；multi-writer
和 single-writer 必须分开。

locality TSV 不含 public output/inout/event/waveform/packed-lane protection，无法由现有产物证明的排除统一标
`protection_or_emitter_only`，不得猜测为可放宽。

## 4. GSim comparison

对 sample 数最高的 state families，在 same-FIR GSim source 中确认是：

- typed local/member 直接读取；
- `$old` snapshot；
- array row/lane read；
- 或同样需要持久 NEXT/state 搬运。

只对 GrhSIM 独有的 slot materialization 估算机器上界，不把 GSim 也执行的真实 state load 计为可删。

## 5. Decision

进入实现的候选必须同时满足：

1. 同一、可证明安全的 eligibility exclusion class 至少 67 samples/direct 1%；
2. 其中独立 `slot_materialize_*` 机器指令占主要部分，而不是 inline/fused payload；
3. 放宽后仍能在最终 state commit 处生成完整 consumer activation，且 alias group all-or-none；
4. 不依赖多写端口的中间 write predicate，也不绕过 protected/local users。

若信号主要是必要 inline loads，或每个安全子类低于 67 samples，则停止 remaining-read 方向，不实现更宽 direct forwarding。

## 6. Planned artifacts

```text
build/logs/xs_perf/no0443/analyze_remaining_register_reads.py
build/logs/xs_perf/no0443/register_read_sample_rows.tsv
build/logs/xs_perf/no0443/{shape,exclusion,state_family}_summary.tsv
build/logs/xs_perf/no0443/analysis_summary.txt
build/logs/xs_perf/no0443/gsim_read_crosscheck.txt
```
