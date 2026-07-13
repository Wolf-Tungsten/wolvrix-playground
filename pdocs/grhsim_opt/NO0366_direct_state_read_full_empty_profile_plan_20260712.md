# NO0366 Direct state-read full-empty profile plan

日期：2026-07-12

## 1. 目的

[NO0365](./NO0365_simtop_direct_state_read_fixed_aslr_runtime_gate_20260712.md) 表明 direct state-read 删除
`3.466%` host instructions、改善 backend stall density `11.567%`，但 cmask6 full-empty density 增加 `5.839%`，
使总 cycles 回退 `6.263%`。本阶段 sample 同一个 cmask6 event，把新增前端延迟映射到 generated batch，区分：

1. 少数 native functions 因地址/尺寸变化形成集中热点；
2. direct frontier 改变动态 batch/function locality，导致 compute-wide 增量。

## 2. 采样口径

按 NO0365 的顺序执行 NO0300 / direct / NO0300 三轮 CoreMark 50k：

```text
event:  cpu/de_no_dispatch_per_slot.no_ops_from_frontend,cmask=0x6/u
period: 10,000,000
stack:  dwarf,8192
CPU:    138 (SMT sibling 330 monitored)
NUMA:   membind node 1
ASLR:   setarch -R
limit:  -C 50000
```

每条命令先执行 `source env.sh`，unset `EMU_RUNTIME_PROFILE`，固定 seed 0、CoreMark image、NEMU difftest、
`-b 0 -e 0`。每轮前使用与 NO0365 相同的 quiet gate，CPU138/330 连续三秒平均空闲都达到 99% 才启动。
`perf record` 的 unwind 和写盘会扰动 timing，因此 profile host time 不进入性能结论。

## 3. 有效性门禁

三轮都必须满足：

- guest cycles `50001`、`cycleCnt=49996`、`instrCnt=73580`、terminal PC `0x80001312`；
- 无 mismatch/assertion/abort/fatal/error/`input_fullpass_blocked`；
- `Total Lost Samples: 0`；
- 两次 baseline 总 samples spread `<=3%`；
- direct/baseline-mean 总 sample 增幅应与无 record stat 的 `+12.468%` 同向，允许 unwind 扰动后相差 3 个百分点；
- exact symbols 能解析到全部 117 个 compute/commit batch functions。

若门禁失败，不形成 batch delta；先重跑受影响一侧。

## 4. 分析方法

NO0300 与 direct 的 activity schedule SHA256 相同，117 个 batch IDs 和 supernode membership 完全一致，因此本轮
同名 batch 是严格逻辑对照。对两次 baseline samples 取均值，报告：

1. compute/commit/eval/other phase samples 与 excess share；
2. 每个 batch 的 baseline mean、direct、absolute/relative delta，按 excess samples 排序；
3. top-10/top-20 对总 excess 的覆盖，判断集中还是 compute-wide；
4. 用 `nm -S -C` 连接两版 batch symbol address、低位 offset 和 symbol size，检查 excess 与 native layout delta；
5. 对最大 excess functions 做 `perf annotate`，只用于排除单一指令集中；该 PMU 非 precise，不把 sample IP 当成
   精确 stall 指令。

如果增量集中在少数地址变化函数，下一步做两边一致的 batch alignment 因果探针；如果增量广泛且与地址/尺寸无明显
关系，再采 direct/baseline dynamic batch activation/work，检查函数访问序列。

## 5. 预定产物

```text
build/logs/xs_perf/no0366/fixed_baseline1_cmask6_50k.data
build/logs/xs_perf/no0366/fixed_baseline1_cmask6_50k_emu.log
build/logs/xs_perf/no0366/fixed_baseline1_cmask6_50k_symbols.report
build/logs/xs_perf/no0366/fixed_direct_cmask6_50k.data
build/logs/xs_perf/no0366/fixed_direct_cmask6_50k_emu.log
build/logs/xs_perf/no0366/fixed_direct_cmask6_50k_symbols.report
build/logs/xs_perf/no0366/fixed_baseline2_cmask6_50k.data
build/logs/xs_perf/no0366/fixed_baseline2_cmask6_50k_emu.log
build/logs/xs_perf/no0366/fixed_baseline2_cmask6_50k_symbols.report
build/logs/xs_perf/no0366/full_empty_batch_delta.tsv
build/logs/xs_perf/no0366/full_empty_batch_delta.report
```
