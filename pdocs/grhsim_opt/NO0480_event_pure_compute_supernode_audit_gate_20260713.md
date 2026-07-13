# NO0480 Event-pure compute supernode audit gate

日期：2026-07-13

## 1. Full audit result

按 [NO0479](./NO0479_event_pure_compute_supernode_audit_plan_20260713.md) 扫描 NO0357 的 66 个 compute TUs，共解析
63,241 个 supernodes。保守结构 gate 得到：

| item | count |
|---|---:|
| event-pure supernodes | 1,611 |
| covered compute batches | 48 |
| transient producer declarations | 8,246 |
| SystemTask conditions | 6,006 |
| DPIC conditions | 5,466 |

1,609/1,611 supernodes 共享 `event_edge_slots_[0] == posedge`；另两个分别为 slot 5/149 posedge，均无 profile
sample。rejections 为 external write 369、mixed event keys 24、non-side-effect control 6、unknown assignment 5；其余
61,226 个没有 explicit-event side effect。

event-pure 判定只接受 lexical local producer + 同一 exact edge 的 SystemTask/DPIC。materialized value/state/memory write、
activation/change propagation、其他 call 和 mixed edge 均未纳入。

## 2. Profile coverage

连接 NO0448 固定 5,590 compute profile rows，只计入 supernode payload source span，不计 active-word scan/clear：

| ownership | samples | direct % |
|---|---:|---:|
| comment/fused producer | 185 | 2.772% |
| exact side-effect body | 104 | 1.558% |
| shared supernode prelude | 19 | 0.285% |
| total | 308 | 4.614% |

308/308 samples 均属于 clock slot 0 posedge supernodes。该数值是完整 payload 上界：posedge 时 producer 与 condition 仍须执行；
outer guard 实际只能回收 edge-false activations。进入 runtime 前必须另测 event hit/miss 频率，不能把 4.614% 直接当作收益。

## 3. Manual closure

抽查 hot supernodes 41912（batch 35）、11509（batch 16）和代表 supernode 23604（batch 21）：

- active bit 在 payload scope 外正常清除；
- payload 只读取 value/state slots 并形成 scalar/wide lexical locals；
- 所有可见调用都在同一 clock-posedge exact guard 内；
- payload 不写 materialized slot/state，也不设置 downstream activity。

其中 supernode 11509 在 event guard 前复制 256-bit state arrays，并执行 wide shift/slice/compare；这说明 edge-false 空转不只包含
简单 bool test。

## 4. GSim boundary

same-FIR GSim 对应 assertion producer 与 `gAssert` 位于同一个 `oldFlag` block，没有逐 side-effect exact-edge C++ guard。
全量 source 静态计数为 GSim `gAssert` 6,243；GrhSIM 则有 SystemTask 7,236、DPIC 6,526。代表 assertion 在 GrhSIM
通常拆成同条件的 SystemTask + DPIC，GSim 用单一 `gAssert` 表达。

该对照不能据此删除任一 GrhSIM side effect，但确认两侧 control-flow shape 不同；outer grouping 后仍需观察成对 call boundary 是否
保留额外 guard/materialization。

## 5. Decision

308 samples/direct 4.614% 通过 NO0479 的 1% gate，进入 generated-copy outer event guard object probe。优先 batches
58/21/35/41/24/30，合计 855 个 event-pure supernodes、4,527 producers、5,583 side effects、151 samples/direct
2.262%。本阶段仍不修改 emitter 或运行 SimTop。
