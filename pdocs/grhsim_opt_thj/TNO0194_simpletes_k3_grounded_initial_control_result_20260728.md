# TNO0194 SimpleTES K3 grounded initial control result

## 1. 阶段结论

[TNO0193](./TNO0193_simpletes_k3_grounded_fresh_research_launch_20260728.md) 启动的 fresh instance
`7291c6c2` 已完成 initial control。前三次 runtime invocation 因运行期 whole-CCD 空闲门禁失败而自动丢弃；
第 4 次在固定 node0 CCD 上完整通过 ABBA 四样本、fixed-ASLR、CPU affinity、NUMA first-touch、PMU 和
功能门禁。

正式绝对 walltime 为：

```text
control:           54,520 / 54,505 ms, mean 54,512.5 ms
candidate-control: 54,555 / 54,613 ms, mean 54,584.0 ms
same-code delta:   +71.5 ms / +0.131162577% candidate slower
SimpleTES score:   0.9986900923347501
```

两侧 generated fingerprint 均为 `b55d17026338f456`，candidate mode 为 `control`、patch files 为 `0`、
enable options 为 `0`；因此这 `71.5 ms` 只是同产物测量噪声，不是代码回退或优化结果。initial evaluator 总耗时
`907.267285949 s`，其中包含三次 strict infrastructure retry。本阶段完成后于 `03:45:18 +08:00` 进入第一条
正式 K3 generation；本记录形成时尚无 candidate final response 或候选性能结论。

## 2. 固定身份与正式放置

```text
candidate digest: 345fe98fbbc4ff3b
parent pin:       d31118bea0fe
Wolvrix pin:      16a9f493687a
generated fp:     b55d17026338f456 (control == candidate-control)
group order:      ABBA
headline metric:  Host time spent walltime_ms
```

最终 placement 为：

```text
CCD:          node0:0-7,192-199
target CPU:   2
SMT sibling:  194
helper CPU:   96
NUMA node:    0
selection:    count=16, mean_idle=99.871875%, min_idle=99.33%
               target_idle=100.0%, sibling_idle=100.0%
```

## 3. 正式四样本原值

| index / role | walltime ms | pre mean/min idle % | runtime mean/min/sibling idle % | cycles:u | instructions:u | ctx switch | migration |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `1 control` | `54,520` | `99.750000 / 98.00` | `99.536000 / 98.42 / 99.94` | `199,101,510,184` | `162,370,962,137` | `759` | `0` |
| `2 candidate-control` | `54,555` | `99.736875 / 98.80` | `99.343333 / 98.00 / 99.52` | `199,236,262,156` | `162,370,966,339` | `776` | `0` |
| `3 candidate-control` | `54,613` | `99.545625 / 98.08` | `99.293333 / 97.95 / 99.69` | `199,454,559,639` | `162,370,966,695` | `792` | `0` |
| `4 control` | `54,505` | `99.185000 / 96.33` | `99.532667 / 98.30 / 99.70` | `199,094,422,394` | `162,370,960,708` | `776` | `0` |

四个样本均满足：

- `personality=00040000`，即 `setarch x86_64 -R` fixed-ASLR；
- allowed CPU 精确为 `[2]`，executable identity 通过；
- emu 的 `21,082` 页与 NEMU 的 `115` 页均 `local_ratio=1.0` on node0；
- PMU scheduled percent 与 event audit 通过，CPU migration 为 `0`；
- guest cycle、terminal PC、signature 与唯一 walltime 行均通过。

## 4. 被丢弃的基础设施样本

这些 absolute walltime 仅用于说明 retry 行为，均不进入正式 baseline 聚合：

| invocation | 已执行 walltime ms | rejection evidence |
| --- | --- | --- |
| `1` | `54,722 / 54,353 / 54,449 / 54,645` | 第 4 样本 monitor `mean_idle=96.149333%`、`min_idle=94.10%`，低于 `98%/95%` 门槛，整组作废。 |
| `2` | `53,761` | 首样本 whole-CCD mean/min 为 `98.813333%/97.60%`，但 SMT sibling 仅 `97.81% < 98%`，立即作废。 |
| `3` | `54,488` | 首样本 monitor `min_idle=94.06% < 95%`，立即作废。 |

evaluator 使用 `GRHSIM_INFRA_RETRIES=8`，实际在第 4 次 invocation 获得有效窗口。它没有降低门槛，也没有把上述
受扰样本写入最终 `runtime_result`。

## 5. 阶段裁决

initial control 已给出本轮 post-RWA 默认配置的可信绝对起点，但同码 canary 的 `0.131162577%` 差异再次说明
单一 order 小差值必须视为噪声。后续候选仍须先通过代码/功能/结构证据，再由正式 50k walltime 决定是否保留；
若候选首个 ABBA 正向，还必须按 evaluator 协议完成反向 BAAB promotion gate。
