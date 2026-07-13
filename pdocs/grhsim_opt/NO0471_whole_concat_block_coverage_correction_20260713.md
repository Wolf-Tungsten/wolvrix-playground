# NO0471 Whole concat block coverage correction

日期：2026-07-13

## 1. Correction

[NO0470](./NO0470_wide_concat_dynamic_select_recovery_gate_20260713.md) 以 113 个 `dst[word] |= concat_*_bits_*`
accumulation samples 计算 safe matcher coverage。归档后复核发现，如果候选绕过整个 concat，`const concat_*_bits` term
declaration 上的 samples 也必须计入，113 不能直接称为 whole-block 上界。

本次保留 NO0470 原结果，新增一次 5,590-row source-range join：以已解析的 61 个 concat groups 的首个 term 到最后一个
accumulation 为闭区间，连接全部 source-backed samples；不扩大 group 集合，也不使用 nearest comment。

## 2. Corrected coverage

whole-block 结果为 129 samples、129 unique machine offsets，比 accumulation-only 多 16：

| consumer | accumulation-only | whole block |
| --- | ---: | ---: |
| materialized/external | 28 | 34 |
| dynamic wide shift | 28 | 29 |
| dynamic slice | 17 | 22 |
| single other consumer | 18 | 20 |
| other slice | 12 | 13 |
| multiple other consumers | 10 | 11 |

新增 16 个主要是 term-declaration payload，另有 1 个 operand/state-read；没有新的 consumer class。

## 3. Corrected safe gate

local single-consumer whole-block 上界由 NO0470 的 57 修正为 62 samples/direct `0.929%`：

- dynamic wide shift 29；
- local dynamic slice 13；
- single other consumer 20。

62 仍低于 67/direct `1%`，且三类语义仍不可合并为 indexed-lane matcher。materialized、multi-user 和 other-slice groups
也仍不满足安全删除条件。因此 NO0470 的停止结论保持不变：不进入 GSim/结构诊断/generated-copy probe。

后续 residual 排名统一使用 129-row whole-block 口径，不再使用 113-row accumulation-only 数字作为 full candidate 上界。
