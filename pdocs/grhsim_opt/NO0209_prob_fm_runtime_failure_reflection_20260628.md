# NO0209 Prob/FM CoreMark 50k Runtime Failure Reflection

日期：2026-06-28

关联：

- [`NO0207`](./NO0207_activity_schedule_prob_partition_upgrade_plan_20260625.md)
- [`NO0208`](./NO0208_activity_schedule_prob_partition_rollout_progress_20260625.md)
- [`NO0085`](./NO0085_xs_no0076_fresh_rerun_20260510.md)
- [`NO0086`](./NO0086_grhsim_runtime_aware_coarsen_ordering_experiments_20260511.md)
- [`NO0198`](./NO0198_xiangshan_coremark50k_runtime_profile_no_preserve_20260615.md)

## 结论先写

这次 `prob + mixed DP + FM` 在 CoreMark 50k 上失败，不是一个小参数问题，也不是“FM 实现没调好”。更核心的问题是：我把 **prob 内部的 weighted-boundary 改善**误当成了**相对 plain 的 runtime 候选信号**，实验推进顺序错了。

最终事实：

- `dp1_fm4` 相对 prob baseline 的确降低了 weighted boundary；
- 但相对真正默认基线 `plain`，它把 `dag_edges` 变成 `1.98x`，把 `boundary_activation_edges` 变成 `1.18x`，把 `compute_compute_value_pairs` 变成 `1.21x`；
- CoreMark 50k runtime 从 `326,433ms` 退到 `628,792ms`，慢 `1.93x`。

因此这条线当前不能作为 runtime 候选继续推进。保留它最多只能作为诊断/研究分支，不能进默认策略，也不能再用“prob 内部结构变好”来给 runtime 试验背书。

## 1. 失败证据

### 1.1 runtime 对照

公共口径：

- workload：`coremark-2-iteration.bin`
- difftest：on
- `XS_SIM_MAX_CYCLE=50000`
- waveform / commit trace / GrhSIM perf：off
- 两组 fresh emit/build，独立 `XS_GRHSIM_BUILD`

| case | host time | cycles/s | 25k host_ms | instrCnt | cycleCnt | guest cycle spent |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `plain` | 326,433 ms | 153.17 | 128,141 | 73,580 | 49,996 | 50,001 |
| `prob_dp1_fm4` | 628,792 ms | 79.52 | 264,415 | 73,580 | 49,996 | 50,001 |
| ratio | 1.926x slower | 0.519x | 2.064x | same | same | same |

日志：

- `build/logs/xs/xs_wolf_grhsim_coremark50k_plain_run_20260628.log`
- `build/logs/xs/xs_wolf_grhsim_coremark50k_prob_dp1_fm4_run_20260628.log`

机器 gate：

- `plain`：`coremark50k-fast` PASS
- `prob_dp1_fm4`：`coremark50k-fast` FAIL，仅 host time 失败；correctness 口径一致

### 1.2 相对 plain 的静态结构

| case | compute_supernodes | dag_edges | boundary_activation_edges | compute_compute_value_pairs |
| --- | ---: | ---: | ---: | ---: |
| `plain` | 72,180 | 702,085 | 2,451,342 | 2,098,240 |
| `prob_dp1_fm4` | 71,656 | 1,390,609 | 2,890,748 | 2,537,646 |
| delta | -524 | +688,524 | +439,406 | +439,406 |
| ratio | 0.993x | 1.981x | 1.179x | 1.209x |

这里已经足够说明问题：`compute_supernodes` 少了不到 1%，但调度 DAG 和 compute-to-compute activation 工作量大幅增加。CoreMark 50k 慢 `1.93x` 与 `dag_edges≈1.98x` 的方向高度一致。

### 1.3 prob 内部结构改善是真的，但不够

以 `dp0_fm0` 为 prob 内部 baseline：

