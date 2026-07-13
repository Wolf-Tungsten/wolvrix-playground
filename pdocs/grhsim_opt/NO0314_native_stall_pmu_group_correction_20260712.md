# NO0314 Native stall PMU group correction

日期：2026-07-12

## 1. 触发

[NO0313](./NO0313_no0286_no0300_native_stall_pmu_plan_20260712.md) 首次 old1 同时请求以下六个
事件：cycles、instructions、两个 I-cache native events 和两个 dispatch-slot native events。功能运行到相同
50k 终点，但 perf CSV 中六项均只有 `83.00%` 调度。

该 run 不满足“全部事件 100% 调度”的验收条件，数据作废，不进入任何 A/B 结论：

```text
build/logs/xs_perf/no0314/native_old1_perf.csv
build/logs/xs_perf/no0314/native_old1_emu.log
```

## 2. 修正

原生组移除 `instructions:u`，恢复此前 NO0298 已验证可同时 100% 调度的五事件口径：

```text
cycles:u
ic_tag_hit_miss.all_instruction_cache_accesses:u
ic_tag_hit_miss.instruction_cache_miss:u
de_no_dispatch_per_slot.no_ops_from_frontend:u
de_no_dispatch_per_slot.backend_stalls:u
```

instructions 已由 [NO0302](./NO0302_ordered_memory_write_affine_overall_50k_gate_20260712.md) 的独立
old/new/old 无插桩配对完整覆盖，不需要在本组重复 multiplex。修正后的原生组重新从 old1 开始，仍执行
old/new/old，并要求五项逐项 `100%`。

## 3. 约束

后续若补 cache/TLB 事件，也按可同时 100% 调度的组拆分；不使用 perf 的 multiplex scale 值替代原生计数，
不把本次 83% run 混入 baseline 均值。

