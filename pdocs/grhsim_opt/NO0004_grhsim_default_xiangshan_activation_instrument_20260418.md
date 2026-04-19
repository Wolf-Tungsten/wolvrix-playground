# NO0004 GrhSIM Default XiangShan 结构边与 Step 激活统计（2026-04-18）

> 归档编号：`NO0004`。目录顺序见 [`README.md`](./README.md)。

本文记录一次对 `grhsim` 的机理级插桩统计，目标是回答 3 个问题：

1. 最终形成了多少个 `supernode`
2. `supernode` 之间有多少条边
3. 运行时每个 `step` 激活了多少节点

测例选择 `default-xiangshan`，workload 使用 `tmp/gsim/ready-to-run/bin/coremark-NutShell.bin`。

## 口径

- emitted model 目录：`tmp/grhsim_default_xiangshan_activity_20260418/grhsim_emit`
- 可执行文件：`tmp/grhsim_default_xiangshan_activity_20260418/grhsim-compile/emu`
- workload：`tmp/gsim/ready-to-run/bin/coremark-NutShell.bin`
- CPU 绑定：`taskset 0x1`
- 运行窗口：`-C 30000`
- runtime activity 开关：`GRHSIM_ACTIVITY_PROFILE=1`

静态结构统计来自：

- `tmp/grhsim_default_xiangshan_activity_20260418/grhsim_emit/activity_schedule_supernode_stats.json`

运行时统计来自一次实际运行：

```bash
GRHSIM_ACTIVITY_PROFILE=1 EMU_PROGRESS_EVERY_CYCLES=0 taskset 0x1 \
  /home/gaoruihao/wksp/wolvrix-playground/tmp/grhsim_default_xiangshan_activity_20260418/grhsim-compile/emu \
  -i /home/gaoruihao/wksp/wolvrix-playground/tmp/gsim/ready-to-run/bin/coremark-NutShell.bin \
  --no-diff -b 0 -e 0 -C 30000
```

## 插桩口径说明

这次统计是在 `SimTop::eval()` 粒度上做的，因此本文的 `step` 指的是一次 host 侧 `eval()`，不是 guest cycle。对应地：

- 本次 `-C 30000` 的运行最终得到 `step_samples = 60102`
- 可以粗略理解为每个 guest cycle 对应约 2 次 `eval()`，再加少量启动/收尾样本

本次 runtime 统计有两个和“节点激活”相关的量：

### 1. `executed_supernodes_per_step`

定义：

- 在单个 `eval()` 内，按 fixed-point round 扫描 `supernode_active_curr_`
- 每轮把当前 active bit 的 `popcount` 累加起来

这表示：

- 单个 `step` 里被执行了多少次 `supernode`

注意这不是“去重后的激活节点数”。如果同一个 `supernode` 在同一 `step` 的多个 round 中重复进入执行，这个指标会重复计数，因此它可能高于静态总 `supernode` 数。

### 2. `peak_active_supernodes_per_step`

定义：

- 在单个 `eval()` 内，对每个 round 的 `grhsim_count_active_supernodes(supernode_active_curr_)` 取峰值

这更接近：

- 单个 `step` 内，任意时刻等待被处理的活跃前沿宽度

它是有界的，最大值不会超过静态总 `supernode` 数。

### 3. `executed_ops_per_step`

本次 quick validation run 中该指标仍为 `0`，原因是生成代码里还没有把 op 数增量补全到 runtime 计数路径，因此本文不使用它做结论。

## 结果

### 1. 静态结构

| 指标 | 数值 |
| --- | ---: |
| `supernodes` | `74906` |
| `dag_edges` | `1225442` |
| `ops_per_supernode.mean` | `72.93` |
| `ops_per_supernode.median` | `70` |
| `ops_per_supernode.p90` | `72` |
| `ops_per_supernode.p99` | `135` |
| `ops_per_supernode.max` | `4096` |
| `out_degree.mean` | `16.36` |
| `out_degree.median` | `2` |
| `out_degree.p90` | `38` |
| `out_degree.p99` | `157` |
| `out_degree.max` | `16139` |

