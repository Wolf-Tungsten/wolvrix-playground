# dataset — topo-partition-proj 实验数据

Phase 0 起，一切实验（采样/打分/搜索/训练）的唯一图输入来自这里。格式说明见
`docs/05-图导出实现记录.md` 与 `wolvrix/docs/grhsim/grhsim-am-pipeline.md` §3.2.4。

## 目录

| 路径 | 内容 | 大小 |
|---|---|---|
| `xs_full_20260730/instruction_graph.jsonl` | 全香山 AM 指令图导出（格式 `wolvrix.am-instruction-graph.v1`） | 1.44 GB，14,954,654 行 |
| `xs_full_20260730/block_assignment.jsonl` | 生产调度 plain 基线解（格式 `wolvrix.am-block-assignment.v1`，header 含对账指标） | 233 MB，4,703,732 行 |
| `xs_full_20260730/lower_json.log` | 导出当次 lower-json 运行日志（统计与耗时，溯源用） | 2.4 KB |
| `xs_full_20260730/graph_cache.npz` | harness 图缓存（numpy 数组 + 规范拓扑序，由 `harness.graph.load_graph` 自动生成/复用） | 派生产物 |
| `xs_full_20260730/gnn_cpu_bench.json` | Phase 0 任务 5 CPU 摸底实测（gather/SpMM/matmul 耗时） | 派生产物 |
| `xs_full_20260730/cpsat_gap.json` | Phase 1 任务 3 CP-SAT 精确最优 vs 搜索 gap 实测（12 个小区域） | 派生产物 |
| `regions_xs_full_20260730/` | 第一版训练数据集：512 个采样区域（`region_XXXX.npz`）+ `manifest.json` + `coverage.json`，生成方式与覆盖检查见 docs/07 | 206 MB |
| `labels_xs_full_20260730/` | Phase 1 标签：512 区域的最优排列 + 锚点/搜索分数（`label_XXXX.npz`）+ `manifest.json`（M1 汇总），见 docs/08 | 派生产物 |
| `examples/tiny_graph.jsonl` | 7 指令手工小程序的导出样例（导出器单测产物），供读图代码做格式冒烟 | 17 行 |
| `xs_full_20260731_l1/` | T2-E1 数据集：L1（GRH 层 reg-to-mem 后 simplify）后的 AM 指令图 + 生产划分 + plaindp 复算 + 导出日志 | 见 doc 20 §4 |
| `xs_full_20260731_l2/` | T2-E2 数据集：L2 单干（AM 层 DCE/fold/CSE，未经 L1 的脏图输入） | 见 doc 20 §4 |
| `xs_full_20260731_l1l2/` | T2-E3 数据集：L1+L2 两级 | 见 doc 20 §4 |
| `xs_gsim_prod_20260803/` | supernode-align 专题：gsim 生产口径（不 flatten，supernode-max-size=15）topo-proj 导出，含 instruction_graph + coarsen/dp 两段 assignment（`--stop-after-stage=graphPartition`） | 1.9 GB，见 pdocs/grh-notepad/supernode-align/NO0002 |
| `xs_am_prod_20260803/` | supernode-align 专题：AM 生产口径（grhsim-am-rename post-stats，b1 调度参数）指令图 + block assignment | 1.3 GB，同上 |
| `supernode_align_baseline_20260803.json` | 上述两侧的 supernode-align 基线指标（`scripts/supernode_align_metrics.py` 输出） | 见 NO0002 §3 |
| `xs_gsim_flat_prod_20260804/` | supernode-align **新基线**（NO0010）：gsim 打平图生产口径（--flatten-nodes，supernode-max-size=15）topo-proj 导出 | 见 pdocs/grh-notepad/supernode-align/NO0010 |
| `xs_am_flat_final_20260804/` | 同上：AM 侧（ir-scale 收官提交 5335696 重建，rotation coarsen）指令图 + assignment | 同上 |
| `xs_am_flat_final_seq_20260804/` | 同上：AM 侧（5335696 + 相位式 coarsen）指令图 + assignment | 同上 |
| `xs_am_opt1_seq_20260804/` | 同上：AM 侧（HEAD ba0a69a + 相位式 + 新 optimize：CSE 解锁 Observable / assign 别名 / ROM 折叠）指令图 + assignment，cross_values 704,356（3.65x） | 见 pdocs/grh-notepad/supernode-align/NO0011 |
| `xs_am_no0007p3_20260808/` | supernode-align **atom 口径基线**（NO0013）：AM 侧（NO0007 P3：atom 计权分区，指令图/归属均带 post-merge atom 字段）指令图 + assignment，compute_network 515,057（2.8911x），nodes 2,620,125 atoms（0.8608x） | 见 pdocs/grh-notepad/supernode-align/NO0013 |

基线锚点（详见 `docs/06-基线解导出与对账.md`）：plain 基线 34,236 blocks
（33,738 compute + 497 commit + 1 input sink），`dag_edges=325,838`，
`compute_compute_value_pairs=3,305,393`，cost（`incoming_copy_cost`）= **6,468,546**。
三项指标已经 `exp/tools/reconcile_baseline.py` 独立复算对账一致；对任意新划分
用 harness scorer（`exp/harness/scorer.py`，向量化、全图约 4s）重算，基线对账入口：

```bash
python3 exp/tools/score_baseline.py \
    exp/dataset/xs_full_20260730/instruction_graph.jsonl \
    exp/dataset/xs_full_20260730/block_assignment.jsonl
```

区域数据集重生成（harness 采样器，参数见 `exp/harness/sampler.py` 的 `SamplerConfig`）：

```bash
python3 exp/tools/sample_dataset.py \
    exp/dataset/xs_full_20260730/instruction_graph.jsonl \
    exp/dataset/regions_xs_full_20260730 --count 512
```

## `xs_full_20260730` 溯源

- 输入：`build/xs/grhsim-am-detgroup/wolvrix_xs_post_stats.json`（top = SimTop）。
- 计数：4,669,495 节点 / 4,803,814 变量 / 8,031,598 def_use 边 / 2,234,514
  external_read / 19,046 order 边；`comb_loop_atoms = 0`。
- 校验：行数与 header 计数一致；抽样 JSON 解析合法；def_use + order 边 Kahn 全排
  成拓扑序（图为 DAG）。
- 重新生成（wolvrix 含导出器，环境变量触发）：

```bash
WOLVRIX_GRHSIM_AM_INSTRUCTION_GRAPH_JSONL=$PWD/instruction_graph.jsonl \
    wolvrix/build/bin/grhsim-am-lower-json \
    build/xs/grhsim-am-detgroup/wolvrix_xs_post_stats.json SimTop --schedule
```

## 版本管理

香山 RTL 或 wolvrix lowering/调度语义改版后，旧导出即过期（风险登记 R6）：重跑上面的
命令，另建 `xs_full_<date>/` 目录存放，不覆盖旧目录；harness 消费时在配置里写死所用
数据目录名。
