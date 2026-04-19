# NO0009 Activity-Schedule Topo 重构后性能与 Supernode 结构画像（2026-04-19）

> 归档编号：`NO0009`。目录顺序见 [`README.md`](./README.md)。

这份记录承接 [`NO0008 Activity-Schedule Topo 延后与 Supernode-DP 重构计划`](./NO0008_activity_schedule_topo_refactor_plan_20260419.md)，目标是回答两个问题：

1. 这次 `activity-schedule` 改动后，构建侧性能特征发生了什么变化。
2. 最终 `supernode` 的结构特征变成了什么样子。

## Commit 锚点

| 仓库 | 路径 | commit |
| --- | --- | --- |
| `wolvrix-playground` | `/workspace/gaoruihao-dev-gpu/wolvrix-playground` | `afbd3a8c7ce6272780cfbc28f141284c4f4eba76` |
| `wolvrix` | `./wolvrix` | `55273662c656bd3c18963792e65731920a4804f4` |

## 数据来源

- 当前构建日志：
  - [`../../build/logs/xs/xs_wolf_grhsim_build_20260419_152314.log`](../../build/logs/xs/xs_wolf_grhsim_build_20260419_152314.log)
- 当前 `activity-schedule` supernode 统计：
  - [`../../build/xs/grhsim/grhsim_emit/activity_schedule_supernode_stats.json`](../../build/xs/grhsim/grhsim_emit/activity_schedule_supernode_stats.json)
- 当前运行观察日志：
  - [`../../build/logs/xs/xs_wolf_grhsim_20260419_153700.log`](../../build/logs/xs/xs_wolf_grhsim_20260419_153700.log)
- 对比基线：
  - [`../../build/logs/xs/xs_wolf_grhsim_build_20260417_210502.log`](../../build/logs/xs/xs_wolf_grhsim_build_20260417_210502.log)
  - [`NO0007 GSim / GrhSIM Supernode Edge-Step Tracking Snapshot`](./NO0007_gsim_grhsim_supernode_edge_step_tracking_20260418.md)

## 1. 当前结论

先给结论：

- 这次重构已经把 `activity-schedule -> write_grhsim_cpp -> xs_wolf_grhsim_emit` 重新打通，但 `activity-schedule` 本身变慢了，主热点仍然不在 `DP`，而在 `tail/coarsen`。
- 最终 `supernode` 数从 `84314` 降到 `77272`，平均 size 从 `64.796` 提升到 `70.701`，说明 final supernode 更少、更大、更接近 `72` 的常规上限。
- 但分布不再是单一的“72 封顶”形态，而是出现了少量 `4096` 级大 supernode。结合日志中的 `max_sink_supernode_op=4096` 与 `ops_max=4096`，可推断这些大节点来自 `sink special partition`。
- `tail` 仍然是主导路径：`93.97%` 的 eligible ops 被归入 `tail partition`，`sink` 只占 `6.03%` 的 ops，但它引入了超大 supernode 和更重的边度尾部。
- 运行侧没有再出现之前那种 very-early abort；但在本次观察窗口内，`coremark` 仍未跑完，启动阶段推进偏慢。

## 2. 构建侧性能特征

### 2.1 与 `2026-04-17` 旧成功基线对比

| 指标 | `2026-04-17` | `2026-04-19` | 变化 |
| --- | ---: | ---: | ---: |
| `seed_supernodes` | `5133505` | `4538037` | `-11.60%` |
| `coarse_supernodes` | `1347140` | `1284354` | `-4.66%` |
| `dp_supernodes` | `79735` | `77272` | `-3.09%` |
| `final supernodes` | `84314` | `77272` | `-8.35%` |
| `ops_mean` | `64.796` | `70.701` | `+9.11%` |
| `coarsen_iters` | `12` | `17` | `+41.67%` |
| `coarsen` | `63363 ms` | `100566 ms` | `+58.71%` |
| `dp_prep` | `1220 ms` | `2857 ms` | `+134.18%` |
| `dp` | `254 ms` | `216 ms` | `-14.96%` |
| `materialize_segments` | `512 ms` | `1025 ms` | `+100.20%` |
| `final_materialize` | `9321 ms` | `9810 ms` | `+5.25%` |
| `total` | `90480 ms` | `135704 ms` | `+49.98%` |

