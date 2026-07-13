# NO0497 SimTop pure-event word profile build gate

日期：2026-07-13

## 1. Build scope

按 [NO0496](./NO0496_simtop_pure_event_word_profile_fresh_emit_gate_20260713.md) 使用标准 XiangShan difftest
GrhSIM 入口，对 profile-only 154-file model 执行 Clang O3 archive build 与 emu link。主机 load 为约 149/145/147（384
logical CPUs），无其他 compiler；本轮将 model build 从旧门禁 64 路收敛到 32 路，不作 build-time 性能比较。

```text
model:
  build/xs_grhsim_no0495_pure_event_profile_20260713/grhsim/grhsim_emit
emu:
  build/xs_grhsim_no0495_pure_event_profile_20260713/grhsim/grhsim-compile/emu
log:
  build/logs/xs/xs_wolf_grhsim_compile_no0497_pure_event_profile_20260713.log
```

编译口径为 `clang++ -std=c++20 -O3`、`ar rv`、`NUM_CORES=1`、ChiselDB/Constantin/waveform off。

## 2. Integrity

```text
difftest/support CXX       40
generated compile         153
sched compile             117
archive members           152
sched archive members     117
error/fatal/killed          0
final link                  1
exit status                 0
wall time              3:18.42
peak process RSS         1.19 GiB
```

最终 emu 为未 strip x86-64 PIE executable。SHA256：

```text
emu      3e5ba9e36f0b3a8655073d237c3f1dece8136926ce8aa1d1c1bffca0b420f1cf
archive  5a0c83c95dd68f3d2aa54606725216fd60de810b33eebb873ace84db8e1e3d52
```

## 3. Binary delta

与 NO0357 no-profile direct-state-read emu 对比：

| Metric | NO0357 | Profile | Delta |
|---|---:|---:|---:|
| archive bytes | 99,341,410 | 99,358,958 | +17,548 |
| emu bytes | 93,707,232 | 93,720,576 | +13,344 |
| text bytes | 93,532,652 | 93,545,148 | +12,496 |
| data bytes | 9,368 | 9,424 | +56 |
| bss bytes | 14,688 | 14,688 | 0 |

107 个 sites、两个 117-entry counter arrays、getter/dump 以约 12.5 KiB text 与 56-byte initialized data 穿过 O3；bss
不变。体积只用于证明 profile 实际编译进 emu，不用于性能判断。

## 4. Decision

build/link gate 通过。下一步先做短 cycle smoke，确认初始化、NEMU、assertion 与 profile dump 接线；通过后执行 10k
CoreMark/NEMU difftest并分析 22-row hit/miss TSV。
