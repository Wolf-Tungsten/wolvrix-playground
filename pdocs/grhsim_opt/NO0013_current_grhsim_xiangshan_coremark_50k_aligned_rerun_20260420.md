# NO0013 当前 GrhSIM XiangShan CoreMark 50k Aligned Rerun（2026-04-20）

> 归档编号：`NO0013`。目录顺序见 [`README.md`](./README.md)。

这份记录用于补齐最近一轮 `grhsim` emitter 调整之后的 `50000-cycle` 对齐复测。它的目的不是新增 workload，而是严格沿用 [`NO0011`](./NO0011_current_grhsim_xiangshan_coremark_50k_runtime_snapshot_20260420.md) 的 `50k-cycle` 观测口径，判断最近 `supernode` 内联和宽值 `bitint` 生成策略修改之后，`XiangShan coremark` 的功能与性能是否仍和旧结论一致。

## 数据来源

- 本次运行日志：
  - `build/logs/xs/xs_wolf_grhsim_20260420_codex_50k.log`
- 对齐基线：
  - [`NO0011 当前 GrhSIM XiangShan CoreMark 50k Runtime Snapshot`](./NO0011_current_grhsim_xiangshan_coremark_50k_runtime_snapshot_20260420.md)
- 相关 smoke 快照：
  - [`NO0012 当前 GrhSIM XiangShan CoreMark 30k Smoke Runtime Snapshot`](./NO0012_current_grhsim_xiangshan_coremark_30k_smoke_runtime_snapshot_20260420.md)

## 1. 运行命令

```bash
make -j2 run_xs_wolf_grhsim_emu RUN_ID=20260420_codex_50k XS_SIM_MAX_CYCLE=50000 XS_COMMIT_TRACE=0 XS_PROGRESS_EVERY_CYCLES=5000
```

本次运行口径：

- workload：`coremark-2-iteration.bin`
- runtime 上限：`50000 cycles`
- `commit trace`：关闭
- 进度打印间隔：`5000 cycles`
- 目的：与 `NO0011` 的 `50k-cycle` 结论做同口径对齐复测

## 2. 最终结果

本次运行正常推进到 cycle limit，并以 `EXCEEDING CYCLE/INSTR LIMIT` 结束，没有出现 diff mismatch、assert 或 crash。

最终日志摘要：

- `instrCnt = 73580`
- `cycleCnt = 49996`
- `IPC = 1.471718`
- `Guest cycle spent = 50001`
- `Host time spent = 781443 ms`

对应日志末尾可见：

- `Core 0: EXCEEDING CYCLE/INSTR LIMIT at pc = 0x80001312`
- `Core-0 instrCnt = 73580, cycleCnt = 49996, IPC = 1.471718`
- `Host time spent: 781443ms`

同时日志中仍可看到：

- `The first instruction of core 0 has commited. Difftest enabled.`
- `Running CoreMark for 2 iterations`

因此这轮复测的功能结论是：

- 最近 emitter 修改后，`grhsim` 仍然可以稳定跑到 `50000 cycles`
- guest 执行轨迹在 `50k` 窗口内仍能推进到与 `NO0011` 相同的 `instrCnt / cycleCnt`

## 3. 当前运行速度

按本次 `0 -> 50000 cycles` 窗口直接折算：

| 指标 | 数值 |
| --- | ---: |
| simulated cycles | `50000` |
| guest instructions | `73580` |
| host wall time | `781.443 s` |
| host simulation speed | `63.98 cycles/s` |
| host instruction throughput | `94.16 instr/s` |

这说明：

- 功能上，本次复测与 `NO0011` 对齐
- 性能上，当前版本显著慢于 `NO0011`

## 4. 分段推进情况

从日志中的 `EMU_PROGRESS` 可直接抽出以下进度点：

| model cycles | instr | host ms |
| --- | ---: | ---: |
| `5000` | `3` | `34310` |
| `10000` | `458` | `72460` |
| `15000` | `5532` | `148883` |
| `20000` | `14121` | `234000` |
| `25000` | `20048` | `321461` |
| `30000` | `27809` | `411562` |
| `35000` | `35570` | `501293` |
| `40000` | `43350` | `591433` |
| `45000` | `52481` | `683507` |
| `50000` | `73580` | `781418` |

对应的分段速度：

| 区间 | cycles/s | instr/s |
| --- | ---: | ---: |
| `10000 -> 15000` | `65.43` | `66.39` |
| `15000 -> 20000` | `58.74` | `100.91` |
| `20000 -> 25000` | `57.17` | `67.77` |
| `25000 -> 30000` | `55.49` | `86.14` |
| `30000 -> 35000` | `55.72` | `86.49` |
| `35000 -> 40000` | `55.47` | `86.31` |
| `40000 -> 45000` | `54.30` | `99.17` |
| `45000 -> 50000` | `51.07` | `215.49` |

这说明：

- `5000 cycles` 和 `10000 cycles` 之前仍然有明显的 early boot 慢启动问题
- 中后段也没有恢复到 `NO0011` 的 `65 ~ 100 cycles/s` 区间，而是更多落在 `51 ~ 59 cycles/s`
- 最后一个区间 `instr/s` 明显抬升，说明 guest 指令密度在末段上升，但 host `cycles/s` 仍没有回升

## 5. 与 NO0011 的对齐结论

和 [`NO0011`](./NO0011_current_grhsim_xiangshan_coremark_50k_runtime_snapshot_20260420.md) 对比，当前版本的关键差异是：

| 指标 | `NO0011` | 本次 `NO0013` | 变化 |
| --- | ---: | ---: | ---: |
| simulated cycles | `50000` | `50000` | `0` |
| guest instructions | `73580` | `73580` | `0` |
| host wall time | `560.738 s` | `781.443 s` | `+39.36%` |
| host simulation speed | `89.17 cycles/s` | `63.98 cycles/s` | `-28.24%` |
| host instruction throughput | `131.22 instr/s` | `94.16 instr/s` | `-28.24%` |

因此应当把这轮复测的结论拆成两部分：

- 功能结论：对齐。最近 emitter 修改后，`grhsim` 仍能在 `50k-cycle` 口径下稳定推进到与 `NO0011` 相同的 `instrCnt / cycleCnt`。
- 性能结论：不对齐。当前版本相对 `NO0011` 明显变慢，`host time` 增加约 `39.36%`，整体吞吐下降约 `28.24%`。

## 6. 当前应记住的事实

如果只保留一组事实，应当记住：

- 最近 emitter 修改后的版本已经通过 `50000-cycle` XiangShan GrhSIM 对齐复测
- 功能没有在这次复测中出现明显回退
- 但性能相对 `NO0011` 有明确回退：
  - `560.738 s -> 781.443 s`
  - `89.17 cycles/s -> 63.98 cycles/s`

因此，当前版本的状态更准确地说是：

- `functional alignment preserved`
- `runtime performance regressed`