这里最重要的结论不是“DP 更快了一点”，而是：

- `DP` 本体只占当前总耗时的 `0.16%`
- `dp_prep + dp + refine + materialize_segments` 合计也只有 `3.02%`
- `sink_partition + tail_partition + seed_partition + coarsen` 合计占 `83.90%`

所以，这次改动后真正拖慢 `activity-schedule` 的阶段不是 `DP`，而是 special partition 之后的 cluster 演化与 coarsen。

### 2.2 当前阶段耗时画像

| 阶段 | 时间 | 占总时间比例 |
| --- | ---: | ---: |
| `build_op_data` | `6583 ms` | `4.85%` |
| `sink_partition` | `2798 ms` | `2.06%` |
| `tail_partition` | `6971 ms` | `5.14%` |
| `seed_partition` | `3523 ms` | `2.60%` |
| `coarsen` | `100566 ms` | `74.11%` |
| `dp_prep` | `2857 ms` | `2.11%` |
| `dp` | `216 ms` | `0.16%` |
| `materialize_segments` | `1025 ms` | `0.76%` |
| `final_materialize` | `9810 ms` | `7.23%` |

这说明当前实现虽然在设计上把 “supernode topo 直接服务 DP” 这件事理顺了，但从 host 时间看，收益还没有传导成整体加速。现阶段的主要成本仍然是：

1. special partition 生成更多“带结构语义的初始 cluster”
2. 这些 cluster 进入 `coarsen` 后需要更多轮才能稳定
3. `DP` 已经退化成一个相对很小的尾端步骤

## 3. Special Partition 特征

本次日志首次明确给出了 `sink` / `tail` special partition 统计：

| 指标 | 数值 |
| --- | ---: |
| `sink_supernodes` | `81` |
| `sink_ops` | `329686` |
| `tail_supernodes` | `4537956` |
| `tail_initial_seed_ops` | `472211` |
| `tail_shared_seed_ops` | `1050410` |
| `tail_absorbed_ops` | `3610886` |
| `tail_ops` | `5133507` |
| `eligible_ops` | `5463193` |
| `residual_ops` | `0` |

派生关系：

- `tail_ops / eligible_ops = 93.97%`
- `sink_ops / eligible_ops = 6.03%`

这意味着：

- `tail` 已经吸走几乎全部 eligible ops，是当前 partition 主体
- `sink` 规模很小，但形态特殊，对最终结构分布有很强影响
- `residual_ops=0` 说明 special partition 已经把可分区 op 全部吃完，后面的 `coarsen/DP` 是在一个“全覆盖 seed 图”上继续收缩，而不是在剩余残图上补洞

## 4. Final Supernode 结构画像

### 4.1 尺寸分布

| 指标 | 数值 |
| --- | ---: |
| `supernodes` | `77272` |
| `ops min` | `1` |
| `ops mean` | `70.701` |
| `ops median` | `70` |
| `ops p90` | `72` |
| `ops p99` | `72` |
| `ops max` | `4096` |

这组数字的结构含义很明确：

- 主体分布已经高度贴近 `72` 的常规 supernode 上限
- `p90/p99` 都压在 `72`，说明绝大多数 final supernode 都接近满载
- `max=4096` 又说明存在一小批完全不属于“72 上限体系”的 oversized 节点

这里可以做一个明确推断：

- 结合构建参数 `max_sink_supernode_op=4096`
- 以及这次唯一新增的 special partition 类型就是 `sink`

可推断 `4096` 级别的 supernode 来自 `sink special partition`，而不是 `DP` 主体合并路径。

### 4.2 压缩层次

