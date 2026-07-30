# 07 harness 重建落地与 M0 验收（Phase 0 任务 2 后半–5）

2026-07-30。继 05（指令图导出）、06（基线解导出与首次对账）之后，Phase 0 剩余任务
全部落地在 `topo-partition-proj/exp/`：harness 四个模块 + 第一版训练数据集（512 区域）
+ 对账/覆盖/摸底证据。本文是 as-built 记录与 M0 验收门核对。wolvrix 侧本轮零改动。

## 1. 模块与产出物总览

| 产出物 | 位置 | 说明 |
|---|---|---|
| 图加载 | `exp/harness/graph.py` | JSONL → numpy（`graph_cache.npz` 缓存：解析 16.4s + Kahn 6.2s，之后秒级加载）；comb-loop 收缩后的确定性 Kahn **规范拓扑序**（指令 id 序实测非拓扑：def_use 逆序边 638,805 条、order 4 条，采样/搜索不能直接用） |
| Scorer | `exp/harness/scorer.py` | 任意 assignment → `cost` + 三项体检指标，向量化全图 4.2s；CLI `exp/tools/score_baseline.py` |
| 采样器 | `exp/harness/sampler.py` | topo 窗口 + BFS、halo、留出禁区、稀有配额；CLI `exp/tools/sample_dataset.py` |
| 搜索器骨架 | `exp/harness/searcher.py` | 段 DP（生产移植 + 新公式）+ 模拟退火；CLI `exp/tools/run_search_smoke.py` |
| CPU 摸底 | `exp/harness/gnn_bench.py` | gather/SpMM/matmul 实测；CLI `exp/tools/run_gnn_bench.py` |
| 训练数据集 v1 | `exp/dataset/regions_xs_full_20260730/` | 512 区域 npz + manifest + coverage，206 MB |
| 单元测试 | `exp/tests/` | 18 个用例全绿（scorer 位宽折算、采样器、DP 对拍暴力、SA 合法性） |

## 2. 任务 2 后半：harness scorer 与对账（M0 核心证据）

口径与 06 文档及 `reconcile_baseline.py` 完全一致（scorer.py docstring 逐条写明）。
`exp/tools/score_baseline.py` 全香山复跑：

```
incoming_copy_cost             harness=6468546      production=6468546
dag_edges                      harness=325838       production=325838
compute_compute_value_pairs    harness=3305393      production=3305393
footprint(blocks)              harness=34236        production=34236
compute_blocks                 harness=33738        production=33738
commit_blocks                  harness=497          production=497
[score] OK: harness scorer matches the production scoreboard
```

三项图侧指标由 scorer 从指令图独立复算；块计数由 assignment 记录侧核对（input sink
记为 size 0 的 compute 块，header 的 compute_blocks 不含它，scorer 按此口径修正）。
位宽折算（ceil(w/64) 下限 1、同块同值去重、external_read 永久边界、commit 块内读免费、
04 文档 cost=4 例子）由 `exp/tests/test_scorer.py` 6 个用例保证。

## 3. 任务 3：采样器与覆盖检查

### as-built 与 D4 的偏差（实测驱动，详见 sampler.py docstring）

1. **halo 改为非对称 1 跳**。D4 默认"往外 2 跳"在全香山重尾 hub（最大出度 ~16k）下
   不可行：实测无上限 1 跳 halo 中位 7,763 / p90 246,872 / 最大 267,954 节点，
   2 跳中位 235,974 / 最大 628,732——512 个区域的文件量将超过图本身。as-built：
   **前驱方向（producer + order 前驱）完整保留**（它们就是区域成本的永久边界，
   一条不能少），**后继方向每内部节点封顶 512**（`halo_fanout_cap`，纯特征上下文；
   137/512 个区域触顶）。边界成本信息零损失，halo 实测中位降到 2,889 / 最大 51,961。
2. **超稀有 opcode 保底覆盖**。首版随机采样 38/39 类——`changed.neg` 全图仅 1 个节点。
   新增 `cover_threshold=2048`：全图节点数低于阈值的 7 个类型（div/changed.pos/
   latch.write/mem.fill/mul/ashr/changed.neg）各保底一个 BFS 播种区域。

