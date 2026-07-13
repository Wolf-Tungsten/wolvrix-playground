# TNO0004 SimTop commit, state-read, and PHR optimization

记录日期：2026-07-13

来源范围：`NO0255..NO0269`，原始记录见 [NO0255](../grhsim_opt/NO0255_simtop_same_fir_perf_profile_20260710.md) 至 [NO0269](../grhsim_opt/NO0269_packed_active_flag_scan_20260711.md)。

状态：完成一轮 SimTop commit/compute 热点优化；保留全掩码 commit、state-read predicate reuse、PHR true-merge、wide broadcast 与 packed active scan。

## 1. 同 FIR 基线

fresh same-FIR GSim/GrhSIM 50k 对照中，hybrid GrhSIM 仍慢 `4.285x`。约一半时间落在 commit，batch112/126 含 61,376 个全掩码 register writes，却仍走通用 masked merge。

## 2. Commit 与 state-read 优化

| Change | Functional gate | Main result |
| --- | --- | --- |
| full-mask scalar/wide commit direct update | Vtype 200k、SimTop 50k | SimTop 提速 `1.381x`，gap 收敛到 `3.400x` |
| same-supernode scalar state-read changed reuse | SimTop 10k/50k、Vtype 200k | batch7 text `-22.74%`，总 instructions `-2.09%`，wall 约 `-0.5%..-1.2%` |
| sched54 `-Os` | 功能通过 | instructions/branches 增加，撤回 |

post-profile 证明 state-read reuse 主要压低 batch7；下一热点转为 compute54 的 PHR multi-write scalarization。

## 3. PHR true-merge

GrhSIM 将 Phr.sv 的 532 行展开为约 13.5k `LogicAnd`，而 GSim 保留数组和 28 个 indexed writes。strict true-merge 经 collision/reset synthetic 修正后，将主组恢复为 41 个 indexed memory writes。

50k A/B/A 中：

```text
instructions  -1.62%
text         -38.09%
branches      +9.24%
```

row-aware reader activation 将每行 reader flags 从 67 降到平均 2.1，但 instructions 仅再降 `0.18%`，说明 reader activation 与其他 supernode 高度重叠。

## 4. 两个全局热点修复

1-bit 到 256-bit 的通用 replicate 约贡献 2.43B branches。编译期 word broadcast fast path 使 instructions/branches 分别下降 `9.77%/11.90%`，cycles 只下降 `1.03%`。

随后将 eval activity 空集判断从逐 byte 改为 32-byte packed scan：

```text
Host time  -16.88%
cycles     -16.79%
branches    -9.14%
eval branch sample share 10.53% -> 0.74%
```

## 5. 阶段结论

这一阶段证明 SimTop 大头可以来自少数通用代码形态，而不只是 supernode 数量。full-mask commit、PHR array recovery、broadcast 和 packed active scan 都取得了可观收益；下一主线转向 TAGE/ROB/DCache 等仍被 scalarized 的数组状态。

## 6. 规则审计与关键数据

记录类型：same-FIR excess-instruction root-cause 总结。单一议题边界是“SimTop commit/state 路径中哪些 GrhSIM 独有代码形态解释首轮 GSim gap”。本节只恢复代表性 A/B/A 原始量级；各实现与 gate 的逐步记录仍以来源 NO 文档为准。

所有 50k SimTop 样本均完成 `50001` guest cycles；GrhSIM 为 `instrCnt/cycleCnt=73580/49996`、terminal PC `0x80001312`，GSim 对照为 `73584/49998`、PC `0x8000131e`。

| Gate | Baseline mean host ms | Candidate host ms | Baseline mean host cycles | Candidate host cycles | Delta |
| --- | ---: | ---: | ---: | ---: | ---: |
| same-FIR GSim vs GrhSIM | 31,249.5 | 133,891 | - | - | GrhSIM `4.285x` wall |
| full-mask commit | 146,451 | 106,076 | - | - | wall `-27.57%` |
| PHR true-merge | 129,135 | 102,602 | 468,122,750,789 | 372,017,886,726 | cycles `-20.53%` |
| word broadcast | 121,684.5 | 120,181 | 439,506,290,528 | 434,979,922,745 | cycles `-1.03%` |
| packed active scan | 124,080 | 103,140 | 440,134,503,459 | 366,243,299,520 | cycles `-16.79%` |

same-FIR GSim 双 baseline wall spread 为 `1.79%`。后四项均为 baseline/candidate/baseline 夹测；其中 PHR、broadcast、active-scan 的 host instructions 分别变化 `-1.62%/-9.77%/-2.45%`，说明 wall/cycles 收益不能只按删指令比例解释。原始表见 [NO0255](../grhsim_opt/NO0255_simtop_same_fir_perf_profile_20260710.md)、[NO0256](../grhsim_opt/NO0256_full_mask_register_commit_specialization_20260710.md)、[NO0266](../grhsim_opt/NO0266_phr_true_merge_p1_simtop_50k_gate_20260711.md)、[NO0268](../grhsim_opt/NO0268_wide_bit_replicate_broadcast_fastpath_20260711.md) 和 [NO0269](../grhsim_opt/NO0269_packed_active_flag_scan_20260711.md)。
