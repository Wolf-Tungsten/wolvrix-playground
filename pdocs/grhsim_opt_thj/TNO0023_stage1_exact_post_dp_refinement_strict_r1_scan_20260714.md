# TNO0023 Stage 1 exact post-DP refinement and strict-r1 structure scan

记录日期：2026-07-14

状态：实现与 focused test PASS，`strict / rounds=1` 的 SimTop structure scan PASS；尚未生成候选 C++/emu，也尚未执行 100-cycle、10k 或 50k runtime gate。核心与 XiangShan 默认均保持 `off`。

## 1. 本轮范围

本文落实 [TNO0021](./TNO0021_current_default_baseline_and_stage1_refinement_plan_20260714.md) 的 Stage 1：在 current-default plain DP partition 形成之后、flatten 为最终 compute supernode 之前，加入 bounded exact refinement。它不替换 plain coarsen/DP，不恢复历史 prob/CBAW/FM 路径，也不改变 graph op/value、commit、reg-to-mem 或 emitter activation 语义。

SimTop structure scan 复用 [TNO0022](./TNO0022_fresh_current_default_no0300_baseline1_20260714.md) 的 fresh pre-reg-to-mem checkpoint，因此输入 graph 与 current-default NO0300 基线一致。本轮显式设置：

```text
WOLVRIX_XS_GRHSIM_POST_DP_REFINE_POLICY=strict
WOLVRIX_XS_GRHSIM_POST_DP_REFINE_MAX_ROUNDS=1
WOLVRIX_XS_GRHSIM_POST_DP_REFINE_MAX_MOVES=4096
WOLVRIX_XS_GRHSIM_POST_DP_REFINE_MAX_MOVED_OP_PPM=10000
WOLVRIX_XS_GRHSIM_POST_DP_REFINE_MAX_REGRESSION_PPM=10000
```

生成流程在 activity-schedule stats 写出后停止。原始日志和结构结果为：

```text
build/logs/xs/xs_wolf_grhsim_build_activity_stage1_strict_r1_scan_20260714.log
build/xs_activity_stage1_strict_r1_20260714/grhsim/grhsim_emit/activity_schedule_supernode_stats.json
```

## 2. 接口与默认行为

新增的公共 options 为：

| Option | Default | 含义 |
| --- | --- | --- |
| `postDpRefinePolicy` | `off` | `off / strict / bae-budget / balanced` |
| `postDpRefineMaxRounds` | `1` | bounded refinement 最大轮数 |
| `postDpRefineMaxMoves` | `4096` | 最多移动的 cluster 数；一次 swap 计两个 |
| `postDpRefineMaxMovedOpPpm` | `10000` | moved-op 总预算，默认 compute ops 的 `1%` |
| `postDpRefineMaxRegressionPpm` | `10000` | mixed policy 相对初始 partition 的单项回退预算，默认 `1%` |

这些参数已同步到 activity-schedule CLI、Python binding kwargs 和 XiangShan GrhSIM 脚本环境变量；脚本会把实际值打印到生成日志。policy 只接受上述四值，两个 ppm 参数均限制为不超过 `1,000,000`。

默认 policy 是 `off`，此时不进入 evaluator，也不修改 plain segments。focused test 已比较“未指定 policy”和显式 `off` 的 session schedule 输出并确认相同。当前 SimTop 级 explicit-off fresh identity 运行尚未完成，因而本文不把 generated source byte identity 写成已闭合结论。

## 3. Exact evaluator

refinement 同时维护 compute BAE 与最终 quotient DAG 两套精确状态：

- compute BAE 按每个 value 的 distinct target segment 计数，并排除 producer 所在 segment；`value -> target segment` refcount 使 target cluster 移动后可以按 `0 <-> nonzero` 更新 distinct 数。
- DAG 从 cluster DAG 的全部 compute-compute edge 和 compute-commit edge 建立 quotient pair refcount；move/swap 只收集与被移动 cluster 相邻的 logical edge，再精算 quotient pair refcount 的 `0 <-> nonzero` 变化。
- 每个 proposal 都使用 move/swap 后的 owner 同时计算 source、target、pred 和 succ，因而 swap 的两侧不是按两个相互独立的单点 move 近似。
- proposal 接受前重新按当前 partition 计算 exact delta；应用后同步更新 value-target、compute-commit 和 DAG refcount。
- 每个有接受项的 round 结束后执行 compute BAE 与 DAG full recount；在最终 schedule 构造后，再用实际 schedule stats 校验 modeled compute BAE/DAG。任一不一致都使 pass 失败。

这里日志中的 `compute_bae_*` 只对应 compute-compute value pairs；总 `boundary_activation_edges` 还包含 compute-commit value pairs。本轮没有 oversize final split，因此 modeled 值与 final full recount 可直接逐项核对。

## 4. Move、swap 与不变量

单点 move 的 destination 来自 incident value/commit 的 peer segment 以及 cluster DAG 的直接 pred/succ owner。候选先按 affinity 排序，再按 BAE/DAG normalized gain 稳定排序；应用时重新检查：

- source segment 仍非空，destination 不超过 compute cap；
- 所有直接 pred 位于同 segment 或更早 segment，所有直接 succ 位于同 segment 或更晚 segment；
- policy 仍满足，且 moved-cluster/moved-op 预算仍有余额；
- 每个 cluster 在整个 refinement 中最多移动一次。

被容量阻塞、但 exact metric 与 policy 已通过的 move 可以成为 swap seed。swap 枚举 destination segment 中可释放足够容量的 cluster，同时检查交换后两侧 cap、两侧 proposed-owner topology 和联合 exact delta。实现包含该路径，但本轮 SimTop scan 先接受了 `4096` 个 move，已经耗尽 moved-cluster cap，所以最终 `swaps=0`；这不表示 full-cap swap 机制不存在或没有候选。

