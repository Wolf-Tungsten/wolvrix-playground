# 17 GSim 屏蔽 Coarsen 的 XiangShan CoreMark 50k 对比（2026-07-31）

本文记录一个消融实验：在 gsim 中屏蔽 `graphCoarsen()`（保留功能必需的
`mergeResetAll`），让 DP 划分直接作用在未 coarsen 的图上，对比
XiangShan coremark 50k 仿真速度与图结构。打平实验背景见
[`12`](12-gsim-node打平实验设计与实现.md) / [`13`](13-gsim-node打平coremark50k对比.md)。

## 方法

- 新开关 `--no-coarsen`（`reference/gsim/src/graphPartition.cpp`）：
  跳过 `mergeWhenNodes / mergeOut1 / mergeIn1 / mergeSublings`，
  保留 `mergeResetAll`（reset 超节点是发射端 reset 代码的前提）。
  其余流程（DP 划分、replication、发射）不动。
- 参数与基线完全一致：`--supernode-max-size=15`，同一份 SimTop.fir。
  超节点数不做对齐——测的就是 coarsen 本身的效果。
- 对照：`build/xs/gsim`（基线，coarsen 开启）vs
  `build/xs/gsim-nocoarsen`（本实验）。

## 图结构对比（`SimTop_supernode_stats.json`）

| 指标 | 基线（有 coarsen） | 无 coarsen | 倍数 |
| --- | ---: | ---: | ---: |
| 发射超节点 | 84,642 | 217,690 | 2.57x |
| 定义节点数 | 488,844 | 1,386,132 | 2.84x |
| dag_edges（super->next） | 645,853 | 1,253,603 | 1.94x |
| activation_edges | 1,379,972 | 2,245,036 | 1.63x |
| unique_activation_edges | 719,101 | 1,347,610 | 1.87x |
| active_source_nodes | 442,722 | 1,358,024 | 3.07x |
| emu 二进制大小 | 55.7 MB | 84.8 MB | 1.52x |

无 coarsen 时 DP 把 2,708,065 个单节点超节点划成 218,801 段
（平均 ~12.4 节点/段，贴近 max-size=15 上限）；coarsen 版则先把图
合并到 293,985 再划成 84,786（平均 ~32 节点/段，含 coarsen 链）。

## CoreMark 50k 性能对比

相邻三连跑（nocoarsen → base → nocoarsen），日志
`build/logs/xs/nocoarsen_{50k_1,base_50k_2,50k_3}_20260731.log`：

| 次序 | 版本 | Host time | instrCnt / cycleCnt |
| --- | --- | ---: | --- |
| 1 | 无 coarsen | 56,123 ms | 73,584 / 49,998 |
| 2 | 基线 | 22,605 ms | 73,584 / 49,998 |
| 3 | 无 coarsen | 56,402 ms | 73,584 / 49,998 |

- 功能门：三次运行指令/周期数完全一致，difftest 通过。
- **无 coarsen 慢 `2.49x`**（56,263 ms vs 22,605 ms）。

rocket 前瞻（未对齐超节点）：4,076 vs 2,343 超节点（1.74x），
慢 36%（507k vs 690k cycles/s），输出逐字节一致。

## 结论

1. **coarsen 是 gsim activity 划分性能的主要来源**：去掉它，超节点
   变多 2.57 倍、块间边变多 1.94 倍、激活源节点变多 3.07 倍，仿真
   慢 2.49 倍。合并出的"大超节点"（coarsen 链）既减少了激活单元
   数量，也把拓扑相邻的逻辑保持在一起降低跨块激活。
2. 与打平实验（[`13`](13-gsim-node打平coremark50k对比.md)，node 粒度
   打平后仅慢 3.6%）对照，因果链闭合：**node 层次（表达式树容器）
   不重要，coarsen 的合并策略才是 gsim 划分优势的核心**。
3. 注意混淆项：无 coarsen 版同时少了 when2mux（在 mergeWhenNodes
   内），when 保留为 if/else 语句；这部分代码形态差异也包含在
   2.49x 中，但从结构指标（边数、激活源数 3 倍）看，主导因素仍是
   划分粒度而非 when 形态。