派生量：

- 平均每个 `supernode` 对应 `16.36` 条 DAG 出边
- 平均每个 `supernode` 包含 `72.93` 个 op

### 1.1 和 `gsim next` 的静态边数对比

如果口径收敛到：

- `grhsim`: final activity-schedule `dag_edges`
- `gsim`: emitted `next` edges

那么这次 `default-xiangshan` 的结果是：

| 指标 | `grhsim` | `gsim` |
| --- | ---: | ---: |
| supernodes | `74906` | `131580` |
| supernode edges | `1225442` | `612269` |
| average outgoing edges / supernode | `16.3597` | `4.6532` |

这说明：

- `grhsim` 的 `dag_edges` 总量约为 `gsim next` 的 `2.00x`
- `grhsim` 的平均出度约为 `gsim next` 的 `3.52x`

这里的 `grhsim dag_edges` 和 `gsim next` 都是 supernode 粒度去重后的边数。

- 如果 `supernode A` 有多个值流向同一个 `supernode B`
- 两边都只记一条 `A -> B`

### 2. Step 级动态统计

| 指标 | 数值 |
| --- | ---: |
| `step_samples` | `60102` |
| `executed_supernodes_per_step.avg` | `6169.76` |
| `executed_supernodes_per_step.min` | `187` |
| `executed_supernodes_per_step.p50` | `262` |
| `executed_supernodes_per_step.p90` | `18873` |
| `executed_supernodes_per_step.p99` | `26102` |
| `executed_supernodes_per_step.max` | `75680` |
| `peak_active_supernodes_per_step.avg` | `457.06` |
| `peak_active_supernodes_per_step.min` | `187` |
| `peak_active_supernodes_per_step.p50` | `187` |
| `peak_active_supernodes_per_step.p90` | `991` |
| `peak_active_supernodes_per_step.p99` | `1379` |
| `peak_active_supernodes_per_step.max` | `74906` |

折算为静态 `supernode` 总量占比：

| 指标 | 占 `74906` 的比例 |
| --- | ---: |
| `executed_supernodes_per_step.avg` | `8.2367%` |
| `executed_supernodes_per_step.p50` | `0.3498%` |
| `executed_supernodes_per_step.p90` | `25.1956%` |
| `executed_supernodes_per_step.p99` | `34.8463%` |
| `executed_supernodes_per_step.max` | `101.0333%` |
| `peak_active_supernodes_per_step.avg` | `0.6102%` |
| `peak_active_supernodes_per_step.p50` | `0.2496%` |
| `peak_active_supernodes_per_step.p90` | `1.3230%` |
| `peak_active_supernodes_per_step.p99` | `1.8410%` |
| `peak_active_supernodes_per_step.max` | `100%` |

### 2.1 和 `gsim active supernodes per step` 的动态对齐

如果按“每次 `eval/step` 总共执行了多少个 supernode”来对齐：

- `grhsim` 应该看 `executed_supernodes_per_step`
- `gsim` 应该看 `active supernodes per step`

原因是：

- `grhsim` 的一个 `eval()` 内可能跨多个 fixed-point round
- 如果某个 supernode 在 `commit_state_updates()` 之后再次被激活并再次执行，这次重复执行应当重新计数

也就是说，`grhsim` 在这个问题上的正确口径不是去重后的 unique supernode 数，而是累计执行次数。

按这个口径，这次结果是：

| 指标 | `grhsim executed_supernodes_per_eval` | `gsim active_supernodes_per_step` |
| --- | ---: | ---: |
| samples | `60102` | `1900000` |
| avg | `6169.76` | `10260.63` |
| min | `187` | `2138` |
| p50 | `262` | `10009` |
| p90 | `18873` | `16437` |
| p99 | `26102` | `18487` |
| max | `75680` | `131580` |

需要单独强调两点：

- `grhsim` 的 `eval` 不是 guest cycle，而是一次 host 侧 `SimTop::eval()`
- `gsim` 的 `step` 是它自己的 step 调度粒度，因此这两组数字可以做机制对照，但不能被误读成同一个时间基准上的一比一吞吐统计

