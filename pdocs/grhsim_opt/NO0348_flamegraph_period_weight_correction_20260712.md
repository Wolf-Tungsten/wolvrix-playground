# NO0348 Flamegraph period-weight correction

日期：2026-07-12

## 1. 触发

[NO0347](./NO0347_instruction_flamegraph_tool_setup_20260712.md) 初始 runbook 将 FlameGraph 横轴写成
sample count，并使用 `--countname samples`。生成后的 folded sum 门禁显示：

```text
GSim folded sum   = 80,025,000,000
GrhSIM folded sum = 172,850,000,000
```

它们精确等于 [NO0346](./NO0346_fixed_period_event_count_gate_correction_20260712.md) 的 approximate event
counts，而不是 `3201/6914` samples。官方 `stackcollapse-perf.pl` 会读取 perf-script 中每条 sample 的
`period=25000000` 并按 period 加权。

## 2. 修正

初始 SVG 的 stack geometry 正确，但计数单位标签错误，且尚未用于分析结论。已使用相同 folded input 覆盖重生：

```text
flamegraph.pl --countname 'approx instructions' ...
```

修正后的两张 SVG 均包含 `approx instructions`，不再含旧的 `samples` count label。folded sum 分别严格为
`80.025B/172.850B`，并确认 GSim 图含 `SSimTop::subStep*`，GrhSIM 图同时含
`eval_compute_batch_*` 与 `eval_commit_batch_*`。

横轴现在表示 fixed-period profile 的 approximate instructions；它可用于同次 profile 内的函数 share 和两边
近似 ratio，但仍不替代 NO0344 的精确 perf stat retired instructions。

## 3. 有效产物

```text
build/logs/xs_perf/no0345/fixed_gsim_50k_instructions.folded
build/logs/xs_perf/no0345/fixed_gsim_50k_instructions.svg
build/logs/xs_perf/no0345/fixed_grhsim_50k_instructions.folded
build/logs/xs_perf/no0345/fixed_grhsim_50k_instructions.svg
```
