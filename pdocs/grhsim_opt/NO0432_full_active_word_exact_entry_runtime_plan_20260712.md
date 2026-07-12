# NO0432 Full active-word exact-entry runtime plan

日期：2026-07-12

## 1. Objective and binaries

[NO0431](./NO0431_full_active_word_exact_entry_50k_gate_20260712.md) 已闭合 exact-entry 双边功能。本轮测量在
117 个 sched entry 严格同址、`.text` 同长后，full-word clear/restore 删除本身的 runtime 效果：

```text
exact baseline:
  build/xs_grhsim_no0428_exact_entry_baseline_20260712/grhsim/grhsim-compile/emu
  SHA256 cad7eca081fb8f9974be8bafdb996991414a65787b4aa16447f32f79acc6ebd4
exact candidate:
  build/xs_grhsim_no0428_exact_entry_candidate_20260712/grhsim/grhsim-compile/emu
  SHA256 b342b9e7a6e4d71a479a91f03fa8a39a4c333006bc0145cb05096bacf1b9d1a4
```

exact baseline 与 NO0427 native baseline 是同一 binary；两版 exact emu 都是 93,707,232 bytes、`.text`
87,114,910 bytes，117 个入口为 `0x18c310..0x52f26f0` 逐项同址。

## 2. Controlled runtime

继续锁定 NO0425/NO0427 已验证的 CPU131/323，以便在现场 exact A/B/A 之外，还能将相同 CPU 上的 native/exact
layout 方向作为次级诊断：

```text
CPU=131
SMT sibling=323
NUMA node=1
ASLR=setarch -R
order=exact baseline / exact candidate / exact baseline
```

每条命令先 `source env.sh`；固定 seed 0、CoreMark image、NEMU difftest、`-b 0 -e 0 -C 50000`，unset
`EMU_RUNTIME_PROFILE`，设置 `EMU_PROGRESS_EVERY_CYCLES=0`。

每轮前用 `mpstat -P 131,323 1 3`，两核平均 idle 均须 `>=99%`。任何 rejected attempt 原样保留；仍使用
本组双 baseline 均值，不以 NO0427 的历史 baseline 代替。

事件组不变：

```text
cycles:u
instructions:u
de_no_dispatch_per_slot.no_ops_from_frontend:u
cpu/de_no_dispatch_per_slot.no_ops_from_frontend,cmask=0x6/u
de_no_dispatch_per_slot.backend_stalls:u
```

正式 A/B/A 前先对 exact candidate 做 100-cycle PMU preflight，要求五事件 100% scheduled、功能正确，并确认
fixed-ASLR state 地址与 exact baseline 布局一致。

## 3. Acceptance and interpretation

三轮必须 exit 0，达到 guest/cycleCnt/instr/PC `50,001/49,996/73,580/0x80001312`，无 mismatch、
assert/abort、fatal/error、segmentation fault 或 `input_fullpass_blocked`。五事件须 100% scheduled，两次
baseline cycles spread `<=1%`。

以双 baseline 均值计算：

1. cycles/instructions 变化和 instruction benefit realization；
2. IPC、frontend、cmask6、backend density；
3. exact candidate 与 NO0427 native candidate 的 cycles/cmask6 差异，量化恢复 entry layout 后回收的前端成本；
4. 不跨 CPU 引用 GSim absolute counters。

如果 exact candidate instructions 仍下降且 cycles 转为改善，则证明机制有效、NO0427 回退由布局主导；但 native
production binary 仍慢，开关继续默认关闭，后续必须寻找可部署的 stable-entry/link layout。若 exact 仍不改善，则
停止 full-word consume，不用布局解释掩盖真实回退。

## 4. Planned artifacts

```text
build/logs/xs_perf/no0432/exact_candidate_preflight_{emu.log,perf.csv}
build/logs/xs_perf/no0432/{baseline1,candidate,baseline2}_{emu.log,perf.csv}
build/logs/xs_perf/no0432/*_quiet_gate_attempt_*.log
```
