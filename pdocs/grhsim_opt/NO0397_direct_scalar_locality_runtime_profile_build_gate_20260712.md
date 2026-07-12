# NO0397 Direct scalar-locality runtime-profile build gate

日期：2026-07-12

## 1. Build

承接 [NO0396](./NO0396_direct_scalar_locality_runtime_profile_emit_gate_20260712.md)，使用 XiangShan difftest 标准
Clang/O3 GrhSIM flow 构建 direct runtime-profile model。所有命令先执行 `source env.sh`，模型并行度限制为 32；构建
前 load average `25.33/22.25/24.37`，机器有 384 个逻辑 CPU、可用内存 942 GiB。

```text
model objects:     152
harness objects:    40
warnings/errors:     0
wall time:       2:16.83
max RSS:       1,273,804 KiB
```

## 2. Binary gate

最终产物：

```text
build/xs_grhsim_no0395_direct_rtprof_20260712/grhsim/grhsim-compile/emu
file bytes: 95,600,640
text:       95,423,321
data:            9,424
bss:            14,688
SHA256: cea2a13068f29a56243c402a686fa02d3b57243c4a54d0904ffdd8be9678dae9
```

binary strings 同时包含 `EMU_RUNTIME_PROFILE`、`[EMU_RUNTIME_PROFILE] enabled`、
`[GRHSIM_RUNTIME_PROFILE] supernode_fire_tsv=... rows=...` 和默认 fire TSV 路径。archive 与最终链接均完成，可以进入
100-cycle smoke；本阶段尚未运行仿真。

日志：

```text
build/logs/xs/xs_wolf_grhsim_compile_no0395_direct_rtprof_20260712.log
build/logs/xs/xs_wolf_grhsim_compile_no0395_direct_rtprof_20260712.time
```
