# NO0442 Outer reset-mux recovery audit gate

日期：2026-07-13

## 1. Run validity

从 NO0439 的同一 3.2 GiB pre-reg checkpoint 恢复，开启 full-group 与 branch-shape profile，只运行到 pre-sched。
运行前 load average 为 `58.04/384 CPUs`，available memory `926.27 GiB`。本轮不采集 host/PMU 性能，wall time
只作资源记录。

首次启动漏传必需的空 `json_out` positional，driver 将 `info` 误作 read-args 路径并在建输出目录/读 checkpoint 前
exit 1；修正为显式 `''` 后重新启动，有效 run exit 0。

有效 run 结果：

```text
groups=4318 visited_groups=4318
intent_candidate_groups=760 intent_conflict_groups=0
true_groups=835 edge_padded_true_groups=174
true_skipped=3483 intent_groups=254
```

4,318/4,318 groups 和 `835/174/254` true/edge/intent 精确复现，随后报告 `stop after pre-sched enabled`。
wall `3:53.34`，maximum RSS `29,127,292 KiB`；reg-to-mem 自报 `184,378ms`。

## 2. Dynamic target connection

全图共有 1,143 个 `branch_not_in_update_shape` records。只连接 NO0439 中带动态样本的 47 group IDs，47/47 均
唯一命中，覆盖 75 states/78 samples；没有用其余静态 groups 扩大收益估计。

严格 outer-event-reset 要求每个 group 同时满足：

- 所有 rows 都有顶层 mux；
- common guard 与 event relation/polarity；
- guard 命中同一 event 或其取反，0 unmatched rows；
- common updateCond/mask/events/edges；
- 所有 reset arms 为常量；
- normal dependency DFS 0 truncated rows。

结果为：

| Class | States | Samples | Direct total | Commit |
| --- | ---: | ---: | ---: | ---: |
| strict outer reset, `kAnd + self` | 36 | 37 | 0.554307% | 4.262673% |
| strict outer reset, `kOr + self` | 13 | 15 | 0.224719% | 1.728111% |
| strict outer reset, `kMux + self` | 9 | 9 | 0.134831% | 1.036866% |
| outer mux, non-event guard | 17 | 17 | 0.254682% | 1.958525% |

三个严格 normal-root classes 合计只有 58 states/61 samples，即 direct/commit `0.913858%/7.027650%`。即使一个
实现同时支持 `kAnd/kOr/kMux`，仍低于预声明的 67 direct samples/1% 门槛；单一 root 最大只有 37 samples。

## 3. GSim crosscheck

same-FIR GSim source 证实这些 array bases 有真实稀疏写价值，但也支持上述拆分：

- uTage `entries.valid$NEXT[index] = 1`，commit 为 512-row loop；
- L2 PMU 对两个动态 source indexes 分别 set/clear，commit 为 1,024-row loop；
- PTW `l0BitmapReg` 和 DCache `meta_array` 都按动态多维 index 写；
- FTQ `perfQueue.isCfi` 在一个动态 queue row 上显式写 32 lanes，其 GrhSIM 顶层 guard 不是 reset event。

因此 17 个 non-event samples 不能通过放宽 event relation 并入 reset 子类。GSim 保留数组说明方向存在理论收益，但不能替代
current transform 的可证明语义和动态门槛。

## 4. Decision

NO0439 的 78-sample aggregate 在语义审计后降为 61-sample strict candidate，未过 1% direct gate。按 NO0440 预声明：

- 不实现 outer reset-mux peel；
- 不删除 `branch_not_in_update` 检查；
- 保留诊断开关默认关闭；
- scalar-array re-aggregation 当前其他单一 rejection class 也均低于 1%，本轮主线停止该方向。

下一步回到 latest direct machine/source 差异，选择新的、独立达到 direct 1% 的热点，不把多个语义无关的 reg-to-mem
拒绝原因拼成实现依据。

## 5. Artifacts

```text
build/logs/xs_perf/no0440/simtop_outer_mux_audit.{log,resource}
build/logs/xs_perf/no0440/connect_outer_mux_shapes.py
build/logs/xs_perf/no0440/outer_mux_group_summary.tsv
build/logs/xs_perf/no0440/outer_mux_sample_summary.txt
build/logs/xs_perf/no0440/gsim_sparse_write_crosscheck.txt
```
