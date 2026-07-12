# NO0469 Wide concat dynamic-select recovery plan

日期：2026-07-13

## 1. Signal

[NO0468](./NO0468_exact_or_and_static_slice_residual_gate_20260713.md) 之后重新归一化 comment/fused 与 shared-prelude
payload，发现 direct-wide-concat accumulation 是新的统一类：

| metric | count |
| --- | ---: |
| sampled `dst[word] |= concat_*_bits_*` rows | 113 |
| unique source locations / machine offsets | 113 / 113 |
| comment/fused / shared-prelude | 87 / 26 |
| direct share | 1.693% |
| static accumulation lines in 66 compute TUs | 201,597 |

样本 opcode 为 `or=51`、`mov=26`、`shl=21`，其余是 SIMD/load/shift。代表组先构造 1064-bit/512-bit concat，随后
分别做 dynamic wide shift 或 1-bit dynamic slice；因此要审计的是“物化整个 concat 后只动态选择小结果”，不是单条 OR。

## 2. Existing bypass boundary

current emitter 已有两类结构恢复：

- `svPackedArray` attribute + `kSliceArray` 的 packed-array lane view；
- `regToMem.intent.mode=array-index` 的 register-read concat + `kSliceArray/kSliceDynamic` direct storage access。

热点仍进入 `emitDirectWideConcatOperation`，说明 matcher 未覆盖。已观察到的边界包括 concat operands 已是同一
`kMemoryReadPort` 的多行读取，以及没有 reg-to-mem intent 的规则 `kRegisterReadPort` storage 序列。本阶段先证明失配原因与
可恢复结构，不放宽 emitter。

## 3. Audit method

对 113 个 sample 从 source block 反向恢复 concat group，并连接紧随其后的 consumer：

1. result words、operand count/width、destination local/materialized；
2. operand def family：同 memory read、规则 register-state stride、mixed/other；
3. consumer kind：dynamic slice/array slice/dynamic shift/static/multiple users；
4. result width 与 selected width、index source、out-of-range semantics；
5. 现有 packed-array/reg-to-mem bypass 的具体失败条件。

同一 machine offset 只计一次；sample 与 group/consumer 连接不成功时保留 unresolved，不靠最近 comment 推断。

## 4. GSim crosscheck

对可恢复组的 stable consumer/result names 搜索 same-FIR GSim source，检查 GSim 是否保留 array/indexed read，还是也物化宽
concat。anonymous 组只作保守上界。只有 GSim 不共有的 full-pack work 才视为 GrhSIM-specific candidate。

## 5. Decision gate

只有同一个安全 matcher class 同时满足以下条件，才进入结构诊断或 generated-copy O3 probe：

1. 覆盖至少 67 samples/direct `1%`；
2. concat 只有受支持的 dynamic-select consumers，或能逐 user 独立绕过且不改变其他 users；
3. operand storage/index mapping、lane order 与越界返回零语义可证明；
4. 不重复 current reg-to-mem intent/packed-array 已命中的结构。

后续 probe 必须删除代表组的 full concat assembly，whole-object instructions/memory-form/jumps 均不增。若任一结构条件不足，
停止该类，不用 source regex 在 production emitter 中猜 storage layout。
