# NO0405 Current same-condition mux reuse plan

日期：2026-07-12

## 1. Problem and historical constraint

[NO0404](./NO0404_global_compute_machine_source_attribution_gate_20260712.md) 将 direct compute excess 的 `82.77%`
归到 payload + generic runtime；`grhsim_mux_u64` 自身覆盖 58/66 batches、450/5,590 compute samples。当前 66 个
production compute sources 有 642,023 个 scalar mux calls，但 emitter/generated source 中已经没有 NO0091 的
`mux_mask/grhsim_select_u64` 路径。

历史约束必须同时保留：

- [NO0090](./NO0090_grhsim_branchless_mux_select_coremark50k_20260511.md) 的 branchless mask-select 相对 ternary 提升
  50k wall time `3.05%`，因此不撤回 branchless 默认形态；
- [NO0129](./NO0129_scalar_mux_ternary_negative_smoke_20260521.md) 的全局 ternary 20k 回退 `8.1%`，不重复该实验；
- [NO0091](./NO0091_grhsim_same_cond_mux_merge_coremark50k_20260512.md) 的相邻同条件 run threshold>=8 曾提升
  `1.84%`，但当时 schedule、generated source、binary layout 和性能差距均不同，只作为 current 诊断的先验。

## 2. Static and direct-fire gate

复用 NO0357 production generated C++、NO0399 direct 50k fire 和 NO0401 byte-identical O3 objects，不重跑仿真。
逐 supernode 解析 scalar `kMux` op 的 outer `grhsim_mux_u64`，提取其第一个 condition argument；只有 operation 顺序连续、
condition expression 完全相同且都在同一 supernode 的 run 才计入。

分别输出 run length `2/4/8/16` 的：

```text
runs
covered_mux_ops
source_mask_evaluations_saved = sum(run_length - 1)
dynamic_mask_evaluations_saved = sum((run_length - 1) * direct_fire)
```

必须校验 outer call 数、解析失败数、batch/supernode 覆盖和 642,023 total call 口径；nested mux calls 只作为 operand expression，
不能误计为当前 op 的独立 run。

## 3. Production O3 realization gate

source run 不等于机器冗余。对 direct-fire top runs 和 length=8/16 代表，在相同 production source 上做局部 generated-code
probe：一次计算 mask，run 内改用 select expression；只重编对应 translation unit，并与原 O3 object 对照：

1. function/supernode 语义代码范围和 run 命中必须精确；
2. 统计 run block 的 `test/setcc/neg/and/or/cmov`、memory operands、bytes 和 instructions；
3. probe 只能减少或保持 run block instructions，且 whole function `.text` 增幅不得超过 1%；
4. 若 Clang 已在原 object 复用 condition，source saved 不进入动态上界。

probe object 不链接、不运行，不能作为 correctness 或 runtime 结果；它只决定是否值得恢复 emitter 路径。

## 4. Decision rule

只有同时满足以下条件才另起默认关闭的实现计划：

1. threshold>=8 的 direct weighted source saved 至少为 NO0388 direct compute `139.750B` instructions 的 1%；
2. 至少 3 个不同 batches 的代表 run 在 O3 后确实减少机器指令，且没有 >1% whole-function text growth；
3. 机会不能由一个低 fire supernode 或单一 source family 主导；
4. 实现只恢复 emit 层相邻 run mask reuse，不做 schedule merge、全局 ternary或 supernode-wide lazy mask。

任一条件不满足即停止该候选，继续检查 `or_words_full/and_words_full` 的 current machine realization。通过后才允许实现、单测、
fresh SimTop emit/build/功能门禁，并最终使用 fixed-ASLR exact-entry paired runtime 验收。

预期产物：

```text
build/logs/xs_perf/no0405/{run_rows,threshold_summary,batch_summary,top_runs}.tsv
build/logs/xs_perf/no0405/representative_o3_probe_summary.tsv
build/logs/xs_perf/no0405/current_same_cond_mux_summary.txt
```
