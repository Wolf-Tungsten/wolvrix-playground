# NO0472 All concat seed coverage gate

日期：2026-07-13

## 1. Scope expansion

[NO0471](./NO0471_whole_concat_block_coverage_correction_20260713.md) 仍以“至少有 accumulation sample”的 61 groups
为 seed。comment/fused + shared-prelude 实际共有 226 个 source rows 命中 `concat_<scope>_<operand>_bits_<word>`：

- accumulation rows 113；
- term/source declaration rows 113；
- unique concat groups 152。

本次把 seed 扩展到任意 concat term/accumulation row，重新从 source 恢复 152/152 groups 和 consumers。226 个 rows 对应
221 个 unique machine offsets；全部 source-backed samples 都落在恢复出的 group block 内，没有剩余 concat source family。

## 2. Consumer result

| consumer class | samples | direct share |
| --- | ---: | ---: |
| single other consumer | 87 | 1.303% |
| materialized/external | 40 | 0.599% |
| multiple other consumers | 34 | 0.509% |
| dynamic wide shift | 29 | 0.434% |
| dynamic slice | 23 | 0.345% |
| other slice | 13 | 0.195% |

`single other consumer=87` 不是统一 matcher。按真实 consumer helper 再拆：

| single-consumer helper | groups | samples |
| --- | ---: | ---: |
| `grhsim_and_words_full` | 53 | 58 |
| `grhsim_and_words` | 8 | 8 |
| `grhsim_reduce_or_words` | 8 | 13 |
| copy | 4 | 4 |
| compare/mux | 4 | 4 |

最宽松地把 full/generic concat-to-AND 合并，也只有 66 samples/direct `0.989%`；两者都执行同一 wide AND payload，但仍少于
预声明的 67。reduce/copy/compare/mux 不能并入 AND matcher。

## 3. Relation to previous gates

NO0470/NO0471 对 61 accumulation-seeded groups 的结构结论仍有效，但不是全部 concat source coverage。本篇补齐遗漏的
91 groups 后，dynamic slice/shift 仍未过门槛；新增主要来自 16x64 concat 后接 wide AND 的 term samples。

materialized/multi-user groups 仍不能删除；dynamic wide shift 仍需完整宽结果；concat-to-AND 即使合并 full/generic 也只有 66。

## 4. Decision

226-row concat source family 已全量闭合，但没有同一安全 matcher 达到 direct `1%`：

- 不做 GSim crosscheck、结构诊断或 generated-copy probe；
- 不为差 1 个 sample 的 concat-to-AND 放宽预声明门槛；
- 不把 reduce/copy/compare/mux 与 AND 合并；
- 后续 residual ledger 将全部 226 concat rows 标记为已审计。

下一步检查扣除 logical-AND、mux、concat 与历史 helper 后的 state-ref/slot expression normalized templates；若最大模板仍低于
67，则结束 comment/fused residual 的 source-template 路线。
