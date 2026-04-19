# NO0010 当前 GrhSIM Supernode 图结构相对 GSim 的差异（2026-04-19）

> 归档编号：`NO0010`。目录顺序见 [`README.md`](./README.md)。

这份记录只看 `supernode` 图结构，不讨论运行性能。目标是回答：

1. 当前这版 `grhsim` 的 final supernode DAG，相对 `gsim` 的 emitted supernode 图，结构上差在哪里。
2. 这次 `activity-schedule` 改动之后，这种差异是收敛了还是进一步放大了。

## 数据来源

- 当前 `grhsim` supernode 统计：
  - [`../../build/xs/grhsim/grhsim_emit/activity_schedule_supernode_stats.json`](../../build/xs/grhsim/grhsim_emit/activity_schedule_supernode_stats.json)
- 当前 `grhsim` 构建日志：
  - [`../../build/logs/xs/xs_wolf_grhsim_build_20260419_152314.log`](../../build/logs/xs/xs_wolf_grhsim_build_20260419_152314.log)
- `gsim` 静态结构基线：
  - [`NO0003 GSim Default XiangShan Activation Instrumentation`](./NO0003_gsim_default_xiangshan_activation_instrument_20260418.md)
  - [`NO0007 GSim / GrhSIM Supernode Edge-Step Tracking Snapshot`](./NO0007_gsim_grhsim_supernode_edge_step_tracking_20260418.md)
- 上一版 `grhsim` 结构基线：
  - [`NO0009 Activity-Schedule Topo 重构后性能与 Supernode 结构画像`](./NO0009_activity_schedule_topo_refactor_perf_and_supernode_profile_20260419.md)
  - [`../../build/logs/xs/xs_wolf_grhsim_build_20260417_210502.log`](../../build/logs/xs/xs_wolf_grhsim_build_20260417_210502.log)

## 1. 可直接对齐的结构口径

本文只使用下列可直接对齐的静态图指标：

- `gsim supernodes`
  - emitted supernode 总数
- `gsim next edges`
  - emitted supernode 粒度的直接调度边
- `gsim depNext edges`
  - emitted supernode 粒度的更宽口径依赖边
- `grhsim supernodes`
  - final activity-schedule supernode 总数
- `grhsim dag_edges`
  - final supernode DAG 去重边数
- `grhsim out-degree distribution`
  - final supernode DAG 的出度分布

不在本文中直接对齐的口径：

- `gsim emitted members`
- `grhsim ops_per_supernode`

原因是两边的“payload 单位”并不完全等价，直接拿来做每个 supernode 的负载均值对比容易误导。

## 2. 当前结构总览

| 指标 | 当前 `grhsim` | `gsim` |
| --- | ---: | ---: |
| supernodes | `77272` | `131580` |
| direct edges | `1252417` | `612269` |
| average outgoing edges / supernode | `16.2079` | `4.6532` |

如果把 `gsim next + depNext` 合并成宽口径边集：

| 指标 | 当前 `grhsim` | `gsim` |
| --- | ---: | ---: |
| wide edges | `1252417` | `1332420` |

派生关系：

- `current grhsim supernodes / gsim supernodes = 58.73%`
- `current grhsim dag_edges / gsim next = 2.0455x`
- `current grhsim avg out-degree / gsim next avg out-degree = 3.4832x`
- `current grhsim dag_edges / (gsim next + depNext) = 93.996%`

## 3. 当前差异的核心结论

结论先写清楚：

- 当前 `grhsim` 的图，相对 `gsim`，不是“更大图”，而是“更粗但更密的图”。
- `grhsim` 只保留了 `58.73%` 的 supernode 数量，却保留了 `204.55%` 的 `gsim next` 直接边数。
- 如果拿 `gsim next + depNext` 这个更宽口径边集来看，当前 `grhsim dag_edges` 已经接近它的 `94%`。
- 也就是说，`grhsim` 并没有随着节点数下降而同步把跨 supernode 连接显著压薄；相反，它更像是把大量依赖压缩进了一个节点更少、边仍然很多的 DAG。

这是一种非常典型的“coarse but dense”结构。

## 4. 这种差异具体意味着什么

### 4.1 节点更少

当前 `grhsim` final supernode 数量只有 `77272`，而 `gsim` emitted supernode 是 `131580`。

这说明：

- `grhsim` 的聚合粒度明显更粗
- 它把更多计算内容折叠进了单个 supernode
- 从“节点个数”这个维度看，`grhsim` 比 `gsim` 更激进地压缩了图

### 4.2 但边没有跟着稀释

按直观预期，如果 supernode 聚合是“结构友好”的，那么：

- 节点数下降
- 边数也应明显下降
- 平均出度至少不应明显变大

但当前观测到的是反方向：

- 节点数下降到 `58.73%`
- 直接边数却变成 `2.0455x`
- 平均出度变成 `3.4832x`

