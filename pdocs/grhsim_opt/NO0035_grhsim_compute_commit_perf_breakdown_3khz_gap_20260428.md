# NO0035 GrhSIM Compute / Commit 计时拆解与 3kHz 目标差距（2026-04-28）

> 归档编号：`NO0035`。目录顺序见 [`README.md`](./README.md)。

这份记录固化一次带 `eval` 级 perf trace 的 `XiangShan coremark 50k` 复测结果，目标不是再给一个新的总耗时快照，而是回答两个更具体的问题：

- 当前 `compute` / `commit` 两阶段各自慢在哪里。
- 如果 runtime 目标是 `3 kHz`，当前差距到底有多大，首先该压哪一段。

## 数据来源

- 构建日志：
  - [`../../build/logs/xs/xs_wolf_grhsim_build_20260428_perf_batch_50k_v2.log`](../../build/logs/xs/xs_wolf_grhsim_build_20260428_perf_batch_50k_v2.log)
- 运行日志：
  - [`../../build/logs/xs/xs_wolf_grhsim_20260428_perf_batch_50k_v2.log`](../../build/logs/xs/xs_wolf_grhsim_20260428_perf_batch_50k_v2.log)
- 相关历史记录：
  - [`NO0011 当前 GrhSIM XiangShan CoreMark 50k Runtime Snapshot`](./NO0011_current_grhsim_xiangshan_coremark_50k_runtime_snapshot_20260420.md)
  - [`NO0023 GrhSIM Compute-Commit Two-Phase Eval Plan`](./NO0023_grhsim_compute_commit_two_phase_eval_plan_20260423.md)
  - [`NO0034 Sink Activation Event-Delta Narrowing Plan`](./NO0034_sink_activation_event_delta_plan_20260427.md)

## 1. 运行口径

本轮先重新 `emit -> build`，再用 `eval` perf trace 跑 `50000-cycle coremark`：

```bash
make --no-print-directory xs_wolf_grhsim_emu RUN_ID=20260428_perf_batch_50k_v2 WOLVRIX_GRHSIM_PERF=1
env GRHSIM_TRACE_EVAL_EVERY=10000 \
  make --no-print-directory run_xs_wolf_grhsim_emu \
  RUN_ID=20260428_perf_batch_50k_v2 \
  XS_SIM_MAX_CYCLE=50000 \
  XS_PROGRESS_EVERY_CYCLES=5000
```

trace 口径说明：

- `WOLVRIX_GRHSIM_PERF=1`：生成带 `eval` perf 代码的 runtime。
- `GRHSIM_TRACE_EVAL_EVERY=10000`：每 `10000` 次 `eval()` 打一次 trace。
- 本轮总共采到 `10` 个 sample：`eval #10000 ~ #100000`。

## 2. 最终运行结果

`50k` 运行正常结束，日志末尾摘要如下：

- `instrCnt = 73580`
- `cycleCnt = 49996`
- `IPC = 1.471718`
- `Guest cycle spent = 50001`
- `Host time spent = 645230 ms`

折算后的整体速度：

| 指标 | 数值 |
| --- | ---: |
| guest cycles/s | `77.49` |
| host us / guest cycle | `12904.34` |
| observed eval count | `100000` |
| host us / eval (avg) | `6452.30` |

这里最关键的一点是：

- `50001 guest cycles` 对应 `100000 eval`，当前大约是 `2 eval / guest cycle`。

## 3. 3kHz 目标换算

如果 runtime 目标是 `3 kHz`，那么预算应当先换算成时间：

| 指标 | 预算 |
| --- | ---: |
| target guest cycles/s | `3000` |
| target us / guest cycle | `333.33` |
| target us / eval (按 2 eval/cycle 粗算) | `166.67` |

和当前结果相比：

- 当前整机平均是 `12904.34 us / guest cycle`，超预算约 `38.7x`。
- 当前整机平均是 `6452.30 us / eval`，超预算约 `38.7x`。

这意味着：

- `3 kHz` 目标不是“小修小补”级别，而是量级级别的 runtime 降本。

## 4. 单位澄清：`8000us` 不是单次 `eval`

本轮最容易误读的一组数字是：

- `sum(batch_us) = 8163`
- `sum(commit_us) = 8079`

这两个值都来自 `10` 个 sampled eval 的累计值，不是单次 `eval`。

对应平均值应当写成：

| 指标 | 10 sample 累计 | 单 sample 平均 |
| --- | ---: | ---: |
| compute `batch_us` | `8163 us` | `816.3 us` |
| commit `commit_us` | `8079 us` | `807.9 us` |
| traced `eval total_us` | `25160 us` | `2516.0 us` |

