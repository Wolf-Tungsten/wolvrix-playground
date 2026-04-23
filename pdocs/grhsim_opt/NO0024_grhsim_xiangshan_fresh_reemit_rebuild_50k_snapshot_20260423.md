# NO0024 GrhSIM XiangShan Fresh Re-emit / Rebuild 50k Snapshot（2026-04-23）

> 归档编号：`NO0024`。目录顺序见 [`README.md`](./README.md)。

这份记录固化一次从空 `grhsim` 产物开始的 XiangShan `grhsim` fresh 流程：先清理旧的 `grhsim emit/compile` 目录，再重新 `emit grhsim xiangshan` 代码、重新构建 `emu`，最后运行 `coremark 50k`。

本轮结论先写在前面：

- fresh `emit -> build -> run` 全流程成功
- `build/xs/grhsim/emu` 已重新生成，不是沿用旧产物
- `coremark 50k` 正常跑到 `50000-cycle` 上限，没有 diff mismatch、没有 crash
- 本轮运行日志给出的速度约为 **`124.79 cycles/s`**
- 但本轮 runtime 中出现了意外的 `DIFFTEST_STATE` / `STORE_CHK` / `STORE_REC` 调试打印，因此这次速度值应先视为“当前 fresh 快照”，**不直接作为干净 perf baseline**

## 数据来源

- fresh build 日志：
  - `build/logs/xs/xs_wolf_grhsim_build_20260423_codex_reemit_build_50k.log`
- 50k 运行日志：
  - `build/logs/xs/xs_wolf_grhsim_20260423_codex_reemit_build_50k.log`
- 相关方案文档：
  - [`NO0023 GrhSIM Compute-Commit Two-Phase Eval Plan`](./NO0023_grhsim_compute_commit_two_phase_eval_plan_20260423.md)

## 1. 执行口径

本轮先执行 clean：

```bash
make --no-print-directory xs_diff_clean
```

然后重新生成并构建 `grhsim emu`：

```bash
make --no-print-directory xs_wolf_grhsim_emu \
  RUN_ID=20260423_codex_reemit_build_50k \
  WOLVRIX_GRHSIM_WAVEFORM=0
```

最后按 `50k` 口径运行：

```bash
make --no-print-directory run_xs_wolf_grhsim_emu \
  RUN_ID=20260423_codex_reemit_build_50k \
  XS_SIM_MAX_CYCLE=50000 \
  XS_COMMIT_TRACE=0 \
  XS_PROGRESS_EVERY_CYCLES=5000 \
  WOLVRIX_GRHSIM_WAVEFORM=0
```

这次流程的目的不是做局部增量编译，而是确认：

- 当前工作树里的 `grhsim` 修改能够重新完整 emit
- fresh 构建出的 `emu` 可以独立运行
- 在 `coremark 50k` 上至少满足功能正确与基本性能可用

## 2. Fresh Emit / Build 结果

### 2.1 emit 成功

`wolvrix_xs_grhsim.py` 整体执行成功，日志中的关键阶段如下：

| 阶段 | 耗时 |
| --- | ---: |
| `read_sv` | `87353 ms` |
| `xmr-resolve` | `142172 ms` |
| `simplify` | `272318 ms` |
| `activity-schedule` | `228204 ms` |
| `write_grhsim_cpp` | `294158 ms` |
| `total` | `1277306 ms` |

也就是：

- fresh `emit` 总耗时约 **`1277.3s`**，约 **`21.3 min`**
- 其中最重的几段仍然是 `simplify`、`activity-schedule` 和 `write_grhsim_cpp`

### 2.2 activity-schedule 快照

本轮 `activity-schedule` 的关键输出如下：

- `supernodes=76032`
- `sink_supernodes=81`
- `sink_ops=329686`
- `tail_ops=5133507`
- `ops_mean=74.513`
- `ops_p99=144`
- `ops_max=5725`

这说明当前 compute/commit 切分后的 schedule 已经稳定落地到新的 `grhsim_emit` 产物中。

### 2.3 emu 构建成功

build 日志最终到达：

```text
+ LD /workspace/gaoruihao-dev-gpu/wolvrix-playground/build/xs/grhsim/grhsim-compile/emu
```

并确认产物存在：

- `build/xs/grhsim/emu`

因此这次 50k 运行使用的是 fresh build 出来的新 `emu`，不是旧版遗留产物。

## 3. 50k 运行结果

### 3.1 功能结果

运行日志显示：

- 正常推进到 `50000` cycle
- 没有 diff mismatch
- 没有 assertion
- 没有 crash

结束信息为：

| 指标 | 数值 |
| --- | ---: |
| guest cycle spent | `50001` |
| cycleCnt | `49996` |
| instrCnt | `73580` |
| IPC | `1.471718` |
| host time spent | `400695 ms` |
| host simulation speed | **`124.79 cycles/s`** |

其中：

```text
cycles_per_s = 50001 / 400.695s = 124.785685
```

### 3.2 分段推进情况

日志里的进度点如下：

| model cycles | host ms |
| --- | ---: |
| `5000` | `11403` |
| `10000` | `26884` |
| `15000` | `62424` |
| `20000` | `105000` |
| `25000` | `149851` |
| `30000` | `201745` |
| `35000` | `245356` |
| `40000` | `283116` |
| `45000` | `334548` |
| `50000` | `400678` |

从功能角度看，整段运行是稳定的，没有出现中途卡死或异常退出。

## 4. 本轮结果的解释与 caveat

这次 fresh `50k` 运行虽然给出了约 `124.79 cycles/s` 的结果，但日志里同时出现了大量本不该在 perf run 中保留的调试输出，例如：

- `DIFFTEST_STATE`
- `COMMIT_TRACE`
- `STORE_CHK`
- `STORE_REC`

而本轮命令里显式设置了：

```bash
XS_COMMIT_TRACE=0
```

因此可以确认：

- 当前 binary 或 difftest 路径里仍有额外调试打印泄漏
- 这些打印会污染 runtime 测速
- 所以本轮数值更适合作为“fresh rebuild 后的可运行快照”，而不是严格对标历史文档的干净性能结论

也就是说，这次记录可以确认：

1. 新代码能够 fresh emit 并构建出可运行 `emu`
2. `coremark 50k` 功能仍然正确
3. 当前 runtime 大致处于可接受区间

但如果要做严格性能归档，下一步仍应先清掉这些意外调试打印，再复测一轮同口径 `50k`。

## 5. 结论

本轮 fresh 复测回答了两个核心问题：

- **是否真的重新构建并使用了新版 `grhsim emu`？**  
  是。`xs_diff_clean` 后重新 `emit -> build`，并成功生成新的 `build/xs/grhsim/emu`。

- **新版 `grhsim emu` 能否完成 XiangShan CoreMark 50k？**  
  能。它正常跑到 `50000-cycle` 上限，功能正确。

从归档角度，本轮应被视为：

- 一次 `NO0023` 相关修改之后的 fresh build / fresh run 可运行性确认
- 一份带调试打印污染的 `50k` runtime snapshot
- 后续“清理 runtime 调试打印后再做干净 perf 复测”的前置验证
