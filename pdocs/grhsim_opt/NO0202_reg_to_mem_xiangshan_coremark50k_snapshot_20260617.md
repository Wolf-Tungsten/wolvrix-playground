# NO0202 Reg-to-Mem XiangShan CoreMark 50k Snapshot

记录日期：2026-06-17

## 背景

本记录固化本轮 `reg-to-mem` 在 XiangShan `coremark 50k` 上的标准流程复测结果、最终生成代码形态和当前性能判断。

本轮执行约束：

- 使用顶层标准 Makefile 目标，不手写 difftest / clang 编译命令。
- build 使用 `make xs_wolf_grhsim_emu ...`。
- run 使用 `make run_xs_wolf_grhsim_emu ...`。
- 重点产物目录为 `tmp/xs_regtomem_wave_20260616_161520`。
- 避免展开超大生成文件，只用 `rg` / `find` / `stat` / focused count 做诊断。

## 标准 O3 + FST 波形复测

构建 run id：

```text
xs_std_grhsim_o3_wave_coremark50k_20260617_121925
```

关键配置：

```text
WOLVRIX_GRHSIM_WAVEFORM=1
XS_WAVEFORM=1
XS_SIM_MAX_CYCLE=50000
XS_PROGRESS_EVERY_CYCLES=500
```

构建日志：

```text
build/logs/xs/xs_wolf_grhsim_build_xs_std_grhsim_o3_wave_coremark50k_20260617_121925.log
```

运行日志：

```text
tmp/xs_regtomem_wave_20260616_161520/xs_wolf_grhsim_xs_std_grhsim_o3_wave_coremark50k_run_20260617_125412.log
```

波形文件：

```text
tmp/xs_regtomem_wave_20260616_161520/xs_wolf_grhsim_xs_std_grhsim_o3_wave_coremark50k_run_20260617_125412.fst
```

结果：

```text
Core-0 instrCnt = 73580, cycleCnt = 49996, IPC = 1.471718
Host time spent: 2810818ms
```

结论：

- O3 + FST 跑满 50k cycle，以 cycle limit 正常结束。
- 本轮未复现此前关心的 assertion / abort。
- FST 文件约 `772MB`。
- 折算速度约 `17.8 cycles/s`。

## 标准 O3 + no-FST 复测

构建 run id：

```text
xs_std_grhsim_o3_nowave_coremark50k_20260617_135201
```

关键配置：

```text
WOLVRIX_GRHSIM_WAVEFORM=0
XS_WAVEFORM=0
XS_SIM_MAX_CYCLE=50000
XS_PROGRESS_EVERY_CYCLES=500
```

构建日志：

```text
build/logs/xs/xs_wolf_grhsim_build_xs_std_grhsim_o3_nowave_coremark50k_20260617_135201.log
```

运行日志：

```text
tmp/xs_regtomem_wave_20260616_161520/xs_wolf_grhsim_xs_std_grhsim_o3_nowave_coremark50k_run_20260617_140143.log
```

结果：

```text
Core-0 instrCnt = 73580, cycleCnt = 49996, IPC = 1.471718
Guest cycle spent: 50001
Host time spent: 322427ms
```

结论：

- O3 + no-FST 跑满 50k cycle，以 cycle limit 正常结束。
- 未生成 `.fst`。
- 折算速度约 `155.1 cycles/s`。
- no-FST 相比 FST 约 `8.7x` 加速，说明波形 dump 是本轮 FST 配置下的主导开销。

## Reg-to-Mem Pass 统计

no-FST 构建日志显示当前流程启用了 intent：

```text
reg_to_mem_intent=True
```

pass 统计：

```text
reg-to-mem profile: graph_done index=1 total_ms=6765 groups=542 visited_groups=542 true_groups=280 true_skipped=262 intent_groups=262
reg-to-mem profile: summary total_ms=7018 graphs=1 build_uses_ms=1184 discover_anchors_ms=503 group_anchors_ms=2 build_read_index_ms=542 collect_writes_ms=574 true_closure_ms=3 collect_inits_ms=0 regular_write_match_ms=8 reset_write_match_ms=0 finalize_true_match_ms=0 rewrite_true_ms=3691 rewrite_memory_ms=145 rewrite_read_replacement_ms=115 rewrite_erase_read_closure_ms=0 rewrite_fill_ms=0 rewrite_domain_guard_ms=0 rewrite_write_port_ms=0 rewrite_erase_writes_ms=811 rewrite_erase_regs_ms=2345 annotate_ms=2
```

当前解释：

- 一共发现并访问 `542` 个候选组。
- `280` 组走真合并，rewrite 成真正的 memory。
- `262` 组未满足真合并写侧条件，走 intent 合并。
- `true_skipped=262` 与 `intent_groups=262` 对齐。

## 最终生成代码形态

最终生成目录：

```text
build/xs/grhsim/grhsim_emit
```

关键头文件：

```text
build/xs/grhsim/grhsim_emit/grhsim_SimTop.hpp
```

### Real merge

真合并后的字段不是 `state_reg_to_mem_*`，而是普通 memory 字段：

```text
state_mem_rtm_mem_*
```

最终声明统计：

```text
state_mem_rtm_mem_* fields = 280
merged rows              = 15464
```

这个数量与 pass 日志中的 `true_groups=280` 精确对齐。

样例形态：