| 派生指标 | 数值 |
| --- | ---: |
| `seed_supernodes / final_supernodes` | `58.73x` |
| `coarse_supernodes / final_supernodes` | `16.62x` |

这表明本次流的压缩路径是：

- special partition 先生成了 `4538037` 个 seed 级单元
- `coarsen` 将它们压到 `1284354`
- `DP + final materialize` 再压到 `77272`

也就是说：

- 真正的大尺度压缩主要发生在 `coarsen`
- `DP` 的职责更像是 final packing，而不是主要的数量级收缩器

这和上面的耗时画像是相互吻合的。

### 4.3 DAG 边度分布

| 指标 | 数值 |
| --- | ---: |
| `dag_edges` | `1252417` |
| `out_degree min` | `0` |
| `out_degree mean` | `16.208` |
| `out_degree median` | `2` |
| `out_degree p90` | `38` |
| `out_degree p99` | `152` |
| `out_degree max` | `15837` |

这说明 final supernode DAG 呈现明显的重尾结构：

- 大多数 supernode 的扇出并不高，`median=2`
- 但少量 hub 节点把平均值抬到 `16.208`
- `p99=152`、`max=15837` 说明存在极端高扇出 supernode

结合 `ops_max=4096`，可以进一步推断：

- oversized `sink` supernode 不只是“体积大”
- 它们大概率也承担了 DAG 中最重的 fanout hub 角色

这个推断解释了为什么：

- final supernode 数量下降了
- 但 host 侧结构处理并没有同步变轻

因为“更少的节点”不等于“更均匀的节点”，当前图反而更像是“主体接近满载 + 少量超大 hub”的二相结构。

## 5. 运行侧观察

本次重跑命令：

```bash
make -j run_xs_wolf_grhsim_emu RUN_ID=20260419_153700 XS_COMMIT_TRACE=0 XS_PROGRESS_EVERY_CYCLES=1000
```

从 [`../../build/logs/xs/xs_wolf_grhsim_20260419_153700.log`](../../build/logs/xs/xs_wolf_grhsim_20260419_153700.log) 可以确认：

- 已跨过 first commit，`Difftest enabled`
- `8000 cycles` 时仍只有 `instr=3`
- 中断前已推进到 `9000 cycles / instr=238 / commit_pc=0x80001cdc / trap_pc=0x800027c6 / host_ms=55470`
- 观察窗口内仍未出现 `CoreMark Size`、`CoreMark Iterations/Sec`、`HIT GOOD TRAP`

因此运行侧当前只能得出一个谨慎结论：

- 这次修改已经把运行状态从“早期 `activity-schedule` / build 失败”推进到了“可进入程序执行”
- 但还不能宣称 `coremark` runtime 已经恢复，启动阶段仍然偏慢

## 6. 对后续优化的直接指向

这份画像给出的优先级已经比较清楚：

1. 不要再把优化重点放在 `DP` 本体上。当前 `DP` 只占 `0.16%`，不是主热点。
2. 如果要继续追求构建侧加速，首要对象应当是 `tail partition` 之后的 `coarsen` 稳定轮次与 cluster 结构。
3. `sink` special partition 需要继续盯两件事：
   - 是否真的值得保留 `4096` 级超大 node
   - 这些 node 是否正在制造极端 fanout hub
4. 后续如果继续写增量文档，建议固定追踪下面这组指标：
   - `sink_supernodes / sink_ops`
   - `tail_supernodes / tail_ops`
   - `coarsen_iters`
   - `coarsen ms / total ms`
   - `final supernodes`
   - `ops_mean / ops_p99 / ops_max`
   - `out_degree median / p99 / max`

## 7. 一句话总结

这次 `activity-schedule` 重构后的主要结果，不是“DP 更快了”，而是“final supernode 更少、更满、更不均匀了”；当前真正的性能瓶颈已经前移到 `tail + coarsen`，而 `sink` 引入的少量超大 hub supernode 是最值得继续盯的结构信号。
