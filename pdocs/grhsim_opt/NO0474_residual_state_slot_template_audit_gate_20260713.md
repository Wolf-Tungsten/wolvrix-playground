# NO0474 Residual state and slot template audit gate

日期：2026-07-13

## 1. Input closure

按 [NO0473](./NO0473_residual_state_slot_template_audit_plan_20260713.md) 对 comment/fused + shared-prelude 的 residual
state/slot payload 做结构归一化。输入精确闭合为 415 samples、404 unique machine offsets、174 exact normalized templates：

- state-ref payload 197；
- slot-expression payload 218。

另外 90 个 operand/read 沿用 NO0444 fused/inline 边界，未合入本轮候选。logical/mux/concat/helper/array-init 均先按历史
ledger 排除。

## 2. Exact template gate

最大 exact template 只有 41 samples/38 unique offsets/direct `0.614%`；第二名为 state nested Boolean network 24，第三名是
已停止的 simple bool-slot AND 24。没有 exact result-type/operator/storage/nesting template 达到 67。

state-ref bool nested-network coarse 总数虽为 120/direct `1.798%`，但拆成的头部 exact templates 为 24/15/13/12/7/7，
其余更小；这些表达式分别实现 masked OR、state compare gates、local/slot conjunction 等不同 FIR 网络。机器 opcode 也分散为
`setne/cmp/or/cmpb/and` 与 SIMD fusion，不能作为同一可替代 class。

## 3. Multi-add purity correction

slot `uint8_t` multi-add coarse 初始为 70，全部 result type 合计 74。源码显示它们是分层 Boolean count tree，而不是可将
`+` 替换成 `|` 的 concat：carry 是 popcount 语义的一部分。

purity gate 逐条要求 RHS 只含 unique bool slots、constant masks/casts/shift/OR，`N` 个 leaves 必须有 `N-1` 个 additions，
且所有 bitwise AND 都是 constant masks。结果为：

| subclass | samples |
| --- | ---: |
| pure 8-input popcount | 41 |
| pure 6-input popcount | 8 |
| pure 9-input popcount | 5 |
| mixed multi-add | 20 |

即使把不同输入数的 pure popcount 作为一个泛化 class，也只有 54/direct `0.809%`；mixed 不能并入。当前 Clang 已对这些树使用
`paddb/pand/pxor/movdqa` 等 SLP 指令，没有 67-sample source gate 支持改为新 helper。

## 4. Remaining coarse classes

其余 coarse classes 均低于门槛：shift-OR pack 60、scalar bitwise 48、simple bool bitwise 35、comparison 23、scalar add 9、
shift-only 3。simple bool bitwise 已由 NO0454--NO0460 停止。

## 5. Decision

最大 exact template 41、最大安全泛化 class pure popcount 54，均低于 67/direct `1%`：

- 不进入 GSim crosscheck 或 generated-copy O3 probe；
- 不把不同 nested Boolean FIR payload 按 state-ref 外观合并；
- 不把 popcount addition 改为 OR，也不新增低覆盖 popcount helper；
- comment/fused + shared-prelude 的 source-template 路线至此关闭。

下一步回到全局域排名，检查尚未用 corrected profile 闭合的 runtime-frame-only、exact side-effect body 或 commit 域，而不是继续
细分低覆盖 source expressions。
