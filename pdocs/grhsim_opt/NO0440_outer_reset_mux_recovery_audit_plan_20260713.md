# NO0440 Outer reset-mux recovery audit plan

日期：2026-07-13

## 1. Objective

[NO0439](./NO0439_scalar_array_true_merge_rejection_gate_20260713.md) 中
`branch_not_in_update + regular_unmatched` 覆盖 75 states/78 samples，即 latest direct total `1.168539%`。代表 IR
不是缺少普通 row enable，而是：

```text
updateCond = common domain guard
nextValue  = reset polarity mux(normal sparse update, reset value)
```

本轮不放宽 true-merge，也不创建 memory op。先证明多少动态样本可统一识别为 group-wide outer reset mux，并将 normal arm
按结构分类，防止把 reset selector 当成 row-address guard。

## 2. Default-off diagnostic

新增环境变量：

```text
WOLVRIX_REG_TO_MEM_PROFILE_BRANCH_NOT_IN_UPDATE=1
```

值为空、`0`、`false`、`off` 时关闭。它只在 consolidated matcher 即将返回 `branch_not_in_update` 时扫描该 group，输出一条
`branch_not_in_update_shape`；不得改变 matcher return、group 顺序、IR、stats 或 timing 归属。

每条 group summary 至少记录：

- 所有 rows 是否均为单层 outer mux chain；
- mux guard 是否逐 row 相同；
- guard 是某个 write event 本身还是其逻辑取反，并且 polarity 是否一致；
- updateCond、mask、events/edges 是否逐 row 相同；
- reset arm 是否为常量；
- normal arm 根 operation-kind histogram；
- normal arm 是否依赖该 row 自身的 `kRegisterReadPort`。

依赖检查只沿 normal arm 的 def-use DAG 向上遍历并设置上限；超限必须单列，不能当成不依赖旧值。

## 3. Behavior gates

1. nested `transform-reg-to-mem` target 构建无 warning/error；
2. 现有 33-case executable 在 unset/`0`/`1` 下均 exit 0；
3. unset 与 `0` normalized logs byte-identical；
4. 开启模式只允许新增 config bit 和 shape records，pass outcome/stats 必须相同；
5. editable reinstall 后确认 Python native library 包含新 env string。

## 4. SimTop audit

复用 NO0439 的同一 pre-reg checkpoint，仍在 pre-sched 前停止，同时开启 full-group 和 branch-shape profile。要求
4,318 groups、`835/174/254` true/edge/intent 再次精确复现。

把 shape records 按 NO0439 的 group IDs 连接回 78 samples，互斥拆为：

1. `outer_event_mux_consistent`；
2. outer mux 存在但 guard/event/polarity 不一致；
3. reset arm 非常量或逐 row 不兼容；
4. normal arm root 为 mux、OR/AND self-update、无 self 的 direct recompute 或其他；
5. 非 outer reset mux。

同时从 same-FIR GSim source 抽取 uTage、L2 PMU、PTW、DCache 和 FTQ 的 `$NEXT[index]` 写形式，确认分类与对照侧的
稀疏写/复位行为相符。

## 5. Decision

只有满足以下条件的同一 normal-arm class 才进入 functional transform probe：

- outer guard/event/reset polarity、domain guard、mask 和 edges 全部一致；
- reset arm 可无损表示为 memory fill；
- normal arm 可证明保留 old-value fallback 和分支优先级；
- 该 class 仍覆盖至少 67 direct samples。

若 78 samples 在 normal arm 处分散，或最大可证明子类低于 67，则停止从 outer mux 方向实现；不得用整个
`branch_not_in_update` 聚合数替代最终可恢复覆盖率。

## 6. Planned artifacts

```text
build/logs/xs_perf/no0440/{build,test_default,test_zero,test_audit,install}.log
build/logs/xs_perf/no0440/simtop_outer_mux_audit.log
build/logs/xs_perf/no0440/outer_mux_group_summary.tsv
build/logs/xs_perf/no0440/outer_mux_sample_summary.tsv
build/logs/xs_perf/no0440/gsim_sparse_write_crosscheck.txt
```
