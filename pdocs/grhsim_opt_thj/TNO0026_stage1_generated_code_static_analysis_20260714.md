# TNO0026 Stage 1 generated-code static analysis

记录日期：2026-07-14

状态：完成 current-default、strict、balanced 的 generated C++、object/ELF 和 propagation table 对照；bae-budget 完成轻量 ELF/文件统计。候选存在真实 emitted-work 减少，但量级较小且有 batch/table 抵消项，不能替代 50k。

## 1. 比较口径

fresh baseline 与 matched resume-control 的 ELF `.text` 完全相同。JSON reload 会改变生成 C++ 中 `_op_` / `_val_` debug comment 的内部编号和注释字节数，因此源码比较优先使用 matched control，并在比较代码体积时去除纯 debug comment；ELF 与结构表不受此问题影响。

四组基础数据见 [TNO0025](./TNO0025_stage1_candidate_build_and_functional_gates_20260714.md)。本文进一步回答两个问题：

1. 源码/ELF 变小是否只是 supernode 在 sched batch 间搬移；
2. BAE/DAG 下降是否真的删除了 boundary compare/store 和 propagation table work。

## 2. Batch 形态

| Metric | baseline | strict | balanced |
| --- | ---: | ---: | ---: |
| total sched cpp | `117` | `119` | `121` |
| compute batches | `66` | `66` | `66` |
| commit batches | `51` | `53` | `55` |
| active-word dispatch blocks | `8,417` | `8,420` | `8,419` |
| clock-change input activation entries | `522` | `537` | `533` |

compute batch 数不变，新增 translation unit 全来自 commit batch 的 estimated-line 边界重切分。strict/balanced 分别多 `2/4` 次 commit batch 调用；active-word block 和 clock activation table 也轻微增加。这些是 BAE/DAG 下降之外的静态抵消项。

最大的单文件变化不是净收益：以 comment-stripped sched 源码计，strict 的 batch17/18 分别约 `+8.051 MB / -8.465 MB`，balanced 分别约 `+8.018 MB / -8.453 MB`；object `.text` 也一增一减，两文件合计反而约增加 `45 KB / 34 KB`。因此不能把最大 batch 缩小写成 work reduction，它主要来自 schedule relocation。

## 3. 全局真实减少

去除 debug comment 后的 sched 代码：

| Metric | baseline | strict | balanced |
| --- | ---: | ---: | ---: |
| comment-stripped sched bytes | `980,126,852` | `977,542,909` | `977,747,462` |
| delta | - | `-2,583,943` (`-0.2636%`) | `-2,379,390` (`-0.2428%`) |
| ELF `.text` | `88,186,297` | `88,009,949` | `87,971,429` |
| `.text` delta | - | `-176,348` (`-0.2000%`) | `-214,868` (`-0.2437%`) |

bae-budget 未在 quiet gate 前继续扫描 1.3 GB 源码，但其 ELF `.text=87,980,053`，相对 baseline 为 `-206,244`（`-0.2339%`），位于 strict 与 balanced 之间。

以下变化证明全局下降不只是 batch 搬移：

| Emitted item | baseline | strict | balanced |
| --- | ---: | ---: | ---: |
| standalone op comments | `2,128,344` | `2,126,275` | `2,126,474` |
| delta | - | `-2,069` | `-1,870` |
| direct-OR + mask-table entries | `880,842` | `868,062` | `868,469` |
| propagation-entry delta | - | `-12,780` (`-1.451%`) | `-12,373` (`-1.405%`) |
| mask popcount | `1,039,513` | `1,025,111` | `1,024,485` |

standalone op comment 的减少量恰好等于 final boundary-values delta；value definitions 分别减少 `2,070 / 1,871`，`next_value` definitions 分别减少 `2,057 / 1,858`。这些是一组彼此独立的交叉核对，说明 refinement 真正删除了约两千个 boundary compare/store 槽和约 1.4% propagation entries。

model storage 只减少约 `2.6..2.8 KB`，容量收益本身可忽略；潜在 runtime 价值主要来自边界变化判断和 activation propagation 动态工作减少。

## 4. 结论

三种候选都有真实 emitted-work 减少，并非纯 schedule ID relocation。balanced 的 `.text` 最小，bae-budget 次之，strict 的 DAG/代码表也明显改善；但静态收益只有约 `0.2%` ELF `.text` 和 `1.4%` propagation entries，同时 commit batch、active-word block 和 clock activation table 略退。

这个量级不足以预测超过 `1%` 的 SimTop 50k cycles 改善，且代码布局变化可能放大或抵消结构收益。最终仍按 fixed-ASLR、同 CPU/NUMA、五事件 PMU 的 quiet `control / candidate / control` 裁决。
