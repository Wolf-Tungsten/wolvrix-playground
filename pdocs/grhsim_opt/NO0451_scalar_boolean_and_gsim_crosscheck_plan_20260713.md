# NO0451 Scalar Boolean AND GSim crosscheck plan

日期：2026-07-13

## 1. Objective

[NO0450](./NO0450_global_compute_scope_attribution_gate_20260713.md) 校正后，`kAnd` 的 629 个 exact-body samples 中只有
206 个属于 payload。其中进一步严格拆为：

| Shape | Stable-name samples / unique values | Anonymous samples | Decision |
| --- | ---: | ---: | --- |
| Scalar Boolean AND | 147 / 144 | 57 | 本阶段候选，共 204 |
| Scalar 64-bit AND | 0 | 1 | 单独低于门槛 |
| Body-end activation helper | 1 / 1 | 0 | 不是 AND payload |

本阶段回答 204 个 scalar Boolean AND samples 中有多少是 GSim 也必须执行的 same-FIR payload，避免把真实 RTL 逻辑误计成
GrhSIM 独有层。这里不修改 emitter、不重新编译，也不采集新 perf。

## 2. Exact connection

输入固定为：

```text
GrhSIM rows: build/logs/xs_perf/no0448/compute_sample_rows.tsv
GSim source: build/xs_gsim_no0255_current_20260710/
             gsim/gsim-compile/model/SimTop*.cpp
```

对 144 个稳定名字做确定性 canonicalization：普通 `$segment` 转成 GSim `__DOT__segment`；GrhSIM 合并表示的
`$inner_<name>` 转成 GSim `__DOT__inner__DOT__<name>`。一次 `rg -F` 扫描全部 3.7 GiB source 建立 occurrence index，避免按值
重复扫描。

每个 value 的结果互斥为：

1. `exact_and_assignment`：同一 canonical LHS 有赋值，RHS 含真正 bitwise `&`；
2. `exact_non_and_assignment`：同一 LHS 可赋值，但 GSim shape 不是 AND；
3. `read_only_occurrence`：名字只作为读端出现；
4. `name_not_found`：exact canonical name 不存在；
5. `anonymous`：57 个 `_val_*`，不做名字猜测。

必须以赋值 LHS 命中，单纯在 GSim 读端出现不能从差异上界扣除。对 `exact_and_assignment` 再记录同一更新 scope 是否存在 old
snapshot、old/new compare（显式 `cond_*` 或 inline `if`）和 activation/oldFlag；这些 boundary 信息用于说明两边代码形态，但
AND assignment 本身已足以证明 payload 不是 GrhSIM 独有。

## 3. Decision gate

以 204 samples/direct `3.056%` 为原始上界：

- 从上界中只扣除 `exact_and_assignment` 对应的动态 samples；
- 57 个 anonymous、name-not-found、read-only 和 non-AND 全部保守留在上界；
- 若残余至少 67 samples/direct 1%，按 residual source family 和 opcode 进入 O3 machine audit；
- 若残余低于 67，停止 scalar Boolean AND emitter 方向，转向 NO0450 预定的跨 operation comment/fused + shared-prelude
  machine shape。

不按 144 个 unique values 均匀分摊 samples，也不因代表性示例相同就外推未命中项。任何 canonicalization 冲突或一个 LHS
出现互相矛盾的赋值 shape 时先停止并修正连接。

## 4. Planned artifacts

```text
build/logs/xs_perf/no0451/analyze_scalar_and_gsim.py
build/logs/xs_perf/no0451/gsim_name_patterns.txt
build/logs/xs_perf/no0451/gsim_occurrences.txt
build/logs/xs_perf/no0451/{value_crosscheck,sample_crosscheck,class_summary}.tsv
build/logs/xs_perf/no0451/analysis_summary.txt
```