| metric | `dp0_fm0` | `dp1_fm4` | delta | ratio |
| --- | ---: | ---: | ---: | ---: |
| `dag_edges` | 1,526,750 | 1,390,609 | -136,141 | 0.911x |
| `boundary_activation_edges` | 3,065,763 | 2,890,748 | -175,015 | 0.943x |
| `boundary_edge_pi_sum` | 1,045,171.534 | 979,944.896 | -65,226.638 | 0.938x |
| `boundary_edge_change_weight_sum` | 1,292,711.596 | 1,235,870.439 | -56,841.157 | 0.956x |
| `compute_compute_value_pairs` | 2,712,661 | 2,537,646 | -175,015 | 0.935x |

这说明 FM 对 prob 自己的坏结构有修复作用，但它只是把一个远差于 plain 的结构修好一小段；没有跨过 plain 这条硬基线。

## 2. 我前面判断错在哪里

### 2.1 把局部 baseline 当成了真正 baseline

Step 8 structure gate 只比较了：

- `dp0_fm0`
- `dp0_fm4`
- `dp1_fm0`
- `dp1_fm4`

这些都是 `partitionPolicy=prob` 内部组合。这个 A/B 能回答“FM 在 prob 路径内是否改善”，不能回答“prob/FM 是否值得和 plain 比 runtime”。

真正应该最先做的是：

```text
plain structure gate
prob candidate structure gate
plain 50k runtime
prob candidate 50k runtime
```

而不是先在 prob 内部扫出一个最优点，再补 plain 对照。顺序反了。

### 2.2 优化目标和 runtime 主成本不一致

`boundary_edge_pi_sum` / `boundary_edge_change_weight_sum` 是我新增的静态代理目标。它们的问题是：

- 只在 final boundary 上计 value fanout，不直接计 generated C++ 的控制流、函数体大小、activation propagation 热路径；
- 使用静态 `pi`，不是 CoreMark 实际 `f`；
- 没有表达 `dag_edges/outdeg/code footprint/cache/branch/load-store dispatch` 的宿主成本；
- 没有把 commit 阶段 `sink/succ` 的已知大头纳入目标。

这次数据直接打脸：`dp1_fm4` 的 weighted boundary 相对 prob baseline 降了，但相对 plain 的 `dag_edges` 和 activation 规模仍大得多，runtime 跟着大幅回退。

### 2.3 supernode 数是误导指标

`prob_dp1_fm4` 的 `compute_supernodes=71656`，比 plain 的 `72180` 少 `0.73%`。如果只盯 supernode 数，会误以为它更紧凑。

但 runtime 更敏感的是每轮 eval 要走多少边、多少 activation、多少跨 supernode value：

```text
dag_edges:                  +98.1%
boundary_activation_edges:  +17.9%
compute_compute_value_pairs:+20.9%
host time:                  +92.6%
```

所以这次应该把 `dag_edges` / `compute_compute_value_pairs` / `boundary_activation_edges` 放在 supernode 数之前作为硬门槛。

### 2.4 FM 的移动单位和约束不够贴近 codegen 成本

当前 FM 的移动单位是 coarsen 后的 `NodeClusterView` cluster，目标是减少 weighted boundary。它检查了：

- op cap；
- footprint cap；
- `phi`；
- weight cap；
- 保守 topo 无环。

但没有硬约束：

- final `dag_edges` 不得高于 plain；
- `outdeg_p99/max` 不得高于 plain；
- `compute_compute_value_pairs` 不得高于 plain；
- generated `sched_*.cpp` 行数 / `.text` / emu 大小不得显著高于 plain；
- runtime profile 中 `n_comp/n_src/a_succ` 的动态加权成本不得高于 plain。

所以 FM 能在一个错误目标上高效移动 175,258 次，最后仍然得到 runtime 更差的代码。

### 2.5 我忽略了仓库里已有的负例经验

这不是第一次“静态 activation 改善但 runtime 退化”：

