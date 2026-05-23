# NO0185 XS Components 对齐后的 GrhSIM Coarsen 策略记录

日期：2026-05-23

## 背景

本轮目标不是继续追 XiangShan CoreMark runtime，而是先把 `testcase/xs-components`
上已经验证过的 GrhSIM 策略固化下来，避免后续讨论时混淆以下三件事：

- coarsen 阶段是否受 `cap` 限制；
- coarsen 之后是否还会把大块按 `cap=8` 拆开；
- `xs_wolf_grhsim` 的默认参数是否已经和 `testcase/xs-components` 对齐。

本文记录的是已经在 `xs-components` 矩阵上跑通过的口径；后续为了 full
XiangShan `final_materialize` 构建时间做的 boundary-gain 批量化尝试，不计入本文
“已验证策略”。

## 当前策略

### 1. Coarsen 阶段不再受 DP cap 限制

`activity-schedule` 中普通 coarsen 的 merge cap 被放宽为无限大：

```text
coarsenMaxNodes = std::numeric_limits<std::size_t>::max()
```

它传给：

```text
tryMergeNodeOut1
tryMergeNodeIn1
tryMergeNodeBoundaryGain
```

含义是：coarsen 只按图结构和合并策略决定能否合并，不再因为
`max_op_in_compute_supernode=8` 提前停止。

这里的 `cap=8` 不再代表“coarsen 最多合 8 个 compute node/op”，而只代表后续
DP 阶段合并 supernode 时的上限约束。

### 2. Coarsen 之后不再按 cap 拆分

已删除原先这类逻辑：

```text
coarsen 后的大块又按 maxOpsPerComputeSupernode flush/split
```

也就是说，coarsen 形成的大 cluster 会原样进入后续物化流程，不允许因为
`cap=8` 再被切成一串小 supernode。

这点是本轮和 GSIM 对齐的关键。以 `XsPlruLarge` 为例，如果 coarsen 已经把
`1315` 个 compute node 合到大块，再在 final materialize 里按 `cap=8` 切开，
最终会重新膨胀到约 `166` 个 supernode，和 GSIM 的粗粒度结构完全不一致。

### 3. DP 阶段仍然使用 cap

`max_op_in_compute_supernode=8` 仍然保留，但语义收窄为：

- coarsen 之后，DP 可以继续做进一步分段/合并；
- DP 合并时受 `cap=8` 约束；
- DP 不负责把 coarsen 后的大块拆开。

因此当前逻辑可以概括为：

```text
coarsen：只合并，不看 cap
DP：继续合并/分段时看 cap
final materialize：不再把 coarsen 后的大块按 cap 拆开
```

### 4. `splitOversizeComputeNodes` 的位置

`splitOversizeComputeNodes` 仍然存在，但默认关闭：

```text
WOLVRIX_XS_GRHSIM_SPLIT_OVERSIZE_COMPUTE_NODES = false
```

它只在 final materialize 里处理“单个 compute node 自身已经超过
`splitOversizeComputeNodeMaxOps`”的特殊情况。当前 xs-components 对齐策略不依赖
这个开关，默认路径不会触发它。

换句话说，它不是“coarsen 后按 cap 拆 supernode”的主路径。

## xs_wolf_grhsim 参数对齐

顶层 `Makefile` 和 `scripts/wolvrix_xs_grhsim.py` 的 full XiangShan 默认口径：

| 参数 | 当前默认值 | 说明 |
| --- | ---: | --- |
| `XS_WOLF_GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE` | `108` | DP 阶段 compute cap；full XiangShan 普通 coarsen 默认口径 |
| `XS_WOLF_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE` | `4096` | commit supernode cap；full XiangShan 普通 coarsen 默认口径 |
| `XS_WOLF_GRHSIM_SCHED_BATCH_MAX_OPS` | `2048` | emit batch op 上限 |
| `XS_WOLF_GRHSIM_SCHED_BATCH_MAX_ESTIMATED_LINES` | `8192` | emit batch 估算行数上限 |
| `XS_WOLF_GRHSIM_SCHED_BATCH_TARGET_COUNT` | `64` | batch 目标数量 |
| `XS_WOLF_GRHSIM_SCHED_BATCHES_PER_CPP` | `1` | 每个 cpp 的 batch 数 |
| `XS_WOLF_GRHSIM_EMIT_PARALLELISM` | `4` | emit 并行度 |

注意：`xs_wolf_grhsim` 当前固定为 plain coarsen，不再暴露或传递 ESSENT
coarsen 参数。

## xs-components 矩阵验证

命令：

```sh
make -C testcase/xs-components \
  BUILD_DIR=build-no-post-coarsen-split/matrix \
  BENCH_VECTORS=100000 \
  BENCH_VERIFY=2048 \
  matrix
```

