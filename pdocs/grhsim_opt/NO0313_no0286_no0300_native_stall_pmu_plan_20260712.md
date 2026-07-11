# NO0313 NO0286 / NO0300 native stall PMU plan

日期：2026-07-12

## 1. 目的

[NO0312](./NO0312_no0286_no0300_dynamic_work_gate_20260712.md) 已证明 NO0300 的 dynamic work 比
NO0286 少 `4.30%`，但无插桩 cycles 多 `3.85%`，compute samples/work 回退 `9.33%`。本阶段用无插桩
binary 的 AMD 原生 dispatch 计数器区分该单位成本来自 frontend 供给还是 backend stall。

比较对象保持为已通过 50k 功能门禁的原始无 profile emu：

```text
old = build/xs_grhsim_no0286_commit_change_unlikely_20260711/grhsim/grhsim-compile/emu
new = build/xs_grhsim_no0300_ordered_affine_fresh_20260712/grhsim/grhsim-compile/emu
```

## 2. 事件与运行口径

第一阶段事件：

```text
cycles:u
instructions:u
ic_tag_hit_miss.all_instruction_cache_accesses:u
ic_tag_hit_miss.instruction_cache_miss:u
de_no_dispatch_per_slot.no_ops_from_frontend:u
de_no_dispatch_per_slot.backend_stalls:u
```

其中两个 `de_no_dispatch_per_slot` 事件为 slot count，必须同时报告绝对值和每 host cycle 的归一化值。
执行顺序 old / new / old，固定 CPU138 和 NUMA node 1；每次运行 CoreMark 两迭代、NEMU difftest、
`-C 50000`。开始前检查 CPU138 及 SMT sibling CPU330 的空闲度，全部事件必须 `100%` 调度，两次 old
spread 必须显著小于候选差异。

## 3. 分支判定

- frontend empty slots/cycle 恶化而 backend stalls/cycle 不恶化：补 ITLB/取指事件并回到函数/section 布局；
- backend stalls/cycle 恶化：补 L1D/DTLB、load/store dispatch 与资源 stall 事件；
- 两者都不恶化：检查 retire/speculation 类事件和长延迟指令 mix；
- 无论 PMU 方向如何，都必须与 NO0303 的 compute/commit cycles sample 分解一起解释，不能仅凭全局 counter
  猜测某个 generated batch。

## 4. 验收

- 三次功能终点一致，无 mismatch/assertion；
- 所有事件 100% 调度；
- old baseline spread 足够小；
- 得到 frontend/backend 的明确方向后，再决定第二阶段事件，不预先同时运行全部 cache/TLB 组合。

