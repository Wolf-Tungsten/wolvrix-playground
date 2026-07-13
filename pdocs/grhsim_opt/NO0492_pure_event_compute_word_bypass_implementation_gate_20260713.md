# NO0492 Pure-event compute-word bypass implementation gate

日期：2026-07-13

## 1. Implementation

按 [NO0491](./NO0491_pure_event_compute_word_bypass_implementation_plan_20260713.md) 在 `wolvrix` 子仓库
`a3ec022` 实现默认关闭的候选：

```text
EmitOptions attribute: pure_event_compute_word_bypass
Environment:          WOLVRIX_GRHSIM_PURE_EVENT_COMPUTE_WORD_BYPASS
Default:              false
```

生产判定在 GRH/model 层完成，不匹配 generated source。eligible supernode 必须只含显式 pure producer/read 白名单与
SystemTask/DPIC side effects；非 constant producer results 全部要求 non-materialized 且无需 tracked change/boundary activation。
side effects 必须共享单个 posedge/negedge exact event，并排除 final、timed-initial once-only、无 event、multi-event 及有 results
的 DPIC。

eligible word 还要求 compute phase、dispatch mask 等于 clear mask、非 fullpass、非 full-active-word consume。split helper chunks
显式禁用本候选；普通 word 与未 split 的 whole-word helper 才允许分析。

## 2. Generated shape

开关命中后，underlying word 仍先按原逻辑 clear；唯一 outer exact-event guard 包住原 entry tests、payload 和 restore。miss
path 无 `else`、无 local zero materialization、无 restore。内部 SystemTask/DPIC exact-event guards 和原 call order 均保留。

专用 16-task fixture 在禁用 coarsen、每 supernode 1 op 时稳定生成 2 个 homogeneous 8-entry wrappers。两个 wrapper 都满足：

1. clear 位于 marker/outer guard 之前；
2. 8 个 entry tests 与内部 exact-event guards 位于 wrapper 内；
3. 原 `| activeWordFlags` restore 位于 closing brace 之前。

## 3. Structural and functional gates

- unset 与 explicit `0` 的 header/state/eval/schedule 全部 byte-identical，且均无 marker；
- explicit `1` 生成 2 个 wrappers；
- once-only 与 two-event fixtures 为 0 wrappers；
- 开启 posedge fullpass 后 marker 仍为 2，证明 fullpass methods 没有新增包装；
- 开启 full-active-word consume 后所有 `dispatchMask=255` blocks 均无 wrapper；
- 显式开启候选的 commit fixture 无 marker；
- baseline/candidate harness 逐字相同，在 edge-miss、重新激活、两次 posedge 序列中都恰好执行 32 次 task；
- 候选通过开启环境变量后的既有 SystemTask/DPI/active-word 全套 harness。

最终回归：

```text
emit-grhsim-cpp             PASS  217.53 s
emit-grhsim-cpp-memory-fill PASS    5.05 s
```

build、generated harness compile/run 与 `git diff --check` 全部通过。

## 4. Decision

implementation/structural gate 通过，默认输出不变。下一步按 NO0490/NO0491 增加独立默认关闭的 dynamic pure-word active
hit/miss counters，先在 synthetic 闭合 `active = hit + miss`，再 fresh emit SimTop 统计 production eligible word 数与实际 miss
比例。尚未做 SimTop runtime 性能结论。
