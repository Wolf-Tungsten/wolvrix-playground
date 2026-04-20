# NO0012 当前 GrhSIM XiangShan CoreMark 30k Smoke Runtime Snapshot（2026-04-20）

> 归档编号：`NO0012`。目录顺序见 [`README.md`](./README.md)。

这份记录单独固化最近一轮 `grhsim` emitter 调整之后，`XiangShan coremark` 在 `30000-cycle` 有界 smoke run 上的运行与性能特征。这里的目标不是 full run，而是确认当前版本在最近 `supernode` 内联和宽值 `bitint` 生成策略调整后，是否还能稳定推进，并给出一个可复用的 runtime 快照。

## 数据来源

- 本次运行日志：
  - `build/logs/xs/xs_wolf_grhsim_20260420_codex_smoke.log`
- 相关旧快照：
  - [`NO0011 当前 GrhSIM XiangShan CoreMark 50k Runtime Snapshot`](./NO0011_current_grhsim_xiangshan_coremark_50k_runtime_snapshot_20260420.md)
- 相关结构与运行背景：
  - [`NO0009 Activity-Schedule Topo 重构后性能与 Supernode 结构画像`](./NO0009_activity_schedule_topo_refactor_perf_and_supernode_profile_20260419.md)
  - [`NO0010 当前 GrhSIM Supernode 图结构相对 GSim 的差异`](./NO0010_current_grhsim_supernode_graph_vs_gsim_20260419.md)

## 1. 运行命令

```bash
make -j2 run_xs_wolf_grhsim_emu RUN_ID=20260420_codex_smoke XS_SIM_MAX_CYCLE=30000 XS_COMMIT_TRACE=0 XS_PROGRESS_EVERY_CYCLES=5000
```

本次运行口径：

- workload：`coremark-2-iteration.bin`
- runtime 上限：`30000 cycles`
- `commit trace`：关闭
- 进度打印间隔：`5000 cycles`
- 目的：作为最近 emitter 修改后的 bounded smoke run，而不是 CoreMark full completion

## 2. 最终结果

本次运行正常推进到 cycle limit，并以 `EXCEEDING CYCLE/INSTR LIMIT` 结束，没有出现 crash 或明显的功能性失败。

最终日志摘要：

- `instrCnt = 27809`
- `cycleCnt = 29996`
- `IPC = 0.927090`
- `Guest cycle spent = 30001`
- `Host time spent = 390847 ms`

对应日志末尾可见：

- `Core 0: EXCEEDING CYCLE/INSTR LIMIT at pc = 0x80000442`
- `Core-0 instrCnt = 27809, cycleCnt = 29996, IPC = 0.927090`
- `Host time spent: 390847ms`

另外，日志里可以看到：

- `The first instruction of core 0 has commited. Difftest enabled.`
- `Running CoreMark for 2 iterations`

这说明当前版本已经跨过 very-early boot，并进入了 CoreMark 主体执行区间。

## 3. 当前运行速度

按本次 `0 -> 30000 cycles` 窗口直接折算：

| 指标 | 数值 |
| --- | ---: |
| simulated cycles | `30000` |
| guest instructions | `27809` |
| host wall time | `390.847 s` |
| host simulation speed | `76.76 cycles/s` |
| host instruction throughput | `71.15 instr/s` |

这组数字的含义是：

- 当前版本在最近 emitter 修改后仍能稳定推进到 `30000 cycles`
- runtime 速度仍然偏慢，整体仍处于两位数 `cycles/s` 量级
- 这是一份 smoke snapshot，不是 full-run CoreMark 完成速度

## 4. 分段推进情况

从日志中的 `EMU_PROGRESS` 可直接抽出以下进度点：

| model cycles | instr | host ms |
| --- | ---: | ---: |
| `5000` | `3` | `27139` |
| `10000` | `458` | `64695` |
| `15000` | `5532` | `141016` |
| `20000` | `14121` | `229312` |
| `25000` | `20048` | `305299` |
| `30000` | `27809` | `390833` |

对应的分段速度：

| 区间 | cycles/s | instr/s |
| --- | ---: | ---: |
| `5000 -> 10000` | `133.13` | `12.11` |
| `10000 -> 15000` | `65.51` | `66.48` |
| `15000 -> 20000` | `56.63` | `97.28` |
| `20000 -> 25000` | `65.80` | `78.00` |
| `25000 -> 30000` | `58.46` | `90.73` |

这说明：

- `5000 cycles` 时只提交了 `3` 条指令，早期启动阶段的“有效指令推进”非常慢
- 从 `10000 cycles` 之后开始，guest instruction 数量明显增长，CoreMark 主体已经开始持续推进
- 当前版本在中后段大致稳定在 `56 ~ 66 cycles/s`

## 5. 运行行为观察

本次 `30k smoke run` 里，有几个现象值得单独记住：

### 5.1 最近 emitter 修改后，bounded run 仍然稳定

这次样本是在最近 `supernode` 内部“单用户 value 直接内联”和“宽值改用 `bitint` 表达”之后得到的。当前观察结果是：

- 可以正常构建并启动
- 可以跨过 early boot
- 可以进入 `Running CoreMark for 2 iterations`
- 可以持续推进到 `30000 cycles`

至少在这个窗口内，没有看到 emitter 调整导致的立即性功能回退。

### 5.2 early boot 很慢，但不是“启动即挂”

最明显的现象是：

- `5000 cycles` 时只有 `3 instr`
- `10000 cycles` 时也只有 `458 instr`

这说明当前版本前段大部分时间消耗在 very-early boot / runtime warm-up，而不是稳定的 CoreMark 主体吞吐区间。

### 5.3 当前窗口内没有看到显式错误信号

对日志做关键字扫描，没有发现：

- `mismatch`
- `ABORT`
- `assert`
- `Segmentation fault`

因此这次记录应视为“性能偏慢但功能上可持续推进”的 smoke snapshot，而不是失败样本。

## 6. 与 NO0011 的关系

[`NO0011`](./NO0011_current_grhsim_xiangshan_coremark_50k_runtime_snapshot_20260420.md) 记录的是另一份 `50000-cycle` 快照，其整体速度是：

- `89.17 cycles/s`
- `131.22 instr/s`

本次 `NO0012` 的 `30000-cycle` smoke snapshot 是：

- `76.76 cycles/s`
- `71.15 instr/s`

这里不能直接得出“最近 emitter 修改让性能变差了多少”的严格结论，因为：

- 两次运行窗口不同：`30k` vs `50k`
- 两次取样覆盖的 guest 执行区间不同
- `30k` 窗口里 early boot 的占比更高

因此更合理的结论是：

- 当前修改后版本在 `30k` bounded smoke 口径下仍可稳定运行
- 但从这份快照看，runtime 仍然明显受 early boot 阶段拖累

## 7. 当前可作为基线记住的数字

如果只保留一组数字，应当记住：

- `30000 cycles`
- `27809 instr`
- `IPC = 0.927090`
- `390.847 s`
- `76.76 cycles/s`

这组数字就是最近一轮 emitter 修改之后，当前版本 `grhsim xiangshan coremark` 的 `30k-cycle smoke runtime snapshot`。
