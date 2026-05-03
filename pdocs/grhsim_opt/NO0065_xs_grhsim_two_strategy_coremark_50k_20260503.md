# NO0065 XS GrhSIM Two-Strategy CoreMark 50k Snapshot

## 1. 目的

记录一次在当前清理后代码上的 XiangShan `grhsim` 完整复测：重新 emit、重新构建 `emu`、运行 `coremark` 50k bounded run，并记录本轮速度。

本轮代码状态的关键变化：

- `merge-reg` 只保留 `scalar-to-memory` 与 `indexed-bundle-entry-to-wide-register` 两个策略。
- 独立 `scalar-memory-pack` 已合并进 `wolvrix/lib/transform/merge_reg.cpp`，不再作为单独 pass 存在。
- 独立 `record-slot-repack` 已删除。
- `scripts/wolvrix_xs_grhsim.py` 的 checkpoint 流程已线性化，只保留 `activity-schedule` 前的 post-stats checkpoint。

## 2. 执行流程

本轮显式固定 `RUN_ID`：

```bash
RUN_ID=20260503_110204
```

先清理 XS 差分 / `grhsim` 产物：

```bash
make xs_diff_clean RUN_ID=20260503_110204
```

然后重新 emit 并构建 `grhsim` emu：

```bash
make xs_wolf_grhsim_emu RUN_ID=20260503_110204
```

最后运行 XiangShan `coremark`，限制最大周期为 `50000`：

```bash
make run_xs_wolf_grhsim_emu RUN_ID=20260503_110204 XS_SIM_MAX_CYCLE=50000
```

## 3. 构建结果

`xs_wolf_grhsim_emit` 成功，退出码为 `0`。

构建日志：

```text
build/logs/xs/xs_wolf_grhsim_build_20260503_110204.log
```

`emu` 成功链接：

```text
build/xs/grhsim/grhsim-compile/emu
```

产物大小：

```text
165M
```

`emu` 编译时间戳：

```text
emu compiled at May  3 2026, 11:20:14
```

前置 pass 摘要：

```text
memory-read-retime: memory-read-retime: readport_total=136 candidate=10 retimed=10 retimed_rom=0 retimed_simple_ram=10 skip_non_register_addr=95 skip_multiwrite_addr_reg=0 skip_partial_mask=0 skip_addr_fanout=0 skip_multiwrite_memory=23 skip_writeport_partial_mask=0 skip_mismatched_event_domain=8 skip_declared_symbol=0 skip_malformed=0
comb-lane-pack: comb-lane-pack summary groups=4161 roots=55863 packed-width=2750614
```

`merge-reg` 日志确认当前只启用了两个策略：

```text
merge-reg: merge-reg: graphs=1 indexed_bundle_entry_clusters=7983 indexed_bundle_entry_members=110679 rewritten_indexed_bundle_entry_clusters=10172 rewritten_indexed_bundle_entry_members=108887 rewritten_clusters=10172 rewritten_members=108887 scalar_to_memory_changed=true strategies=scalar-to-memory,indexed-bundle-entry-to-wide-register
```

关键点：

- `strategies=scalar-to-memory,indexed-bundle-entry-to-wide-register`
- `scalar_to_memory_changed=true`
- `indexed_bundle_entry_clusters=7983`
- `indexed_bundle_entry_members=110679`
- `rewritten_clusters=10172`
- `rewritten_members=108887`

emit 侧关键耗时：

```text
[wolvrix-xs-grhsim] pass simplify done 234662ms
[wolvrix-xs-grhsim] pass merge-reg done 52977ms
[wolvrix-xs-grhsim] pass simplify done 66548ms
[wolvrix-xs-grhsim] write_post_stats_json done 10337ms
[wolvrix-xs-grhsim] pass stats done 194264ms
[wolvrix-xs-grhsim] write_grhsim_cpp done 34811ms
[wolvrix-xs-grhsim] total done 1050940ms
```

post-stats checkpoint：

