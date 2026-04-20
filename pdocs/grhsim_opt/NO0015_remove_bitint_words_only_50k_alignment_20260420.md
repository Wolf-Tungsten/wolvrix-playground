# NO0015 Remove BitInt Words-Only 50k Alignment（2026-04-20）

> 归档编号：`NO0015`。目录顺序见 [`README.md`](./README.md)。

这份记录固化“把 `grhsim-cpp` 宽值路径里的 `_BitInt` 完全去掉，统一回到 words-only 表示”之后的 `XiangShan coremark` `50000-cycle` 对齐复测结果。目标是验证一个更直接的问题：如果顶层 persistent value 不是 `_BitInt`，而宽运算又频繁在 `words <-> bitint` 间切换，那么彻底去掉 `_BitInt` 是否会更快。

## 数据来源

- 本次运行日志：
  - `build/logs/xs/xs_wolf_grhsim_20260420_codex_no_bitint_50k.log`
- 直接对比对象：
  - [`NO0011 当前 GrhSIM XiangShan CoreMark 50k Runtime Snapshot`](./NO0011_current_grhsim_xiangshan_coremark_50k_runtime_snapshot_20260420.md)
  - [`NO0013 当前 GrhSIM XiangShan CoreMark 50k Aligned Rerun`](./NO0013_current_grhsim_xiangshan_coremark_50k_aligned_rerun_20260420.md)
  - [`NO0014 Persistent Wide BitInt Storage 50k Alignment`](./NO0014_persistent_wide_bitint_storage_50k_alignment_20260420.md)

## 1. 运行命令

```bash
make -j2 run_xs_wolf_grhsim_emu RUN_ID=20260420_codex_no_bitint_50k XS_SIM_MAX_CYCLE=50000 XS_COMMIT_TRACE=0 XS_PROGRESS_EVERY_CYCLES=5000
```

本次运行口径：

- workload：`coremark-2-iteration.bin`
- runtime 上限：`50000 cycles`
- `commit trace`：关闭
- 进度打印间隔：`5000 cycles`
- 变更点：移除宽值 `_BitInt` lowering / runtime / persistent storage，统一回到 `std::array<std::uint64_t, N>` words helper 路线

## 2. 最终结果

本次运行正常推进到 cycle limit，并以 `EXCEEDING CYCLE/INSTR LIMIT` 结束，没有出现 crash、assert 或 diff mismatch。

最终日志摘要：

- `instrCnt = 73580`
- `cycleCnt = 49996`
- `IPC = 1.471718`
- `Guest cycle spent = 50001`
- `Host time spent = 730523 ms`

因此本轮试验的功能结论是：

- `50k` 功能口径仍与 `NO0011 / NO0013 / NO0014` 对齐
- 把 `_BitInt` 完全移除没有带来功能回退

## 3. 当前运行速度

按本次 `0 -> 50000 cycles` 窗口折算：

| 指标 | 数值 |
| --- | ---: |
| simulated cycles | `50000` |
| guest instructions | `73580` |
| host wall time | `730.523 s` |
| host simulation speed | `68.44 cycles/s` |
| host instruction throughput | `100.72 instr/s` |

和上一版“persistent 宽值 `_BitInt` 存储”试验 [`NO0014`](./NO0014_persistent_wide_bitint_storage_50k_alignment_20260420.md) 相比：

- `Host time`：`748.748 s -> 730.523 s`，改善约 `2.43%`
- `cycles/s`：`66.77 -> 68.44`，提升约 `2.49%`
- `instr/s`：`98.27 -> 100.72`，提升约 `2.49%`

和 `_BitInt` emitter 复测 [`NO0013`](./NO0013_current_grhsim_xiangshan_coremark_50k_aligned_rerun_20260420.md) 相比：

- `Host time`：`781.443 s -> 730.523 s`，改善约 `6.52%`
- `cycles/s`：`63.98 -> 68.44`，提升约 `6.97%`

但和旧基线 [`NO0011`](./NO0011_current_grhsim_xiangshan_coremark_50k_runtime_snapshot_20260420.md) 相比：

- `Host time` 仍高约 `30.28%`
- `cycles/s` 仍低约 `23.24%`

所以这轮试验的结论不是“完全恢复”，而是：

- 相比当前两版 `_BitInt` 路线，纯 words-only 更快
- 但它仍没有回到 `NO0011` 的老基线

## 4. 分段推进情况

从日志中的 `EMU_PROGRESS` 可抽出以下进度点：

| model cycles | instr | host ms |
| --- | ---: | ---: |
| `5000` | `3` | `24316` |
| `10000` | `458` | `55733` |
| `15000` | `5532` | `132735` |
| `20000` | `14121` | `196918` |
| `25000` | `20048` | `261251` |
| `30000` | `27809` | `351471` |
| `35000` | `35570` | `441549` |
| `40000` | `43350` | `529226` |
| `45000` | `52481` | `621946` |
| `50000` | `73580` | `730498` |

对应分段速度：

| 区间 | cycles/s | instr/s |
| --- | ---: | ---: |
| `5000 -> 10000` | `159.15` | `14.48` |
| `10000 -> 15000` | `64.93` | `65.89` |
| `15000 -> 20000` | `77.90` | `133.82` |
| `20000 -> 25000` | `77.72` | `92.13` |
| `25000 -> 30000` | `55.42` | `86.02` |
| `30000 -> 35000` | `55.51` | `86.16` |
| `35000 -> 40000` | `57.03` | `88.73` |
| `40000 -> 45000` | `53.93` | `98.48` |
| `45000 -> 50000` | `46.06` | `194.37` |

从这些数字可以读出两点：

- 纯 words-only 路线在总时间上确实优于 `NO0013 / NO0014`
- 但中后段仍长期落在 `46 ~ 78 cycles/s`，说明真正的剩余瓶颈不只是一层 `_BitInt` 转换税

## 5. 本轮试验应记住的事实

如果只保留一组结论，应当记住：

- “persistent value 不是 `_BitInt`，反复转换有税”这个判断是成立的
- 但进一步实验显示，更直接的答案不是“把顶层也都改成 `_BitInt`”，而是“把整条宽值路径都收敛到 words-only”
- words-only 版本把 `50k` 总时间压到了 `730.523 s`
- 它比 `NO0014` 再快约 `2.43%`
- 但仍明显慢于 `NO0011` 的 `560.738 s`

因此这轮试验支持的方向是：

- `_BitInt` 并不是当前 `grhsim-cpp` 宽值路径的最优终态
- 继续优化时应优先围绕 pure words helper、减少 helper 间中间对象、继续查剩余热点
