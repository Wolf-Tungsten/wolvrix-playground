# NO0493 Pure-event compute-word dynamic profile plan

日期：2026-07-13

## 1. Goal and configuration

[NO0492](./NO0492_pure_event_compute_word_bypass_implementation_gate_20260713.md) 已通过 implementation/structural gate，
但静态 eligible words 不能说明运行时 active word 中有多少发生 event miss。本阶段增加独立、默认关闭的动态 profile：

```text
EmitOptions attribute: pure_event_compute_word_profile
Environment:          WOLVRIX_GRHSIM_PURE_EVENT_COMPUTE_WORD_PROFILE
Default:              false
Runtime enable:       existing set_runtime_profile_enabled(bool)
Dump entry:           existing dump_runtime_profile()
TSV override:         WOLVRIX_GRHSIM_PURE_EVENT_WORD_TSV
```

profile 与 `pure_event_compute_word_bypass` 独立：只开 profile 时不改变 active-word 行为；只开 bypass 时不生成计数器。两者
同时开启时共享同一 event-hit 判定，避免诊断形态重复读取 event slot。

## 2. Counter semantics

复用 NO0492 的唯一 eligibility helper，不能另建放宽版分类。每个普通、未 split、非 fullpass、非 full-active-word-consume
的 eligible compute word 生成按 batch 计数：

- `eligible_words`：emit-time static count；
- `active_hit`：`activeWordFlags != 0` 且 exact event hit；
- `active_miss`：`activeWordFlags != 0` 且 exact event miss；
- `active_total = active_hit + active_miss`：dump 时派生，不增加第三个动态 counter。

计数发生在 outer active guard 内、underlying clear 后；inactive scans 不计数。runtime profile 未启用时不递增。init 必须清零，
重复 dump 不修改计数。

## 3. Generated API and output

只有 profile 编译开启时才生成两个 `kBatchCount` arrays。现有 runtime-profile enable/dump API 在 per-supernode profile 或本 profile
任一编译开启时生效；不开任何 profile 的默认 header/state source 保持不变。

独立 TSV 每个 batch 一行，包含：

```text
batch_id  eligible_words  active_hit  active_miss  active_total
```

仅输出 `eligible_words > 0` 的 batch，末尾标准输出报告 path、rows、eligible total、hit、miss 和 miss ratio，便于 SimTop emu
日志直接闭合。

## 4. Gates

扩展 NO0492 fixture：

- default/explicit profile 0 source byte-identical；
- profile-only source 有 counter arrays/increments，但无 bypass marker；
- profile+bypass 的每个 eligible word 只出现一个 event-hit temporary；
- 固定 eval 序列精确得到 static eligible `2`、active hit `4`、active miss `6`、total `10`；
- TSV 两行逐项求和与 aggregate getter/dump 一致，且 `active = hit + miss`；
- once-only/multi-event/commit/fullpass/full-word-consume 不产生 eligible rows；
- 两项 emitter 回归通过。

## 5. Next gate

实现通过后 fresh emit SimTop，只开 profile、不先开 bypass，要求：

1. fresh baseline schedule/direct/source identity 闭合；
2. production eligible word 总数与 NO0484 的 107 words 同量级，差异逐项解释为生产 purity/split/consume gate；
3. 先跑短功能 workload 验证 guest endpoint 与 TSV 闭合，再决定 50k 功能/profile run；
4. 根据 active miss ratio 和 miss 所在 hot batches 决定是否进入 fixed-ASLR bypass runtime A/B/A。
