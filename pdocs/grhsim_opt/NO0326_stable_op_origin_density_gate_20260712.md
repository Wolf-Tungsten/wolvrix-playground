# NO0326 Stable-op origin-density gate

日期：2026-07-12

## 1. 全量连接结果

使用 [NO0324](./NO0324_batch_dynamic_work_profile_tool_plan_20260712.md) 工具严格连接两版 generated
batch、static/fire TSV 与 cmask6 exact-symbol report：

- NO0286 / NO0300 均为 `66 compute + 51 commit` batches；
- supernode 分别全量闭合 `67,934/63,726` 行，无重复、缺 key 或 phase 错配；
- compute work 精确复现 `76,992,970,253 -> 73,155,684,125`；
- compute samples 精确复现 `11,845 -> 13,637`；
- compute samples-per-billion-work 为 `153.845 -> 186.411`，回退 `21.1677%`；
- commit samples/work 回退 `5.0088%`。

工具的 JSON 已确认每版均为 117 个 batch rows。

## 2. Stable-op origin-density 排名

按 [NO0325](./NO0325_stable_op_origin_density_tool_plan_20260712.md) 的 stable-op overlap 启发式，
至少 100 samples 的主要 density-ratio 候选为：

| New batch | Samples | New density | Common coverage | Old-origin density | Ratio | Relative to global | Estimated excess samples |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| compute39 | 279 | 304.97 | 86.08% | 153.79 | 1.983x | 1.637x | +138.3 |
| compute29 | 282 | 360.83 | 89.70% | 195.49 | 1.846x | 1.523x | +129.2 |
| compute13 | 140 | 664.53 | 91.25% | 361.56 | 1.838x | 1.517x | +63.8 |
| compute7 | 108 | 295.56 | 74.58% | 163.31 | 1.810x | 1.494x | +48.3 |
| compute14 | 189 | 320.38 | 84.92% | 186.41 | 1.719x | 1.418x | +79.0 |
| compute4 | 318 | 412.09 | 73.58% | 241.64 | 1.705x | 1.407x | +131.5 |

按 estimated excess samples 排名，compute36/39/4/29 分别约为 `+139.2/+138.3/+131.5/+129.2`。
compute36 common coverage 只有 `63.69%`，而 39/29 的 coverage 接近或超过 `86%`，因此后两者是更干净的
重排候选。该 excess 不可跨 batch 求和当成精确事件分解，只用于确定查看顺序。

## 3. Old12 / new13 近似对照

new13 有 `91.25%` static ops 可映射，最大来源 old12 占 new total ops `57.07%`。两者数据为：

| Metric | old compute12 | new compute13 | Delta |
| --- | ---: | ---: | ---: |
| dynamic work | 203,812,786 | 210,675,741 | +3.37% |
| cmask6 samples | 94 | 140 | +48.94% |
| samples / billion work | 461.21 | 664.53 | +44.08% |
| generated source bytes | 32,342,694 | 30,862,854 | -4.58% |
| function text bytes | `0x202c59` | `0x1e38f4` | -6.06% |
| annotated instructions | 388,655 | 366,971 | -5.58% |

new13 用相近 dynamic work 和更少静态代码产生更多 full-empty 样本。old12/new13 的 annotate 指令类型也相似，
主要为 test/mov/movzbl/cmp/布尔运算；两边最大单 IP 仅约 `1%~1.4%`，没有新增单一 branch/call hotspot。

## 4. 其他候选 annotate

compute39/29/13/4 都呈弥散分布，没有 NO0298 那种 90% 级 guard 集中：

- compute39 的 `shrd` 约占 local samples `11.16%`，其余主要为 mov/xor/test/set；
- compute29/13/4 主要为 mov/test/cmp/set/and/or；
- 四者没有共同的异常 branch/call 形态；
- opcode mix 与各自主要 old origins 大体延续，未发现 ordered-write 新增的一类高频算子。

## 5. 结论与下一步

当前证据支持“相近逻辑被重新 packing/放置后，fetch latency 广泛恶化”，不支持为 compute13/29/39 写
特例或继续减少某类 opcode。cmask6 不是 precise event，IP 有 skid，且 aggregate I-cache/TLB/op-cache miss
计数已在 NO0315/NO0317/NO0321 中改善。

下一步检查本机 AMD IBS fetch 是否可用。若可采样 fetch latency、cache/TLB source 和精确 fetch IP，则对
NO0286/NO0300 做同 workload profile，判断延迟来自 L2/L3/DRAM、TLB 还是其他 fetch completion；再决定函数
对齐、section/order 或 batch packing probe。若 IBS 不可用，退回 L2 instruction request/hit/miss A/B/A。

## 6. 产物

```text
build/logs/xs_perf/no0322/batch_dynamic_work_compare.report
build/logs/xs_perf/no0322/batch_dynamic_work_compare.json
build/logs/xs_perf/no0322/compute_batch_origin_density.report
build/logs/xs_perf/no0322/old_compute12_cmask6_annotate.report
build/logs/xs_perf/no0322/new_compute13_cmask6_annotate.report
build/logs/xs_perf/no0322/new_compute39_cmask6_annotate.report
build/logs/xs_perf/no0322/new_compute29_cmask6_annotate.report
build/logs/xs_perf/no0322/new_compute4_cmask6_annotate.report
```
