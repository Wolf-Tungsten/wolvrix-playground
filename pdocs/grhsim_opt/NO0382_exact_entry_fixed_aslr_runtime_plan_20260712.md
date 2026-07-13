# NO0382 Exact-entry fixed-ASLR runtime plan

日期：2026-07-12

## 1. 目的与输入

[NO0379](./NO0379_exact_entry_explicit_link_build_gate_20260712.md) 已使 baseline/direct 的 117 个 batch 完整入口逐项
同址且 `.text` 同为 `89,041,406` bytes；[NO0380](./NO0380_exact_entry_10k_functional_gate_20260712.md) 和
[NO0381](./NO0381_exact_entry_50k_functional_gate_20260712.md) 已通过双边功能门禁。本轮测量在该严格入口控制下，
direct state-read 的 `-3.465%` host instructions 能否转化为 host cycles 收益。

比较对象：

```text
baseline: d6249d020d019b63abd27b63443c44f9851518613208928f50431c472a190e37
direct:   b93b5f3fa2501a83e49eea206b4356522aa816654fd9cc587eec52ddafb3824c
```

两者只是 layout isolation probes，不改变 direct option 默认关闭的生产配置。

## 2. 受控运行口径

串行执行 exact-entry baseline/direct/baseline 的 CoreMark 50k A/B/A：

- 每条命令先执行 `source env.sh`；
- `setarch "$(uname -m)" -R` 固定 PIE load base；
- `numactl --membind=1` 固定 NUMA node 1，`taskset -c 138` 固定 CPU138；
- 同时监控 SMT sibling CPU330；
- seed 0，固定 CoreMark image、NEMU difftest，参数 `-b 0 -e 0 -C 50000`；
- unset `EMU_RUNTIME_PROFILE`，设置 `EMU_PROGRESS_EVERY_CYCLES=0`；
- 三轮都从独立进程冷启动，不并行运行其他 emu/perf。

事件组与 [NO0365](./NO0365_simtop_direct_state_read_fixed_aslr_runtime_gate_20260712.md) 和
[NO0373](./NO0373_direct_state_read_align4k_runtime_gate_20260712.md) 完全相同：

```text
cycles:u
instructions:u
de_no_dispatch_per_slot.no_ops_from_frontend:u
cpu/de_no_dispatch_per_slot.no_ops_from_frontend,cmask=0x6/u
de_no_dispatch_per_slot.backend_stalls:u
```

正式 A/B/A 前先对 direct 做 100-cycle PMU preflight；五项必须全部 `100.00%` 调度并通过功能终点扫描。

## 3. 机器负载门禁

每一轮运行前记录 `uptime`、内存、其他 emu/perf/编译进程，并执行 `mpstat -P 138,330 1 3`。CPU138 与 CPU330
三秒平均 `%idle` 都必须 `>=99%` 才启动；不通过的 attempt 原样保留，等待后重测。

全机共有 384 个逻辑 CPU，load average 只作辅助信息，不替代目标核 gate。若全机负载升高，仍现场执行两次
exact-entry baseline 夹住 direct；不引用历史 NO0365/NO0373 单点作为当前 baseline。两次 baseline host cycles spread
必须 `<=1%`，否则整组不形成性能比例。

## 4. 功能与 PMU 门禁

三轮都必须满足：

```text
exit code          0
Guest cycles       50001
cycleCnt           49996
instrCnt           73580
terminal PC        0x80001312
```

不得出现 mismatch、assertion、abort、fatal/error 或 `input_fullpass_blocked`。五项 PMU 必须均为 `100.00%` 调度；
固定 ASLR 下两次 baseline 的 difftest state pointer 还必须一致。

## 5. 输出与判定

以两次 exact-entry baseline 均值计算 direct 的：

1. host time、cycles、instructions 的绝对与相对变化；
2. host IPC，以及 frontend empty、cmask6、backend stalls 的绝对值和 per-cycle density；
3. `6 * cmask6` full-empty latency slots 与其余 frontend bandwidth slots；
4. 删减 instructions 按 baseline CPI 可解释的 cycles，以及剩余 CPI/layout 分量；
5. 相对未对齐 NO0365 的 `+6.263%` 和 4 KiB NO0373 的 `-9.084%`，给出 exact-entry 后的因果位置；
6. 复用 NO0344 相邻 fixed GSim 均值，更新 direct/GSim cycles、instructions gap。

若 exact-entry direct 加速，说明 NO0365 的回退主要来自入口地址漂移，并可量化 direct 机制的布局隔离收益；若仍回退，
则剩余根因转向函数内部 basic-block layout、helper/rodata 地址或动态访问序列。无论结果如何，都不把 padding binary
作为生产实现。

本篇只声明性能实验，尚未运行 PMU preflight 或正式 A/B/A。
