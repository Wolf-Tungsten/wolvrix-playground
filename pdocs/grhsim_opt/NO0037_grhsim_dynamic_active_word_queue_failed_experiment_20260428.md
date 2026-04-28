# NO0037 GrhSIM Dynamic Active-Word Queue Failed Experiment（2026-04-28）

> 归档编号：`NO0037`。目录顺序见 [`README.md`](./README.md)。

这份记录用于固化一次已经判定失败的 runtime 实验：尝试把 `compute/commit` 两阶段的 active-word 驱动从固定全量扫描改成动态队列调度。结论很直接：

- 短 smoke run 明显回退。
- `XiangShan coremark 50k` 出现功能错误。
- 这条路线已经判死，代码实现已撤回。

后续优化工作不再把“全量 active-word 扫描太耗时”当作主瓶颈假设，也不再继续推进同类动态 active-word 队列方案。

## 1. 实验目标

实验目标是验证一个很具体的假设：

- 如果只对“本轮新变为非零”的 active word 建队列，
- 再让 `compute` / `commit` 只遍历该队列，
- 是否能显著降低每轮对 `kActiveFlagWordCount` 的固定扫描成本。

对应实验开关：

- `GRHSIM_DYNAMIC_ACTIVE_WORD_QUEUE=1`

关闭该开关时，回到现有固定扫描路径，作为对照组。

## 2. 实验口径

相关运行日志：

- smoke 对照组：
  - [`../../build/logs/xs/xs_wolf_grhsim_20260428_dynamic_queue_smoke_off.log`](../../build/logs/xs/xs_wolf_grhsim_20260428_dynamic_queue_smoke_off.log)
- smoke 实验组：
  - [`../../build/logs/xs/xs_wolf_grhsim_20260428_dynamic_queue_smoke.log`](../../build/logs/xs/xs_wolf_grhsim_20260428_dynamic_queue_smoke.log)
- `50k` 对照组：
  - [`../../build/logs/xs/xs_wolf_grhsim_20260428_dynamic_queue_50k_off.log`](../../build/logs/xs/xs_wolf_grhsim_20260428_dynamic_queue_50k_off.log)
- `50k` 实验组：
  - [`../../build/logs/xs/xs_wolf_grhsim_20260428_dynamic_queue_50k_on.log`](../../build/logs/xs/xs_wolf_grhsim_20260428_dynamic_queue_50k_on.log)

## 3. Smoke 结果：性能直接回退

`1000-cycle` smoke 对比如下：

| 指标 | 队列关闭 | 队列开启 | 变化 |
| --- | ---: | ---: | ---: |
| `Host time spent` | `7549 ms` | `8443 ms` | `+11.84%` |
| `tick_total_us` | `7282656` | `8084623` | `+11.01%` |
| `model_step_us` | `7537849` | `8430353` | `+11.84%` |

仅看 smoke 已经足够说明问题：

- 新增队列登记、去重和两阶段搬运开销，没有换来任何正收益。
- 这不是“收益太小”，而是开销肉眼可见地更差。

## 4. `50k` 结果：不仅更慢，而且错

对照组 `50k` 正常完成，关键结果如下：

- `Host time spent = 616053 ms`
- `tick_total_us = 615759190`
- `model_step_us = 615226793`
- `compute_batch_exec_count = 65118281`
- `commit_batch_exec_count = 82404759`

实验组在大约 `15037` guest cycles 处失败，日志关键错误为：

- `Mismatch for store commits`
- `REF pc=0x80000378`
- `DUT pc=0x80000136`
- `ABORT at pc = 0x8000014e`

失败前已累计的 host 时间：

- `Host time spent = 211757 ms`
- `tick_total_us = 211403540`
- `model_step_us = 211590367`

这说明问题不只是“没提速”，而是：

- 动态 active-word 队列已经破坏了现有 fixed-point / commit 可见性语义。
- 在 `XiangShan coremark 50k` 这种真实 workload 上，功能都过不了。

## 5. 失败原因归纳

这次实验至少说明了三件事：

1. 队列登记和去重不是免费成本。

- 每次激活都要做额外判断、入队、清队列状态。
- 这些 bookkeeping 成本会直接吃掉所谓“少扫几个 active word”的理论收益。

2. `compute` / `commit` 的真实大头不在这里。

- 早先 `NO0035` 里已经看到 `compute` 正文本身很重。
- 这次直接实验证明，仅围绕 active-word 扫描方式做文章，既救不了性能，还会把实现复杂度明显抬高。

3. 当前动态队列方案很容易把调度语义做错。

- 尤其是跨 `compute -> commit -> next round compute` 的重新激活路径。
- 只要漏掉某些“本轮仍需保留、但并非新置位”的 active word，就会造成行为偏差。

## 6. 最终结论

结论明确：

- `GRHSIM_DYNAMIC_ACTIVE_WORD_QUEUE` 这条路线无效。
- 它同时带来了性能回退和功能错误。
- 代码实现已撤回，不保留 runtime 开关。

同时明确记录一条后续约束：

- 后续 `grhsim` runtime 优化，不再把“全量 active-word 扫描太耗时”当作主瓶颈结论。
- 如果没有新的直接证据，不再重复提出同类动态 active-word 队列建议。

## 7. 对后续工作的影响

这次失败实验只否定一个方向：

- “靠动态 active-word 队列替代固定扫描”不是可行主线。

它不否定以下工作继续推进：

- 保留并使用已有 `eval/round/batch` 计时插桩与 perf counters。
- 继续分析真正重的 `compute batch` 正文。
- 继续分析 `commit` phase 中除 active-word 扫描之外的其它框架成本。

相关前序文档：

- [`NO0035`](./NO0035_grhsim_compute_commit_perf_breakdown_3khz_gap_20260428.md)
- [`NO0036`](./NO0036_grhsim_3khz_runtime_optimization_plan_20260428.md)
