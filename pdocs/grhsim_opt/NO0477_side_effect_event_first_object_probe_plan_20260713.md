# NO0477 Side-effect event-first object probe plan

日期：2026-07-13

## 1. Signal

[NO0476](./NO0476_corrected_runtime_frame_closure_gate_20260713.md) 后审计 exact side-effect body：130/130 samples 全落在
`if` condition，127 个 `kSystemTask`、3 个 `kDpicCall`；130/130 都要求 posedge，129 个检查 `event_edge_slots_[0]`。

current generated order 为：

```cpp
if ((data_condition) && (event_edge == posedge) && (proc_guard)) { ... }
```

因此 negedge eval 先求 data condition，再因 event edge 短路。candidate 只交换纯条件顺序：

```cpp
if ((event_edge == posedge) && (proc_guard) && (data_condition)) { ... }
```

DPIC 没有 proc guard，改为 event first + data condition。三部分均为生成的纯读取/逻辑表达式，call body 与执行次数语义不变。

## 2. Representative objects

选择 batches 21/24/35/58/20/27/41，分别覆盖 19/14/11/8/7/6/5 个 samples，合计 70/130、direct
`1.049%`。这些 batches 静态 event conditions 也覆盖主要规模，避免只依赖一个 TU。

## 3. Generated-copy transformation

用 balanced-parenthesis parser 只匹配带 `event_edge_slots_[N] == grhsim_event_edge_kind::{pos,neg}edge` 的 side-effect
`if` 单行。要求：

- system task 精确拆成 data/event/proc 三个 top-level `&&` parts；
- DPIC 精确拆成 data/event 两个 parts；
- before/after 只重排完整 parts，call body 和其余 source byte-exact；
- 不修改 commit 中已由 outer dispatch 处理、因而没有 explicit event part 的 side effects。

## 4. Compile and machine gate

使用 NO0357 header/PCH、`clang++ -std=c++20 -O3` 编 candidate objects；unchanged source rebuild `.text` 必须与 production
一致，production SHA 前后不变。

该优化减少的是 negedge 动态路径，不要求静态 instruction/jump 数下降。进入 emitter implementation 的条件是：

1. 7/7 compile 与 transform scope gate 通过；
2. aggregate whole-object instructions、memory-form、jumps 均不增加，单对象无明显回退；
3. candidate sampled/representative blocks 中，edge-false control transfer 位于 data-condition work 之前，并跳过后者；
4. baseline 尚未由 Clang 自动形成相同 edge-first control flow。

若 objects byte-identical 或不能证明 negedge skipped work，则停止。通过后才实现默认关闭开关和功能测试，不能直接跑 runtime。
