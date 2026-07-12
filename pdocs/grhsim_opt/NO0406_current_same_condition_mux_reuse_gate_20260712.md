# NO0406 Current same-condition mux reuse gate

日期：2026-07-12

## 1. Parser and scope closure

按 [NO0405](./NO0405_current_same_condition_mux_reuse_plan_20260712.md)，离线解析 NO0357 的 66 个 production compute
sources，并连接 NO0399 direct 50k fire。解析器区分独立 scalar `kMux` outer call 与 operand expression 中的 nested/inline
calls；run 只允许同一 supernode 中 operation index 连续且 condition expression 完全相同。

```text
all operation comments             1,910,892
kMux operation comments              143,773
wide mux blocks                           611
scalar mux outer blocks              143,162
scalar parse failures                      0
all grhsim_mux_u64 text calls         642,023
nested / inline calls                 498,861
```

642,023 总调用与 NO0405 preflight 精确一致。代表 batch0/SN12 的 `_op_1739219/_op_1739208` 被识别为同
`value_bool_slots_[119846]`、length=2、direct fire=11,838 的 run，证明 operation 邻接、condition 与 fire 连接均有效。

## 2. Direct-fire source upper bound

| Minimum run length | Runs | Covered outer mux ops | Static saved | Dynamic saved | Direct compute instructions |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 11,429 | 62,836 | 51,407 | 413,378,066 | 0.295798% |
| 4 | 5,483 | 49,048 | 43,565 | 318,286,050 | 0.227754% |
| 8 | 2,169 | 32,522 | 30,353 | 200,286,682 | 0.143318% |
| 16 | 714 | 16,857 | 16,143 | 105,099,601 | 0.075205% |

这里把每个 `(run_length - 1) * direct_fire` 都视为一次可消除 mask evaluation，尚未扣除 Clang/O3 已做的 CSE，因此是
source upper bound。NO0405 要求 threshold>=8 至少覆盖 direct compute `139.750B` instructions 的 1%；实际只有
`0.143318%`，差约 6.98 倍。即使不顾历史 threshold=2/4 的 text/instruction 负担，把所有 length>=2 都纳入，也只有
`0.295798%`。

## 3. Distribution

threshold>=8 覆盖 61 batches、1,970 supernodes，不是单点机会；但总量本身不足：

```text
top batch dynamic share       11.1516%
top single run share           1.1242%
top 10 runs share              8.2409%
top 100 runs share            45.0346%
maximum run length                  68
maximum single-run saved       2,251,545
```

当前 642,023 calls 中 498,861 个是 nested/inline expression，不是 NO0091 emit-level 相邻 outer run；剩余独立 outer mux 的
高 fire 同条件重用量也偏低。这解释了旧版存在收益并不意味着 current schedule 仍值得恢复同一路径。

## 4. Decision

source gate 已失败，按 NO0405 不进入 production O3 probe，不恢复 `mux_mask/grhsim_select_u64`，也不重跑仿真。全局
ternary 仍受 NO0090/NO0129 负向证据约束；本篇没有修改 emitter 或 generated production code。

下一步按 NO0405 fallback，检查 NO0404 helper 头部中的 `grhsim_or_words_full/grhsim_and_words_full`。需要先区分它们的
samples 是 full-width payload 本身，还是仍有重复 truncation、temporary copy 或 lane materialization；已有 NO0225/NO0226
已优化 generic width 与 call boundary，后续只接受能改变 current O3 机器码的新候选。

产物：

```text
build/logs/xs_perf/no0405/analyze_same_cond_mux_runs.py
build/logs/xs_perf/no0405/{run_rows,threshold_summary,batch_summary,top_runs}.tsv
build/logs/xs_perf/no0405/current_same_cond_mux_summary.txt
```
