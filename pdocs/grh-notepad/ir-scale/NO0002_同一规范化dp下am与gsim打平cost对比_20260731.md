# 16 同一规范化 DP 下 GrhSIM AM 图与 GSim 打平图 incoming_copy_cost 对比（2026-07-31）


继 [`15-am与gsim打平dag规模对比`](15-am与gsim打平dag规模对比.md)
的图规模对比之后，本文回答：两张图都用**同一规范化 DP 方法、同一参数**
处理，最终 `incoming_copy_cost` 差多少。

## 方法

工具：`topo-partition-proj/exp/tools/run_fullgraph_plaindp.py`
（规范化基线：canonical Kahn 序（仅非 state_write 指令）+ 段 DP），
参数两边完全一致：`SEGMENT_CAPACITY = 128`、`--penalty 0`（默认）。
state_write 指令不参与段 DP，保持其生产块并记为 commit 块（块内读免费），
评分器 `score_assignment` 两边共用。

输入：

- grhsim AM 图：`exp/dataset/xs_full_20260730/`（基线文件
  `plaindp_nocoarsen_baseline.json`，此前已算好）。
- gsim 打平图：`exp/dataset/xs_gsim_flatten_20260731/`（本次新算，
  同名输出文件），导出见
  [`14-gsim打平图与两段assignment导出`](14-gsim打平图与两段assignment导出.md)。

## 结果

| 指标 | grhsim AM 图 | gsim 打平图 | AM / gsim |
| --- | ---: | ---: | ---: |
| compute 指令（参与段 DP） | ~4.45M | 2,892,712 | 1.54x |
| **incoming_copy_cost** | **5,921,453** | **1,300,813** | **4.55x** |
| compute_compute_value_pairs | 2,903,510 | 1,284,791 | 2.26x |
| dag_edges | 312,938 | 261,362 | 1.20x |
| segments / compute blocks | 41,140 | 26,601 | 1.55x |
| commit blocks | 497 | 40,253 | — |

对照各自生产划分（同一评分器口径）：

| 图 | 生产划分 cost | 规范化 DP cost | 规范化 DP 提升 |
| --- | ---: | ---: | ---: |
| grhsim AM | 6,468,546（plain 基线） | 5,921,453 | -8.5% |
| gsim 打平 | 1,306,149（coarsen+DP） | 1,300,813 | -0.4% |

## 结论

1. **同一规范化 DP 下，gsim 打平图的 incoming_copy_cost 仍只有 AM 图的
   1/4.55。** 差距的主要来源不是划分算法（两边算法与参数完全一致），
   而是**图本身的性质**：gsim 图节点少 35%、def_use 边少 46%、
   external_read 少 59%、位宽总量少 44%，且同样的 DP 在其上能找到
   便宜得多的划分（局部性/共享显著更好）。
2. gsim 自己的 coarsen+DP 与其规范化 DP 仅差 0.4%
   （1,306,149 vs 1,300,813）：gsim 生产划分在 cost 指标上已贴近
   规范化 DP；其相对弱项是 dag_edges（436,787 vs 261,362，高 67%）。
3. AM 生产 plain 基线距其规范化 DP 尚有 8.5% 空间（6,468,546 →
   5,921,453），与 topo-proj docs/08 的既有结论一致。
4. 备注：gsim 侧 commit blocks 为 40,253（state_write 节点的生产块
   直接转为 commit 块），AM 侧为 497；两侧"commit 块内读免费"的
   评分语义一致，不影响 cost 对比。
