# NO0396 Direct scalar-locality runtime-profile emit gate

日期：2026-07-12

## 1. Fresh emit

按 [NO0395](./NO0395_direct_scalar_locality_runtime_profile_plan_20260712.md)，从同一 pre-reg-to-mem checkpoint
fresh emit `direct-state + runtime-profile` model，未开启 typed local 或其他新 codegen 优化。所有命令先执行
`source env.sh`。

```text
output:
  build/xs_grhsim_no0395_direct_rtprof_20260712/grhsim/grhsim_emit
driver total: 393.404 s
wall time:    397.09 s
exit:         0
```

read-args SHA256 仍为 `bd420039...`。

## 2. Structure identity

`activity_schedule_supernode_stats.json` SHA256 为 `e3056375...`，与 NO0300/NO0357/NO0392 相同。direct emitter
再次输出：

```text
reads=75,830 canonical=40,108 aliases=35,722
removed_source_heads=37,672 consumer_heads=39,602
```

profile 与 NO0392 production direct model 均有 154 个 generated files、75,830 个 direct markers 和 920,942 个
register-read comments。profile files 合计 `1,366,675,594` bytes，production 为 `1,357,263,998` bytes；新增约
9.41 MB 来自 runtime counter/static-profile 接线，不用于性能比较。

## 3. Profile wiring gate

生成 header 明确包含：

```cpp
static constexpr bool kRuntimeProfileCompiled = true;
std::array<std::uint64_t, kSupernodeCount> runtime_profile_fire_compute_{};
```

`grhsim_supernode_static.tsv` 有 63,727 行，即 header + 63,726 data rows；没有重复生成 202 MB scalar locality TSV。
schedule key、direct lowering 和 op comment 数均通过，可以进入标准 Clang/O3 build。

## 4. Artifacts

```text
build/logs/xs/xs_wolf_grhsim_build_no0395_direct_rtprof_emit_20260712.log
build/logs/xs/xs_wolf_grhsim_build_no0395_direct_rtprof_emit_20260712.time
```
