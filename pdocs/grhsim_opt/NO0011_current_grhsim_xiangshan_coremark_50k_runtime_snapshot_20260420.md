# NO0011 当前 GrhSIM XiangShan CoreMark 50k Runtime Snapshot（2026-04-20）

> 归档编号：`NO0011`。目录顺序见 [`README.md`](./README.md)。

这份记录单独固化当前 `grhsim` 在 `XiangShan coremark` 上的 `50000-cycle` 运行快照，作为后续 runtime 侧调优的阶段性基线。

## 数据来源

- 本次运行日志：
  - [`../../build/logs/xs/xs_wolf_grhsim_20260419_50000.log`](../../build/logs/xs/xs_wolf_grhsim_20260419_50000.log)
- 相关结构分析：
  - [`NO0009 Activity-Schedule Topo 重构后性能与 Supernode 结构画像`](./NO0009_activity_schedule_topo_refactor_perf_and_supernode_profile_20260419.md)
  - [`NO0010 当前 GrhSIM Supernode 图结构相对 GSim 的差异`](./NO0010_current_grhsim_supernode_graph_vs_gsim_20260419.md)
- 旧速度快照：
  - [`NO0006 GSim / GrhSIM Simulation Speed Tracking Snapshot`](./NO0006_gsim_grhsim_sim_speed_tracking_20260418.md)

## 1. 运行命令

```bash
make -j run_xs_wolf_grhsim_emu RUN_ID=20260419_50000 XS_SIM_MAX_CYCLE=50000 XS_COMMIT_TRACE=0 XS_PROGRESS_EVERY_CYCLES=5000
```

本次运行口径：

- workload：`coremark-2-iteration.bin`
- runtime 上限：`50000 cycles`
- `commit trace`：关闭
- 进度打印间隔：`5000 cycles`

## 2. 最终结果

本次运行正常推进到 cycle limit，并以 `EXCEEDING CYCLE/INSTR LIMIT` 结束，没有出现 early abort。

最终日志摘要：

- `instrCnt = 73580`
- `cycleCnt = 49996`
- `IPC = 1.471718`
- `Guest cycle spent = 50001`
- `Host time spent = 560738 ms`

对应日志末尾可见：

- `Core 0: EXCEEDING CYCLE/INSTR LIMIT at pc = 0x80001312`
- `Core-0 instrCnt = 73580, cycleCnt = 49996, IPC = 1.471718`
- `Host time spent: 560738ms`

## 3. 当前运行速度

按本次 `0 -> 50000 cycles` 窗口直接折算：

| 指标 | 数值 |
| --- | ---: |
| simulated cycles | `50000` |
| guest instructions | `73580` |
| host wall time | `560.738 s` |
| host simulation speed | `89.17 cycles/s` |
| host instruction throughput | `131.22 instr/s` |

这组数值的含义是：

- 当前版本已经能稳定推进到 `50000 cycles`
- 但 runtime 速度仍然处于两位数 `cycles/s` 量级
- 这不是 full-run CoreMark 完成速度，只是 `50k-cycle` 观测窗口的实时快照

## 4. 分段推进情况

从日志中的 `EMU_PROGRESS` 可直接抽出以下进度点：

| model cycles | instr | host ms |
| --- | ---: | ---: |
| `10000` | `458` | `52254` |
| `15000` | `5532` | `102169` |
| `20000` | `14121` | `164024` |
| `25000` | `20048` | `220545` |
| `30000` | `27809` | `297937` |
| `35000` | `35570` | `368954` |
| `40000` | `43350` | `431391` |
| `45000` | `52481` | `491015` |
| `50000` | `73580` | `560722` |

对应的分段速度：

| 区间 | cycles/s | instr/s |
| --- | ---: | ---: |
| `10000 -> 15000` | `100.17` | `101.65` |
| `15000 -> 20000` | `80.83` | `138.86` |
| `20000 -> 25000` | `88.46` | `104.86` |
| `25000 -> 30000` | `64.61` | `100.28` |
| `30000 -> 35000` | `70.41` | `109.28` |
| `35000 -> 40000` | `80.08` | `124.61` |
| `40000 -> 45000` | `83.86` | `153.14` |
| `45000 -> 50000` | `71.73` | `302.68` |

这说明：

- 最早启动阶段之外，当前版本在中后段大致稳定在 `65 ~ 100 cycles/s`
- `instr/s` 波动更大，说明 guest 执行内容的密度在不同区间差异明显

## 5. 运行行为观察

本次运行里，有两个现象值得单独记住：

### 5.1 能跨过早期慢启动

此前短窗口观察中，模型在 very-early boot 阶段表现得很慢。但这次 `50000-cycle` 运行确认：

- 可以跨过 early boot
- 可以进入 `Running CoreMark for 2 iterations`
- 可以持续推进到 `50000 cycles`

因此当前状态不应再归类为“启动即挂”。

### 5.2 启动阶段和中后段速度差异明显

例如：

- `10000 cycles` 时已经花了 `52.254 s`
- 但后续 `10000 -> 50000 cycles` 的平均速度明显更高

这说明当前 runtime 至少分成两段：

- 一段很慢的 early boot / runtime warm-up
- 一段能持续推进的 CoreMark 主体执行区间

## 6. 与旧速度快照的关系

[`NO0006`](./NO0006_gsim_grhsim_sim_speed_tracking_20260418.md) 中旧 `grhsim` sample-run 的速度是：

- `65.11 cycles/s`
- `67.48 cycles/s`（`perf` 口径）

而本次 `50k-cycle` 窗口的整体速度是：

- `89.17 cycles/s`

这里不能直接得出“当前版本快了多少”的严格结论，因为：

- 旧文档的运行窗口是 `30000 cycles`
- 本次窗口是 `50000 cycles`
- 两次运行处在不同 commit、不同模型状态下

但它至少说明：

- 当前版本已经能提供一个更长、更稳定的 runtime 观察窗口
- 后续如果要继续做 runtime 优化，`50000-cycle snapshot` 会比 `30000-cycle sample-run` 更有参考价值

## 7. 当前可作为基线记住的数字

如果只保留一组数字，应当记住：

- `50000 cycles`
- `73580 instr`
- `IPC = 1.471718`
- `560.738 s`
- `89.17 cycles/s`

这组数字就是当前版本 `grhsim xiangshan coremark` 的 `50k-cycle runtime snapshot`。
