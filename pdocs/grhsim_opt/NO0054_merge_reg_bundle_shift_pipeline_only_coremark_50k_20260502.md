# NO0054 `merge-reg` Bundle-Shift-Pipeline Only CoreMark 50k Snapshot

## 1. 目的

记录一次从清理产物开始、完全走 Makefile 标准流程的 XiangShan `grhsim` 构建和运行结果。

本轮只验证一个开关组合：

- `merge-reg` pass 只开启 `enable_bundle_shift_pipeline_to_wide_register`
- 其它 `merge-reg` 策略全部关闭，包括 `enable_scalar_to_memory`
- 构建 `grhsim` emu 后运行 XiangShan `coremark` bounded 50k cycle

## 2. 执行流程

先清理 XS 相关差分 / `grhsim` 产物：

```bash
make xs_diff_clean
```

然后使用标准 Makefile 目标重新 emit 并构建 `grhsim` emu：

```bash
make xs_wolf_grhsim_emu RUN_ID=20260502_bundle_shift_only_fresh \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_SCALAR_TO_MEMORY=0 \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_BUNDLE_SHIFT_PIPELINE_TO_WIDE_REGISTER=1 \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_INDEXED_BUNDLE_ENTRY_TO_WIDE_REGISTER=0 \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_ONEHOT_INDEXED_BANK_TO_WIDE_REGISTER=0 \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_BITSET_TO_WIDE_REGISTER=0 \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_SHIFT_CHAIN_TO_WIDE_REGISTER=0
```

最后运行标准 `coremark` 入口，限制最大周期为 `50000`：

```bash
make run_xs_wolf_grhsim_emu RUN_ID=20260502_bundle_shift_only_fresh \
  XS_SIM_MAX_CYCLE=50000 \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_SCALAR_TO_MEMORY=0 \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_BUNDLE_SHIFT_PIPELINE_TO_WIDE_REGISTER=1 \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_INDEXED_BUNDLE_ENTRY_TO_WIDE_REGISTER=0 \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_ONEHOT_INDEXED_BANK_TO_WIDE_REGISTER=0 \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_BITSET_TO_WIDE_REGISTER=0 \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_SHIFT_CHAIN_TO_WIDE_REGISTER=0
```

## 3. 构建结果

`xs_wolf_grhsim_emit` 成功，退出码为 `0`。

`emu` 成功链接，产物路径：

```text
build/xs/grhsim/grhsim-compile/emu
```

构建日志：

```text
build/logs/xs/xs_wolf_grhsim_build_20260502_bundle_shift_only_fresh.log
```

`merge-reg` 日志确认本轮只启用了 `bundle-shift-pipeline-to-wide-register`：

```text
merge-reg: merge-reg: graphs=1 candidate_clusters=8355 candidate_members=93911 bundle_pipeline_clusters=81 bundle_pipeline_members=3986 indexed_bundle_entry_clusters=0 indexed_bundle_entry_members=0 rewritten_clusters=80 rewritten_members=3978 scalar_to_memory_changed=false strategies=bundle-shift-pipeline-to-wide-register
```

关键点：

- `strategies=bundle-shift-pipeline-to-wide-register`
- `scalar_to_memory_changed=false`
- `bundle_pipeline_clusters=81`
- `bundle_pipeline_members=3986`
- `rewritten_clusters=80`
- `rewritten_members=3978`
- `indexed_bundle_entry_clusters=0`

本轮 `activity-schedule` 关键规模：

```text
supernodes=77324 dag_edges=1060424 ops_mean=66.836 ops_median=70.0 ops_p90=79 ops_p99=144 ops_max=2317
```

## 4. 运行配置

运行目标：

```text
make run_xs_wolf_grhsim_emu
```

输入镜像：

```text
testcase/xiangshan/ready-to-run/coremark-2-iteration.bin
```

DiffTest 参考模型：

```text
testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so
```

最大仿真周期：

```text
XS_SIM_MAX_CYCLE=50000
```

运行日志：

```text
build/logs/xs/xs_wolf_grhsim_20260502_bundle_shift_only_fresh.log
```

## 5. 运行结果

运行跑满 `50000` cycle bound，并以 cycle / instruction limit 正常退出；Makefile 命令退出码为 `0`。

日志尾部：

```text
max cycles: 50000
The first instruction of core 0 has commited. Difftest enabled.
[CYCLE_LIMIT] cycles=10000 max_cycles=50000
[CYCLE_LIMIT] cycles=20000 max_cycles=50000
[CYCLE_LIMIT] cycles=30000 max_cycles=50000
[CYCLE_LIMIT] cycles=40000 max_cycles=50000
[CYCLE_LIMIT] cycles=50000 max_cycles=50000
Core 0: EXCEEDING CYCLE/INSTR LIMIT at pc = 0x80001312
Core-0 instrCnt = 73580, cycleCnt = 49996, IPC = 1.471718
Seed=0 Guest cycle spent: 50001
Host time spent: 540478ms
```

没有出现 RTL assertion、`ABORT` 或 DiffTest mismatch。

## 6. 结论

- 只启用 `merge-reg` 的 `bundle-shift-pipeline-to-wide-register` 策略后，XS `grhsim` 可以完整 emit 并编译出 `emu`。
- `coremark` 50k bounded run 可以跑满 `50000` cycle，并以 cycle limit 正常结束。
- 和 [`NO0053`](./NO0053_merge_reg_scalar_to_memory_only_coremark_50k_20260502.md) 相比，本轮没有在 `AheadBtbReplacer.sv:179`、`cycleCnt = 8687` 触发 assertion。
- 当前证据说明 `bundle-shift-pipeline-to-wide-register` 单独开启在本轮 50k 口径下可通过；`scalar-to-memory` 单独开启仍是更可疑的运行时语义问题来源。