```text
std::array<std::uint8_t, 32> state_mem_rtm_mem_cpu_l_soc_core_with_l2_core_frontend_inner_icache_wayLookup_entries_0_itlbPbmt_5221623_ = std::array<std::uint8_t, 32>{};
std::array<std::uint8_t, 512> state_mem_rtm_mem_cpu_l_soc_core_with_l2_core_frontend_inner_bpu_utage_MicroTageTable_entries_0_cfiPosition_5221635_ = std::array<std::uint8_t, 512>{};
```

调度代码中可以看到按 index 读写这些 memory 字段，例如：

```text
state_mem_rtm_mem_...[(static_cast<std::size_t>(static_cast<std::uint64_t>(value_u8_slots_[...])) & 63u)]
```

这说明 real merge 不是只保留 metadata，而是已经在最终 C++ 中成为真实 array/memory storage。

### Intent merge

intent 合并后的字段为：

```text
state_reg_to_mem_rtm_intent_*
```

最终声明统计：

```text
state_reg_to_mem_rtm_intent_* fields = 262
merged rows                         = 6896
```

这个数量与 pass 日志中的 `intent_groups=262` 精确对齐。

样例形态：

```text
std::array<std::uint64_t, 64> state_reg_to_mem_rtm_intent_0_ = std::array<std::uint64_t, 64>{};
std::array<std::uint8_t, 64> state_reg_to_mem_rtm_intent_1_ = std::array<std::uint8_t, 64>{};
```

最终生成代码中 `state_reg_to_mem_rtm_intent_*` 有约 `36653` 处引用，覆盖初始化、按 row 更新和打包读取。它不是空标注，也不是未消费 attr。

### 合并总量

按最终 C++ storage 形态统计：

```text
real merge   : 280 groups, 15464 original reg rows
intent merge : 262 groups,  6896 original reg rows
total        : 542 groups, 22360 original reg rows
```

如果问“合并后的对象数”，当前是 `542` 个 array/memory-like storage。

如果问“覆盖了多少原 scalar reg row”，当前是 `22360` 个。

## 当前性能判断

当前 no-FST 50k 结果：

```text
322427ms / 50001 guest cycles ~= 155.1 cycles/s
```

这个结果相对近期无波形 grhsim 50k 记录并没有显著提升。例如：

```text
xs_wolf_grhsim_no0200_guard_event_nodes_in_event_supernode50k_20260615.log : 318117ms / ~157.17 cycles/s
xs_wolf_grhsim_no0200_guard_event_capped4096_50k_20260615.log             : 321436ms / ~155.55 cycles/s
当前 reg-to-mem no-FST O3                                                  : 322427ms / ~155.1 cycles/s
```

因此当前结论不是“reg-to-mem 带来明显 runtime 加速”，而是：

- 功能上：O3 标准流程已可跑满 50k，且 FST/no-FST 都未复现 assertion / abort。
- 结构上：real merge 与 intent merge 都已经在最终 C++ 形态中生效。
- 性能上：本轮 50k coremark no-FST 结果基本与 `NO0200` capped commit-node packing 后的速度持平，收益不显著。

可能原因：

- 合并覆盖的 `22360` 个 reg row 相对整图规模仍小。当前图约 `5268574 ops`、`4677017 values`，activity-schedule 后约 `1395331 compute_nodes`、`72413 supernodes`。
- real merge 虽然变成 memory，但动态 index、mask、guard、change detection 和 reactivation 仍在，不能直接消掉运行时成本。
- intent merge 主要改变 physical storage 和 array access 形态，不等价于完整 memory port rewrite，收益更偏局部。
- 被合并对象多集中在 frontend / BPU / queue 一类数组化状态；CoreMark 50k 的主导开销可能仍在大组合 compute、commit supernode、difftest/外围逻辑或 activity propagation。
- FST 场景下波形 dump 成本远大于 reg-to-mem 带来的局部结构变化，容易淹没收益。

## 注意事项

- final C++ 中 real merge 不会出现 `state_reg_to_mem_*` 名字。它通过 `rtm_mem$...` memory symbol 进入 emitter，最终字段名是 `state_mem_rtm_mem_*`。
- 如果需要把 `280` 个 real group 逐一映射回原始 reg symbol，需要额外导出 post-reg-to-mem JSON 或增加 group dump。仅靠最终 C++ 字段名可以确认结构生效，但不适合做完整来源映射。
- 当前性能判断还不是严格同源 `reg_to_mem_intent=0` A/B。已有 no-intent emit 产物不等价于标准 50k run。后续若要定量评价 runtime 收益，应使用同一顶层 Makefile 流程做 `WOLVRIX_XS_GRHSIM_REG_TO_MEM_INTENT=0/1` 对照。

## 后续建议

1. 用标准 Makefile 流程补一组同源 no-intent / intent A/B，固定 O3、no-FST、50k、相同 runtime profile 开关。
2. 给 `reg-to-mem` 增加轻量 group dump，记录 group id、row count、element width、原 reg symbol 前缀、real/intent 归类，避免后续只能从最终 C++ 反推。
3. 对 no-FST emu 做 perf 采样，确认 `state_mem_rtm_mem_*` / `state_reg_to_mem_rtm_intent_*` 所在调度函数是否进入主热点。
4. 若热点不在这些合并对象上，继续沿 `NO0200` 的 commit packing / activity propagation 成本线推进，而不是预期 `reg-to-mem` 单独带来大幅加速。
