# NO0478 Side-effect event-first object probe gate

日期：2026-07-13

## 1. Scope gate

按 [NO0477](./NO0477_side_effect_event_first_object_probe_plan_20260713.md) 在 generated source 副本中重排 exact-event
side-effect 条件。batches 21/24/35/58/20/27/41 共修改 6,013 行：

- `kSystemTask` 3,147 行；
- `kDpicCall` 2,866 行；
- 6,013/6,013 均为 `event_edge_slots_[0] == grhsim_event_edge_kind::posedge`；
- 仅重排 balanced top-level `&&` parts，不改 call body 或无 explicit event 的 side effect。

7 组 baseline/candidate 均使用 NO0357 PCH、`clang++ -std=c++20 -O3` 编译成功且无诊断。baseline rebuild
`.text` 逐对象等于 production，production object SHA 前后不变。

## 2. Whole-object result

| metric | baseline | candidate | delta | delta % |
|---|---:|---:|---:|---:|
| `.text` bytes | 7,033,131 | 7,087,824 | +54,693 | +0.778% |
| instructions | 1,476,699 | 1,495,899 | +19,200 | +1.300% |
| memory-form | 617,541 | 619,479 | +1,938 | +0.314% |
| jumps | 44,086 | 41,955 | -2,131 | -4.834% |
| calls | 6,972 | 6,972 | 0 | 0.000% |

7/7 objects 的 instruction count 都增加，范围为 +1,008 到 +5,507。主要 mnemonic delta 为 `cmp +7,594`、
`movzbl +6,113`、`sete +2,791`、`or +2,786`、`setne +2,398`、`and +1,885`、`test +1,850`；
同时 `cmpb -6,323`、`jne -1,102`、`je -948`。candidate 用 boolean materialization 合并了部分控制流，换来的静态工作明显更多。

## 3. Negedge path proof

batch 21 首个代表块在 source lines 69/70 先计算两个 assertion condition；其中包含四次 bool-slot load、mask、add、compare、
`setcc` 与逻辑合并。SystemTask condition 位于 line 73。

debug objects 显示：

- baseline 和 candidate 都在 line 73 的 edge 检查之前执行完整的 lines 69/70 machine sequence；
- baseline line 73 先 `test data`，再 load/cmp `event_edge_slots_[0]`；
- candidate line 73 先 load/cmp event，再 `test data`，但此时 data producer 已经执行；
- 后续成对 SystemTask/DPIC 使 candidate 出现额外 `setne/or/test` 序列。

因此 candidate 在 negedge 只可能少执行 `if` 内对已物化 local 的测试，不能跳过真正的 data-condition work，不满足 NO0477 的
“edge-false 跳过 data work”要求。

## 4. Gate conclusion

停止 exact side-effect `&&` reorder：它同时违反 aggregate instructions/memory-form 不增加 gate 和 negedge data-work skip gate，
不进入 emitter implementation 或 runtime A/B。

下一条独立路线只能把 event guard 提升到 side-effect condition 的 producer 之前。需先审计 producer 是否只被同 edge 的连续
SystemTask/DPIC cluster 消费；只有 exclusive producer chain 才能安全放进 outer posedge guard，并须保留 schedule order 与 value
可见性。不能把本次失败的条件重排扩大到生产代码。
