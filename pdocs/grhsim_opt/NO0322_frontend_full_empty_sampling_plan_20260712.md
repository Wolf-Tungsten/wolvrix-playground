# NO0322 Frontend full-empty sampling plan

日期：2026-07-12

## 1. 目的

[NO0321](./NO0321_no0286_no0300_op_cache_dispatch_gate_20260712.md) 之后，全局 PMU 已排除 backend
stall、I-cache/ITLB/op-cache miss、decoder supply、taken mispredict 和 redirect 计数增加；唯一与 NO0300 回退
同向的事件是 [NO0317](./NO0317_no0286_no0300_frontend_latency_itlb_gate_20260712.md) 中
`cmask=6` 的 frontend full-empty cycles。本阶段直接 sample 该事件，把增量映射到 generated function 和指令。

## 2. 采样接线门禁

事件：

```text
cpu/de_no_dispatch_per_slot.no_ops_from_frontend,cmask=0x6/u
```

NO0286 `-C 1000`、period `5,000,000`、8 KiB DWARF call graph 探针得到：

```text
samples = 451
event count (approx.) = 2,255,000,000
lost samples = 0
```

样本 IP 能解析到 `GrhSIM_SimTop::eval_compute_batch_*()` 与 `eval_commit_batch_*()`；采样和 symbolization
接线通过。该短跑只作接线检查，不进入热点结论。

## 3. 正式口径

分别运行同一组无 profile NO0286 / NO0300 binary：固定 CPU138、NUMA node 1、CoreMark 两迭代、NEMU
difftest 和 `-C 50000`，事件 period `10,000,000`，保留 8 KiB DWARF call graph。按 NO0317 的总计数估算
old/new 各约 `17k/19k` samples，足以做 phase 和主要 symbol 分布。

profile 插桩与 call-stack unwind 会影响 Host time，因此本轮 timing 不进入性能门禁；性能差异继续使用既有无
record A/B/A。正式 gate 为：

- 两边功能终点一致；
- lost samples 为 0；
- profile event count 与 NO0317 stat 总量方向一致；
- 输出全量 symbol sample/period 报告、compute/commit/eval/other phase 汇总和 top symbol；
- 同名 batch 只有在逻辑映射确认后才能直接比较，不能忘记 NO0303 已证明 old/new batch 内容广泛混排。

## 4. 分析顺序

1. 判断 full-empty 增量主要来自 compute 还是 commit；
2. 列出 new 的 top functions 与 sample 增量来源；
3. 对集中热点做 `perf annotate`，检查落点是否是 branch、call/return、跨页/边界或 helper；
4. 用 generated `_op_<id>` comments 和现有 batch-overlap 工具映射 old/new 逻辑，避免按 batch 编号误配；
5. 只在热点和汇编机制都明确后设计 emitter/layout 候选。