- `NO0085`：activation-affinity ordering 让静态 activation 降 `12.82%`，CoreMark 50k wall time 回退 `18.49%`。
- `NO0086`：简单增大 supernode 粒度 / 降低静态边界，不保证 runtime；文档已经写了后续必须 runtime-aware。
- `NO0110` / `NO0120` 也说明局部代码形态或静态调用减少，不等于 host runtime 改善。

我这次没有把这些历史教训变成 Step 8 的硬 gate，这是流程错误。

### 2.6 这条线没有打到当前 GrhSIM 的已知大头

`NO0198` 的 runtime profile 已经指出：

- GrhSIM 的 `n_sink * f` 是 gsim 的 `7.68x`；
- `a_succ * f` 是 gsim 的 `6.79x`；
- 大头集中在少量大 commit supernode / array-register 展平相关路径；
- host gap 里还有单位 feature 成本约 `4.90x` 的问题。

Step 8 prob/FM 基本在 compute supernode partition 上做文章。它没有直接降低 commit sink/succ 大头，也没有解决 array-register 展平或 commit activation mask 的主问题。即使 compute weighted-boundary 局部改善，也不足以覆盖 DAG/activation 变差带来的损失。

## 3. 当前失败原因归纳

更准确的根因分层如下。

### A. 实验设计失败

我没有把 `plain` 作为第一硬基线，而是先在 prob 路径内部找最优。这导致“局部正向”被误读成“候选可进 runtime”。

### B. 目标函数失败

`boundary_edge_pi_sum` 和 `change_weight_sum` 只能描述一部分边界 value 的静态变化概率，不是 host runtime 目标。它缺少 firing frequency、code shape、activation walk、cache/branch、commit sink/succ 等关键项。

### C. 约束集合失败

Prob/FM 允许 `dag_edges` 相对 plain 接近翻倍。这个级别的结构回退本应直接禁止进入 50k runtime。

### D. 方向优先级失败

当前 GrhSIM XiangShan 50k 的主要收益来自已证明有效的 commit 分组 / activation mask / array-register 形态改善等方向；prob compute partition 没有优先打这些高权重项。

## 4. 以后必须执行的门槛

以后任何 activity-schedule partition 候选，必须先过下面顺序，不能跳。

### 4.1 plain-first structure gate

每个候选都必须和同一源码、同一 `post_stats_json` 的 `plain` 比。没有 plain 对照，不许说“结构正向”。

最低限：

| metric | candidate 要求 |
| --- | --- |
| `dag_edges` | 不高于 plain；若高于 5%，直接 reject |
| `boundary_activation_edges` | 不高于 plain；若高于 5%，直接 reject |
| `compute_compute_value_pairs` | 不高于 plain；若高于 5%，直接 reject |
| `outdeg_p99/max` | 不得明显高于 plain |
| schedule time | 不得明显高于 plain，除非 runtime 已有强证据 |

### 4.2 runtime gate 前置缩短

候选如果连 plain structure gate 都过不了，不跑 50k。最多跑小规模 smoke 验 correctness，不做性能判断。

### 4.3 目标函数必须 runtime-aware

下一版目标不能再只看静态 `pi`。至少要引入：

- per-supernode / per-value 实际 firing frequency `f`；
- generated code footprint；
- `dag_edges/outdeg`；
- activation propagation 数；
- commit sink/succ 成本；
- 历史 profile 中已知高成本项的权重。

否则只是在优化漂亮的结构数字。

### 4.4 文档里必须写 kill criteria

每个阶段文档除了“下一步”还必须写：

- 什么时候停止；
- 哪个指标恶化就直接 reject；
- 是否允许进入 runtime；
- 与 plain 的比较是否已经完成。

Step 8 就缺这个，所以推进过头了。

## 5. 当前处理建议