从累计执行次数看：

- `grhsim` 平均每次 `eval()` 执行 `6169.76` 个 supernode
- `gsim` 平均每次 `step()` 执行 `10260.63` 个 supernode

这意味着当前 `grhsim` 的慢，不是因为“单次 `eval()` 内总共扫过的 supernode 数比 `gsim` 更大”；至少在这次样本里，现象正好相反。

因此 `grhsim` 当前更值得怀疑的点仍然是：

- 单次 supernode 执行的 host 侧动态成本更高
- fixed-point / commit 循环带来的调度控制流更重
- 每次进入有效工作前后的框架开销更大

运行末尾上下文：

- `cycleCnt = 29996`
- `instrCnt = 29365`
- guest `IPC = 0.978964`
- host time spent = `424811ms`

## 机理层面的解读

### 1. `grhsim` 的静态图规模并不小

虽然当前 `grhsim` 的 `supernode` 总数只有 `74906`，明显低于 `gsim` 的 `131580`，但它的 `dag_edges = 1225442` 仍然很大。

如果把 `gsim` 的 `next + depNext` 合并看作更宽口径边集：

- `gsim`: `612269 + 720151 = 1332420`
- `grhsim`: `1225442`

那么 `grhsim` 的边规模已经接近 `gsim` 的 `91.97%`，并不是一个很“稀疏”的小图。

### 2. 单步瞬时活跃前沿其实很窄

从 `peak_active_supernodes_per_step` 看：

- 平均峰值只有 `457.06`
- `p90 = 991`
- `p99 = 1379`

也就是绝大多数 `eval()` 中，单轮待处理的活跃前沿只占总图的 `1%` 左右。

这说明：

- `grhsim` 运行时并不是每轮都在扫大面积全图
- 真正同时挂在 active set 上的 `supernode` 数量相当有限

### 3. 但单步内会发生重复执行

`executed_supernodes_per_step.max = 75680` 已经超过静态总量 `74906`，这说明同一个 `supernode` 会在一个 `step` 内跨多个 fixed-point round 被重复执行。

因此从机制上看，`grhsim` 当前的运行时工作量至少包含两层：

- 窄前沿上的活跃传播
- 同一步内的重复 round / 重复执行

如果后续要继续优化，这个“重复 round 导致的重复触发”是很值得盯的点。

### 4. 和 `gsim` 的 runtime 节点激活口径不能直接机械一比一

当前 `gsim` 文档里的 `active supernodes per step` 更接近：

- 每步实际进入执行的节点数

而本次 `grhsim` 提供的是两个不同语义：

- `executed_supernodes_per_step`
  - 更接近“每步累计执行次数”
- `peak_active_supernodes_per_step`
  - 更接近“每步任意时刻的活跃前沿宽度”

因此：

- `gsim avg active supernodes/step = 10260.63`
- `grhsim avg executed supernodes/step = 6169.76`
- `grhsim avg peak active supernodes/step = 457.06`

这三者可以帮助定位机制差异，但不能被解释为严格同义指标。

## 对后续 `gsim/grhsim` 机制对齐最有价值的点

如果继续往下对齐，我建议把 `grhsim` 这边固定追下面两类量：

1. 静态图规模
   - `supernodes`
   - `dag_edges`
   - `ops_per_supernode`
   - `out_degree_per_supernode`
2. 单步动态行为
   - `executed_supernodes_per_step`
   - `peak_active_supernodes_per_step`
   - 单步 fixed-point round 数
   - 单步重复执行的 `supernode` 数

其中最缺的一项是：

- 单步 fixed-point round 数

只要把它补上，就能把“窄前沿但仍然慢”进一步拆解成：

- round 数过多
- 单 round 内调度开销过大
- 单 `supernode` 进入后执行成本过高

## 产物位置

- 静态结构统计：
  - `tmp/grhsim_default_xiangshan_activity_20260418/grhsim_emit/activity_schedule_supernode_stats.json`
- 运行目录：
  - `tmp/grhsim_default_xiangshan_activity_20260418`
