# NO0014 Persistent Wide BitInt Storage 50k Alignment（2026-04-20）

> 归档编号：`NO0014`。目录顺序见 [`README.md`](./README.md)。

这份记录固化“把 `persistent wide value/state` 切到 `_BitInt` 存储”之后的 `XiangShan coremark` `50000-cycle` 对齐复测结果。目标不是重新做一轮功能 bring-up，而是验证这个结构性试验是否真的回收了上一轮 `_BitInt` emitter 修改里的部分性能回退。

## 数据来源

- 本次运行日志：
  - `build/logs/xs/xs_wolf_grhsim_20260420_codex_bitint_storage_50k.log`
- 直接对比对象：
  - [`NO0011 当前 GrhSIM XiangShan CoreMark 50k Runtime Snapshot`](./NO0011_current_grhsim_xiangshan_coremark_50k_runtime_snapshot_20260420.md)
  - [`NO0013 当前 GrhSIM XiangShan CoreMark 50k Aligned Rerun`](./NO0013_current_grhsim_xiangshan_coremark_50k_aligned_rerun_20260420.md)

## 1. 运行命令

```bash
make -j2 run_xs_wolf_grhsim_emu RUN_ID=20260420_codex_bitint_storage_50k XS_SIM_MAX_CYCLE=50000 XS_COMMIT_TRACE=0 XS_PROGRESS_EVERY_CYCLES=5000
```

本次运行口径：

- workload：`coremark-2-iteration.bin`
- runtime 上限：`50000 cycles`
- `commit trace`：关闭
- 进度打印间隔：`5000 cycles`
- 变更点：宽 `persistent value` 与 `non-memory state` 改为 `_BitInt` 存储，减少 `words <-> bitint` 边界往返

## 2. 最终结果

本次运行正常推进到 cycle limit，并以 `EXCEEDING CYCLE/INSTR LIMIT` 结束，没有出现 crash、assert 或 diff mismatch。

最终日志摘要：

- `instrCnt = 73580`
- `cycleCnt = 49996`
- `IPC = 1.471718`
- `Guest cycle spent = 50001`
- `Host time spent = 748748 ms`

因此本轮试验的功能结论是：

- `50k` 功能口径仍与 `NO0011 / NO0013` 对齐
- 宽值持久化表示切到 `_BitInt` 没有引入新的功能回退

## 3. 当前运行速度

按本次 `0 -> 50000 cycles` 窗口折算：

| 指标 | 数值 |
| --- | ---: |
| simulated cycles | `50000` |
| guest instructions | `73580` |
| host wall time | `748.748 s` |
| host simulation speed | `66.78 cycles/s` |
| host instruction throughput | `98.27 instr/s` |

和上一版 `_BitInt` emitter 复测 [`NO0013`](./NO0013_current_grhsim_xiangshan_coremark_50k_aligned_rerun_20260420.md) 相比：

- `Host time`：`781.443 s -> 748.748 s`，改善约 `4.18%`
- `cycles/s`：`63.98 -> 66.78`，提升约 `4.37%`
- `instr/s`：`94.16 -> 98.27`，提升约 `4.37%`

但和旧基线 [`NO0011`](./NO0011_current_grhsim_xiangshan_coremark_50k_runtime_snapshot_20260420.md) 相比：

- `Host time` 仍高约 `33.53%`
- `cycles/s` 仍低约 `25.11%`

所以这轮试验的结论不是“性能恢复”，而是“回收了一部分回退”。

## 4. 分段推进情况

从日志中的 `EMU_PROGRESS` 可抽出以下进度点：

| model cycles | instr | host ms |
| --- | ---: | ---: |
| `5000` | `3` | `24333` |
| `10000` | `458` | `59042` |
| `15000` | `5532` | `136592` |
| `20000` | `14121` | `231287` |
| `25000` | `20048` | `314109` |
| `30000` | `27809` | `405209` |
| `35000` | `35570` | `478590` |
| `40000` | `43350` | `547771` |
| `45000` | `52481` | `640337` |
| `50000` | `73580` | `748723` |

对应分段速度：

| 区间 | cycles/s | instr/s |
| --- | ---: | ---: |
| `10000 -> 15000` | `64.47` | `65.43` |
| `15000 -> 20000` | `52.80` | `90.70` |
| `20000 -> 25000` | `60.37` | `71.56` |
| `25000 -> 30000` | `54.88` | `85.19` |
| `30000 -> 35000` | `68.14` | `105.76` |
| `35000 -> 40000` | `72.27` | `112.46` |
| `40000 -> 45000` | `54.02` | `98.64` |
| `45000 -> 50000` | `46.13` | `194.67` |

从这些数字可以读出两点：

- 早期 `5k ~ 15k` 确实比 `NO0013` 更快，说明边界转换税被部分回收
- 中后段虽然也有改善，但没有恢复到 `NO0011` 的水平，说明剩余瓶颈不只在 persistent 宽值的 `words <-> bitint` 往返

## 5. 本轮试验应记住的事实

如果只保留一组结论，应当记住：

- `persistent wide value/state -> _BitInt` 这条方向是对的
- 它让 `50k` 总时间从 `781.443 s` 降到 `748.748 s`
- 但当前版本仍明显慢于 `NO0011` 的 `560.738 s`

因此更准确的判断是：

- `boundary conversion cost is real`
- `but it is not the only dominant bottleneck`
