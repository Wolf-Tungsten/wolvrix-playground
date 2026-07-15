# TNO0069 Stage 10 fanin pullback strict implementation and structure gate

记录日期：2026-07-16

状态：strict final-schedule compute-node pullback 已实现；focused tests 与 current-default NO0300 production structure gate PASS。84 个候选全部采用，total/compute BAE 精确减少 254，SN、DAG、topo、state-read 与 compute-commit 保持不变，进入 full emit/O3 与跨 NUMA fixed-ASLR 50k。

## 1. 实现边界

既有 `finalFaninPullbackPolicy` 扩展为：

```text
off / probe / strict
```

`probe` 与 `strict` 共用同一 candidate evaluator、稳定排序、冲突选择和 move/PPM/cap 预算。strict 对 selected candidate 移动完整 compute node，不拆分 node；先在候选 schedule 副本中修改 `supernodeToOps` 与 `computeNodesBySupernode`，再对 touched supernode 做 local topo sort。

应用完成后从 schedule partition 完整重建：

```text
opToSupernode / supernodeOfOp
dag
valueFanout
valueSourceKind / valueSourceSupernode
stateReadSupernodes
topoOrder
```

重建包含 reg-to-mem intent 的隐式 index dependency。采用前后执行 exact validators：supernode 数与 kind、scheduled-op multiset、capacity、commit partition、compute-node partition、DAG、topo、state-read、精确 `(value, commit target)` 向量以及 projected/actual BAE gain。任何失败都使 pass 失败，不采用部分结果。strict 仅接受 `level-id` 且要求本轮没有实际 oversize split。

## 2. Focused gate

`transform-activity-schedule` focused test 覆盖：

- gain-3 正例完整移动 compute node，owner 从 target 变为 source，BAE 精确 `-3`；
- SN/kinds/DAG/topo/state-read/commit identity 与全部 validator；
- strict 重复执行确定性；
- `maxMoves=0` 和 moved-op PPM `0` 的 identity；
- 多候选累计 capacity 只选择并应用一个；
- non-`level-id` 与实际 split 明确失败；
- 非空 state-read 和 commit partition 独立 fixture。

执行结果：

```text
cmake --build wolvrix/build --target transform-activity-schedule -j8  PASS
ctest --test-dir wolvrix/build -R '^transform-activity-schedule$'    PASS
git diff --check                                                     PASS
```

## 3. Production 配置

结构扫描从 canonical current-default NO0300 post-reg checkpoint 恢复，ASLR runtime 口径仍固定关闭；除以下实验变量外保持默认配置：

```text
final_fanin_pullback_policy=strict
final_fanin_pullback_max_node_ops=8
final_fanin_pullback_max_value_width=64
final_fanin_pullback_min_gain=3
final_fanin_pullback_max_moves=4096
final_fanin_pullback_max_moved_op_ppm=5000
final_topo_policy=level-id
```

Stage 1/2 refine、Kahn packing、local/shared clone、pure-event packing、direct state-read 和 full active-word consume 均关闭；DP penalty 保持默认 `1000000 PPM`。

## 4. Selection 与 validators

```text
scanned / pure / common_source  1092530 / 330400 / 10893
exact eligible / selected       84 / 84
applied / moved ops              84 / 262
moved-op limit                   28125
projected / actual BAE gain      254 / 254
gain distribution                3:82, 4:2
node-op distribution             3:82, 8:2
max-width distribution           1:84
```

move limit、budget、capacity、target-empty、node/value overlap rejection 均为 0。strict 日志的 11 项 validator 全部为 `true`：

```text
supernodes kinds scheduled_ops capacity commit compute_partition
dag topo state_read compute_commit bae_gain
```

## 5. Final structure

| Metric | current default | Stage 10 strict | Delta |
| --- | ---: | ---: | ---: |
| supernodes | `63,726` | `63,726` | `0` |
| compute supernodes | `63,241` | `63,241` | `0` |
| commit supernodes | `485` | `485` | `0` |
| DAG edges | `528,622` | `528,622` | `0` |
| boundary values | `1,000,463` | `1,000,537` | `+74` (`+0.007397%`) |
| total BAE | `1,983,923` | `1,983,669` | `-254` (`-0.012803%`) |
| compute-compute pairs | `1,721,698` | `1,721,444` | `-254` (`-0.014753%`) |
| compute-commit pairs | `262,225` | `262,225` | `0` |

compute nodes 保持 `1,092,530`，oversize/split 均为 0，compute p99/max 继续为 108。boundary-value 数小幅增加 74，但 exact activation-edge 目标兑现且其它主要结构量不变，不构成明显失败；按既定软门槛继续 runtime gate。

## 6. 产物与决定

```text
activity-schedule total       177206 ms
strict evaluate/apply/rebuild  11287 ms
script total                  206820 ms
stats SHA256                  133ad4da5abf7e93202ccb466cd4940c3a81f8abe8d1bb0b82b076a1a6478520
```

原始产物：

```text
build/xs_activity_stage10_fanin_strict_20260716/grhsim/grhsim_emit/activity_schedule_supernode_stats.json
build/logs/xs/xs_wolf_grhsim_build_activity_stage10_fanin_strict_20260716.log
```

strict 继续保持默认关闭。下一步完成 full emit、O3 build、fixed-ASLR 100/10k 功能门禁，并在 NUMA0/NUMA1 分别执行 quiet 50k A/B/A；最终按最坏 socket 结果决定是否采用。