```text
build/xs/grhsim/wolvrix_xs_post_stats.json
```

stats 输出：

```text
build/xs/grhsim/grhsim_emit/wolvrix_xs_stats.json
```

## 4. 调度结果

`activity-schedule` 摘要：

```text
activity-schedule: activity-schedule: path=SimTop graph=SimTop supernodes=76621 seed_supernodes=4534581 coarse_supernodes=77181 dp_supernodes=76621 sink_supernodes=5740 sink_ops=127600 eligible_ops=4770644 state_read_tail_absorb_target_supernodes=77896 state_read_tail_absorb_cloned=162028 state_read_tail_absorb_erased=47825 replication_cloned=0 replication_erased=0 state_read_sets=124329 graph_changed=true
```

调度耗时拆分：

```text
activity-schedule: activity-schedule timing(ms): build_op_data=10412 sink_partition=1769 seed_partition=2195 state_read_tail_absorb=71034 rebuild_after_state_read_tail_absorb=4829 coarsen=3733 dp_prep=747 dp=3 refine=0 materialize_segments=505 symbol_partition=17 replication=0 freeze_after_replication=0 final_materialize=9405 export_session=111 total=100742
```

supernode 统计：

```text
[wolvrix-xs-grhsim] activity-schedule supernode stats supernodes=76621 dag_edges=1108768 ops_mean=62.263 ops_median=70 ops_p90=73 ops_p99=108 ops_max=1872 outdeg_mean=14.471 outdeg_p99=104 outdeg_max=16754
```

## 5. 运行结果

运行日志：

```text
build/logs/xs/xs_wolf_grhsim_20260503_110204.log
```

输入镜像：

```text
testcase/xiangshan/ready-to-run/coremark-2-iteration.bin
```

DiffTest 参考模型：

```text
testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so
```

运行跑满 `50000` cycle，以 cycle limit 正常结束。日志中没有匹配到 RTL assertion、DiffTest mismatch、crash、`FATAL`、`panic` 或 `ERROR`。

周期进度：

```text
[CYCLE_LIMIT] cycles=10000 max_cycles=50000
[CYCLE_LIMIT] cycles=20000 max_cycles=50000
[CYCLE_LIMIT] cycles=30000 max_cycles=50000
[CYCLE_LIMIT] cycles=40000 max_cycles=50000
[CYCLE_LIMIT] cycles=50000 max_cycles=50000
```

日志尾部：

```text
[CYCLE_LIMIT] cycles=50000 max_cycles=50000
Core 0: EXCEEDING CYCLE/INSTR LIMIT at pc = 0x8000042c
Core-0 instrCnt = 22484, cycleCnt = 49996, IPC = 0.449716
Seed=0 Guest cycle spent: 50001 (this will be different from cycleCnt if emu loads a snapshot)
Host time spent: 379910ms
```

## 6. 速度

本轮测速使用 `emu` 日志中的 host time 计算，不是单独的 `perf stat` 采样。

```text
Guest cycle spent: 50001
Host time spent: 379910ms
Throughput: 131.61 cycles/s
```

和 [`NO0059`](./NO0059_merge_reg_all_strategies_coremark_50k_20260503.md) 的全策略 run 对比：

```text
NO0059 Host time spent: 378542ms
NO0065 Host time spent: 379910ms
delta: +1368ms, about +0.36%
```

在 50k bounded run 口径下，删除低收益策略后，runtime 速度基本持平。

## 7. 结论

- 当前两策略 `merge-reg` 版本可以完整完成 XiangShan `grhsim` fresh emit、emu build 和 `coremark` 50k bounded run。
- 运行结果跑满 `50000` cycle，退出码为 `0`，没有发现 assertion、DiffTest mismatch 或 crash。
- 本轮速度为 `131.61 cycles/s`，与全策略版本的 `50k` 运行速度基本持平。
- 从构建日志看，`merge-reg` 当前只报告 `scalar-to-memory,indexed-bundle-entry-to-wide-register`，符合本轮“只保留两个有效策略”的预期。
