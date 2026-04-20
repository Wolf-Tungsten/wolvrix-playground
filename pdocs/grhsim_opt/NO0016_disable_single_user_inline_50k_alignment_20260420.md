# NO0016 Disable Single-User Inline 50k Alignment（2026-04-20）

> 归档编号：`NO0016`。目录顺序见 [`README.md`](./README.md)。

这份记录固化“只关闭 single-user supernode local 表达式内联，恢复显式 `local_value_` 临时量，同时保持当前 words-only 宽值路径不变”之后的 `XiangShan coremark` `50000-cycle` 对齐复测结果。目标是隔离验证一个更具体的问题：当前剩余性能差距，是否主要由表达式内联导致。

## 数据来源

- 本次运行日志：
  - `build/logs/xs/xs_wolf_grhsim_20260420_codex_no_inline_50k.log`
- 直接对比对象：
  - [`NO0011 当前 GrhSIM XiangShan CoreMark 50k Runtime Snapshot`](./NO0011_current_grhsim_xiangshan_coremark_50k_runtime_snapshot_20260420.md)
  - [`NO0013 当前 GrhSIM XiangShan CoreMark 50k Aligned Rerun`](./NO0013_current_grhsim_xiangshan_coremark_50k_aligned_rerun_20260420.md)
  - [`NO0015 Remove BitInt Words-Only 50k Alignment`](./NO0015_remove_bitint_words_only_50k_alignment_20260420.md)

## 1. 运行命令

```bash
make -j2 run_xs_wolf_grhsim_emu RUN_ID=20260420_codex_no_inline_50k XS_SIM_MAX_CYCLE=50000 XS_COMMIT_TRACE=0 XS_PROGRESS_EVERY_CYCLES=5000
```

本次运行口径：

- workload：`coremark-2-iteration.bin`
- runtime 上限：`50000 cycles`
- `commit trace`：关闭
- 进度打印间隔：`5000 cycles`
- 唯一变更点：关闭 single-user supernode local 内联，恢复显式 `local_value_` 临时量

## 2. 最终结果

本次运行正常推进到 cycle limit，并以 `EXCEEDING CYCLE/INSTR LIMIT` 结束，没有出现 crash、assert 或 diff mismatch。

最终日志摘要：

- `instrCnt = 73580`
- `cycleCnt = 49996`
- `IPC = 1.471718`
- `Guest cycle spent = 50001`
- `Host time spent = 767220 ms`

因此本轮试验的功能结论是：

- 关闭单用户内联后，`50k` 功能口径仍与 `NO0011 / NO0013 / NO0015` 对齐
- 恢复显式 `local_value_` 没有带来功能回退，但带来了明显 runtime 回退

## 3. 当前运行速度

按本次 `0 -> 50000 cycles` 窗口折算：

| 指标 | 数值 |
| --- | ---: |
| simulated cycles | `50000` |
| guest instructions | `73580` |
| host wall time | `767.220 s` |
| host simulation speed | `65.17 cycles/s` |
| host instruction throughput | `95.90 instr/s` |

和当前 words-only + single-user inline 版本 [`NO0015`](./NO0015_remove_bitint_words_only_50k_alignment_20260420.md) 相比：

- `Host time`：`730.523 s -> 767.220 s`，变慢约 `5.02%`
- `cycles/s`：`68.44 -> 65.17`，下降约 `4.78%`
- `instr/s`：`100.72 -> 95.90`，下降约 `4.79%`

和 `_BitInt` emitter 复测 [`NO0013`](./NO0013_current_grhsim_xiangshan_coremark_50k_aligned_rerun_20260420.md) 相比：

- `Host time`：`781.443 s -> 767.220 s`，仍快约 `1.82%`
- `cycles/s`：`63.98 -> 65.17`，仍高约 `1.86%`

但和旧基线 [`NO0011`](./NO0011_current_grhsim_xiangshan_coremark_50k_runtime_snapshot_20260420.md) 相比：

- `Host time` 仍高约 `36.82%`
- `cycles/s` 仍低约 `26.91%`

所以这轮试验给出的直接结论是：

- 单用户表达式内联不是当前 words-only 路线的负优化来源
- 把它关掉以后，性能反而进一步变差

## 4. 分段推进情况

从日志中的 `EMU_PROGRESS` 可抽出以下进度点：

| model cycles | instr | host ms |
| --- | ---: | ---: |
| `5000` | `3` | `24204` |
| `10000` | `458` | `52397` |
| `15000` | `5532` | `123782` |
| `20000` | `14121` | `207722` |
| `25000` | `20048` | `296291` |
| `30000` | `27809` | `387711` |
| `35000` | `35570` | `479091` |
| `40000` | `43350` | `570636` |
| `45000` | `52481` | `661038` |
| `50000` | `73580` | `767195` |

对应分段速度：

| 区间 | cycles/s | instr/s |
| --- | ---: | ---: |
| `5000 -> 10000` | `177.35` | `16.14` |
| `10000 -> 15000` | `70.04` | `71.08` |
| `15000 -> 20000` | `59.57` | `102.32` |
| `20000 -> 25000` | `56.45` | `66.92` |
| `25000 -> 30000` | `54.69` | `84.89` |
| `30000 -> 35000` | `54.72` | `84.93` |
| `35000 -> 40000` | `54.62` | `84.99` |
| `40000 -> 45000` | `55.31` | `101.00` |
| `45000 -> 50000` | `47.10` | `198.75` |

和 `NO0015` 对照时，可以读出更细的趋势：

- very-early boot 阶段，关闭内联一度看起来更快
- 但从 `20000-cycle` 左右开始就稳定落后于 `NO0015`
- 中后段整体长期停留在 `47 ~ 56 cycles/s`，比 `NO0015` 的同区间更慢

这说明：

- 显式 `local_value_` 临时量引入的额外局部对象与拷贝/传递成本，已经足以抵消 early 阶段的微小优势
- 当前 remaining gap 不能归因到“表达式内联”本身

## 5. 本轮试验应记住的事实

如果只保留一组结论，应当记住：

- 先前“可能是表达式内联导致负优化”的怀疑，在这轮隔离实验下不成立
- 在 pure words-only 宽值路径上，保留 single-user supernode local 内联更快
- 关闭内联并恢复显式 `local_value_` 后，`50k` 总时间从 `730.523 s` 回退到 `767.220 s`
- 因此当前应继续把注意力放在其他 remaining hotspots，而不是回退这条内联策略

因此这轮试验支持的方向是：

- 保持 single-user local inline
- 继续围绕 words helper、表达式形状、临时对象数量和中后段热点做优化
