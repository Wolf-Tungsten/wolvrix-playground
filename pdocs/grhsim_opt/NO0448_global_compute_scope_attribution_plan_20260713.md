# NO0448 Global compute scope-aware attribution plan

日期：2026-07-13

## 1. Objective

[NO0446](./NO0446_assign_sample_ownership_correction_20260713.md) 和
[NO0447](./NO0447_assign_boundary_machine_source_gate_20260713.md) 证明 NO0403 的 operation mapping 有系统性污染：
`current_operation` 会跨 `// Supernode` 延续，且最后一条 op 会吸收共享 deferred tail。`kAssign` 的旧 395 samples 中只有
291 真正落在 assign value body，误差足以改变 1% gate 结论。

因此在选择下一 operation hotspot 前，先对 latest direct 的全部 5,590 compute leaf samples 重建 scope-aware ownership，回答：

1. 每个 operation kind 有多少 samples 真正落在其独立 generated body；
2. 有多少属于 dispatch、共享 typed-local/concat prelude、deferred activation tail 或无法独占的 fused code；
3. 既有 normalized mechanism 分类与 corrected scope 是否一致；
4. 排除已完成方向后，哪个新候选仍有 direct `>=1%` 的可信机器上界。

## 2. Fixed inputs and validity

只复用：

```text
samples: build/logs/xs_perf/no0403/grhsim_all_compute_sample_rows.tsv
source:  build/xs_grhsim_no0357_direct_state_read_20260712/
         grhsim/grhsim_emit/grhsim_SimTop_sched_{0..65}.cpp
```

NO0404 已证明这 66 个 production/debug O3 `.text` byte-identical；本轮不重编、不重跑仿真或 perf。要求 5,590/5,590 rows
逐 batch/line 重新读取实际 source text，0 missing、0 mismatch；每个 recorded `_op_N` 必须能在同一 source 找到，否则停止。

## 3. Ownership model

逐 supernode 解析 marker、dispatch、op comments、value comments 和独立 C++ scope，按下列优先级互斥分类：

- `exact_value_body`：sample 位于 `// value` 后同缩进 `{...}` 内，保留该 `_op_N/kind`；
- `exact_side_effect_body`：system task/DPI/memory side-effect 等无 value comment、但可由独立 scope 证明的 op；
- `shared_supernode_dispatch`：active-word load/test/clear 与 outer dispatch；
- `shared_supernode_prelude`：第一段独立 op body 前的 typed locals、concat/slice builders 和 fused helpers；
- `shared_supernode_tail`：最后一个独立 body 后的 changed aggregate、activation 和 scope close；
- `comment_only_or_fused`：recorded op 没有可独占 body，sample 只能按 normalized mechanism 归因；
- `unresolved`：以上均不能证明，单独保留，不猜 operation kind。

direct register-read markers、packed-lane special path 和 runtime inline frames 都必须服从 caller generated line 的 scope，不能仅按最近
comment 继承 kind。

## 4. Corrected summaries and decision gate

输出 old/corrected operation-kind 对照，并把每个 corrected kind 与 normalized mechanism、opcode、batch 和 result family 交叉。
热点选择只接受：

1. `exact_*_body` 内同一 operation/source shape 至少 67 samples/direct 1%；
2. 不属于已收口的 register read、assign、same-cond mux、full-width logic、change grouping 或 active-word dispatch；
3. shared prelude/tail 不被重新包装为某个 operation kind；
4. 能在 same-FIR GSim 中提出具体多出层，而不是两边共同 payload。

若没有新 exact class 过 1%，下一步转向跨 operation 的 shared-prelude machine shape，而不是继续逐 kind 开题。

## 5. Planned artifacts

```text
build/logs/xs_perf/no0448/analyze_global_scope.py
build/logs/xs_perf/no0448/compute_sample_rows.tsv
build/logs/xs_perf/no0448/{ownership,corrected_operation,mechanism_scope}_summary.tsv
build/logs/xs_perf/no0448/old_corrected_operation_compare.tsv
build/logs/xs_perf/no0448/analysis_summary.txt
```
