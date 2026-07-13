# NO0398 Direct scalar-locality runtime-profile smoke gate

日期：2026-07-12

## 1. Run

承接 [NO0397](./NO0397_direct_scalar_locality_runtime_profile_build_gate_20260712.md)，对 direct runtime-profile emu
运行 CoreMark/NEMU difftest 100-cycle smoke：

```text
EMU_RUNTIME_PROFILE=1
EMU_PROGRESS_EVERY_CYCLES=100
-b 0 -e 0 -C 100
```

所有命令先执行 `source env.sh`。运行前 load average 为 `22.08/21.98/23.67`，但本轮只作功能/profile 接线检查，
host time 不作性能结论。

## 2. Functional gate

```text
exit:          0
guest cycles:  101
model cycles:  100
cycleCnt:       96
instrCnt:        0
commit/trap PC: 0x0 / 0x0
```

日志明确出现 `[EMU_RUNTIME_PROFILE] enabled` 和
`[GRHSIM_RUNTIME_PROFILE] ... rows=63726`。fire TSV 有 63,727 行，即 header + 63,726 data rows；使用 NO0311
compare tool 与 emit-time static TSV 连接，全部 `(supernode_id, phase)` keys 精确匹配。

负向扫描无 mismatch、assert、abort、fatal/error、segmentation fault 或 `input_fullpass_blocked`。该 smoke 只覆盖
初始化/fullpass，下一步进入 50k CoreMark 指令执行与 direct fire 采集。

产物：

```text
build/logs/xs_perf/no0398/direct_rtprof_smoke_100.log
build/logs/xs_perf/no0398/direct_rtprof_smoke_100_fire.tsv
build/logs/xs_perf/no0398/direct_rtprof_smoke_100.{report,json}
```
