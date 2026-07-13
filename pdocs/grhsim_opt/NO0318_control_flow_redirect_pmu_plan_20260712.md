# NO0318 Control-flow redirect PMU plan

日期：2026-07-12

## 1. 目的

[NO0317](./NO0317_no0286_no0300_frontend_latency_itlb_gate_20260712.md) 已证明 NO0300 的 frontend
full-empty latency slots/cycle 增加 `6.62%`，但 bandwidth slots、I-cache miss 和 ITLB miss density 均下降。
本阶段检查该 latency 是否来自更密集的 taken control flow、mispredict 或 frontend resteer。

## 2. 事件

按本机 AMD PMU 定义使用：

```text
cycles:u
ex_ret_brn_tkn:u
ex_ret_brn_tkn_misp:u
bp_de_redirect:u
resyncs_or_nc_redirects:u
```

- `ex_ret_brn_tkn`：retired taken control-flow changes；
- `ex_ret_brn_tkn_misp`：其中的 mispredicted taken branches；
- `bp_de_redirect`：decoder 修正 predicted target 并 resteer predictor；
- `resyncs_or_nc_redirects`：非 branch-mispredict 导致的 pipeline restart。

NO0286 `-C 100` 接线探针已确认五项均 `100.00%` 调度；短跑计数不用于性能结论。

## 3. 运行与归一化口径

继续比较同一组无 profile NO0286 / NO0300 binary，执行 old / new / old，固定 CPU138、NUMA node 1、
CoreMark 两迭代、NEMU difftest 和 `-C 50000`。每轮前检查 CPU138/330 与全机 load，要求三轮功能终点
一致、全部事件 `100%`，且 old spread 显著小于候选差异。

除绝对计数和 per host cycle 外，还需要结合：

- [NO0302](./NO0302_ordered_memory_write_affine_overall_50k_gate_20260712.md) 的 instructions；
- [NO0312](./NO0312_no0286_no0300_dynamic_work_gate_20260712.md) 的 total/compute work。

NO0300 的 instructions 和 work 都下降，因此 taken/redirect 即使绝对值持平，per instruction 或 per work 增加也可能
解释单位 work 的 frontend latency。不能只比较绝对 branch 数。

## 4. 判定

- taken/mispredict/redirect density 恶化：进一步用 profile/annotate 映射热 redirect 到 generated compute batch；
- control-flow density 不恶化：转向 op-cache access/miss 和 decoder/op-cache dispatch source；
- 只有可重复且与 NO0317 latency 增量同方向的事件才进入代码候选设计。