1. `partitionPolicy=plain` 继续保持默认，不动。
2. `prob/FM` 不作为 runtime 候选推进；只保留显式实验开关。
3. 不建议继续补 `dp0_fm0/dp0_fm4/dp1_fm0` 的 50k 性能 A/B 来“找惊喜”。plain 对照已经足够否定这条组合。
4. 如果继续研究 prob partition，先做 plain 对齐结构目标，而不是再调 `pi/alpha/penalty/FM rounds`。
5. 更优先的工程方向应回到已有 profile 指向的高收益区：
   - commit activation mask group；
   - array-register / reg-to-mem 形态；
   - generated C++ code footprint 和 activation dispatch 成本。

## 6. 现有 prob 框架内仍可尝试的跨边界减少机会

回答当前问题：**有机会，但第一目标必须是把 prob 的跨边界结构拉回 plain 附近，而不是继续优化 prob 自己的 weighted-boundary。**

当前代码事实：

- 在 compute-node coarsen 阶段，`partitionPolicy=prob` 走 `tryMergeNodeProb(...)`；
- `plain` 路径才走 `tryMergeNodeOut1(...)` / `tryMergeNodeIn1(...)` / `tryMergeNodeSiblings(...)`；
- 两条路径现在是互斥的，不是“plain 确定性降边界合并先打底，再叠加 prob gain”。

这解释了一个关键现象：prob coarsen 后 cluster 数仍有 `920,723`，plain coarsen 后只有 `464,998`。即使最后 compute supernode 数都在 7.2 万附近，prob 仍在更碎的 cluster graph 上做 DP/FM，导致跨 cluster / 跨 supernode 边界显著更多。

### 6.1 机会 A：prob 先跑 plain deterministic merge seed

优先级最高。

做法：

1. 在 `partitionPolicy=prob` 下，先执行一轮或多轮 plain 的结构性低风险合并：
   - out1：单后继 producer 吸到后继；
   - in1：单前驱 consumer 吸到前驱；
   - siblings：相同 pred set 的 sibling 合并；
2. 再在这个 seed 上执行 `tryMergeNodeProb(...)`；
3. 保留现有 cap / topo / fixed-boundary 约束；
4. 记录新增统计：
   - `prob_seed_out1_merges`
   - `prob_seed_in1_merges`
   - `prob_seed_sibling_merges`
   - seed 后 `clusters_before_prob`

预期：

- 如果 prob 失败的主因是缺失 plain 确定性合并，这一步应显著降低 `dag_edges` / `boundary_activation_edges`；
- 这不需要新 IR，也不需要 runtime profile；
- 若 seed 后 weighted 指标略差，但 unweighted boundary 接近 plain，也比当前方向更有 runtime 意义。

硬 gate：

| metric | 目标 |
| --- | --- |
| `clusters_after_coarsen` | 必须明显接近 plain 的 `~465k`，不能仍停在 `~920k` |
| `dag_edges` | 必须从 `1.39M` 明显下降，目标先压到 `<= plain * 1.10` |
| `boundary_activation_edges` | 目标先压到 `<= plain * 1.05` |
| `compute_compute_value_pairs` | 目标先压到 `<= plain * 1.05` |

如果做不到，说明 prob gain 本身在破坏 plain 的低风险边界收敛，应停止 prob coarsen 方向。

### 6.2 机会 B：把 prob chain candidate 从互为唯一放宽到 one-sided out1/in1

当前 `tryMergeNodeProb(...)` 的 chain candidate 很保守：只接受 `cluster.succs.size()==1` 且 `succ.preds.size()==1` 的互为唯一链。plain 的 out1/in1 更宽：

- out1 只要求当前 cluster 单后继；
- in1 只要求当前 cluster 单前驱。

这意味着 prob 漏掉了大量 plain 可以合并、且通常会减少跨边界的 one-sided 链。

做法：

- 在 prob candidate generation 中加入 one-sided out1/in1 candidates；
- 用 prob gain 排序，但必须加 unweighted boundary guard；
- 统计 `prob_candidate_out1` / `prob_candidate_in1` / accepted 数。