结果文件：

```text
testcase/xs-components/build-no-post-coarsen-split/matrix/matrix/results.csv
```

所有 case verify 均通过。

| case | GSIM ms | GrhSIM ms | GrhSIM/GSIM | GSIM supernodes | GrhSIM supernodes |
| --- | ---: | ---: | ---: | ---: | ---: |
| `XsBranchAluSmall` | `2.114` | `2.196` | `1.04x` | `4` | `4` |
| `XsVectorMaskMedium` | `10.267` | `12.139` | `1.18x` | `1` | `1` |
| `XsAgeMatrixMedium` | `4.291` | `3.604` | `0.84x` | `1` | `1` |
| `XsPlruLarge` | `24.220` | `25.880` | `1.07x` | `3` | `3` |
| `XsStoreMergeLarge` | `3.458` | `2.146` | `0.62x` | `1` | `1` |

`XsPlruLarge` 的关键结构结果：

```text
compute_nodes = 1315
compute_supernodes = 2
commit_supernodes = 1
supernodes = 3
dag_edges = 1
boundary_activation_edges = 3
```

它和 GSIM 的 `3` 个 supernode 对齐，是本轮策略的主要正向证据。

## 结论

在 `testcase/xs-components` 规模上，原始 `8/768` 对齐策略成立：

- coarsen 阶段不看 `cap=8`；
- coarsen 之后不再按 `cap=8` 强拆；
- DP 阶段仍保留 `cap=8` 作为进一步合并的约束；
- xs-components 矩阵功能全 pass，且 supernode 数量基本对齐 GSIM。

full XiangShan 默认口径已从 xs-components 的 `8/768` DP/commit cap 调整为
`108/4096`。coarsen 阶段仍不使用 cap；该调整只影响 coarsen 后的 DP 分段和
commit 聚合，避免 full XiangShan 在普通 coarsen 下被重新膨胀到 40 万级
supernode。

## Full XiangShan 默认验证

命令：

```sh
timeout 900s make xs_wolf_grhsim_emit \
  RUN_ID=codex_default_108_20260523 \
  XS_GRHSIM_BUILD=build/xs/grhsim_default_108_20260523 \
  XS_WOLF_GRHSIM_POST_STATS_JSON=build/xs/grhsim/wolvrix_xs_post_stats.json \
  XS_WOLF_GRHSIM_RESUME_FROM_STATS_JSON=1 \
  WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1
```

结果文件：

```text
build/logs/xs/xs_wolf_grhsim_build_codex_default_108_20260523.log
build/xs/grhsim_default_108_20260523/grhsim_emit/activity_schedule_supernode_stats.json
build/xs/gsim/gsim-compile/model/SimTop_supernode_stats.json
```

关键结果：

| 指标 | 数值 |
| --- | ---: |
| plain coarsen | `enable_essent_mffc_build=False`, `enable_essent_coarsen=False` |
| coarsen cap | `coarsenMaxNodes = max()` |
| compute cluster before/after coarsen | `6635278 -> 910492` |
| GrhSIM final supernodes | `56531` |
| GrhSIM compute/commit supernodes | `56016 / 515` |
| GSIM final supernodes | `84714` |
| GrhSIM / GSIM supernode ratio | `0.667` |
| activity-schedule elapsed | `277118 ms` |
| total stopped run elapsed | `299683 ms` |

结论：full XiangShan 默认 plain coarsen 在 10 分钟 gate 内完成，并且 final
supernode 数量回到 GSIM 80k 量级；此前 `422k` 级别的膨胀来自 coarsen 后 DP
cap 过小，不是普通 coarsen 本身失败。

补充：按当前决策，compute-node plain coarsen 不加 XiangShan 大图专用 bound；
如果要继续追 GSIM `graphCoarsen` 的 DP 前 `294107` 规模，需要优化 coarsen
策略本身，而不是用大图限量 fallback。

## XiangShan 放大后的风险

同一策略直接放到 full XiangShan 上，目前还没有拿到新的 CoreMark 50k 速度。

原因不是仿真 runtime 已经失败，而是 fresh rebuild 卡在 activity-schedule 的
`final_materialize` 阶段：

```text
compute_nodes = 6635278
final_materialize start 后长时间无输出
```

旧 binary 曾经跑出过：

```text
50000 cycles
73580 instr
host time = 384822 ms
```

但该 binary 时间戳仍是 `2026-05-21 12:30:09`，不是本轮改动后的有效结果。

因此当前状态应表述为：

- xs-components 上的结构和性能对齐策略已经验证；
- full XiangShan 上需要先解决 `final_materialize` 构建时间问题；
- 在新 emu 未生成前，不能声称拿到了“改动后”的 CoreMark 50k 仿真速度。
