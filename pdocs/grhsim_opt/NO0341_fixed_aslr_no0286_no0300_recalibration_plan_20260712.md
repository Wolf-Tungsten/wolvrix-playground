# NO0341 Fixed-ASLR NO0286 / NO0300 recalibration plan

日期：2026-07-12

## 1. 目的

[NO0338](./NO0338_pie_aslr_performance_runbook_correction_20260712.md) 发现历史 SimTop perf 没有固定 PIE
load base；[NO0340](./NO0340_fixed_aslr_bitrev_order_runtime_gate_20260712.md) 进一步确认，同一 NO0300 binary
在 fixed-ASLR 与历史随机基址下的 host cycles 相差 `8%~9%`。该幅度已覆盖此前 NO0286 / NO0300
约 `4%` 的相对回退，因此必须先重做受控 old/new 比较，再继续解释 ordered-affine 的单位 work 成本。

本轮只校准性能口径，不重建模型、不修改 generated C++：

```text
old = build/xs_grhsim_no0286_commit_change_unlikely_20260711/grhsim/grhsim-compile/emu
new = build/xs_grhsim_no0300_ordered_affine_fresh_20260712/grhsim/grhsim-compile/emu
```

两者均已确认为 x86-64 PIE，且此前通过相同 CoreMark 10k/50k 功能门禁。

## 2. 受控口径

按 old / new / old 顺序执行三轮 CoreMark 50k，并固定以下条件：

- 每条命令先 `source env.sh`；
- 外层使用 `setarch "$(uname -m)" -R` 关闭 ASLR；
- `numactl --membind=1`、`taskset -c 138` 固定 NUMA node 1 与 CPU138；
- workload 为 `coremark-2-iteration.bin`，NEMU difftest 和 `-C 50000` 不变；
- 使用与 NO0340 相同的四事件：`cycles:u`、`instructions:u`、frontend empty slots 和 cmask6 cycles；
- 每轮前检查全机 load、CPU138 及 SMT sibling CPU330；若目标 CPU 忙或全机负载异常，等待后重查；
- 不混入 NO0338 前的随机基址数据。

命令前缀统一为：

```text
setarch "$(uname -m)" -R numactl --membind=1 taskset -c 138 perf stat ...
```

## 3. 门禁

三轮必须同时满足：

1. `Guest cycle spent = 50001`、`cycleCnt = 49996`、`instrCnt = 73580`、terminal PC
   `0x80001312`，且没有 mismatch/assertion/abort；
2. 四项 PMU event 均为 `100.00%` 调度；
3. 两次 old host cycles spread 不超过 `1%`；若超门限，先检查负载并补跑 old，不对 new 形成结论；
4. 同时报告绝对计数、new 相对 old mean 的变化，以及 empty/cmask6 的 per-cycle 变化。

instructions 用于确认两版 dynamic instruction 差异仍约为历史 `-8.45%`；cycles 与 cmask6 density 决定
NO0300 在 fixed-ASLR 下究竟是加速还是减速。该结果形成独立 runtime gate 后，再以同一 fixed-ASLR 口径
复测 GSim，更新 GrhSIM/GSim 的直接差距。

## 4. 预定产物

```text
build/logs/xs_perf/no0341/fixed_old1_emu.log
build/logs/xs_perf/no0341/fixed_old1_perf.csv
build/logs/xs_perf/no0341/fixed_new_emu.log
build/logs/xs_perf/no0341/fixed_new_perf.csv
build/logs/xs_perf/no0341/fixed_old2_emu.log
build/logs/xs_perf/no0341/fixed_old2_perf.csv
```
