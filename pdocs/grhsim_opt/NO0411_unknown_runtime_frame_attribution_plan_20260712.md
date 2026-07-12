# NO0411 Unknown runtime-frame attribution plan

日期：2026-07-12

## 1. Problem

[NO0410](./NO0410_deferred_activation_cost_audit_gate_20260712.md) 已关闭 current change-tracking 改写。回到
[NO0404](./NO0404_global_compute_machine_source_attribution_gate_20260712.md) 的 generic runtime helper，907 个 samples 中
仍有 147 个没有 helper name，约为 direct compute `2.63% / 3.675B` instructions，是尚未归因的最大单桶。

这 147 个 samples 全部带 runtime inline frame，但 DWARF location 是 `grhsim_SimTop_runtime.hpp:?` / line 0；现有脚本
按 definition line 二分查找，因此无法命名。它们不是没有 runtime frame，也不能直接并入 generated payload。

## 2. Exact-code preflight

先对 samples 较集中的 compute17/33 使用完整 `-g` 重编。两份 `.text` SHA256 均与 production 完全相同：

```text
batch17 963e8cb124efae50652b9f1d5ce447ef7f915d1d8ec0ad8c48cf2e69b25ffdbf
batch33 614fd3439df155796f093f1e5c4b239fd32a4f5258546ef66ec9f649f9fc838d
```

full debug 仍只返回 runtime header line 0，没有新增 inline helper DIE；因此不扩展 full-debug 编译，继续复用 NO0401
66/66 byte-identical line-table objects。

## 3. Strict basic-block attribution

对每个 unknown sample：

1. 在对应 production-identical object 中定位 exact instruction；
2. 以 control-transfer 指令划分 basic block，只在同 block 内搜索；
3. 分别寻找 sample 前后最近的 generated sched source line，最大半径 32 instructions；
4. 只有双侧 caller 行属于同一 supernode，且 operation marker 相同或一侧仍在同一 operation body 时才接受；
5. 从 caller source expression、operation kind和邻近 runtime-known instructions恢复 helper/语义类。

双侧不一致、跨 operation、只有 runtime line 0 或超出半径的样本保持 unresolved。另做半径 64 sensitivity，只用于报告
上界，不能覆盖严格结果。

## 4. Machine classes

恢复结果按互斥类统计：

- wide slice/index/shift；
- wide concat/insert/cast；
- wide arithmetic/reduction；
- storage/reference/materialization；
- changed/activation fusion；
- compiler spill/copy/control；
- unresolved。

同时报告 opcode、stack operand、batch、supernode 和 operation 分布。`mov/or/and` 不能脱离 caller 语义直接判为可删；
只有明确的 copy/spill 才进入 removable upper。

## 5. Decision

只有同一可泛化 helper/语义类满足以下条件才进入代码 probe：

1. 严格归属至少 56 samples，即 direct compute 5,590 samples 的 1%；
2. 覆盖 unknown 桶至少 20%；
3. 代表 basic blocks 中存在可删除的 machine work，而不是 helper 的真实 payload或 register allocation结果。

若没有单类达到 56 samples，则把 147 个 line-0 samples按恢复后的 payload/spill 类并回 NO0404，不修改 emitter，继续下一个
超过 1% 的全局 payload shape。

