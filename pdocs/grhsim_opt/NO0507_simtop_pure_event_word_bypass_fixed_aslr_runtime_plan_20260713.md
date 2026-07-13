# NO0507 SimTop pure-event word bypass fixed-ASLR runtime plan

日期：2026-07-13

## 1. Purpose and inputs

[NO0506](./NO0506_simtop_pure_event_word_bypass_50k_functional_gate_20260713.md) 已确认 production bypass 的
100/10k/50k 功能轨迹与 NO0357 direct-state-read baseline 精确一致。本轮测量 107 个 pure-event word wrappers 在真实
SimTop 50k 上能否把 NO0500 的 6,948,664 次 active miss 转化为 host cycles 收益，并同时观察 NO0503 的 batch 27
codegen cliff 是否抵消动态绕过。

比较对象均为 profile-off x86-64 PIE：

```text
baseline:
  build/xs_grhsim_no0357_direct_state_read_20260712/grhsim/grhsim-compile/emu
  cad7eca081fb8f9974be8bafdb996991414a65787b4aa16447f32f79acc6ebd4
candidate:
  build/xs_grhsim_no0501_pure_event_bypass_20260713/grhsim/grhsim-compile/emu
  86d544a8edc08d420785e2c292280398696f44993659a5a5efe082165ecfa6fe
```

## 2. Controlled run

串行执行 baseline/candidate/baseline 的 CoreMark 50k A/B/A：

- 每条命令先执行 `source env.sh`；
- 外层 `setarch "$(uname -m)" -R` 固定 PIE load base；
- `numactl --membind=1` 固定 NUMA node 1；
- 在 NUMA1 即时 survey 一对安静 SMT siblings，锁定 primary CPU 执行整组，不在中途换核；
- seed 0，固定 image/NEMU，参数 `-b 0 -e 0 -C 50000`；
- 显式 unset `EMU_RUNTIME_PROFILE` 与 pure-event TSV，`EMU_PROGRESS_EVERY_CYCLES=0`；
- 三轮均独立冷启动，不并行运行其他本任务 emu/perf。

事件组沿用 NO0385/NO0386：

```text
cycles:u
instructions:u
de_no_dispatch_per_slot.no_ops_from_frontend:u
cpu/de_no_dispatch_per_slot.no_ops_from_frontend,cmask=0x6/u
de_no_dispatch_per_slot.backend_stalls:u
```

正式运行前先对 candidate 做 100-cycle PMU preflight，五项必须全部 `100.00%` 调度。

## 3. Load and validity gates

当前共享机 load 曾升至 `215/384`，因此不引用 NO0361/NO0386 的历史 raw time。具体门禁为：

1. survey 本身绑定到非目标核，在 NUMA1 选择五秒采样中 sibling-pair 最低 idle 最高的候选；
2. preflight 和每轮 A/B/A 前执行 `mpstat -P primary,sibling 1 3`，两者三秒平均 idle 均须 `>=99%`；
3. 未通过的 attempt 原样保留且不启动 perf，等待后重试同一锁定 CPU；
4. 每轮记录全机 load、内存及其他 emu/perf/编译进程；全机 load 只作辅助，不能替代目标核门禁；
5. 两次 baseline host cycles spread 必须 `<=1%`，否则整组不形成 candidate 比例并补跑 baseline。

三轮必须全部达到 guest cycles `50,001`、`cycleCnt=49,996`、`instrCnt=73,580`、terminal PC
`0x80001312`，且无 mismatch/assertion/abort/fatal/error/`input_fullpass_blocked`。五项 PMU 都须为 `100.00%` 调度；
fixed-ASLR 下两次 baseline 的 difftest state pointer 必须一致。

## 4. Analysis and decision

以两次 baseline 均值计算 candidate 的 host time、cycles、instructions、host IPC，以及 frontend empty、cmask6、backend
stalls 的绝对变化和 per-cycle density。主要门禁是 cycles 改善，并要求 instructions 或 stall 指标没有足以推翻收益的回退。

若 candidate 加速，则继续判断收益由删 instructions 还是 CPI 改善贡献；若持平/回退，则结合 NO0503 batch 27 cliff 与
NO0500 per-batch miss 热度，形成排除 codegen-cliff words 或改变函数组织的独立候选，不按 batch id 掩盖。

预定产物位于：

```text
build/logs/xs_perf/no0507/
```

本篇只声明实验方案，尚未运行 PMU preflight 或正式 A/B/A。
