# NO0439 Scalar-array true-merge rejection gate

日期：2026-07-13

## 1. SimTop checkpoint replay

按 [NO0437](./NO0437_scalar_array_true_merge_rejection_plan_20260713.md) 从 NO0357 的同一
`wolvrix_xs_pre_reg_to_mem.json` 恢复，只运行 reg-to-mem 并在 pre-sched 前停止。运行前 load average 为
`41.87/384 CPUs`、available memory 约 927 GiB；本轮不是性能测试，没有采集或解释 host time/PMU。

full-group profile 输出 4,318/4,318 个 `first_reg/last_reg` 记录，最终计数为：

```text
groups=4318 visited_groups=4318
intent_candidate_groups=760 intent_conflict_groups=0
true_groups=835 edge_padded_true_groups=174
true_skipped=3483 intent_groups=254
```

计数精确复现 NO0357，driver 随后报告 `stop after pre-sched enabled`，没有进入 activity schedule 或 C++ emit。
回放 exit 0，wall time `3:36.04`，maximum RSS `29,129,672 KiB`。

## 2. Connection method

解析器读取 NO0436 的 `match_kind=aggregate_array` rows，并将 group 的首末成员拆成数字/非数字 token：

- 非数字 token 和不变数字 token 必须逐项相同；
- 只允许一个数字 row token 在首末边界内变化；
- 多个数字维度同时变化时拒绝猜测；
- 0 个或多个 group 命中分别记为 `missing` 或 `ambiguous`。

该规则把 140 states/143 samples 连接到 124 个已发现 states/127 samples；剩余 16/16 无 group，0 ambiguous。
已连接状态中没有任何一个属于 `rewrite_true_done ok=1`，与 sampled scalar commit state 在 current generated code 中仍存在
一致。

## 3. Rejection result

| Outcome/reason | States | Samples | Direct total | Commit |
| --- | ---: | ---: | ---: | ---: |
| `branch_not_in_update + regular_unmatched` | 75 | 78 | 1.168539% | 8.986175% |
| `priority_guard + regular_unmatched` | 28 | 28 | 0.419476% | 3.225806% |
| discovery `missing` | 16 | 16 | 0.239700% | 1.843318% |
| `family_mismatch + regular_unmatched` | 12 | 12 | 0.179775% | 1.382488% |
| `mux_chain + regular_unmatched` | 9 | 9 | 0.134831% | 1.036866% |

只有 `branch_not_in_update` class 超过预声明的 67 direct samples/1% 门槛。它覆盖五个头部 aggregate bases：

| Base | Samples |
| --- | ---: |
| PTW `l0BitmapReg` | 14 |
| L2 bus PMU `latencyRecord.valid` | 11 |
| DCache `meta_array` | 8 |
| uTage `entries.valid` | 8 |
| FTQ `perfQueue.isCfi` | 7 |

ROB `debug_lsTopdownInfo.s2.paddr.valid` 另有 6 samples。头部不是由多个零散拒绝原因拼出的偶然阈值。

## 4. Semantic preflight

代表写端口的 pre-reg IR 和 emitted SV 显示，`branch_not_in_update` 不是普通的 row guard 漏配：

```text
updateCond = io_pll0_lock
nextValue  = !reset ? normal_value : reset_value
```

uTage 的 `normal_value` 是 `_GEN_7 | entries_0_valid`，L2 PMU normal path 同时含按 source 的 set/clear 和旧值，ROB
normal path 则是多路 valid 组合。current consolidated matcher 把最外层 `!reset` 当作普通 mux branch，并要求它出现在
`updateCond` 的 OR terms 中，因此在 row 0 立即返回 `branch_not_in_update`；fallback matcher 也无法识别该复合 next-value
形状。

所以不能只删除 branch/update 对应检查。那会继续把 group-wide reset selector 送入 row-address matcher，既不能证明匹配，
也可能破坏异步复位和优先级语义。

## 5. Decision

scalar-array re-aggregation 通过动态覆盖门槛，但实现 gate 尚未通过。下一阶段只审计
`branch_not_in_update` groups 的 group-wide outer reset mux：

1. 验证所有 rows 的 normal/reset guard、events、edge、mask 和 reset polarity 一致；
2. 验证 reset arm 可表示为 memory fill，且 normal arm 可以递归恢复成有地址的写族；
3. 分别统计 outer-mux 可剥离、normal arm 可匹配和最终可 rewrite 的 groups/samples；
4. 未证明 old-value fallback、reset precedence 和 branch priority 时不得放宽 matcher。

只有最终可安全 rewrite 的子类仍覆盖 direct total 至少 1%，才实现默认关闭的 transform probe。

## 6. Artifacts

```text
build/logs/xs_perf/no0437/simtop_reg_to_mem_all_groups.log
build/logs/xs_perf/no0437/simtop_reg_to_mem_all_groups.resource
build/logs/xs_perf/no0437/connect_scalar_array_groups.py
build/logs/xs_perf/no0437/scalar_array_group_map.tsv
build/logs/xs_perf/no0437/scalar_array_group_summary.txt
build/logs/xs_perf/no0437/branch_not_in_update_groups.tsv
```
