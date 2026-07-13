# NO0402 Production scalar-load realization gate

日期：2026-07-12

## 1. Scope and code-identity gate

按 [NO0401](./NO0401_production_scalar_load_realization_plan_20260712.md)，输入固定为 NO0357 production direct
的 compute batches 0..65、NO0392 scalar locality TSV 和 NO0399 direct 50k fire。66 个 translation units 使用相同
Clang/O3/PCH，只增加 line table 调试信息重编；逐 object dump `.text` 后，66/66 与 production SHA256 完全相同，合计
`70,924,958` bytes。因此本篇只改变 DWARF 和离线统计，不改变任何实际执行指令，也没有新的 runtime 性能样本。

class layout probe 固化 scalar array base offset，再由 `base + slot_index * element_size` 得到唯一 displacement。反汇编只统计
production `.text` 中命中这些 displacement 的非 `lea` memory operands，并通过 inline caller line 映射回 generated
supernode block。

## 2. Direct line-map result

377,895 个 source candidates 对应 506,399 条目标 displacement instructions。直接使用 DWARF caller line 时：

```text
resolved generated-source instructions       467,717
  resolved candidate instructions             382,660
  resolved non-candidate instructions          85,057
runtime-helper-only / unresolved               38,682

static machine accesses                       382,660
static machine redundant                        91,977
dynamic machine redundant                  917,141,270
machine / source-saved                            9.126181%
machine / direct-compute instructions              0.656273%
```

`-gline-tables-only`、带调试信息的 PCH 和 full `-g` batch42 均保持相同 `.text`；full `-g` 没有继续补回
`grhsim_mux_u64` 等 helper 丢失的 caller frame。以 bool slot7622 为例，127 条同 displacement instructions 中 84 条可见
generated caller，43 条只落到 runtime helper line，说明剩余问题是 DWARF 归属不足，而不是未知机器码。

## 3. Basic-block neighborhood audit

为避免把 38,682 条 helper-only instructions 直接忽略，增加一层保守归属：

1. 从 branch target 和 branch/return 后继划分同一 `.text` 内的基本块；
2. 在同一基本块内向前、向后各搜索最多 32 条真实指令；
3. 只有两侧最近的 generated source line 都落到同一个 supernode 时才接受；
4. 同 supernode 且存在相同 displacement candidate 时计入该 candidate，否则记为 non-candidate；其余保持 ambiguous。

全量结果为：

```text
same-supernode resolved                         29,741
  candidate                                     27,356
  non-candidate                                  2,385
ambiguous                                        8,941

audited static machine accesses                410,016
audited static machine redundant                98,577
audited dynamic machine redundant          962,028,206
machine / source-saved                            9.572836%
machine / direct-compute instructions              0.688392%
```

剩余 8,941 条 ambiguous instructions 逐条按“同 batch、同 displacement 的 candidate 中最大 direct fire”全部视为可消除，
额外上界为 `187,982,146`，总上界为：

```text
dynamic machine redundant upper          1,150,010,352
upper / source-saved                              11.443387%
upper / direct-compute instructions                0.822905%
```

再把已确认同 supernode 但没有对应 candidate 的 2,385 条也故意恢复为未知，并同样按最大 fire 加权，总量为
`1,173,563,833`，仍只占 direct compute instructions 的 `0.839759%`。该压力测试不依赖 non-candidate 排除是否完全准确。

## 4. Compiler realization shape

O3 后 377,895 个 candidates 的机器访存分布为：

| Machine accesses | Candidate rows | Dynamic machine redundant |
| ---: | ---: | ---: |
| 0 | 66,456 | 0 |
| 1 | 244,925 | 0 |
| 2 | 53,649 | 550,557,045 |
| 3 | 6,522 | 126,089,372 |
| 4 | 2,824 | 65,923,599 |
| 5-7 | 1,911 | 113,136,942 |
| 8+ | 1,608 | 106,321,248 |

即 311,381/377,895 rows 在机器码中只剩 0 或 1 次目标访存。代表 rows 也显示 source touches 不能直接当作 load：

| Supernode / batch | Source touches | Machine accesses | Dynamic source saved | Dynamic machine redundant |
| --- | ---: | ---: | ---: | ---: |
| 38314 / 42 | 48 | 2 | 5,296,289 | 112,687 |
| 59486 / 62 | 65 | 1 | 1,777,920 | 0 |
| 11271 / 12 | 2 | 2 | 150,152 | 150,152 |
| 23721 / 24 | 3 | 2 | 300,208 | 150,104 |
| 26591 / 30 | 4 | 4 | 450,456 | 450,456 |

compute62 的 source saved 为 `727,590,232`，审计后的 machine redundant 为 `18,690,264`，实现率仅
`2.568790%`。compute1 从 NO0394/NO0400 起就没有 repeated-read candidate，本机制不能覆盖当前最大的 compute hotspot。

## 5. Decision

按 NO0401 预声明规则，只要 dynamic machine redundant 低于 source saved 的 10%，或低于 direct compute instructions 的
1%，就停止 typed-local。直接归属和严格邻域归属均同时低于两条门槛；即使采用 ambiguous 与 non-candidate 压力上界，
direct-compute 占比仍只有 `0.839759% < 1%`。

因此不实现 materialized scalar typed-local cache。NO0400 的 `10.050B` 是 source-level 假热点，主体已被 Clang/O3 CSE、
hoist 或合并；强行增加 locals 更可能带来 register pressure 和布局扰动。下一步回到 NO0388 的剩余 compute root cause，
优先分析不属于本候选的 compute1 通用 slot/ref 与 changed/activation 机器指令。

产物：

```text
build/logs/xs_perf/no0401/analyze_machine_loads.py
build/logs/xs_perf/no0401/neighbor32_analysis/{text_identity_manifest,
    machine_candidate_rows,machine_batch_summary,machine_threshold_summary,
    machine_access_distribution,machine_top_candidates,machine_neighbor_resolution}.tsv
build/logs/xs_perf/no0401/neighbor32_analysis/machine_summary.txt
```
