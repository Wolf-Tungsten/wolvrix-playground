# NO0345 Fixed-ASLR latest instruction profile plan

日期：2026-07-12

## 1. 目的

[NO0344](./NO0344_fixed_aslr_gsim_grhsim_direct_compare_gate_20260712.md) 确认 latest NO0300 GrhSIM
仍为 GSim 的 `2.159x` host instructions，额外 instructions 算术解释 `77.82%` excess cycles。已有
[NO0282](./NO0282_same_fir_instructions_profile_compute8_timer_fanout_20260711.md) 使用的是更早的 NO0278，
且没有固定 PIE load base；其 compute/commit 占比和 top batch 不能直接当作 NO0300 当前事实。

本阶段用与 NO0282 完全相同的固定 period 重新 profile same-FIR GSim 和 NO0300：

```text
GSim  = build/xs_gsim_no0255_current_20260710/gsim/gsim-compile/emu
GrhSIM = build/xs_grhsim_no0300_ordered_affine_fresh_20260712/grhsim/grhsim-compile/emu
event = instructions:u
period = 25000000
call graph = dwarf,8192
```

## 2. 运行口径

- 每条命令先 `source env.sh`；
- 使用 `setarch "$(uname -m)" -R numactl --membind=1 taskset -c 138`；
- CoreMark 2 iterations、NEMU difftest、`-b 0 -e 0 -C 50000` 不变；
- 顺序为 GSim、GrhSIM，每轮前检查全机 load、CPU138 与 sibling CPU330；
- `perf record` 使用 `-e instructions:u -c 25000000 --call-graph dwarf,8192`；
- profile 不与 NO0282 的随机地址样本混合，只比较类别占比和版本变化。

命令形态：

```text
setarch "$(uname -m)" -R numactl --membind=1 taskset -c 138 \
  perf record -e instructions:u -c 25000000 --call-graph dwarf,8192 -- <emu> ... -C 50000
```

## 3. 数据门禁

1. GSim 与 GrhSIM 分别到达 NO0344 中已确认的 50k 功能终点，无 mismatch/assertion/abort；
2. `perf report --header-only` 显示 event/period/call graph 与计划一致；
3. `Total Lost Samples = 0`；
4. 近似 event count 与 NO0344 perf stat instructions 的误差不超过一个 period；
5. GrhSIM/GSim sample ratio 应与 `2.159x` instruction ratio 相符，偏差超过一个 sample 的量化误差时
   先检查 profile 接线。

## 4. 符号分类与输出

从 `perf report --stdio --no-children -n` 和 `perf script` 生成以下分类：

- GSim：`SSimTop::subStep*`、`SSimTop::step`、emulator harness、other/unresolved；
- GrhSIM：`eval_compute_batch_*`、`eval_commit_batch_*`、`eval` control、helpers、other/unresolved；
- 各边 top leaf symbols 及其 samples/share；
- GrhSIM compute/commit 估算 instructions，并与 GSim 全部 `subStep*` 比较；
- 相对 NO0282 的类别与 top-batch 变化，判断后续优化是否已移除原热点。

系统当前没有 `stackcollapse-perf.pl`/`flamegraph.pl`。profile 数据通过后，将官方 FlameGraph 工具固定到
`build/tools` 并单独记录 revision，再由同一 `perf script` 生成两边 instruction flamegraph；第三方工具不提交
到源码树。

## 5. 预定产物

```text
build/logs/xs_perf/no0345/fixed_gsim_50k_instructions.data
build/logs/xs_perf/no0345/fixed_gsim_50k_instructions_emu.log
build/logs/xs_perf/no0345/fixed_gsim_50k_instructions.report
build/logs/xs_perf/no0345/fixed_gsim_50k_instructions.perf-script
build/logs/xs_perf/no0345/fixed_grhsim_50k_instructions.data
build/logs/xs_perf/no0345/fixed_grhsim_50k_instructions_emu.log
build/logs/xs_perf/no0345/fixed_grhsim_50k_instructions.report
build/logs/xs_perf/no0345/fixed_grhsim_50k_instructions.perf-script
```
