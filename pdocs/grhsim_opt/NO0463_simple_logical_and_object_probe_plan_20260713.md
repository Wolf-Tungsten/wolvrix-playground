# NO0463 Simple logical AND object probe plan

日期：2026-07-13

## 1. Objective

[NO0462](./NO0462_fused_and_prelude_machine_audit_gate_20260713.md) 定位到 114 samples/direct `1.708%` 的
simple-pure logical AND，且 same-FIR GSim payload 没有 C++ `&&` 形态。本阶段只在 NO0357 generated source 副本中把
exact simple forms 的 `&&` 改为 bitwise `&`，验证 production Clang/O3 是否真的消除短路控制流。

不修改 emitter、IR、schedule、tracked source 或 production generated artifacts；本阶段也不运行仿真或 perf。

## 2. Representative objects

选择如下 6 个 compute batches：

| batches | purpose | covered samples |
| --- | --- | ---: |
| 36, 21, 26 | local/bool-slot hotspot | 68 |
| 57, 58 | bool-slot/bool-slot | 10 |
| 65 | bool-slot/local and bool-slot/bool-slot | 2 |
| total | all three operand shapes | 80/114 |

80 samples 占候选 `70.18%`、direct `1.199%`。batch 36 单独覆盖 51 samples，用于检查密集短路链；其余对象防止结论
只依赖单个 TU layout。

## 3. Exact transformation

转换器仅接受单行完整匹配：

```cpp
const bool result = (operand_a) && (operand_b);
```

其中每个 operand 必须是 `grhsim_v<id>_<generation>` 或 `value_bool_slots_[<index>]`。只把中间 token `&&`
替换为 `&`，其余 bytes 保持不变。嵌套表达式、helper call、state storage、constant、comparison、`next_value` 中的复杂式均拒绝。

C++ bool local 天然归一化为 0/1；NO0454 已闭合 `value_bool_slots_` 的 0/1 写入不变量；两侧 operand 都是无副作用读取，
所以 exact candidate 的逻辑值与求值副作用一致。转换后逐文件记录命中数，并复核 source diff 只含目标 token。

## 4. Compile and compare

使用 NO0357 generated header、同一 `grhsim_SimTop.hpp.pch`、`clang++ -std=c++20 -O3` 编译 6 个 candidate objects。
baseline 使用 NO0357 production objects；编译前后逐个核对 production SHA 不变。

对每个对象及 aggregate 统计：

- `.text` bytes 与反汇编 instruction count；
- conditional/unconditional jump count；
- 含 memory operand 的 instruction count；
- call count 与主要 mnemonic delta。

## 5. Decision gate

只有同时满足以下条件才进入默认关闭的 emitter 实现：

1. 6/6 objects 编译成功，转换与 production SHA gate 通过；
2. aggregate instruction count 和 jump count 都下降；
3. aggregate memory-form 不增加，6 个对象中没有明显局部回退；
4. local/bool-slot 与 bool-slot/bool-slot 两类至少各有一个对象得到净收益。

任一硬门禁失败就停止该方向，不做 full emit/build/runtime；通过后也只允许实现 exact simple forms，不能扩展到 NO0462 的
202 个 other logical-AND samples。
