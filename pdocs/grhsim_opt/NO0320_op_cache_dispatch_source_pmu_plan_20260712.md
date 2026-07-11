# NO0320 Op-cache and dispatch-source PMU plan

日期：2026-07-12

## 1. 目的

[NO0317](./NO0317_no0286_no0300_frontend_latency_itlb_gate_20260712.md) 将 NO0300 回退定位到非
I-cache/ITLB miss 的整周期 frontend 断供；[NO0319](./NO0319_no0286_no0300_control_flow_redirect_gate_20260712.md)
又排除了 taken branch、mispredict、decoder redirect 和 resync 计数增加。本阶段检查 op cache 是否因代码布局变化
产生更多 miss，并观察实际 dispatched ops 更偏 decoder 还是 op cache。

## 2. 事件

```text
cycles:u
op_cache_hit_miss.all_op_cache_accesses:u
op_cache_hit_miss.op_cache_miss:u
de_src_op_disp.decoder:u
de_src_op_disp.op_cache:u
```

派生并报告：

```text
op_cache_miss_rate = op_cache_miss / all_op_cache_accesses
op_cache_dispatch_share = op_cache_dispatch / (decoder_dispatch + op_cache_dispatch)
```

loop-buffer dispatch 未放入本组；若 decoder + op-cache 的总量或份额不能闭合，再单独检查 loop buffer，避免首轮
超过原生计数器容量。NO0286 `-C 100` 探针已确认五项均 `100.00%` 调度；其数值不进入性能结论。

## 3. 运行门禁

继续使用同一组无 profile NO0286 / NO0300 binary，执行 old / new / old，固定 CPU138、NUMA node 1、
CoreMark 两迭代、NEMU difftest 和 `-C 50000`。每轮前检查 CPU138/330 及全机 load；要求功能终点一致、
全部事件 `100%`，且 old Host time/cycles spread 显著小于候选差异。

所有事件同时报告绝对值、per host cycle、per [NO0312](./NO0312_no0286_no0300_dynamic_work_gate_20260712.md)
`work_total` 和 per [NO0302](./NO0302_ordered_memory_write_affine_overall_50k_gate_20260712.md) instruction，
避免 NO0300 的动态工作下降掩盖单位工作 op-cache 压力。

## 4. 判定

- miss rate 或 miss/work 恶化且与 latency 增量同向：检查 generated function/basic-block 的 op-cache 覆盖与边界；
- decoder share 上升：检查 NO0300 batch 重排后无法从 op cache 稳定供给的代码区域；
- op-cache 指标全部改善：停止扩大全局 PMU 列表，转为 sample full-empty frontend latency 并映射到函数；
- 任一方向都必须结合 NO0303 的 compute/commit profile，不能只凭全局计数设计 emitter 改动。