所以：

- “`compute` / `commit` 各有 `8 ms`”这个说法，如果直接拿去对 `3 kHz` 比，是不对的。
- 正确口径是“sampled eval 平均 `compute 816 us`、`commit 808 us`、总 traced eval `2516 us`”。

即便按正确口径，距离 `166.67 us / eval` 的预算仍然很远：

- `compute + commit` 两阶段平均就有 `1624.2 us / eval`，已经超预算约 `9.75x`。
- sampled `eval total_us` 平均 `2516.0 us / eval`，超预算约 `15.1x`。

还需要注意：

- `sampled eval total_us` 是带 trace 的 `eval()` 内部观测值。
- `host us / eval (avg)` 是整机 wall time 平均值，包含 `eval()` 之外的 runtime / harness / difftest 成本。
- 两者不是同一口径，不能直接相减，但都足以说明当前离 `3 kHz` 目标还很远。

## 5. Sampled Eval 总览

10 个 sample 的 `eval end` 摘要如下：

| eval id | batch_us | commit_us | total_us | commit / batch |
| --- | ---: | ---: | ---: | ---: |
| `10000` | `411` | `931` | `2191` | `2.265` |
| `20000` | `529` | `723` | `2090` | `1.367` |
| `30000` | `535` | `635` | `1996` | `1.187` |
| `40000` | `835` | `815` | `2618` | `0.976` |
| `50000` | `999` | `886` | `2827` | `0.887` |
| `60000` | `922` | `743` | `2584` | `0.806` |
| `70000` | `999` | `770` | `2700` | `0.771` |
| `80000` | `890` | `865` | `2670` | `0.972` |
| `90000` | `1029` | `757` | `2738` | `0.736` |
| `100000` | `1014` | `954` | `2746` | `0.941` |

这组 sample 反映出两个事实：

- 前段 sample 里 `commit` 比 `compute` 更重，例如 `eval #10000` 是 `931 us vs 411 us`。
- 中后段 sample 里 `compute` 反超，例如 `eval #90000` 是 `1029 us vs 757 us`。

所以当前不是“只有 commit 慢”，而是：

- 前段偏 `commit` 重。
- 中后段偏 `compute` 重。
- 两者长期均值接近 `1:1`。

## 6. Fixed-Point 轮次拆解

sampled eval 基本都是 `2 rounds`，但第二轮几乎不重要。

按 `10` 个 sample 汇总：

| round | count | batch_us | commit_us | total_us | executed_batches | executed_supernodes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `round 1` | `10` | `8113` | `8029` | `20873` | `9820` | `62364` |
| `round 2` | `10` | `50` | `50` | `614` | `76` | `579` |

对应平均值：

- `round 1 total_us ≈ 2087 us / eval`
- `round 2 total_us ≈ 61 us / eval`

因此：

- 当前瓶颈几乎全部在第一轮。
- `round 2` 不值得作为第一优先级优化对象。

## 7. 为什么 Compute 慢

先看 compute phase 的“已执行 batch body”本身：

- `3276` 次 sampled compute batch 执行，累计 `8162 us`
- 平均 `2.49 us / batch`
- 平均 `816.2 us / sampled eval`

最重要的结论是：

- `compute` 的慢，不是纯扫描假开销。
- 单看 batch body 本身，已经达到 `816 us / eval`，仅这一项就已经是 `166.67 us / eval` 预算的约 `4.9x`。

本轮最热的 compute batch：

| batch | 10 sample 累计 total_us | avg_us / sample | max_us | avg executed supernodes / sample |
| --- | ---: | ---: | ---: | ---: |
| `669` | `158` | `15.8` | `21` | `81.0` |
| `262` | `149` | `14.9` | `18` | `23.0` |
| `453` | `148` | `14.8` | `18` | `25.0` |
| `332` | `146` | `14.6` | `17` | `14.0` |
| `385` | `116` | `11.6` | `15` | `8.0` |

从这些热点可以看到：

- 热 compute batch 在 `10` 个 sample 里几乎每次都会出现，说明是稳定热路径，不是偶发噪声。
- 最重的 batch 并不一定对应最多 supernode，说明成本不只取决于节点数，还取决于 batch 内部语句形态、宽值操作、条件层次和 memory/state 访问模式。
- 换句话说，`compute` 这里已经不是“dispatch 太慢”，而是“被 dispatch 到的正文就很重”。

当前对 compute 的判断可以收敛为：

