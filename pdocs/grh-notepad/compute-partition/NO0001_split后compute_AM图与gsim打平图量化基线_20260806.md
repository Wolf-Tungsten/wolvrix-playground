# NO0001 split 后 compute AM 图与 gsim 打平图量化基线

日期：2026-08-06
状态：基线已固化（工具 + 数据 + 指标可重跑）

## 1. 切入点

split-am-graph 阶段（NO0002/NO0004）把 AM 图原生拆成 compute/commit 两张子图。
**compute AM 图在语义上与 gsim 打平图（--flatten-nodes）同构**：都是纯组合指令 +
状态/接口边界读的打平数据流图。本专题以此为切入点研究
partition-am-compute-graph 的分区算法，对齐目标沿用 supernode-align 的裁定口径：
**同等超节点数下跨超节点 value 数（compute_network 口径）**。

本记录做三件事：split 阶段原生导出落地、两图量化基线、差异归因初判。

## 2. 工程产物

- **split 图原生导出**（`grhsim_am_graph_split.cpp`，env 触发）：
  `WOLVRIX_GRHSIM_AM_SPLIT_GRAPH_JSONL=<prefix>` 产出 `<prefix>.compute.jsonl` /
  `<prefix>.commit.jsonl`（格式 `wolvrix.am-split-graph.v1`；node.id=全局指令 id，
  含 atom/min_instruction/state_write，commit 侧含 event_rank；边含诱导 def_use、
  边界 external_read（commit 侧带 src_side="compute"）、order）。
  成员资格/诱导边/atom 注解全部取自 split 上下文，与分区 pass 所见一致——**不做
  全图导出的离线过滤**。三向对账精确闭合：全图 du 5,499,248 = compute 内
  5,147,372 + compute→commit 边界 351,876；er 1,531,730 = 1,524,880 + 6,850；
  order 19,046 = 13,762 + 5,284。
- **分析脚本** `scripts/compute_partition_metrics.py`（参数化路径，可重跑）；
  数据 `build/xs/am-split-export/{split.compute,split.commit}.jsonl` + `metrics.json`。
- 对照数据集：gsim 打平 `topo-partition-proj/exp/dataset/xs_gsim_flat_prod_20260804`
  （88,375 块 dp 划分）；AM 生产划分 `build/xs/am-graph-export/block_assignment.jsonl`
  （28,344 compute 块）。

## 3. 图级规模（A）

| 指标 | AM compute（split） | gsim 打平 | gsim 剔 state_write |
|---|---:|---:|---:|
| nodes | **3,062,283** | 3,043,902 | 2,892,712 |
| def_use_edges | 5,147,372 | 4,340,605 | 4,033,923 |
| external_reads | 1,524,880 | 918,456 | 850,698 |
| order_edges | 13,762 | 5,719,920 | 5,150,276 |
| Σ node width | 60,693,790 | 32,094,103 | 29,022,651 |
| Σ def_use edge width | 197,914,802 | 40,323,349 | 37,054,608 |

- **节点数基本相当**（+0.6% / 剔写后 +5.9%）——"语义同构"量化成立。
- AM def_use 边多 28%（1.19x vs 原始 / 1.28x vs 剔写）；AM 无 order 边负担
  （gsim 打平图带 5.7M order 边，AM 仅 13.8k——AM lowering 的 effect 序更省）。
- **宽度差异巨大**：Σ node width 1.89x、Σ du width 4.9x（AM 有 79,263 位宽大
  concat）。这预示 copy-cost 类指标比值会远高于 value 计数类比值（下文 4.12x vs
  1.59x 印证）。

## 4. 生产者出度分布（B，def_use 按 (src,dst) 去重；gsim 剔写）

| 出度桶 | AM compute | gsim |
|---|---:|---:|
| 0 | 190,927 | 324,686 |
| 1 | 2,271,409 | 2,315,194 |
| 2 | 377,193 | 127,189 |
| 3 | 73,005 | 30,916 |
| 4-7 | 85,175 | 44,142 |
| 8-15 | 40,431 | 32,763 |
| 16-63 | 21,337 | 15,920 |
| ≥64 | 2,806 | 1,902 |
| **≥2 合计** | **599,947** | **252,832** |

出度≥2 规模 **2.37x**（max 出度 AM 20,726 / gsim 6,167）——与 supernode-align
NO0012 的 fanout≥2 结构差归因一致，是目前最主要的图级结构差距。

## 5. 生产划分主指标（C，NO0012 口径）

