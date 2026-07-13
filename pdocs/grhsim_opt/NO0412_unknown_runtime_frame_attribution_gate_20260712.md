# NO0412 Unknown runtime-frame attribution gate

日期：2026-07-12

## 1. Input closure

按 [NO0411](./NO0411_unknown_runtime_frame_attribution_plan_20260712.md)，从 NO0404 的 production-identical O3 rows
提取 147/147 个 `runtime.hpp:0` samples，覆盖 38 batches / 147 unique IPs。batch17/33 full `-g` `.text` 与 production
SHA 完全相同，但仍不提供 helper inline DIE，因此最终归属继续使用 NO0401 line-table objects。

## 2. Strict line-0 attribution

基本块 ±32 双侧 generated line 最初只直接闭合 9 个 samples。进一步接受一种仍在同 block 内的严格单侧形态：

```text
line-0 sample -> nearest known runtime helper -> generated operation line
```

只有 known helper 名确实出现在该 generated operation body 中才接受，且不跨 control-transfer。该规则闭合 83 个
samples；其余 55 个保持 unresolved。±64 只作 sensitivity，没有覆盖严格结果。

| Resolution | Samples | Compute share |
| --- | ---: | ---: |
| Strict line-0 helper -> operation | 83 | 1.485% |
| Direct generated line | 9 | 0.161% |
| Unresolved | 55 | 0.984% |

## 3. Recovered helpers

| Helper | Samples | Compute share | Interpretation |
| --- | ---: | ---: | --- |
| `grhsim_mux_u64` | 80 | 1.431% | branchless scalar mux / mux-to-zero OR chain payload |
| `grhsim_slice_words` | 4 | 0.072% | dynamic wide slice/index payload |
| `grhsim_or_words_full` | 3 | 0.054% | full-width OR payload |
| Unresolved helper | 60 | 1.073% | 含 55 unresolved + 5 direct multi-helper expressions |

80 个 mux samples 的 operation 分布为 62 `kRegisterReadPort`、13 `kMux`、3 `kOr`、1 `kAnd`、1 `kAssign`。这里的
`kRegisterReadPort` 不是“读取状态本身需要 mux”，而是 operation marker 后被内联的 consumer expression；代表 generated
body 是多个 `grhsim_mux_u64(cond, value, 0)` 再 OR。机器形态为：

```text
zero materialization       21
stack RMW logic            17
register copy              15
stack move/spill           12
memory/value move           7
register logic              6
other                       2
```

这些指令共同实现条件 mask、operand load和 OR reduction，不能把 15 个 register copies 或 12 个 stack moves从整个 mux
表达式中独立删除。

## 4. GSim cross-check

对同名 `delayedNotFlushedWriteBackNums_delayed_bits_r_16` 检查 same-FIR GSim generated source。GSim 同样生成：

```cpp
(-(uint8_t)canWbSeq & delayedNotFlushedWriteBackNums_delayed_bits_r_16) |
(-(uint8_t)!canWbSeq & 0)
```

并在大量 `_wbCnt_T_*` 中线性展开。该形态是共同 RTL mux/OR payload，不是 GrhSIM 遗漏 indexed memory 或
reg-to-mem recovery。把 recovered 80 合回 NO0404 后，current mux machine samples 为 `450 + 80 = 530`，约占 direct
compute `9.48% / 13.25B` instructions。

但 helper form 已有三项约束：

- [NO0090](./NO0090_grhsim_branchless_mux_select_coremark50k_20260511.md)：mask-select 相对 ternary 提速 `3.05%`；
- [NO0129](./NO0129_scalar_mux_ternary_negative_smoke_20260521.md)：current-style workload 上 ternary 20k 回退 `8.1%`；
- [NO0406](./NO0406_current_same_condition_mux_reuse_gate_20260712.md)：current same-condition reuse 上界仅 compute
  `0.143%`。

因此 recovered mux class 虽超过 1%，但代表 blocks 是已知必要 payload，且可替代 helper forms 已被当前数据或历史 A/B
否决，不重复代码 probe。

## 5. Residual upper bound and decision

55 个 strict unresolved samples 合计只占 compute `0.984%`，已经低于 NO0411 的 56-sample / 1% gate。即使把它们全部
视为可删也不能进入实现；其中 machine copy-like 仅 14 samples（stack move 9、register copy 4、zero init 1），占
compute `0.250%`。

本轮不修改 emitter。147 个 unknown 桶已拆为既有 mux payload主体、少量已知 wide helper和低于 1% 的 residual，不能再
作为 3.675B 全可删成本。下一步转向 NO0404 中仍有明确双边净差的 dispatch：GrhSIM/GSim `413/332` samples，约解释
`2.025B / 3.35%` compute excess。

产物：

```text
build/logs/xs_perf/no0411/analyze_unknown_runtime_frames.py
build/logs/xs_perf/no0411/{unknown_sample_rows,resolution_summary,helper_summary,
    semantic_summary,machine_summary,operation_summary,batch_summary}.tsv
build/logs/xs_perf/no0411/representative_blocks.tsv
```

