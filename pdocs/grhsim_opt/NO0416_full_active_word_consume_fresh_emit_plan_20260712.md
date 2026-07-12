# NO0416 Full active-word consume fresh emit plan

日期：2026-07-12

## 1. Objective

在 [NO0415](./NO0415_full_active_word_consume_implementation_gate_20260712.md) 的 synthetic gate
通过后，从 NO0357 相同 pre-reg-to-mem checkpoint fresh emit SimTop，只新增：

```text
WOLVRIX_XS_GRHSIM_FULL_ACTIVE_WORD_CONSUME=1
```

继续保留 direct state-read、ordered/decoded reg-to-mem、`level-id`、108-op compute、4096-op commit、
64 batch target、4 路 emit 和 storage-ref aliases off。不开 runtime profile、waveform、perf 或
input/posedge fullpass specialization。

## 2. Inputs and output

```text
checkpoint:
  build/xs_grhsim_event_order_src_20260710/grhsim/wolvrix_xs_pre_reg_to_mem.json
reference source:
  build/xs_grhsim_no0357_direct_state_read_20260712/grhsim/grhsim_emit
fresh output:
  build/xs_grhsim_no0416_full_word_consume_20260712/grhsim/grhsim_emit
```

执行前必须 `source env.sh` 并重新安装 editable Python binding，确认 site package 已包含
`full_active_word_consume` option string，不能复用旧 `.so`。

## 3. Fresh emit gates

1. config log 明确 `full_active_word_consume=True`；
2. `activity_schedule_supernode_stats.json` SHA256 仍为
   `e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77`；
3. direct state-read 仍为 reads/canonical/aliases `75,830/40,108/35,722`；
4. generated file set、compute/commit batch 数和所有 graph/schedule 计数与 NO0357 一致；
5. 当前参考 7,932 个 compute word 中 7,853 个 full-mask word 命中 consume，79 个 partial word
   保留 clear/restore；
6. commit schedule 与 NO0357 byte-identical，non-schedule state/header/eval 也必须不变；
7. source parser 不得发现 full compute word 残留 local clear/restore，或 partial/commit word 被误删。

本阶段只验收 fresh source，不编译或运行仿真。通过后另起 O3 build gate，再做 10k/50k 功能。
