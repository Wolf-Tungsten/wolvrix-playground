# NO0468 Exact OR and static slice residual gate

日期：2026-07-13

## 1. Scope closure

按 [NO0467](./NO0467_exact_or_and_static_slice_residual_plan_20260713.md) 重放 scope-corrected rows 与 same-FIR GSim
source。exact scope 精确闭合为 `kOr=222`、`kSliceStatic=136`；其中 payload 分别为 102/30，其余 120/106 个
read/changed/writeback/activation/runtime-helper samples 均未合入候选。

本阶段没有重新运行仿真、perf 或 candidate 编译。

## 2. Static slice

30 个 `kSliceStatic` payload/direct `0.449%` 的机器码为 11 `mov`、11 `and`、3 `shr`、2 `cmp`，以及各 1 个
`pand/movzbl/movups`。source 全部是 state/local/slot 的必要 shift/mask 或与 consumer 融合后的 load/compare；总量本身低于
67/direct `1%`，也没有与 OR 共享同一个可替代机制。停止 static slice。

## 3. OR source and GSim classes

102 个 `kOr` payload 分为 52 stable-name samples（48 values）与 50 anonymous samples。same-FIR exact-LHS 扫描结果为：

| GSim classification | samples |
| --- | ---: |
| exact OR assignment | 15 |
| stable name missing | 37 |
| anonymous | 50 |

15 个 exact assignments 是共同 FIR OR payload；missing/anonymous 全部保守保留，因此 operation-level 最大上界为
87/direct `1.303%`。但 87 个残余不是单一 source/machine class：

| residual source class | samples | direct share |
| --- | ---: | ---: |
| nested masked OR | 46 | 0.689% |
| simple bool-slot OR | 10 | 0.150% |
| state scalar OR | 9 | 0.135% |
| constant-zero identity OR | 8 | 0.120% |
| bool-slot scalar OR | 7 | 0.105% |
| nested OR | 4 | 0.060% |
| other scalar OR | 3 | 0.045% |

最大 nested-masked class 也只有 46 samples。

## 4. Machine boundary

全部 102 个 OR payload 的头部 opcode 以 `or=35`、`setne=15`、`and=13` 为主；扣除 GSim exact common 后，最大
opcode 类为 `or=26`，其后 `setne=15`、`and=12`。这些分别实现 OR lane、Boolean result normalize 与 nested mask term，
不能跨 source class 合并成一个可删除机制。

8 个 constant-zero source samples 只对应 5 个共享/fused machine addresses：同一 `por` 地址重复 3 samples，其余为
`or/pxor/test`。Clang 已消掉 scalar `0 | value` 本身，line attribution 落在相邻 SIMD/consumer payload；没有独立 identity
指令组可供删除。

## 5. Decision

operation-level 保守上界虽然为 87/direct `1.303%`，但最大同一可替代 source class 只有 46/direct `0.689%`，最大
machine opcode class 只有 26/direct `0.390%`。按 NO0467 预声明 gate：

- 停止 `kOr/kSliceStatic`，不做 generated-copy probe；
- 不重复 full-width helper 或 one-bit byte-result 实验；
- 不把不同 FIR OR/slice payload 仅凭 operation kind 合并过门槛；
- 下一步重新排序 corrected global residual，选择尚未审计且单一 payload 可能达到 direct `1%` 的类别。