这说明 `grhsim` 的聚合不是在“吃掉边”，而更像是在“吃掉点、保留边”。

换句话说：

- `gsim` 更像是一个 finer-grained、局部连接更克制的 supernode 图
- 当前 `grhsim` 更像是一个 coarser-grained、跨节点连接更重的 supernode 图

### 4.3 `grhsim` 的边规模已经接近 `gsim` 的宽口径依赖图

如果只对齐 `gsim next`，当前 `grhsim` 会显得“边数异常多”。

但如果把 `gsim depNext` 也考虑进去：

- `gsim next + depNext = 1332420`
- `current grhsim dag_edges = 1252417`

也就是：

- 当前 `grhsim` 的 final DAG 边规模，已经接近 `gsim` 的“直接边 + 依赖边”合并宽口径

这意味着当前 `grhsim final dag` 承载的，不像是一个只保留局部直接调度关系的轻量图，而更像是把大量更宽口径的依赖关系也保留到了 final supernode DAG 里。

## 5. 当前 GrhSIM 图自己的形态

当前 `grhsim` final supernode DAG 分布如下：

| 指标 | 数值 |
| --- | ---: |
| supernodes | `77272` |
| dag_edges | `1252417` |
| out-degree min | `0` |
| out-degree mean | `16.2079` |
| out-degree median | `2` |
| out-degree p90 | `38` |
| out-degree p99 | `152` |
| out-degree max | `15837` |
| ops mean | `70.7008` |
| ops p90 | `72` |
| ops p99 | `72` |
| ops max | `4096` |

这个分布说明当前 `grhsim` 图不是均匀稠密，而是：

- 主体节点的局部扇出其实不高，`median=2`
- 但存在少量极端 hub，把 `mean` 拉到 `16.2079`
- `max=15837` 说明尾部非常重

因此更准确的形态描述应该是：

- 不是“所有 supernode 都比 `gsim` 更宽”
- 而是“主体 supernode 已经很大，同时还叠加了少量超强 hub”

## 6. 当前版本相对旧版 GrhSIM 的变化

为了看这次 `activity-schedule` 改动是否让 `grhsim` 更接近 `gsim`，把旧版 `grhsim` 也拉进来：

| 指标 | 旧版 `grhsim` | 当前 `grhsim` | `gsim` |
| --- | ---: | ---: | ---: |
| supernodes | `74906` | `77272` | `131580` |
| dag_edges / next edges | `1225442` | `1252417` | `612269` |
| average outgoing edges / supernode | `16.3597` | `16.2079` | `4.6532` |

派生关系：

- 旧版 `grhsim dag_edges / (gsim next + depNext) = 91.97%`
- 当前 `grhsim dag_edges / (gsim next + depNext) = 94.00%`

这说明：

- 当前版本并没有显著向 `gsim` 的“稀边图”方向收敛
- 它相对 `gsim` 的结构差异依然很大
- 甚至从宽口径边规模看，当前 `grhsim` 比旧版还更接近 `gsim next + depNext` 的合并边集

不过有一点变化值得单独记住：

- 当前 `grhsim` 的平均出度从 `16.3597` 轻微降到 `16.2079`
- 但 final supernode 数从 `74906` 上升到 `77272`
- 同时 oversized 节点上限从 `72` 变成 `4096`

也就是说，当前版本的变化不是简单“更稀”或“更密”，而是：

- 主体平均密度变化不大
- 但节点分布更不均匀，出现了极大 supernode 和极端 hub 的更重尾部

## 7. 对当前结构差异的解释

基于当前证据，一个相对稳妥的解释是：

1. `grhsim` 的 supernode 聚合目标与 `gsim` 不同，导致它更倾向于先做大粒度聚合，再在 DAG 上保留更多跨节点依赖。
2. 这次 `sink/tail special partition` 进一步放大了这种特征：
   - `tail` 吞掉了绝大多数 eligible ops
   - `sink` 引入了少量超大 supernode
3. 最终形成的不是“更像 `gsim` 的轻量调度图”，而是“更少节点 + 接近宽口径依赖边规模 + hub 更重”的图。

这里尤其要注意：

- 目前没有 `gsim` 的出度分布分位数，所以“当前 `grhsim` 的 heavy-tail 比 `gsim` 更强”这一点，仍然主要是基于平均边度与 `grhsim` 自身尾部统计做推断
- 但“节点更少、边更多、平均出度显著更高”这一层结论是直接观测，不依赖推断

## 8. 当前最值得记住的结构结论

如果只保留一句话，应当是：

- 当前 `grhsim` 相对 `gsim` 的主要差异，不是 supernode 数不够少，而是 final supernode DAG 仍然过于稠密；它已经压掉了大量节点，却没有等比例压掉跨 supernode 连接。

如果保留两句话，再加一句：

- 这次 `activity-schedule` 改动后，这种“少点多边”的差异没有消失，反而出现了更明显的 oversized node + hub 重尾结构。
