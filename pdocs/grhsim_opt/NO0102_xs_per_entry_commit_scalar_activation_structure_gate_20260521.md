# NO0102: XS Per-Entry Commit Scalar Activation 结构验收

Date: 2026-05-21

## 背景

`NO0100` 实现了默认关闭的 per-entry commit scalar activation table 候选，目标是替换 hot commit batch 中大量重复的 inline scalar register write activation block。`NO0101` 已确认小测试会输出诊断字段。

本轮只做 XiangShan fresh emit 结构验收，不做 build/runtime。fresh emit 的原因是需要验证新的 emitter codegen 选项；旧 no0162 产物不包含该路径。

## 命令口径

```sh
mkdir -p tmp/no0102_xs_per_entry_commit_scalar_diag

WOLVRIX_GRHSIM_DIAG_COMMIT_SCALAR_TABLE=1 \
WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1 \
WOLVRIX_XS_GRHSIM_POST_STATS_JSON=/home/gaoruihao/wksp/wolvrix-playground/build/xs/grhsim/wolvrix_xs_post_stats.json \
WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE=108 \
WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE=4096 \
WOLVRIX_XS_GRHSIM_SCHED_BATCH_MAX_OPS=2048 \
WOLVRIX_XS_GRHSIM_SCHED_BATCH_MAX_ESTIMATED_LINES=8192 \
WOLVRIX_XS_GRHSIM_SCHED_BATCH_TARGET_COUNT=800 \
WOLVRIX_XS_GRHSIM_EMIT_PARALLELISM=8 \
WOLVRIX_XS_GRHSIM_EMIT_FULL_WORD_BITWISE=1 \
WOLVRIX_XS_GRHSIM_EMIT_PER_ENTRY_COMMIT_SCALAR_ACTIVATIONS=1 \
python3 scripts/wolvrix_xs_grhsim.py dummy.f SimTop \
  tmp/no0102_xs_per_entry_commit_scalar_diag/grhsim_emit "" "" info \
  --waveform off --perf off \
  > tmp/no0102_xs_per_entry_commit_scalar_diag/emit.log 2>&1
```

## 结果

Activity schedule 与 emit 完成：

```text
activity-schedule supernode stats supernodes=76227 compute_supernodes=75712 commit_supernodes=515 dag_edges=1112974 boundary_values=1362332 boundary_activation_edges=2534237 ... ops_mean=90.858 ops_median=99 ops_p90=108 ops_p99=108 ops_max=4096 outdeg_mean=14.601 outdeg_p99=171 outdeg_max=15768
pass activity-schedule done 411977ms
write_grhsim_cpp done 78698ms
total done 512162ms
```

生成产物：

```text
1.7G  tmp/no0102_xs_per_entry_commit_scalar_diag/grhsim_emit
972   grhsim_SimTop_sched_*.cpp
```

Commit scalar table 诊断：

```text
commit-scalar-table candidates=188024823 accepted=188017176 reject_memory=5057 reject_wide=2561 reject_next_slot=29 table_runs=763 table_writes=283374 per_entry_runs=757 per_entry_writes=283301 per_entry_activation_entries=611206
```

结构命中计数：

```text
108   sched cpp files contain PerEntryActivations
1514  PerEntryActivations declarations
762   apply_commit_scalar_state_write_table calls
7157  remaining inline "Commit writes update visible state directly" blocks
```

代表性片段 `grhsim_SimTop_sched_951.cpp`：

```cpp
static constexpr grhsim_active_mask_entry kCommitScalarWrites_75761_0PerEntryActivations[] = {
    ...
};
apply_commit_scalar_state_write_table(kCommitScalarWrites_75761_0, 50u, kCommitScalarWrites_75761_0PerEntryActivations, SIZE_MAX, 9351u, activeWordFlags);
```

另一个较大命中样本 `grhsim_SimTop_sched_935.cpp` 中出现：

```text
PerEntryActivations declaration
apply_commit_scalar_state_write_table(..., 402u, ..., SIZE_MAX, ...)
```

但该文件后续仍有 inline `Commit writes update visible state directly` block，说明 per-entry table 覆盖了大 run，但没有消除全部直接 commit write 路径。

## 判定

结构 gate 通过：

- `per_entry_writes=283301`，覆盖了几乎全部 table writes；
- `per_entry_activation_entries=611206`，说明 per-entry activation mask 不是退化为 common/union activation；
- 代表性 sched 文件已经生成 `PerEntryActivations` 与 `SIZE_MAX` helper 调用；
- 生成规模没有异常失控，仍在约 `1.7G` C++ 源码级别。

但这还不是 runtime 收益结论：

- 仍有 `7157` 个 inline commit write block；
- 新 table helper 可能降低 branch density，也可能增加 table load 与 loop overhead；
- 当前只验证 generated-code shape，没有编译、反汇编、perf 或 difftest runtime 数据。

## 下一步

可以进入下一篇独立文档做 build + 带 difftest runtime：

- 使用本轮已生成的 `tmp/no0102_xs_per_entry_commit_scalar_diag/grhsim_emit`，不要再次 fresh emit；
- build 后先看 compile wall time 与热点 object；
- 跑 CoreMark 20k/50k，runtime 必须带 difftest；
- 如果 runtime 无收益，再对比 hot commit batch 反汇编中的 branch/load/store 变化，判断 table loop 是否抵消了 inline block 收益。

本轮结束后检查进程，无 `wolvrix_xs_grhsim.py`、`clang++`、`make`、`perf record`、`grhsim-compile/emu` 遗留进程。
