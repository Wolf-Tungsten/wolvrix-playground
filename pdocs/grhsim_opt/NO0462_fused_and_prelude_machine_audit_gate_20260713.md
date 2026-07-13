# NO0462 Fused and prelude machine audit gate

日期：2026-07-13

## 1. Inputs and closure

本阶段只重放 [NO0461](./NO0461_fused_and_prelude_machine_audit_plan_20260713.md) 指定的既有 artifacts：

```text
samples: build/logs/xs_perf/no0448/compute_sample_rows.tsv
source:  build/xs_grhsim_no0357_direct_state_read_20260712/grhsim/grhsim_emit
objects: build/logs/xs_perf/no0401/grhsim_SimTop_sched_*_debug_pch.o
GSim:    build/xs_gsim_no0255_current_20260710/gsim/gsim-compile/model
audit:   build/logs/xs_perf/no0461
```

目标 ownership 精确闭合为 comment-only/compiler-fused 1,210 与 shared-supernode-prelude 489，共
1,699/1,699 samples。所有候选 sample offsets 均命中 NO0401 的 production-identical line-table objects；没有重新运行
仿真、采集 perf 或借用 NO0457 candidate objects。

## 2. Residual source classes

扣除已审计 mux、full-width logic、activation/dispatch、register read 与 assign 后，1,699 个目标中有 316 个 source rows
包含逻辑与。进一步只接受如下无副作用的两操作数形式：

```cpp
const bool result = (grhsim_v...) && (value_bool_slots_[...]);
const bool result = (value_bool_slots_[...]) && (value_bool_slots_[...]);
const bool result = (value_bool_slots_[...]) && (grhsim_v...);
```

嵌套表达式、state helper、常量、比较与任意非上述 operand 均保留在 `other_logical_and`。互斥结果为：

| source class | samples | direct share |
| --- | ---: | ---: |
| not logical AND | 1,383 | 20.719% |
| other logical AND | 202 | 3.026% |
| simple pure logical AND | 114 | 1.708% |

114 个样本对应 111 个唯一 source locations，全部是 payload；operand shape 为 local/bool-slot 80、bool-slot/bool-slot
33、bool-slot/local 1。batch 36 单独覆盖 51 samples，其余分散于 21 个 batches。

## 3. Machine evidence

114 个样本的头部 opcodes 为 `cmpb=60`、`setne=31`，其余包括 10 个直接 `je/jmp`、7 个 load/move、
4 个 `test` 及 2 个 SIMD/copy instructions。以 sample instruction 为起点向后 12 条扫描，84/114 可见 control
instruction，其中 76 个为 `je/jne`；最常见形态是当前 `cmpb/setne` 后 1--2 条出现远跳 `je`。

因此该类不是仅有 source spelling 差异：production O3 仍为短路语义保留了可采样的 compare/setcc/branch control。
但 sample line 可能覆盖融合 consumer，不能把 114 全部当成可删除 branch 数，也不能从 samples 直接预测 cycles。

## 4. Same-FIR GSim boundary

3.7 GiB same-FIR GSim generated C++ 中共有 84,602 行包含 ` && `；逐行排查后 84,602/84,602 全部是：

```cpp
if (cycles >= LOG_START && cycles <= LOG_END) {
```

GSim payload 中没有逻辑与 source line。相对地，GrhSIM 66 个 sampled compute TUs 中上述 simple-pure form 静态出现
83,363 行。这证明“payload 逻辑与使用 C++ 短路表达式”是 GrhSIM-specific generated-code shape。

该证据不证明 GSim 删除了相同 FIR payload：NO0404 已显示 GSim 会把 Boolean work 融入 local/payload lines，且可能使用
bitwise expression。stable/anonymous value 也没有在本阶段重新建立一一 crosswalk。因此 GSim 对照只用于确认 code-shape
差异，114 samples 仍按保守上界进入 probe。

## 5. Decision

simple-pure class 为 114 samples/direct `1.708%`，超过预声明的 67 samples/direct `1%` 门槛，允许进入局部
generated-copy O3 probe。probe 只能把上述三种 exact forms 的 `&&` 替换为 `&`：C++ `bool` local 为 0/1，
`value_bool_slots_` 的 0/1 write invariant 已由 NO0454 闭合，且两侧 operand 无副作用。

下一步先覆盖 batch 36 的 local/bool-slot 热点及 bool-slot/bool-slot 代表 batches。只有 representative objects 的 aggregate
instructions 与 branches 同时下降、memory forms 不增，才考虑默认关闭的 emitter 实现；否则停止该类。此阶段未修改 emitter。