其余按 D4 执行：内部 2k–8k、两种方式各半、禁区 = topo 序连续 10%（[2,101,272,
2,568,221)，取中段 0.45–0.55）、稀有结构引导比例 12.5%。

### 覆盖报告（M0 采样覆盖检查，`coverage.json`）

```
512 区域（topo 252 / bfs 260），生成 17.4s，206 MB
internal 规模：min 2050 / median 4990.5 / max 8182（全部落在 [2048, 8192]）
opcode 类型覆盖：39/39（含全图仅 1 节点的 changed.neg）
稀有结构区域占比：34.6%（177 个；要求 ≥10%）
内部节点并集：1,725,412（全图 37.0%）
holdout 违规：0
```

## 4. 任务 4：搜索器骨架

- **段 DP**：生产代码（`activity_schedule.cpp:535-615`）逐行语义的 Python 移植，
  换 04 文档新 cost 公式（位宽折算、无段惩罚），容量 128；超大 comb-loop-atom 例外
  暂不支持（香山为零），遇到显式报错。正确性：30 组随机小图与暴力枚举全切分逐一
  对拍（`test_searcher.py`）。
- **SA 骨架**：初始序 = 规范拓扑序；移动 = relocate（直接前驱/后继界定的合法范围，
  对线性扩张是精确判定）+ swap；Metropolis + 指数降温；保留最优。commit 类
  （state_write）节点按生产口径排出排列问题（读免费、不产值）。
- **冒烟**（`run_search_smoke.py`，3 个最小区域、60 次迭代）：闭环跑通，
  initial 2070/2090/1265 → best 2070/2090/1264；单次 DP 约 12–48ms（n≈2k）。
  改善≈0 是预期内：D7 的 1万–10万次迭代下才有意义，且 BFS 区域成本由冻结边界
  主导（2070/2049≈1.01，边界值占了大部分，留给 R1 风险跟踪）。
- **Phase 1 待办**：C++ 段 DP 内核（Python 单次 ~30ms × 10k 迭代 ≈ 5 min/区域，
  不可接受）、增量评分、移动集合与温度表调参、10k–100k 迭代标签流水线。

## 5. 任务 5：CPU 推理摸底（校准 K7 规模上限）

全香山真实边表（4,669,495 节点 / 8,050,644 def_use+order 边）、float32、
numpy 代理（生产将是手写 C++ gather/SpMM，只会更快——实测值是保守上限）：

```
 dim   gather     spmm   matmul    layer  2-layer  3-layer   GB/s
  32    0.13s    2.40s    0.11s    2.76s    5.63s    8.39s   7.7
  64    0.24s    5.25s    0.23s    5.94s   12.11s   18.05s   8.5
```

（layer = gather + 段和聚合 + [h,agg]@W 两次 matmul；model = L×layer + 打分头。）
结论：**K7 上限（隐维 ≤64、2–3 层）在 CPU 上成立**——d=64×3 层全图推理 ≈18s，
落在 02 §6.5 的 10–60s 推理预算内，距 15 分钟编译总预算余量充足；SpMM（段和）
是主要耗时，C++ 化还有数倍空间（R3 风险解除为"已提前暴露且有杠杆"）。

## 6. M0 验收门核对

| 验收项 | 状态 | 证据 |
|---|---|---|
| 全香山导出成功 | ✅ | docs/05；本目录数据集溯源一致 |
| 对账通过 | ✅ | §2 六项指标全等（harness scorer 独立复算） |
| 采样覆盖检查通过 | ✅ | §3：39/39 类型、规模全在区间、稀有占比 34.6%、holdout 0 违规 |
| CPU 摸底给出模型规模实测上限 | ✅ | §5：d64×3 层 ≈18s，K7 成立 |

Phase 0 完成。后续按 04 文档进 Phase 1（搜索器完整版 + 标签流水线）。
