# NO0453 Boolean byte normalization machine audit plan

日期：2026-07-13

## 1. Objective

[NO0452](./NO0452_scalar_boolean_and_gsim_crosscheck_gate_20260713.md) 保留 170/direct `2.547%` 的 strict GSim residual，
并发现 GrhSIM scalar Boolean AND source 经常把 byte storage 逐 operand 转成 C++ `bool`。由于 exact-common 的 34 个 AND 也
可能使用比 GSim 更多的 normalization，本阶段审计全部 204 个 payload samples，而不是只审计 residual。

当前 source 形态为：

| Source property | Samples |
| --- | ---: |
| At least one `static_cast<bool>` | 159 |
| At least one packed `uint8_t` state read | 105 |
| Zero explicit bool cast | 45 |
| Exactly two materialized bool slots, zero cast/state read | 41 |

代表块中 `value_bool_slots_[a] & value_bool_slots_[b]` 已被 O3 合并为 `test byte,byte`，但随后仍有 `setne` 把结果规范成
C++ `bool`，之后才与旧 slot 比较。这里 `test` 是真实 AND，`setne` 才可能是 GrhSIM byte-storage 实现额外引入的层。

## 2. Fixed machine input

复用 NO0401 的 66 个 line-table objects：

```text
build/logs/xs_perf/no0401/grhsim_SimTop_sched_{0..65}_dbg.o
```

NO0402/NO0404 已逐 `.text` SHA 证明其与 NO0357 production O3 objects 相同；本阶段不重编 SimTop、不运行仿真或 perf。按
NO0451 的 204 个 batch/object offsets 提取所在基本块及前后数据流，不能只按 mnemonic 分类。

每个 sampled IP 互斥归入：

1. `operand_normalize`：对一个 byte operand 做 compare/test + setcc 后再参与 AND；
2. `result_normalize`：AND 已完成，单独 setcc 转成 0/1 result；
3. `necessary_and_or_load`：真实 AND/test/pand 或必要 operand load；
4. `changed_compare_or_activation`：与旧 result 比较、生成 changed 或激活 mask；
5. `consumer_fusion`：AND 已与 compare/select/consumer 合并，不能单独删除；
6. `copy_spill_control_or_unresolved`：保守留存。

分类以 sampled instruction 的 def/use 和同基本块邻接为依据；同一 source line 上的真实 `test` 与 normalization `setne` 必须拆开。

## 3. O3 realization probe

从高频 source shape 各抽一个 standalone 函数，用当前 SimTop compiler flags 比较：

- current `const bool next = bool(a) & bool(b)`；
- byte result `const uint8_t next = a & b`；
- 对 byte operand 显式声明 0/1 invariant 后的 Boolean expression。

要求 candidate 版本在 O3 汇编中真实减少 compare/setcc，而不是只改变 C++ 拼写；同时不能增加 branch、load/store 或延长 live
range。probe 只证明机器可实现性，不代替 SimTop 动态收益。

## 4. 0/1 invariant gate

任何省略 normalization 的 emitter 实验前，必须闭合：

1. `value_bool_slots_` 的初始化和所有写路径只写 0/1；
2. packed 1-bit state 的 init、scalar/memory commit、checkpoint restore 只产生 0/1；
3. public input、DPI、memory mask、random init 等边界在进入 byte storage 前已截断到 1 bit；
4. 不能依赖 C++ `bool` 的 object representation 去 alias packed byte storage。

若只能证明 materialized value slots、不能证明 packed state，则候选严格限定在 value-slot operands/result，不把 state reads 一并
放宽。

## 5. Decision gate

- `operand_normalize + result_normalize` 必须至少 67 samples/direct 1%；
- O3 probe 至少删除一条目标机器指令，且无新 branch/memory instruction；
- 不把 necessary AND、changed compare 或 consumer fusion计入收益上界；
- 任一 0/1 写入来源不能闭合时停止对应范围。

通过后才新增最小 emitter 开关和单元测试，再 fresh emit 一个代表 sched object 做 `.text` probe；未通过则停止 scalar Boolean
normalization，转向跨 operation shared prelude。

## 6. Planned artifacts

```text
build/logs/xs_perf/no0453/analyze_boolean_machine.py
build/logs/xs_perf/no0453/{sample_machine_rows,class_summary,source_shape_summary}.tsv
build/logs/xs_perf/no0453/representative_blocks.txt
build/logs/xs_perf/no0453/boolean_normalization_probe.{cpp,s,summary.txt}
build/logs/xs_perf/no0453/invariant_audit.txt
build/logs/xs_perf/no0453/analysis_summary.txt
```
