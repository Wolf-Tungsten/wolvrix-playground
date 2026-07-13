# NO0476 Corrected runtime-frame closure gate

日期：2026-07-13

## 1. Closure result

按 [NO0475](./NO0475_corrected_runtime_frame_closure_plan_20260713.md) 对 current scope-corrected rows 与 NO0411
unknown rows 做 `(batch_id, offset)` join：

- current runtime-frame rows 562/562；
- current empty/line-0 rows 138/138；
- empty keys 命中 NO0411 138/138，0 missing/duplicate；
- NO0411 old-only keys 9/9 全部在 current rows 中成为 source-backed ownership。

9 个 old-only rows 分为 shared-prelude 7、comment/fused 1、exact-value 1，均有真实 generated source line，说明 scope correction
没有丢样本，只是不再把它们归为 runtime-frame-only。

## 2. Empty helper replay

138 个 empty rows 精确复现 NO0412 的结构：

| old resolution | samples |
| --- | ---: |
| recovered `grhsim_mux_u64` | 80 |
| recovered `grhsim_or_words_full` | 3 |
| strict unresolved | 55 |

recovered mux 的 machine classes 仍是 zero materialization、stack RMW、register copy、stack spill、memory move 与必要 logic；
NO0412 已用 same-FIR GSim 和历史 ternary/reuse A/B 关闭。full OR 属 NO0408 已关闭的 wide logic payload。

55 个 strict unresolved/direct `0.824%` 低于 67/direct `1%`，无需重做 basic-block attribution。

## 3. Named helpers

current named runtime helpers 为 mux 186、full OR 110、full AND 75、udiv 26，其余单 helper 最大 7。加入 empty 桶恢复后，
mux 与 full-width logic 仍分别落入 NO0412/NO0408；`udiv=26` 与其他 helpers 均不过门槛。

## 4. Decision

corrected runtime-frame-only 域没有新单一 residual class 达到 direct `1%`：

- 不重新编译/运行 perf，不修改 helper/emitter；
- 不把 55 unresolved 与 udiv/reduce/slice 等不同 helpers 合并；
- runtime-frame-only 至此按 corrected keys 全量关闭。

下一步审计 exact side-effect body 130 samples，区分 system-task condition 与真正 call payload；side effects 必须保持功能语义，不能因
性能直接删除。
