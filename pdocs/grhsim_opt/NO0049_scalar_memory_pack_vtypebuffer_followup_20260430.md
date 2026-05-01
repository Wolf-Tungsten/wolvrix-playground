# Scalar Memory Pack `VTypeBuffer` Follow-up

## 背景

承接：

- [NO0048](./NO0048_scalar_memory_pack_residual_point_cond_direction_20260430.md)

`NO0048` 明确指出，下一步不该再追 `fill` 侧，而应直接吃掉 `VTypeBuffer` 这一类 `multiple point branches` residual。

当时残留特征是：

- `writeCond` 是按 lane 展开的 `Or(And(needAllocVec_i, Eq(addr_i, const)), ...)`
- `data` 不是简单的 mux tree，而是：
  - 一部分是 `Or(And(mask_i, payload_i), ...)`
  - 另一部分是 `Or(Mux(mask_i, payload_i, zero), ...)`

旧实现只能识别“同一个 SSA cond 被 replicate / and 到 data 上”的形态，因此会漏掉：

- `writeCond` 和 `data mask` 分别各自重建一套等价 `And(base, Eq(addr,const))`
- `Mux(mask, payload, zero)` 这种和 `And(mask, payload)` 语义等价的 lowered 形态

## 本次实现

### 1. point mask 支持结构等价匹配

在 [`wolvrix/lib/transform/scalar_memory_pack.cpp`](../../wolvrix/lib/transform/scalar_memory_pack.cpp) 中新增了 `matchesEquivalentPointCondMask(...)`：

- 先保留原有 exact / assign / not / replicate 的 `matchesProjectedCondMask(...)`
- 若 exact 失败，再把 `maskValue` 直接按 point-cond 结构解析
- 只要解析出的：
  - `baseTerms`
  - `addr`
  - `constIndex`
  与目标 point branch 一致，就认为这是同一个 point 条件

这样可以识别：

- `writeCond` 用 `_val_3483997`
- `data` 用 `_vtypeBufferWdataVec_T_1`

虽然它们不是同一个 SSA value，但结构完全等价。

### 2. point data 支持 `Mux(mask, payload, zero)`

在 `parseMaskedPointDataTerm(...)` 中新增保守匹配：

- 若 term 是 `kMux(cond, trueValue, falseValue)`
- 且 `cond` 与目标 point branch 结构等价
- 且 `falseValue` 可证明是全零

则把它直接按 `payload` 处理。

这里故意只接受 `false arm = zero`：

- `Mux(mask, payload, nonzero_default)` 不能安全地等价成 point write
- 本次不做任何“默认值吸收”或“OR 上下文推理”

## 新增测试

在 [`wolvrix/tests/transform/test_scalar_memory_pack.cpp`](../../wolvrix/tests/transform/test_scalar_memory_pack.cpp) 新增两类单测：

- `buildDuplicatedPointMaskWriteDesign()`
  - 验证 `writeCond` / `data mask` 各自重建等价 point cond 仍能命中
- `buildDuplicatedPointMuxMaskWriteDesign()`
  - 验证 `Or(Mux(mask_i, payload_i, zero), ...)` 能被恢复成 memory point writes

本地验证：

- `./wolvrix/build/bin/transform-scalar-memory-pack`
- `ctest --test-dir wolvrix/build --output-on-failure -R transform-scalar-memory-pack`

均通过。

## 真实回放结果

基于现成 replay JSON：

- `build/xs/scalar_memory_pack_replay_from_json_20260430_v8_multi_fill/after_flatten_simplify_plus_scalar_memory_pack.json`

重装当前 editable 包后，直接再跑一次 `scalar-memory-pack`，得到：

- `_op_2299558` 从 reject 变为 accept
- `candidate_clusters`: `4 -> 7`
- `candidate_members`: `256 -> 448`
- `rewritten_clusters`: `4 -> 7`
- `rewritten_members`: `256 -> 448`

更关键的是 residual bucket 变化：

- `failed to parse register write pattern: multiple point-update branches do not encode nextValue as a mux tree over point conditions`
  - 之前：`7 / 448`
  - 现在：`0 / 0`

也就是说，`VTypeBuffer` 这一整组 7 个 sibling clusters 都已经被吃掉：

- `vill`
- `vma`
- `vta`
- `vsew`
- `vlmul`
- `isVsetvl`
- `pdestVl`

## 结论

这一步说明 `scalar-memory-pack` 后续最有效的方向确实不是继续追 `fill`，而是：

- 扩 point-cond 的结构等价匹配
- 吃 lowered 的 point-data 形态

并且这条路已经在真实 XiangShan `VTypeBuffer` residual 上验证有效。

当前 replay 中，`multiple point-update branches` 这一类 residual 已被清零；剩余问题已经不再属于同一个 family。