- 第一类成本：真实 batch body 计算成本过高。
- 第二类成本：phase 外围扫描成本也存在，但仅第一类就已经远超预算。

## 8. 为什么 Commit 慢

`commit` 的情况和 `compute` 不一样。

先看 sampled commit batch body：

- `6620` 次 sampled commit batch 执行，累计只有 `1910 us`
- 平均 `0.289 us / batch`
- 平均 `191 us / sampled eval`

但 round 级 `commit_us` 汇总是：

- `8079 us / 10 samples`
- 平均 `807.9 us / sampled eval`

这说明：

- `commit` phase 的真正 batch body 只占 `23.6%`
- 剩余 `76.4%` 不是“写入正文”，而是 phase 外围成本

这里的“外围成本”在本轮 trace build 中主要包括：

- 整个 commit loop 对 active-word 范围的全量扫描
- `active word -> batch index` 的派发表查找
- 大量极小 commit batch 的间接调用、条件判断和统计累加
- 当前 batch trace 自身的 `fprintf` / `chrono` 开销

也就是说：

- `commit_us` 不能直接理解成“sink write 真正执行了 808 us”。
- 更接近事实的表述是：“当前 commit phase 每次 sample 要花 `808 us`，其中只有约 `191 us` 是 batch body，其余大部分是扫描、调度和 trace build 自带的外围成本。”

再看结构形态：

- sampled unique compute batch：`320`
- sampled unique commit batch：`662`
- sampled compute batch events：`3276`
- sampled commit batch events：`6620`

这说明：

- `commit` 触发的 batch 明显更多，而且大多是很小的 batch。
- 当前 commit 更像是在做“大量极小任务”的稀疏派发，而不是少量重任务。

这也是为什么当前 commit phase 的优化重点不应放在“单个 sink write 再快一点”，而应放在：

- 如何减少 commit phase 的全局扫描
- 如何减少 tiny batch 的调度次数
- 如何把 commit 从“active-word sweep 驱动”改成“touched shadow / touched write 驱动”

## 9. 当前最重要的结构结论

把上面的结果压缩成一句话：

- `compute` 慢在正文。
- `commit` 慢在框架。

更具体一点：

1. `compute`

- 真正执行的 batch body 已经很重。
- 少数稳定热点 batch 每次 sample 都会反复出现。
- 即使完全不算 commit，`compute body` 单独也已经超出 `3kHz` 对应的 `eval` 预算很多。

2. `commit`

- 真正写入的 batch body 不重。
- 重的是“为了完成 commit phase 而做的大量扫描、派发、判断、统计和本轮 trace build 的日志开销”。
- 这类成本如果不改 phase 驱动方式，很难靠微调 sink body 消掉。

3. `fixed-point`

- 第二轮几乎可以忽略。
- 首轮 `active_in` 已经是 `~6028 supernodes / ~2382 active words`，真正的主战场是首轮首相位，而不是多轮反复收敛。

## 10. 对后续优化方向的约束

如果目标真的是 `3 kHz`，那当前数据给出的约束非常明确：

- 第一优先级不是 `round 2`，也不是 `clear_evt`。
- 第一优先级是把 `commit` 从“全局扫 + 大量 tiny batch 派发”改成更稀疏的 touched-set 驱动。
- 第二优先级是对稳定重热点 compute batch 做正文降本，而不是继续做只影响少量 sink body 的局部微优化。

基于本轮数据，后续方案至少要同时满足：

1. `commit phase` 降本不能只靠 sink body 微调。

- 因为当前 sampled commit body 只有 `191 us / eval`，就算把正文全抹掉，`commit` 也还剩大约 `600 us / eval` 量级的外围成本。

2. `compute phase` 必须直面热点 batch 正文。

- 因为 current sampled compute body 自己就有 `816 us / eval`，已经远高于预算。

3. 不能只看 traced stage time。

- 本轮整机平均仍是 `6452 us / eval`。
- 即使 `compute + commit` 降很多，`eval` 之外的 runtime / harness / difftest 成本也仍然需要继续清理。

## 11. 本轮结论

本轮可以固化为三条结论：

- `8163 us / 8079 us` 是 `10` 个 sample 的累计，不是单次 `eval`。
- 正确口径下，当前 sampled `compute` 与 `commit` 长期均值都在 `~0.8 ms / eval`，距离 `3 kHz` 目标下的 `166.67 us / eval` 预算仍有数量级差距。
- `compute` 的主问题是正文热 batch 过重；`commit` 的主问题是 phase 框架成本过高，尤其是全局扫描和大量 tiny batch 派发。
