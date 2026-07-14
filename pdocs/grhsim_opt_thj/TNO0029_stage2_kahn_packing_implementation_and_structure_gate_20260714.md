# TNO0029 Stage 2 Kahn packing implementation and structure gate

记录日期：2026-07-14

状态：实现、focused tests、explicit-off SimTop identity 和 standalone strict structure scan PASS；strict/balanced 因 mixed exact metrics 回退，`bae-budget` 满足 1% 预算并进入 fresh emit/build/50k。

## 1. 实现范围

Stage 2 在 coarsen 后 current value-local topological order 与 plain DP 之间加入可选 same-Kahn-level packing。新增 options：

| Option | Default |
| --- | ---: |
| `kahnLevelPackPolicy` | `off` |
| `kahnLevelPackMaxMoves` | `4096` |
| `kahnLevelPackMaxMovedOpPpm` | `10000` |
| `kahnLevelPackMaxRegressionPpm` | `10000` |

policy 支持 `off / strict / bae-budget / balanced`。参数已同步到 C++ CLI 的分离/`=` 两种形式、Python kwargs 和 XiangShan 脚本 `WOLVRIX_XS_GRHSIM_KAHN_LEVEL_PACK_*` 环境变量。两个 ppm 参数限制为不超过 `1,000,000`；core 与 XS 默认均为 `off`。

核心流程为：

1. 对 post-coarsen quotient DAG 计算 Kahn/longest-pred level，但保留 current position slots，不做全 layer 拼接。
2. 对每个 value 的 target clusters 按当前位置扫描，只连接同 level 相邻 target，形成稀疏 affinity pair；每 cluster 保留稳定 top-32 peer，并最多生成 4 个 directed candidate。
3. swap 只发生在同 level position slot；双方 pred/succ 在 proposed position 下逐边检查，每 cluster 最多移动一次，swap 计两个 cluster 与双方 ops。
4. 最终 permutation 做 bijection 与全部 quotient edge full scan；不调用 topo sort 静默修复。
5. 按新顺序完整重建 `NodeClusterView`、`ClusterValueEdges` 和 plain DP，不能复用旧 cluster/value-fanout ID。
6. candidate segment 数不得增加，并逐段验证非空、全覆盖与 108-op cap；candidate 用自己的 segment count 重映射 compute-to-commit endpoint。
7. baseline/candidate 各自 full recount compute BAE 与 quotient DAG，再由 Stage 1 共用且行为等价的 exact policy helper 整体采用或回退；final actual schedule 再次 recount。

大图复杂度限制包括 level scratch/stamp array，避免 per-value hash 小分配；affinity 不展开 high-fanout clique；top-32 discovery 后每 cluster 最多 4 candidates。SimTop 本轮候选为 `206,700`，没有出现无界 candidate explosion。

## 2. Correctness tests 与 review

focused gate：

```text
cmake --build wolvrix/build --target transform-activity-schedule -j4
ctest --test-dir wolvrix/build --output-on-failure -R '^transform-activity-schedule$'
```

结果 `1/1 PASS`，约 `0.04 s`。覆盖：

- unspecified 与 explicit `off` 完整 session equality；
- `maxMoves=0` 与 `maxMovedOpPpm=0` 分别保持 baseline；
- strict packing 确定性地共置 shared-value targets、降低 BAE 且 DAG 不退；
- compute-to-commit fanout 在 cluster/segment ID remap 后保持；
- Stage 2 与 Stage 1 strict 组合的 cap/topology/final recount；
- noncontiguous same-level cross-slot topology fixture；
- 80-target high-fanout bounded/deterministic fixture；
- invalid policy 和两个 ppm 超界诊断；
- dynamic-input reg-to-mem intent 同时开启 Stage 2/Stage 1 仍保持原子性。

`emit-grhsim-cpp` 回归也 PASS，耗时 `231.94 s`。两轮独立只读 review 均未发现 P0/P1；确认 Stage 1 policy helper 抽取与原公式等价，commit endpoint、final recount 和 Stage 1 组合都使用实际 candidate segment count。

## 3. Explicit-off SimTop identity