以下 cluster 被锁定：包含 `indivisible` op、带非空 reg-to-mem intent group、超过 cap、需要 oversize split 的 cluster；split-sensitive cluster 所在 segment 和相邻 pred/succ 也一并保护，避免 refinement 改变 final split 语义。本轮 current-default graph 在该阶段没有需要保护的 cluster，日志为 `locked_clusters=0`。

## 5. SimTop 规模复杂度修正

直接为每个 cluster 展开所有 high-fanout value 的全部 target segment 会使候选构造成本失控。当前实现保留 exact evaluator，但把启发式候选发现限制为：

- 每个 value 或 commit endpoint 只保留 affinity 最高的 `4` 个 peer segment；
- 每个 cluster 合并 value/commit peer 与 DAG neighbor 后最多检查 `16` 个 destination；
- 每轮最多保留 `32,768` 个 capacity-blocked move seed，并最多构造 `65,536` 个 swap candidate；
- exact evaluation 只访问被移动 cluster 的 incident values/edges，复用 stamp array 和 scratch buffer，避免 proposal 级全图 recount 与重复大对象分配。

这些限制只裁剪 destination discovery，不把 BAE/DAG 计算改成近似；保留下来的 proposal 仍经过 exact delta、应用前复算和 round/final full recount。该修正后，SimTop strict/r1 的 refinement 本体耗时为 `2,533 ms`。

## 6. Focused tests

focused target 已通过：

```text
cmake --build wolvrix/build --target transform-activity-schedule -j4
ctest --test-dir wolvrix/build --output-on-failure -R '^transform-activity-schedule$'
```

CTest 结果为 `1/1 PASS`，test time `0.05 s`。新增或扩展的检查包括：

- default policy 与显式 `off` 产生相同 schedule；
- slack segment 上的 strict move 可确定性地同时降低 BAE 与 DAG；
- 两侧满 cap 时 strict swap 可确定性地同时降低 BAE 与 DAG；
- strict 开启时 reg-to-mem dynamic-input intent group 仍保持原子性；
- 通用 schedule shape、cap、topology 与重复运行确定性检查继续通过。

本项只代表 focused unit gate；完整 CTest、emitter test 和 SimTop 功能 gate 留给后续候选 build/runtime 文档。

## 7. Strict/r1 structure scan

refinement 搜索统计为：

| Metric | Result |
| --- | ---: |
| rounds | `1` |
| retained candidates | `49,676` |
| accepted moves / swaps | `4,096 / 0` |
| moved ops | `51,569` |
| moved-op budget | `56,251`（`5,625,117` compute ops 的 `1%`，向下取整） |
| locked clusters | `0` |
| rejected by capacity | `385,401` |
| rejected by topology | `1,449,288` |
| rejected by policy | `658,981` |
| refinement elapsed | `2,533 ms` |

`retained candidates` 是每 cluster 筛选后的 best move 加上 bounded swap candidates；三类 rejection 统计的是 destination/swap proposal 检查次数，两者不是同一分母，不能据此直接计算 acceptance rate。当前先触发的是 `4096` moved-cluster cap，而不是 `1%` moved-op cap。

结构对照如下：

| Metric | Current-default baseline | strict/r1 | Delta |
| --- | ---: | ---: | ---: |
| graph ops / values | `7,204,108 / 6,833,009` | `7,204,108 / 6,833,009` | `0 / 0` |
| total / compute / commit supernodes | `63,726 / 63,241 / 485` | `63,726 / 63,241 / 485` | `0 / 0 / 0` |
| compute BAE / compute-compute pairs | `1,721,698` | `1,699,454` | `-22,244` (`-1.2920%`) |
| compute-commit pairs | `262,225` | `262,225` | `0` |
| total boundary activation edges | `1,983,923` | `1,961,679` | `-22,244` (`-1.1212%`) |
| boundary values | `1,000,463` | `998,394` | `-2,069` (`-0.2068%`) |
| DAG edges | `528,622` | `508,629` | `-19,993` (`-3.7821%`) |
| compute ops p99 / max | `108 / 108` | `108 / 108` | `0 / 0` |

日志 modeled 值为 `compute_bae 1,721,698 -> 1,699,454`、`dag_edges 528,622 -> 508,629`；final stats JSON 精确复现 `compute_compute_value_pairs=1,699,454` 和 `dag_edges=508,629`。同时 `1,699,454 + 262,225 = 1,961,679`，与 final total BAE 一致。由此 Stage 1 exact evaluator 的本轮 SimTop full recount gate 闭合。

## 8. 当前结论与下一步

strict/r1 在不改变 graph 大小、supernode 数或 compute cap 的前提下，将 total BAE 降低 `1.1212%`、DAG edges 降低 `3.7821%`，refinement 阶段实测耗时为 `2,533 ms`；它通过结构门槛，值得进入候选 emit/build 和 SimTop 50k。

本文仍不能下 runtime 正收益结论。下一步应完成 explicit-off SimTop identity、strict/r1 fresh C++ emit/build、100-cycle/10k/50k 功能门禁，并按 TNO0022 固定的 CPU106/298、NUMA1、fixed-ASLR 口径完成 `baseline1 / candidate / baseline2` quiet A/B/A。若 50k 无正收益，再结合 generated C++、`.text`、PMU/perf 判断是否扫描 rounds `2/4` 或 mixed policy；结构下降本身不替代 50k 裁决。
