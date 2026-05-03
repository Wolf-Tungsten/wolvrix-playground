# NO0059 `merge-reg` All Strategies CoreMark 50k Snapshot

## 1. 目的

参考 [`NO0053`](./NO0053_merge_reg_scalar_to_memory_only_coremark_50k_20260502.md) 的测试口径，记录一次从清理产物开始、完全走 Makefile 标准流程的 XiangShan `grhsim` 构建和运行结果。

本轮验证的开关组合：

- `merge-reg` pass 开启全部策略
- 构建 `grhsim` emu 后运行 XiangShan `coremark` bounded 50k cycle
- 重点确认全部策略同时开启时，是否还能通过 50k cycle 口径

## 2. 执行流程

先清理 XS 相关差分 / `grhsim` 产物：

```bash
make xs_diff_clean
```

然后使用标准 Makefile 目标重新 emit 并构建 `grhsim` emu，显式打开全部 `merge-reg` 策略：

```bash
make xs_wolf_grhsim_emu \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_SCALAR_TO_MEMORY=1 \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_BUNDLE_SHIFT_PIPELINE_TO_WIDE_REGISTER=1 \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_INDEXED_BUNDLE_ENTRY_TO_WIDE_REGISTER=1 \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_ONEHOT_INDEXED_BANK_TO_WIDE_REGISTER=1 \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_BITSET_TO_WIDE_REGISTER=1 \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_SHIFT_CHAIN_TO_WIDE_REGISTER=1
```

最后运行标准 `coremark` 入口，限制最大周期为 `50000`：

```bash
make run_xs_wolf_grhsim_emu XS_SIM_MAX_CYCLE=50000 \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_SCALAR_TO_MEMORY=1 \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_BUNDLE_SHIFT_PIPELINE_TO_WIDE_REGISTER=1 \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_INDEXED_BUNDLE_ENTRY_TO_WIDE_REGISTER=1 \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_ONEHOT_INDEXED_BANK_TO_WIDE_REGISTER=1 \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_BITSET_TO_WIDE_REGISTER=1 \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_SHIFT_CHAIN_TO_WIDE_REGISTER=1
```

## 3. 构建结果

`xs_wolf_grhsim_emit` 成功，退出码为 `0`。

`emu` 成功链接，产物路径：

```text
build/xs/grhsim/grhsim-compile/emu
```

产物大小：

```text
164M
```

构建日志：

```text
build/logs/xs/xs_wolf_grhsim_build_20260503_092021.log
```

`merge-reg` 日志确认本轮启用了全部策略：

```text
merge-reg: merge-reg: graphs=1 candidate_clusters=2171 candidate_members=38329 bundle_pipeline_clusters=81 bundle_pipeline_members=3986 indexed_bundle_entry_clusters=7896 indexed_bundle_entry_members=108549 rewritten_clusters=10202 rewritten_members=114224 scalar_to_memory_changed=true strategies=scalar-to-memory,bundle-shift-pipeline-to-wide-register,indexed-bundle-entry-to-wide-register,onehot-indexed-bank-to-wide-register,bitset-to-wide-register,shift-chain-to-wide-register
```

关键点：

- `strategies=scalar-to-memory,bundle-shift-pipeline-to-wide-register,indexed-bundle-entry-to-wide-register,onehot-indexed-bank-to-wide-register,bitset-to-wide-register,shift-chain-to-wide-register`
- `scalar_to_memory_changed=true`
- `bundle_pipeline_clusters=81`
- `indexed_bundle_entry_clusters=7896`
- `rewritten_clusters=10202`
- `rewritten_members=114224`

调度结果：

```text
activity-schedule: activity-schedule: path=SimTop graph=SimTop supernodes=76474 seed_supernodes=4527672 coarse_supernodes=77024 dp_supernodes=76474 sink_supernodes=5716 sink_ops=122293 eligible_ops=4757291 state_read_tail_absorb_target_supernodes=77732 state_read_tail_absorb_cloned=160616 state_read_tail_absorb_erased=47574 replication_cloned=0 replication_erased=0 state_read_sets=119022 graph_changed=true
```

emit 侧耗时摘要：

```text
write_grhsim_cpp done 35541ms
total done 1138484ms
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
build/logs/xs/xs_wolf_grhsim_20260503_094331.log
```

## 5. 运行结果

运行跑满 `50000` cycle，以 cycle limit 正常结束，没有出现 RTL assertion、DiffTest mismatch 或 crash。

日志尾部：

```text
[CYCLE_LIMIT] cycles=50000 max_cycles=50000
Core 0: EXCEEDING CYCLE/INSTR LIMIT at pc = 0x8000042c
Core-0 instrCnt = 22484, cycleCnt = 49996, IPC = 0.449716
Seed=0 Guest cycle spent: 50001 (this will be different from cycleCnt if emu loads a snapshot)
Host time spent: 378542ms
```

过程中周期进度：

```text
[CYCLE_LIMIT] cycles=10000 max_cycles=50000
[CYCLE_LIMIT] cycles=20000 max_cycles=50000
[CYCLE_LIMIT] cycles=30000 max_cycles=50000
[CYCLE_LIMIT] cycles=40000 max_cycles=50000
[CYCLE_LIMIT] cycles=50000 max_cycles=50000
```

## 6. 结论

- 全部 `merge-reg` 策略同时开启后，XS `grhsim` 可以完整 emit 并编译出 `emu`。
- `coremark` 50k bounded run 可以跑满 `50000` cycle，并以 cycle limit 正常结束。
- 本轮没有复现 [`NO0053`](./NO0053_merge_reg_scalar_to_memory_only_coremark_50k_20260502.md) 中 `scalar-to-memory` only 在 `AheadBtbReplacer.sv:179`、`cycleCnt = 8687` 触发的 assertion。
- 全策略组合的实际改写规模为 `rewritten_clusters=10202`、`rewritten_members=114224`，明显大于单策略测试。
- 当前证据说明，在本次 2026-05-03 的 fresh clean/build/run 口径下，`merge-reg` 全策略组合可以通过 XiangShan `coremark` 50k。
