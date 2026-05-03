# NO0053 `merge-reg` Scalar-to-Memory Only CoreMark 50k Snapshot

## 1. 目的

记录一次从清理产物开始、完全走 Makefile 标准流程的 XiangShan `grhsim` 构建和运行结果。

本轮只验证一个开关组合：

- `merge-reg` pass 只开启 `enable_scalar_to_memory`
- 其它 `merge-reg` 策略全部关闭
- 构建 `grhsim` emu 后运行 XiangShan `coremark` bounded 50k cycle

## 2. 执行流程

先清理 XS 相关差分 / `grhsim` 产物：

```bash
make xs_diff_clean
```

然后使用标准 Makefile 目标重新 emit 并构建 `grhsim` emu：

```bash
make xs_wolf_grhsim_emu \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_SCALAR_TO_MEMORY=1 \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_BUNDLE_SHIFT_PIPELINE_TO_WIDE_REGISTER=0 \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_INDEXED_BUNDLE_ENTRY_TO_WIDE_REGISTER=0 \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_ONEHOT_INDEXED_BANK_TO_WIDE_REGISTER=0 \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_BITSET_TO_WIDE_REGISTER=0 \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_SHIFT_CHAIN_TO_WIDE_REGISTER=0
```

最后运行标准 `coremark` 入口，限制最大周期为 `50000`：

```bash
make run_xs_wolf_grhsim_emu XS_SIM_MAX_CYCLE=50000 \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_SCALAR_TO_MEMORY=1 \
  WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_BUNDLE_SHIFT_PIPELINE_TO_WIDE_REGISTER=0 \
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
build/logs/xs/xs_wolf_grhsim_build_20260502_173744.log
```

`merge-reg` 日志确认本轮只启用了 `scalar-to-memory`：

```text
merge-reg: merge-reg: graphs=1 candidate_clusters=7541 candidate_members=85811 bundle_pipeline_clusters=0 bundle_pipeline_members=0 indexed_bundle_entry_clusters=0 indexed_bundle_entry_members=0 rewritten_clusters=0 rewritten_members=0 scalar_to_memory_changed=true strategies=scalar-to-memory
```

关键点：

- `strategies=scalar-to-memory`
- `scalar_to_memory_changed=true`
- `bundle_pipeline_clusters=0`
- `indexed_bundle_entry_clusters=0`
- `rewritten_clusters=0`
- `rewritten_members=0`

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
build/logs/xs/xs_wolf_grhsim_20260502_175913.log
```

## 5. 运行结果

运行没有跑满 `50000` cycle，而是在 `cycleCnt = 8687` 触发 RTL assertion 后停止。

日志尾部：

```text
max cycles: 50000
The first instruction of core 0 has commited. Difftest enabled.
Assertion failed at build/xs/rtl/rtl/AheadBtbReplacer.sv:179.
The simulation stopped. There might be some assertion failed.
Core 0: ABORT at pc = 0x0
Core-0 instrCnt = 167, cycleCnt = 8687, IPC = 0.019224
Seed=0 Guest cycle spent: 8691
Host time spent: 34512ms
```

失败点：

```text
build/xs/rtl/rtl/AheadBtbReplacer.sv:179
```

## 6. 结论

- 只启用 `merge-reg` 的 `scalar-to-memory` 策略后，XS `grhsim` 可以完整 emit 并编译出 `emu`。
- `coremark` 50k bounded run 没有跑满 `50000` cycle。
- 本轮失败点是 `AheadBtbReplacer.sv:179`，不是此前单线程 `grhsim` 早期排查记录中的 `MEFreeList.sv:2026`。
- 失败窗口推进到 `cycleCnt = 8687`、`instrCnt = 167`。
- 关闭其它 `merge-reg` 策略后，`scalar-to-memory` 单独开启仍然存在运行时语义问题，后续应优先围绕 `AheadBtbReplacer.sv:179` 做对拍和 cone 追踪。