| 指标 | AM（28,344 块） | gsim dp（88,375 块） | 比值 |
|---|---:|---:|---:|
| cross_values（compute_network） | **527,025** | **178,151** | **2.9583x** |
| value-block 对 | 1,913,302 | 1,204,898 | 1.5879x |
| incoming_copy_cost | 5,008,284 | 1,214,610 | 4.1234x |
| dag_edges（块级去重） | 240,745 | 412,492 | 0.5836x |

对账：AM 的 pairs/cost 与 assignment header（全设计口径）**精确相等**（header 评分
本就剔除 commit 消费者）；gsim 复算 178,151 与 NO0012 基线精确一致。AM 侧
dag_edges 与 header 差 15,595 = header 含的 compute→commit 块对。

## 6. 同等超节点数对比（D，核心发现）

同一离线分区器（amcoarsen rotate + 贪心装箱）双向重分区：

| 方向 | 参数 | 落点块数 | cross_values | 对比 |
|---|---|---:|---:|---|
| AM→gsim 块数 | cap=46 | 88,118（−0.29%） | 1,134,926 | 是 gsim 生产 178,151 的 **6.37x** |
| gsim→AM 块数 | cap=132 | 28,638（+1.0%） | 753,314 | AM 生产 527,025 仅为其 **0.70x** |

**结论：生产口径 2.96x 差距的主因是粒度与划分器行为，不是图结构不可达。**

- AM 划分器擅长的粗粒度区间（28k 块）里，**AM 图结构与 gsim 相当甚至更好**
  （同分区器同块数 0.70x）；
- 把 AM 图压到 gsim 的细粒度（88k 块，块均 ~35 指令）时，DP 容量截断把
  cross_values 抬到 1.13M——截断行为本身是大问题（细粒度下分区器失效，不是
  图变差了）；
- gsim 生产划分器在 88k 块拿到 178k，说明**细粒度可达**——缺的是 AM 侧在细
  粒度下不失效的分区算法，而非图不够好。

解读注意（口径）：D 的双向重分区用的是 AM 离线分区器，gsim 生产 dp 划分是另一套
算法；gsim 重分区时 state_write 节点作为普通成员占容量（与其生产超节点一致）。

## 7. commit 图快报（E，context 指标）

写指令 147,365；不同事件签名（event_rank）**449** 个；compute→commit 边界
external_read 351,876 条、唯一 value 147,353（copy 折算 391,979）；order 边 5,284。
compute→commit 值流与 supernode-align NO0012 的 commit 消费跨块 context 指标
（185,548，20260804 opt1 数据集）同量级。

## 8. 归因初判与下一步

差距分解（生产口径 2.96x）：

1. **粒度与划分器**（主因）：gsim 88,375 块（块均 ~34 指令）vs AM 28,344 块
   （块均 ~108 指令）。同块数对比显示 AM 图结构不差；瓶颈是 AM 分区器在细粒度
   的容量截断失效。
2. **出度≥2 结构差**（次因，2.37x）：集中在 and/mem.read/logic_and/eq/mux
   （NO0012 已定位），是图形级 pass 的目标（与 supernode-align 线共享库存）。
3. **宽度差**（Σ du width 4.9x）：影响 copy cost（4.12x），与位宽建模/大 concat
   处理相关，跨块拷贝成本口径下需单独评估。

下一步（候选，按预期杠杆排序）：

- 细粒度分区算法：修 DP 容量截断（ oversize 处理、segment 内二分、惩罚函数），
  目标在 ~88k 块量级不失效，直接对标 gsim 生产 178k；
- 粒度-指标扫描：AM 生产划分在不同 maxInstructionsPerBlock 下的 cross_values 曲线
  （分区器不修的可达边界）；
- 出度≥2 图形级 pass（mem.read 标量化、守卫形态重构，与 supernode-align 协调）。

## 9. 复现

```bash
# 导出 split 图（生产调度参数与 canonical 一致）
WOLVRIX_GRHSIM_AM_SPLIT_GRAPH_JSONL=$PWD/build/xs/am-split-export/split \
  build/wolvrix/bin/grhsim-am-lower-json build/xs/grhsim-am/wolvrix_xs_post_stats.json \
  SimTop --schedule --max-instructions-per-block 128 --dp-segment-penalty 1
# 指标
.venv/bin/python scripts/compute_partition_metrics.py \
  --am-graph build/xs/am-split-export/split.compute.jsonl \
  --am-assign build/xs/am-graph-export/block_assignment.jsonl \
  --gsim-graph topo-partition-proj/exp/dataset/xs_gsim_flat_prod_20260804/instruction_graph.jsonl \
  --gsim-assign topo-partition-proj/exp/dataset/xs_gsim_flat_prod_20260804/block_assignment_dp.jsonl \
  --json build/xs/am-split-export/metrics.json
```