从 [TNO0022](./TNO0022_fresh_current_default_no0300_baseline1_20260714.md) 的同一 fresh pre-reg checkpoint 恢复，显式设置：

```text
KAHN_LEVEL_PACK_POLICY=off
POST_DP_REFINE_POLICY=off
STOP_AFTER_ACTIVITY_SCHEDULE=1
```

结果 stats JSON 与 current-default baseline 逐字节一致，SHA256 均为：

```text
e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77
```

JSON 的 `182` 个 scalar leaf 全部相同，包括 graph ops/values `7,204,108 / 6,833,009`、SN `63,726`、DAG `528,622`、BAE `1,983,923`。由此 Stage 2 default-off SimTop identity 闭合。

原始产物：

```text
build/logs/xs/xs_wolf_grhsim_build_activity_stage2_kahn_off_identity_20260714.log
build/xs_activity_stage2_kahn_off_identity_20260714/grhsim/grhsim_emit/activity_schedule_supernode_stats.json
```

## 4. Strict structure scan

standalone 扫描保持 Stage 1 `off`，Stage 2 使用 `strict / 4096 moves / 1% moved ops / 1% regression budget`。搜索统计：

| Metric | Result |
| --- | ---: |
| Kahn levels | `517` |
| shared values / affinity pairs | `197,117 / 190,118` |
| directed candidates | `206,700` |
| swaps / moved clusters | `420 / 840` |
| moved ops | `56,251`（命中 `1%` 上限） |
| rejected budget / topology | `204,066 / 104` |
| packing elapsed | `3,683 ms` |
| candidate topology/shape | PASS |

结构对照：

| Metric | baseline | candidate | Delta |
| --- | ---: | ---: | ---: |
| compute segments | `63,241` | `63,166` | `-75` |
| total SN（含 485 commit） | `63,726` | `63,651` | `-75` |
| compute BAE | `1,721,698` | `1,721,423` | `-275` (`-0.0160%`) |
| total BAE | `1,983,923` | `1,983,648` | `-275` (`-0.0139%`) |
| DAG edges | `528,622` | `529,261` | `+639` (`+0.1209%`) |

首版 exact-count equality gate 因 `63,241 -> 63,166` 提前回退；其修正见 [TNO0028](./TNO0028_stage2_same_kahn_level_packing_plan_20260714.md) §6。改为“不得增加”后，candidate cap/topology/full recount 均通过，strict 最终仅因 DAG 增加 `0.1209%` 回退，因此 strict 输出仍为 baseline。

搜索 permutation 与 candidate metrics 不依赖 policy，policy 只做最终 exact adoption：

- `strict`：DAG 退化，reject；
- `balanced`：BAE normalized gain 小于 DAG normalized regression，reject；
- `bae-budget`：BAE 改善，DAG 回退低于 `1%` 预算，accept。

因此不重复运行结果必然相同的 balanced structure search；`bae-budget` 直接进入完整 fresh emit/O3 build 和 SimTop 50k，落实“轻微结构退化也跑最终仿真”的口径。

原始 strict 重扫日志：

```text
build/logs/xs/xs_wolf_grhsim_build_activity_stage2_kahn_strict_nonincrease_scan_20260714.log
build/xs_activity_stage2_kahn_strict_nonincrease_20260714/grhsim/grhsim_emit/activity_schedule_supernode_stats.json
```

## 5. 当前结论

Stage 2 的默认 identity、bounded search、topology/ID remap、exact recount 与 focused correctness 已闭合。候选只获得很小的 BAE 收益，但减少 `75` 个 compute supernode，同时带来 `639` 条 DAG edge 的轻微回退；结构不足以判断 runtime。下一步只以 `bae-budget` fresh generated C++、ELF `.text`、100/10k/50k 和 fixed-ASLR runtime 裁决，默认继续保持 `off`。

## 6. 勘误：baseline DP 与 candidate DP

§1 首句的“在 topological order 与 plain DP 之间加入”是概念上的候选插入点。代码实际先运行 baseline plain DP 以建立比较基准，packing 后再重建 view/value edges 并重跑 candidate plain DP；最终 policy 比较的是这两个完整 DP 结果。该差异不影响本篇结构数据或 default-off 结论。
