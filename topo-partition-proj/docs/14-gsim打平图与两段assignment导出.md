# 14 GSim 打平图结构与 Coarsen/DP Block Assignment 导出（2026-07-31）


本文记录把（打平后的）gsim 节点图与 gsim 自己的 coarsen / DP 两段划分结果
按 topo-partition-proj 的 JSONL 格式导出的实现与验证。导出目的：让
`topo-partition-proj` 的 harness（scorer / sampler / searcher）可以直接
消费 gsim 的图与 gsim 的划分解，与 grhsim AM 的图/解在同一口径下对比。
打平实验背景见 [`12-gsim-node打平实验设计与实现`](12-gsim-node打平实验设计与实现.md)
与 [`13-gsim-node打平coremark50k对比`](13-gsim-node打平coremark50k对比.md)。

## 1. 实现

- 代码：`reference/gsim/src/topoProjExport.cpp`（新增），开关
  `--export-topo-proj=<dir>`；三个调用点在 `graphPartition()`
  内（`src/graphPartition.cpp`）：
  - 入口（`orderAllNodes()` 后、coarsen 前）：写 `instruction_graph.jsonl`；
  - `graphCoarsen()` + `resort()` 后：写 `block_assignment_coarsen.jsonl`；
  - `graphInitPartition()` + `orderAllNodes()` 后：写 `block_assignment_dp.jsonl`。
- 与 `--flatten-nodes` 正交：不加打平开关时导出的就是原始 gsim 图。
- assignment header 内附带按 topo-proj 口径在生产侧算好的三项指标
  （`dag_edges / compute_compute_value_pairs / incoming_copy_cost`），
  供 `exp/tools/reconcile_baseline.py` 对账。

## 2. 映射（gsim → topo-proj）

- **instruction** := sortedSuper 中的 VALID_NODE 成员（即 graphPartition
  看到的全部节点）；id 按 sortedSuper 拓扑序密集分配。
- **op** := 打平后唯一计算 enode（或树根）的 opType；合成 op：
  `60 REF`（纯连接）、`61 CONST_INT`、`62 INPUT`、`63 REG_UPDATE`、
  `64 NONE`；`atom = id`、`comb_loop_atom = 0`（全图无组合环）。
- **def_use 边** := 普通 ref enode 引用（`var = src`）。
- **external_read** := 读接口输入（NODE_INP）、读寄存器状态
  （NODE_REG_SRC）、读存储内容（`OP_READ_MEM`；memory 不是节点，
  追加合成变量 id）。reg_src 作为孤立节点导出（无边），
  `reg_dst → reg_src` 更新边**不导出**（跨拍边界，非值边）——
  第一版把它导成 order 边，harness Kahn 立刻报环
  （reg_src→组合逻辑→reg_dst→reg_src），改为 AM 同口径的
  "state 读 = external_read、state 写 = sink"后 DAG 成立。
- **order 边** := reg reset 相关 dep 边（reg_src → 异步复位条件、
  条件 → reg_dst）与 memory reader → writer 顺序边。
- **state_write** := `NODE_REG_DST / NODE_WRITER / NODE_READWRITER`。
- **block** := 各阶段的 SuperNode（dense id 按 sortedSuper 序），
  `kind` 恒为 `compute`（gsim 无 compute/commit 二分），
  `super_type` 原样记录。

## 3. 验证（rocket，`TestHarness-rocket.fir`，`--flatten-nodes`）

- 图：52,255 节点 / 84,864 def_use / 15,941 external_read / 103,063 order；
  harness `load_graph` 计算 Kahn 拓扑：**0 违序边（DAG 成立）**。
- 两段 assignment 对账（生产侧 vs 图侧独立复算）：
  - coarsen：`dag_edges 14,629 / pairs 25,675 / cost 26,954`，三项全等；
  - dp：`dag_edges 8,807 / pairs 20,529 / cost 21,694`，三项全等。

## 4. 全香山导出（打平版，`--supernode-max-size=16`）

数据集：`topo-partition-proj/exp/dataset/xs_gsim_flatten_20260731/`
（本地产物，不入库）。同次运行再次通过打平 post-check（0 违规）。

- `instruction_graph.jsonl`（1.74 GB）：3,043,902 节点（另有 2,274 个
  memory 合成变量）/ 4,340,605 def_use / 918,456 external_read /
  5,719,920 order（order 主要来自异步复位 dep 扇出）。
- `block_assignment_coarsen.jsonl`（174 MB）：286,748 blocks；
  `dag_edges 641,213 / pairs 1,460,695 / cost 1,472,037`。
- `block_assignment_dp.jsonl`（157 MB）：84,901 blocks；
  `dag_edges 436,787 / pairs 1,295,427 / cost 1,306,149`。

注意口径差异：topo-proj 的 `dag_edges` 只数 def_use 跨 block 边，
不包含 order/dep，因此 DP 的 436,787 与 gsim 自身 stats JSON 的
`dag_edges = 650,272`（含全部 super->next 边）不可直接比较。

## 5. 对账与 DAG 验证结果

全香山 reconcile（`exp/tools/reconcile_baseline.py`）：

```text
coarsen: dag_edges 641213 / pairs 1460695 / cost 1472037 — 三项全等 (OK)
dp:      dag_edges 436787 / pairs 1295427 / cost 1306149 — 三项全等 (OK)
```

harness `load_graph`（Kahn 5.7s）：3,043,902 指令全部可排，**违序边 0**
（DAG 成立）；`state_write` 节点 151,190。`graph_cache.npz` 为 harness
生成的派生缓存，与 JSONL 同目录存放、可随时重建。

## 6. 复现命令

```bash
reference/gsim/build/gsim/gsim \
  --flatten-nodes --supernode-max-size=16 \
  --cpp-max-size-KB=8192 --sep-mod=__DOT__ --sep-aggr=__DOT__ \
  --export-topo-proj=topo-partition-proj/exp/dataset/xs_gsim_flatten_20260731 \
  --stop-after-stage=graphPartition --dir /tmp/gsim_flat_topoproj_dump \
  build/xs/rtl/rtl/SimTop.fir
```