这个方案比 6.1 更“prob 原生”，但风险也更大：如果 gain 函数仍错，它会继续选错。因此优先级低于 deterministic seed。

### 6.3 机会 C：prob coarsen gain 加 unweighted boundary 项

当前 prob gain 更偏向：

```text
edgeTotalProb * weight
checkSaved
active * weight expansion penalty
```

它没有把“每条跨边界边自身就有固定 host 成本”作为一等项。CoreMark 50k 的结果说明这个固定成本不能忽略。

下一版 gain 应至少改成 composite：

```text
gain =
  beta_count  * saved_unweighted_boundary_fanout
+ beta_pi     * saved_weighted_boundary
+ beta_dag    * saved_cluster_dag_edge
+ checkSaved
- active_work_expansion
```

第一版参数可以保守：

- `beta_count=1.0`
- `beta_pi=0.25~1.0`
- `beta_dag=1.0`

硬约束：

- weighted gain 可以决定排序；
- 但 unweighted boundary gain 不得为负；
- 任何合并若预计增加 cluster DAG edge 或 activation fanout，默认 reject。

### 6.4 机会 D：DP / FM 增加 unweighted guard，而不是只看 weighted cut

DP 已经有 `mixed-pi = 1 + alpha*pi`，但仍只是在局部 segment cost 上表达。FM 当前也以 weighted move gain 为主。

可做两层 guard：

1. DP 同时计算两个方案：
   - unweighted DP；
   - mixed weighted DP；
   - 用估算的 `(unweighted_boundary, dag_edges, weighted_boundary)` tuple 选，不允许 mixed 方案 unweighted 明显更差。
2. FM move 必须满足：
   - weighted gain > 0；
   - unweighted fanout gain >= 0；
   - segment outdeg / owner fanout 不增加。

这不会解决 prob coarsen 初始 cluster 太碎的问题，但能防止 DP/FM 在错误目标上继续扩大边界。

### 6.5 机会 E：plain fallback / hybrid select

在 stop-after structure gate 中，可以同时生成：

- plain partition；
- prob hybrid partition；

然后按 hard tuple 选择：

```text
(dag_edges, boundary_activation_edges, compute_compute_value_pairs, weighted_boundary)
```

这个更像实验工具，不一定适合默认编译路径，因为双生成会增加 schedule 时间。但它适合快速判断：prob 的任何新策略是否真的跨过 plain。

### 6.6 推荐执行顺序

不要从 FM 继续调参。按下面顺序来：

1. **先做 6.1 deterministic seed**：prob 路径先继承 plain out1/in1/siblings 合并，再跑 prob。
2. 跑 stop-after structure gate，只和 plain 比：
   - 若 `dag_edges / boundary_activation_edges / compute_compute_value_pairs` 仍明显高于 plain，停止；
   - 不跑 50k。
3. 若 6.1 接近 plain，再做 6.3 composite gain，避免 prob 后续合并破坏 unweighted boundary。
4. 最后才考虑 6.4 DP/FM guard。

### 6.7 明确的成功条件

下一次 prob 候选必须至少达到：

| metric | 必须满足 |
| --- | --- |
| `dag_edges` | `<= plain * 1.05` |
| `boundary_activation_edges` | `<= plain * 1.05` |
| `compute_compute_value_pairs` | `<= plain * 1.05` |
| `compute_supernodes` | 不作为主要成功指标 |
| CoreMark 50k | 只有 structure 过门槛后才跑 |

如果这些结构门槛都过了，再谈 runtime。否则就是重复这次错误。

## 7. 给后续自己的硬提醒

不要再把“某个新策略内部改善”写成“候选正向”。真正基线只有默认 `plain` 和 CoreMark 50k runtime。

如果一个候选相对 plain：

```text
dag_edges +98%
boundary_activation_edges +18%
compute_compute_value_pairs +21%
```

它不应该进入性能候选。即使它在自己的小世界里把 weighted-boundary 降了 6%，也只是把坏结构修得没那么坏。
