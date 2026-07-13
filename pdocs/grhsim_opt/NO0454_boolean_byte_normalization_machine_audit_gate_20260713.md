# NO0454 Boolean byte normalization machine audit gate

日期：2026-07-13

## 1. Machine input and correction

按 [NO0453](./NO0453_boolean_byte_normalization_machine_audit_plan_20260713.md)，本轮复用 NO0401 中与 NO0357 production
`.text` byte-identical 的 line-table objects，连接 NO0451 的全部 204 个 scalar Boolean AND samples/54 batches；没有重编
SimTop、运行仿真或采集 perf。最终 analyzer exit 0，wall `30.64s`，maximum RSS `5,958,312 KiB`，204/204 object offsets
均精确命中。

首轮保守 def/use 规则得到 48 normalization samples，但人工检查 22 个 unresolved 发现：第一个 byte 的 `cmp/setne` 与最终
AND 之间插入了第二个 operand 的 compare/setcc，旧规则遇到中间 flag writer 就停止，尽管目标寄存器没有被覆盖。修正规则只
允许跨越不改写目标寄存器的 compare；遇到寄存器覆盖、control 或先被 changed compare 消费仍停止。修正后原 22 项中 21 项
明确连接到 bitwise consumer，1 项继续 unresolved；没有通过放宽 source kind 或按 mnemonic 猜测来扩大候选。

## 2. Basic-block classification

最终互斥分类为：

| Machine class | Samples | Direct total share | Interpretation |
| --- | ---: | ---: | --- |
| Necessary AND / load | 72 | 1.079% | `and/test/pand` 与必要数据搬运 |
| Operand normalization | 57 | 0.854% | 25 `cmpb` + 32 `setne`，结果明确进入后续 AND |
| Consumer / nested-op fusion | 50 | 0.749% | Eq/Not、SIMD、OR/shift 等真实 payload |
| Result normalization | 12 | 0.180% | AND/OR/test 已完成后的独立 `setne` |
| Changed compare / activation | 10 | 0.150% | old/new 与变更传播，不计候选 |
| Control / unresolved | 3 | 0.045% | 2 control + 1 无法证明的 setne |

`operand_normalization + result_normalization = 69 samples/direct 1.033708%`，刚超过 67/direct 1% 门槛。代表块分别显示：

```asm
cmpb $0, state_byte
setne operand_bit
and   value_slot, operand_bit
```

以及：

```asm
test  value_slot_a, value_slot_b  # real AND
setne result_bit                  # separate result normalization
```

前者的 compare/setcc、后者仅 setcc 进入上界；真实 `and/test`、changed compare 和 activation 均未计入。

## 3. O3 realization probe

使用 SimTop 同一 Clang 21.1.5、`-std=c++20 -O3`，保留 changed compare、activation mask 和 result writeback。表内指令数
排除 alignment nop、包含 `ret`：

| Shape | Current bool | Assumed byte + byte result | Assume leaf + bool result | Explicit `&1` byte |
| --- | ---: | ---: | ---: | ---: |
| Two packed state bytes | 11 | 8 | 11 | 9 |
| Packed state + value slot | 9 | 8 | 11 | 9 |
| OR chain then AND | 14 | 11 | 13 | 16 |

只有 assumed-byte operands + `uint8_t` result 在三种 shape 都减少 `3/1/3` 条指令，memory-form 数分别保持 `5/5/8`，三组都
没有条件 branch。单纯 raw byte 的 OR chain 被 SLP 成 15 条 SIMD instructions；显式 `&1` 为 16 条；只给 leaf 加 assume、
仍保留 bool result 不能删 state2 normalization，且 state+slot 回退到 11 条。因此后三种实现均拒绝，不能把“去掉 cast”当成
等价方案。

## 4. 0/1 invariant audit

代码路径与 current SimTop generated source 双侧闭合：

- width-1 GRH value/state 的语义 C++ 类型由 `logicCppType` 定为 `bool`；`uint8_t` 仅是 typed bucket/packed storage；
- current SimTop 640,983 条 `value_bool_slots_` 直接赋值中，625,355 来自 `next_value`；614,098 个近邻声明为
  `const bool`，11,241 个 `auto` 来自 bool reg-to-mem row，16 个长 activation block 人工确认仍为 `const bool`；
- 其余为 11,241 个 bit constants、688 个显式 bool cast、3,695 个 width-1 direct state reads 和 4 个 bool DPI outputs；
- value bucket/state storage 均先清零；literal/random init 对 width 1 cast 为 bool；memory fill/direct write 按 width 截断；
- scalar register/latch commit 的 `state.cppType=bool`；bool shadow/table/range helper 均以 `& UINT8_C(1)` 截断后写 state；
- public width-1 port 和 DPI 参数使用 bool；未发现可从外部 raw overwrite 私有 `state_logic_storage_` 的 model restore API。

因此正常 generated-model execution 下，Boolean value slot 与 packed width-1 state byte 都保持 0/1。候选可以在读取 byte 时向
编译器声明该范围，但必须保留所有写侧 cast/truncation，也不能把 packed byte alias 成 C++ `bool&`。

## 5. Decision

机器覆盖、O3 realization 和 0/1 invariant 三道 gate 均通过，允许进入最小 emitter 实现设计；本篇仍未修改 emitter。候选必须
同时满足：

1. 只作用于 width-1 bitwise expression；
2. byte operands 显式携带 0/1 compiler assumption；
3. 中间/result 使用 byte bit 表示，不能立即转回 C++ bool；
4. change tracking、activation 和写侧截断完全保持。

由于动态上界只比门槛多 2 samples，下一阶段先加默认关闭开关、单元生成测试和小 O3 probe；随后 fresh emit 代表 SimTop
sched object，要求目标 compare/setcc 真实减少且整体 `.text`/branch/load 不恶化，再决定是否进行完整 build/功能回归。

产物：

```text
build/logs/xs_perf/no0453/analyze_boolean_machine.py
build/logs/xs_perf/no0453/{sample_machine_rows,class_summary,source_shape_summary}.tsv
build/logs/xs_perf/no0453/representative_blocks.txt
build/logs/xs_perf/no0453/boolean_normalization_probe.{cpp,s,o,summary.txt}
build/logs/xs_perf/no0453/invariant_audit.txt
build/logs/xs_perf/no0453/analysis_summary.txt
```
