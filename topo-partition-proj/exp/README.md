# exp — topo-partition-proj 实验台（harness）

Phase 0 起在本目录重建"导出 → 采样 → 评分 → 搜索"闭环（docs/04，验收记录见 docs/07）。
代码在仓库根 `.venv` 里跑（`numpy` + `pytest`；先 `source ../../.venv/bin/activate`）。

## 模块（`harness/` 包）

| 模块 | 内容 |
|---|---|
| `harness/graph.py` | 指令图 JSONL → numpy 数组（含 `graph_cache.npz` 缓存）；comb-loop 收缩后的确定性 Kahn 规范拓扑序 |
| `harness/scorer.py` | 任意 block assignment 打分：`cost`（位宽折算拷贝数，优化目标）+ `dag_edges` / `compute_compute_value_pairs` / `footprint`（体检指标）；全图约 4 s |
| `harness/sampler.py` | 区域采样：topo 窗口 + BFS 各半、非对称 1 跳 halo、连续 10% topo 禁区（留出）、稀有结构配额、超稀有 opcode 保底 |
| `harness/searcher.py` | 段 DP（生产口径移植 + 新 cost 公式，容量 128）+ 模拟退火（合法范围内 relocate + swap、温度按移动代价分布标定） |
| `harness/kernel.c` / `harness/kernel.py` | 段 DP 的 C 内核（ctypes 桥接，约 40µs/次 @n=5k，比 Python 快 ~1000×；无编译器时回退 Python DP） |
| `harness/cpsat_oracle.py` | 小区域（≤200 节点）精确最优：CP-SAT  monotone-seg 建模，量搜索离最优的 gap |
| `harness/gnn_bench.py` | CPU gather/SpMM/matmul 实测，校准编译期 GNN 推理预算（K7） |

## 命令行入口（`tools/`）

```bash
# 基线对账（harness scorer vs 生产 header 指标）
python3 tools/score_baseline.py dataset/xs_full_20260730/instruction_graph.jsonl \
    dataset/xs_full_20260730/block_assignment.jsonl
# 生成 512 个训练区域 + 覆盖报告
python3 tools/sample_dataset.py dataset/xs_full_20260730/instruction_graph.jsonl \
    dataset/regions_xs_full_20260730 --count 512
# Phase 1 标签流水线：512 区域锚点 + SA 搜索 + 标签落盘（多进程）
python3 tools/run_label_pipeline.py dataset/regions_xs_full_20260730 \
    dataset/xs_full_20260730/block_assignment.jsonl dataset/labels_xs_full_20260730 \
    --iterations 100000 --workers 32
# Phase 1 CP-SAT gap 测量（小区域精确最优 vs 搜索）
python3 tools/run_cpsat_gap.py dataset/xs_full_20260730/instruction_graph.jsonl \
    dataset/xs_full_20260730/block_assignment.jsonl \
    dataset/xs_full_20260730/cpsat_gap.json --count 12
# 搜索器冒烟（采样 → 锚点 → 搜索闭环）
python3 tools/run_search_smoke.py dataset/regions_xs_full_20260730 \
    dataset/xs_full_20260730/block_assignment.jsonl --regions 3 --iterations 10000
# CPU 推理摸底
python3 tools/run_gnn_bench.py dataset/xs_full_20260730/instruction_graph.jsonl
# 旧版逐行对账脚本（docs/06 的首次对账证据，保留）
python3 tools/reconcile_baseline.py dataset/xs_full_20260730/instruction_graph.jsonl \
    dataset/xs_full_20260730/block_assignment.jsonl
```

## 测试

```bash
python3 -m pytest tests/ -q
```

## 数据

见 `dataset/README.md`。大规模导出、图缓存、区域数据集均本地保留、不入库
（`dataset/.gitignore`）。
