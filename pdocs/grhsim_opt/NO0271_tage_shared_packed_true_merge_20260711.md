# NO0271 TAGE shared packed-view true-merge

日期：2026-07-11

## 目标

承接 [NO0270](./NO0270_simtop_tage_commit_guard_branch_miss_diagnosis_20260711.md)，把
`frontend.inner_bpu.tage.tables_[0..7].usefulCtrs[4][2][512]` 从 32768 个 scalar register write
恢复为 64 个 512-row memory。目标不是按信号名做特例，而是补齐 `reg-to-mem` 对 shared packed
concat、尾部 no-op mux 和复合 reset guard 的通用识别能力。

## 漏识别链路

SimTop pre-reg-to-mem IR 中，每个 512-row group 有以下形态：

1. 512 个 register read 先进入同一个 packed concat；
2. packed concat 同时被两个 `kSliceArray` 使用；
3. 每行只有一个 register write，正常写由 row equality guard 选择；
4. reset/fill 条件是多个 reset 项的 OR，其中一项为 `!core_reset && io_resetUseful`；
5. next-value mux 尾部还有 `mux(resetUsefulGuard, zero, zero)`。

旧 true-only discovery 只接受 repeated concat layout 或单个 register read 有额外用户，因此第 2 项
不会形成 storage candidate。补上 shared packed-view discovery 后，strict write matcher 又依次暴露：

- 尾部两臂相同的 mux 被误当成第二个写分支；
- 普通写中的 `!io_resetUseful` 不能证明排除复合 reset 项；
- 第 255 行中，共享 reset 项内部恰好含一个可解析为常量 255 的 equality，被误当成 row-255
  fallback write。

## 实现

修改位于 `wolvrix/lib/transform/reg_to_mem.cpp`：

1. concat 有多个用户时允许进入 true-only storage discovery，后续仍由完整 read closure 和 write
   matcher 决定是否改写；
2. `matchMuxWriteChain()` 删除尾部 data 与最终 fallback 相同的 no-op branch；
3. reset 排除证明支持 `!term`、`!(A || B)`，以及 `!A => !(A && B)`；
4. 在 consolidated-write 匹配前统计每个 update term 覆盖的 row 数。覆盖整组的未消费 term 优先
   作为 group fill/reset 候选，避免其内部 equality 偶然命中某一 row；
5. 上述分类之后仍必须通过普通写与 reset 互斥证明、逐行 addr/data/mask/event 一致、reset term set
   一致、全掩码 fill 等既有 strict gate。

新增/扩展的 synthetic case 位于 `wolvrix/tests/transform/test_reg_to_mem_pass.cpp`：

- shared packed concat 被两个 dynamic slice 使用；
- compound reset 后接两臂相同的 no-op mux；
- group-wide reset 内含 equality，且常量恰好等于最后一行；
- 原有 multiple write family、fallback-data family、reset fill 和 domain guard case 继续覆盖。

## Local gate

所有命令均先执行 `source env.sh`。最终相关 CTest：

```text
emit-grhsim-cpp       PASS 144.68s
transform-reg-to-mem PASS   0.02s
total                       144.72s
```

日志：

```text
build/logs/xs_perf/no0271/ctest_reg_to_mem_emit_shared_reset_20260711.log
build/logs/xs_perf/no0271/ctest_transform_reg_to_mem_shared_reset_20260711.log
```

## SimTop stop-after gate

诊断复用同一份 pre-reg-to-mem checkpoint：

```text
build/xs_grhsim_event_order_src_20260710/grhsim/wolvrix_xs_pre_reg_to_mem.json
```

最终 stop-after-pre-sched 结果：

| metric | 修改前 | 修改后 |
| --- | ---: | ---: |
| candidate groups | `3849` | `3849` |
| true groups | `511` | `575` |
| rewritten 512-row groups | `4` | `68` |
| TAGE useful-counter groups | `0` | `64` |

group 770 到 group 833 连续覆盖 8 张 table、每表 8 个 `[512]` group；首尾组均生成 1 个
memory write 和 1 个 fill。日志：

```text
build/logs/xs_perf/no0271/tage_shared_reset_group_diag_20260711.log
```

## Fresh C++ structure gate

fresh 产物：

```text
build/xs_grhsim_no0271_tage_true_merge_20260711/grhsim
build/logs/xs/xs_wolf_grhsim_build_no0271_tage_true_merge_20260711.log
build/logs/xs/xs_wolf_grhsim_compile_no0271_tage_true_merge_20260711.log
```

目标结构计数：

| generated shape | NO0269 old | NO0271 new |
| --- | ---: | ---: |
| target `kRegisterWritePort` | `32768` | `0` |
| target `kMemoryWritePort` | `0` | `64` |
| target `kMemoryFillPort` | `0` | `64` |
| target `std::array<uint8_t, 512>` state | `0` | `64` |

activity-schedule 同时发生以下变化：

| metric | NO0269 old | NO0271 new | delta |
| --- | ---: | ---: | ---: |
| supernodes | `71067` | `69113` | `-2.75%` |
| DAG edges | `676785` | `664215` | `-1.86%` |
| boundary activation edges | `2367056` | `2284102` | `-3.50%` |
| compute-compute value pairs | `2018559` | `2008189` | `-0.51%` |
| compute-commit value pairs | `348497` | `275913` | `-20.83%` |

生成 C++ 总字节数下降 `3.45%`，最终 executable `.text` 下降 `2.62%`。但 batch 重排使
`sched_5.cpp` 从 `238424` 行增至 `499590` 行，并成为单文件 compile tail；这是 compile-time
代价，不进入 runtime 收益计算。

## 结论

shared packed-view 的 strict true-merge 已在真实 SimTop C++ 中生效，32768 个 scalar write 被 64 个
indexed memory write + fill 取代。功能与 runtime gate 独立记录在
[NO0272](./NO0272_tage_true_merge_simtop_50k_gate_20260711.md)。

## Full CTest 增量

完成全量 CMake build 后顺序执行 48 个 CTest，结果为 `46/48`。本轮相关的
`transform-reg-to-mem`、`emit-grhsim-cpp`、`emit-grhsim-cpp-memory-fill` 及全部 ingest 测试均通过；
失败项为：

```text
transform-comb-lane-pack: Expected one packed kAnd for storage frontier rewrite
transform-repcut: expected repcut partition static feature export
```

全量重建并单独复跑后仍是相同结果。两项失败均为既有基线：以下 2026-07-10 日志在本轮
`reg-to-mem` 修改之前已经记录了完全相同的 `46/48` 和错误文本：

```text
build/logs/xs/no0248_wolvrix_ctest_after_eventblock_fix_20260710.log
build/logs/xs/no0248_wolvrix_ctest_precise_event_gate_20260710.log
```

本轮日志：

```text
build/logs/xs_perf/no0271/cmake_build_all_tage_true_merge_20260711.log
build/logs/xs_perf/no0271/ctest_all_tage_true_merge_20260711.log
build/logs/xs_perf/no0271/ctest_rebuilt_unrelated_failures_20260711.log
```
