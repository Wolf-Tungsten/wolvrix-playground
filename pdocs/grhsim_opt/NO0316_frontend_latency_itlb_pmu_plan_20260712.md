# NO0316 Frontend latency / bandwidth and ITLB PMU plan

日期：2026-07-12

## 1. 目的

[NO0315](./NO0315_no0286_no0300_native_stall_pmu_gate_20260712.md) 已将 NO0300 的单位 work 回退定位到
frontend supply：frontend empty slots/cycle 增加 `3.00%`，但 I-cache access/miss 和 backend stall density
都下降。本阶段进一步区分 frontend latency、frontend bandwidth 和 ITLB miss，避免把所有 empty slots 都解释为
取指延迟。

比较对象继续使用同一组无 profile binary：

```text
old = build/xs_grhsim_no0286_commit_change_unlikely_20260711/grhsim/grhsim-compile/emu
new = build/xs_grhsim_no0300_ordered_affine_fresh_20260712/grhsim/grhsim-compile/emu
```

## 2. 事件与派生量

五事件组为：

```text
cycles:u
de_no_dispatch_per_slot.no_ops_from_frontend:u
cpu/de_no_dispatch_per_slot.no_ops_from_frontend,cmask=0x6/u
bp_l1_tlb_miss_l2_tlb_hit:u
bp_l1_tlb_miss_l2_tlb_miss.all:u
```

按本机 `frontend_bound_latency` metric 的定义计算：

```text
latency_slots = 6 * cmask6_cycles
bandwidth_slots = frontend_empty_slots - latency_slots
```

其中 latency 表示连续至少六个 dispatch slots 均因前端无 op 而空闲的周期；bandwidth 表示剩余前端供给不足。
同时报告所有 slot/TLB 事件的绝对值和 per host cycle 值。

## 3. 运行门禁

- 先用 NO0286 `-C 100` 校验 raw PMU 语法；结尾用户态 modifier 必须写成 `/u`；
- 五项短跑均已确认 `100.00%` 调度；100-cycle 数值只作事件接线检查，不进入性能结论；
- 正式执行 old / new / old，固定 CPU138、NUMA node 1、CoreMark 两迭代、NEMU difftest 和 `-C 50000`；
- 每次运行前检查 CPU138 与 SMT sibling CPU330；若机器负载或 baseline 漂移偏高，保留 A/B/A 配对而不使用单次绝对值；
- 三次必须功能终点一致、全部事件 `100%` 调度，且 old spread 显著小于候选差异。

## 4. 后续判定

- latency density 或 ITLB miss density 恶化：继续检查取指地址转换和 redirect；
- bandwidth density 恶化而 latency/ITLB 不恶化：检查 decoder/op-cache 来源和 taken-branch/redirect 密度；
- 两者都不恶化：回查事件定义和 retire/speculation 口径，不直接形成代码改动。

