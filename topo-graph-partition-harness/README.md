# topo-graph-partition-harness

## 目标

`topo-graph-partition-harness` 是一个 C++20 harness，用于把 `activity-schedule`
导出的 compute DAG 作为固定输入，统一完成图读取、合法性检查、划分结果检查、评分、
实验运行和搜索树记录。

边界必须清楚：harness 只消费已经放入 `cases/` 的 compute DAG 文件。它不能在本目录内
调用 wolvrix、xs-components、Scala/Chisel、GRH emit 或 `activity-schedule` 导出流程。
真实 case 由用户在 harness 外生成并手工加入 `cases/`。case 顶层只分为
`cases/regular/` 和 `cases/final/`：regular 是中小型快速迭代集合，必须带 oracle
参考；final 是完整 Xiangshan gate，不要求也不维护 oracle 参考。

本 README 只描述 harness 搭建要求和验收标准，不展开后续分图算法方向。具体算法尝试必须
放在 `INSTRUCTIONS.md` 约束的单次尝试节点中记录。

核心职责：

- 约定 `activity-schedule` compute DAG 的 JSON 输入格式。
- 约定算法模块输出的 partition result JSON 格式。
- 固定 `validate_graph`、`validate_partition`、`score_partition`、`brute_force_oracle`
  和 `run_experiment` 的实现边界。
- 提供可替换的 C++ algorithm 接口，但 checker、score、oracle 不允许随算法尝试改写。
- 提供 `INSTRUCTIONS.md`，保证之后每次算法尝试都执行同一套流程，并创建一个新的
  search tree 节点。
- 每个 search tree 节点的快速迭代必须覆盖当前 `cases/regular/` manifest 的全部评分；
  当至少 80% regular case 在划分质量和 oracle 距离上确认获得正向收益时，才允许触发
  `cases/final/`。
- 搜索节点可以声明重点观察的 case，但重点 case 只能用于解释结果和定位回退，不能作为评分集合。
  节点生成时必须先冻结完整 regular manifest，后续 baseline、candidate、delta 和触发判定都以该 manifest
  的全部 case 为准。
- `cases/final/` 下只放完整 Xiangshan 大图，不参与 regular 快速迭代；它只在 regular
  80% 阈值通过后作为最终 gate 单独运行。
- regular 阶段只决定是否允许开启 final，不决定节点成功。单个 search node 是否成功，最终看
  final gate 是否在 10 分钟硬界限内完成，并且 final 指标相对 baseline 获得划分质量综合收益。
- 每个 search tree 节点必须产出 full-case score matrix，逐 case 记录 baseline、candidate、delta、
  validation 状态和运行状态；没有矩阵或矩阵缺行的节点无效。
- final gate 的默认综合收益以 `cut_weight` 为主，结合 `quotient_edges`、`quotient_p99_out_degree`
  和 runtime 约束；final 超时、缺 score、validation 失败或综合收益不成立，节点必须 `reject` 或
  `branch`，不能记为 `keep`。
- 支持真实目标图，尤其是
  `testcase/xs-components/src/main/scala/cases/XsIcacheReplacerLarge.scala` 导出的
  compute DAG。

## 非目标

- 不在 README 中设计或推荐具体启发式算法。
- 不把算法试验结论写进 harness 搭建文档。
- 不让算法模块携带自己的 checker 或 score 逻辑。
- 不用 Python 承担 validation、score、oracle 或正式实验执行。
- 不在 harness 内调用 wolvrix、xs-components 或任何 producer/exporter。
- 不把 GRHSim、wolvrix JSON、Chisel/RTL 编译输出写入 `topo-graph-partition-harness/runs/`。
- 不直接修改 GRH、`activity-schedule` 调度语义或 emitted RTL 语义。
- 不通过删除失败 case、放宽 checker、改 score 来制造进展。

## C++ 实现约束

harness 主链路必须使用 C++20。

强制要求：

- `validate_graph`、`validate_partition`、`score_partition`、`brute_force_oracle`、
  `run_experiment` 必须是 C++ 实现。
- 算法主实现必须通过 C++ 接口接入 harness。
- Python 只允许用于离线画图、报表汇总、临时查看 JSON，不能重写检查、评分或 oracle。
- 如果需要脚本封装，也只能调用 C++ 可执行程序。

原因：

- 大图 validation、score、商图 DAG 检查会成为热路径。
- `activity-schedule` 在 C++ 侧，C++ harness 更容易对齐数据结构和性能约束。
- checker 必须足够快，才能在每次尝试中高频执行。

## 目录结构

```text
topo-graph-partition-harness/
  README.md
  INSTRUCTIONS.md
  CMakeLists.txt
  schemas/
    compute-op-dag.schema.json
    partition-result.schema.json
  include/tgp/
    graph.hpp
    graph_io.hpp
    partition.hpp
    validator.hpp
    scorer.hpp
    algorithm.hpp
    oracle.hpp
    experiment.hpp
  lib/
    json.cpp
    graph_io.cpp
    validate_graph.cpp
    quotient_graph.cpp
    validate_partition.cpp
    score_partition.cpp
    brute_force_oracle.cpp
    experiment.cpp
  algorithms/
    README.md
    <algorithm>.cpp
  app/
    tgp_validate_graph.cpp
    tgp_validate_partition.cpp
    tgp_score_partition.cpp
    tgp_oracle.cpp
    tgp_run_experiment.cpp
  cases/
    regular/
      <CaseName>/
        <CaseName>.compute-op-dag.json
        <CaseName>.oracle.json
        <CaseName>.oracle.ckpt
    final/
      <case>.compute-op-dag.json
  runs/
    sample-config.json
    <run-id>/
      config.json
      result.json
      score.json
      log.md
  memory/
    index.md
    search_tree.md
    experiments/
      EXP0001_*.md
```

`algorithms/` 只放可替换算法模块。固定模块只能放在 `lib/` 和 `include/tgp/` 中维护。
`cases/` 顶层只允许 `regular/` 和 `final/` 两个子目录。`regular/` 下按 case 粒度建立一级目录：
`cases/regular/<CaseName>/<CaseName>.compute-op-dag.json`。不要再使用 `real/`、`sampled/`、
`small/` 这类分类目录。每个 regular case 目录应放同名 oracle 参考。`final/` 只放完整
Xiangshan gate case，不放缩小图、占位图或 oracle 参考。

`runs/` 只允许存放普通 experiment 的 config、partition result、score 和 log，不允许存放
producer 侧生成物。oracle 产物不放在普通 `runs/`；regular oracle 输出放在对应
`cases/regular/` case 目录下，作为快速迭代参考资料。

`memory/search_tree.md` 是树搜索状态机，不只是一个结果表。它至少要区分 active frontier、parked
child hypotheses、closed nodes 和 family ledger，避免所有当前节点失败后搜索树失忆。

## 输入图格式

`activity-schedule` 导出 compute 侧 DAG，格式为 JSON：

```json
{
  "format": "wolvrix.compute-op-dag.v1",
  "graph_id": "SimTop.logic_part.activity_compute",
  "source": {
    "pass": "activity-schedule",
    "path": "SimTop.logic_part",
    "created_at": "2026-05-26T00:00:00Z"
  },
  "options": {
    "node_granularity": "op",
    "edge_weight": "value_bitwidth_words"
  },
  "nodes": [
    {
      "id": 0,
      "op_id": 123,
      "kind": "kAnd",
      "symbol": "optional.stable.name",
      "topo_pos": 0,
      "attrs": {
        "granularity": "op"
      }
    }
  ],
  "edges": [
    {
      "src": 0,
      "dst": 1,
      "weight": 2,
      "values": [
        { "id": 456, "width": 1 },
        { "id": 457, "width": 1 },
        { "id": 458, "width": 126 }
      ]
    }
  ]
}
```

必备语义：

- `nodes[].id` 是连续整数，范围 `[0, n)`。
- 每个 node 表示一个 compute op，顶点不带容量权重。
- `nodes[].weight` 禁止出现；超节点大小限制只按包含的 op 个数计算。
- `nodes[].topo_pos` 是 `activity-schedule` 导出的稳定 topo 位置。
- `edges[].values[]` 表示从 `src` op 传到 `dst` op 的 value。
- value 不带独立权重；`values[].width` 是该 value 的 bit width，至少为 1。
- `edges[].weight = ceil(sum(edges[].values[].width) / 64)`，最小为 1。
- 输入图必须是 DAG。
- 重边应在导出阶段合并；如果输入存在重边，`graph_io` 必须 canonicalize 后合并。
- 图只包含 compute 侧顶点，不混入 commit supernode。

## 输出划分格式

算法模块只输出划分，不输出评分结论：

```json
{
  "format": "wolvrix.compute-op-partition.v1",
  "graph_id": "SimTop.logic_part.activity_compute",
  "algorithm": {
    "name": "example_algorithm",
    "version": "0.1",
    "parameters": {
      "max_nodes_per_part": 128
    }
  },
  "constraints": {
    "max_nodes_per_part": 128
  },
  "assignment": [
    { "node": 0, "part": 0 },
    { "node": 1, "part": 0 },
    { "node": 2, "part": 1 }
  ],
  "part_order_hint": [0, 1],
  "stats_hint": {
    "runtime_ms": 1.2
  }
}
```

固定 checker 必须重新计算所有合法性和指标。`part_order_hint` 和 `stats_hint` 只是辅助信息，
不能作为合法性依据。

## C++ 数据结构

核心图结构使用连续 id 和紧凑 vector，避免热路径依赖字符串 key 或 map：

```cpp
namespace tgp
{
    using NodeId = uint32_t;
    using PartId = uint32_t;

    struct Node {
        NodeId id = 0;
        uint64_t opId = 0;
        uint32_t topoPos = 0;
    };

    struct Edge {
        NodeId src = 0;
        NodeId dst = 0;
        uint32_t weight = 1;
    };

    struct ComputeDag {
        std::string graphId;
        std::vector<Node> nodes;
        std::vector<Edge> edges;
        std::vector<uint32_t> outBegin;
        std::vector<uint32_t> outEdges;
        std::vector<uint32_t> inBegin;
        std::vector<uint32_t> inEdges;
    };

    struct PartitionResult {
        std::string graphId;
        std::vector<PartId> partByNode;
        uint32_t maxNodesPerPart = 0;
    };
}
```

实现要求：

- JSON 解析后立即 canonicalize node id、edge order 和重边。
- 大图检查使用紧凑邻接表。
- 商图边去重优先使用排序后的 `(srcPart, dstPart)` pair vector。
- 所有 CLI 和 algorithm 共享同一份 `ComputeDag` / `PartitionResult` 结构。

## 固定模块

### `graph_io`

职责：

- 读取 `compute-op-dag.v1`。
- 读取 `compute-op-partition.v1`。
- 写出 canonical partition result、score、oracle result。
- 检查 JSON 版本字段。
- 将 JSON 载入连续 id C++ 结构。

### `validate_graph`

检查项：

- node id 连续且无重复。
- edge 两端存在。
- edge weight 为正整数。
- 无自环。
- 输入图是 DAG。
- `topo_pos` 覆盖全部节点，并且每条边满足 `topo_pos[src] < topo_pos[dst]`。
- 如果存在 `values`，同一 `(src, dst)` 下 value id 不重复。

CLI：

```bash
tgp_validate_graph --graph cases/regular/Foo/Foo.compute-op-dag.json
```

### `validate_partition`

检查项：

- assignment 覆盖全部节点。
- 每个 node 恰好出现一次。
- part id canonicalize 后连续。
- 每个 part 非空。
- part 内 node 数不超过 `max_nodes_per_part`。
- 每个原图 edge 要么在 part 内部，要么形成商图 edge。
- 商图去重后必须是 DAG。
- `part_order_hint` 如存在，必须能被验证为合法 topo order；否则忽略并重新计算。

CLI：

```bash
tgp_validate_partition \
  --graph cases/regular/Foo/Foo.compute-op-dag.json \
  --partition runs/foo/result.json
```

### `score_partition`

固定指标：

| 指标 | 说明 |
| --- | --- |
| `cut_weight` | 所有跨 part 原图边的权重和 |
| `cut_edges` | 跨 part 原图边条数 |
| `parts` | part 数 |
| `max_part_size` | 最大 part node 数 |
| `mean_part_size` | 平均 part node 数 |
| `p90_part_size` | part node 数 p90 |
| `quotient_edges` | 商图去重边数 |
| `quotient_avg_out_degree` | 商图平均出度 |
| `quotient_p99_out_degree` | 商图 p99 出度 |
| `runtime_ms` | 算法报告的运行时间 |

CLI：

```bash
tgp_score_partition \
  --graph cases/regular/Foo/Foo.compute-op-dag.json \
  --partition runs/foo/result.json \
  --out runs/foo/score.json
```

### `brute_force_oracle`

oracle 是 harness 固定模块，用于小图最优证明，也用于真实图上的长跑上界、下界、
checkpoint 和局部证明。oracle 不属于默认 experiment workflow；只有用户显式要求时才运行。
其输出应和输入 case 放在一起，作为后续算法尝试的参考基准。

要求：

- 使用同一份 `validate_partition` 和 `score_partition`。
- 支持 `--threads`、`--prefix-depth`、`--time-limit-sec`、`--checkpoint-interval-sec`、
  `--checkpoint`、`--resume`。
- 搜索状态必须可序列化。checkpoint 必须记录 `graph_id`、`max_nodes_per_part`、`prefix_depth`、
  `task_order`、incumbent、score、counter 和 `completed_task_ranges`；resume 只能复用完全匹配的
  graph、容量约束、prefix depth 和 task order。
- 默认 task order 是 `prefix_cut_desc_v1`，先处理或剪掉当前 prefix cut 已经不可能优于 incumbent
  的任务。
- 输出必须区分 `optimal=true`、`optimal=false but bounded`、`timeout without bound`。
- 超时也必须输出 incumbent、lower bound、gap、frontier 摘要。
- 如果 `graph.nodes.size() <= max_nodes_per_part`，oracle 必须直接给出单个超节点、`cut_weight=0`
  的最优证明，不进入指数搜索。
- `XsIcacheReplacerLarge` 导出的 compute DAG 必须能进入 oracle 路径。

CLI：

```bash
tgp_oracle \
  --graph cases/regular/Foo/Foo.compute-op-dag.json \
  --max-nodes-per-part 128 \
  --threads 32 \
  --prefix-depth 10 \
  --time-limit-sec 86400 \
  --checkpoint-interval-sec 30 \
  --checkpoint cases/regular/Foo/Foo.oracle.ckpt \
  --out cases/regular/Foo/Foo.oracle.json
```

### `run_experiment`

统一实验入口，负责：

- 读取 graph。
- 读取 config。
- 调用一个 algorithm。
- 写出 partition result。
- 调用固定 validator。
- 调用固定 scorer。
- 写出 run log。

CLI：

```bash
tgp_run_experiment \
  --algorithm <name> \
  --graph cases/regular/Foo/Foo.compute-op-dag.json \
  --config runs/foo/config.json \
  --out-dir runs/foo \
  --time-limit-sec <n>
```

`--time-limit-sec` 是可选参数，给需要硬超时的门禁 case 用。常规小图迭代可以不传；
`cases/final/` 下的最终门禁图要求显式传入 600 秒预算。

## 算法插件边界

README 只定义 harness 接口，不规定算法路线。

```cpp
namespace tgp
{
    struct AlgorithmConfig;
    struct ComputeDag;
    struct PartitionResult;

    class PartitionAlgorithm
    {
    public:
        virtual ~PartitionAlgorithm() = default;
        virtual std::string_view name() const = 0;
        virtual PartitionResult run(const ComputeDag &graph, const AlgorithmConfig &config) = 0;
    };
}
```

算法模块允许：

- 读取 `const ComputeDag &`。
- 读取 config。
- 输出 `PartitionResult`。
- 输出调试统计。

算法模块禁止：

- 修改输入图。
- 修改 checker。
- 修改 score。
- 绕过 `validate_partition`。
- 删除失败 case。

## 输入 Case 来源

harness 的输入 case 是 `compute-op-dag.v1` JSON 文件，固定放在 `cases/` 下。case 来源规则：

- `activity-schedule` 导出能力在 wolvrix producer 侧实现和测试，不属于 harness 运行流程。
- harness 不提供、也不调用导出命令。
- `cases/` 顶层只允许 `regular/` 和 `final/`。
- 用户在 harness 外生成中小型真实图后，手工把 `*.compute-op-dag.json` 放入
  `cases/regular/<CaseName>/<CaseName>.compute-op-dag.json`。
- 完整 Xiangshan 最终门禁图放入 `cases/final/`，不混入 regular 快速迭代 case 集。
- case 文件必须可由 `tgp_validate_graph` 验证。
- case 文件应记录节点数、边数、权重总和等 summary stats。
- node id 必须稳定对应 producer 侧 compute op，`op_id` 记录原始 GRH operation id，方便 harness 报告定位。

oracle 参考资料的来源规则：

- regular case 必须具备同目录 oracle 参考，例如 `foo.oracle.json` 和 `foo.oracle.ckpt`。
- oracle 只在用户显式要求刷新或补齐时运行；普通算法尝试引用已有 regular oracle。
- final case 不要求 oracle 参考，也不得因为缺 final oracle 阻塞 final gate。
- 如果 regular case 缺 oracle 参考，该 case 不能进入有效 regular manifest；需要先由用户显式要求补齐
  oracle，或把该 case 移出 regular manifest 并记录原因。

## 指令文档

必须维护：

```text
topo-graph-partition-harness/INSTRUCTIONS.md
```

用途：

- 作为之后每次算法尝试的固定执行指令。
- 一次执行只创建一个新的 search tree 节点。
- 每次执行必须先枚举并覆盖当前 `cases/regular/` manifest；当 80% regular case 确认正收益后，
  才允许触发 `cases/final/`。
- 每次执行必须把 regular manifest 和 final manifest 分别固化，并在实验文档中记录每个 case
  的路径、graph summary、验证状态、运行时间和 score。
- 每个阶段都必须有可比较的 baseline。baseline 可以来自 parent 节点，也可以来自专门的 baseline
  节点，但必须覆盖同一份 stage manifest；缺 baseline 时只能先补 baseline，不能宣称候选算法成功。
- 候选算法必须对 stage manifest 内每个 case 生成 `result.json`、`score.json` 和 `log.md`。
  缺任何 case、跳过任何 case、只记录子集分数，节点都必须保持 invalid 或 rejected。
- 节点可以声明本次尝试预计最可能影响哪些 case，但该声明不能改变执行范围。执行范围永远是冻结后的完整
  regular manifest；重点 case 只允许作为 interpretation 线索。
- regular 阶段是 final gate 的开启阈值，不是节点成功判定。regular 门禁必须对每个 case 都有
  baseline/candidate/delta/oracle-distance 行，并从完整矩阵计算：
  - `regular_positive_count`
  - `regular_total_count`
  - `regular_positive_ratio = regular_positive_count / regular_total_count`
  - `regular_oracle_gap_improved_count`
  当 `regular_positive_ratio >= 0.80`，并且正收益同时覆盖划分质量和 oracle 距离时，才允许运行 final。
- 节点成功条件只由 final gate 决定：
  - final manifest 全部 case graph validation 成功；
  - baseline 与 candidate 都覆盖全部 final case；
  - candidate partition validation 和 score 全部成功；
  - 每个 final run 都在 `--time-limit-sec 600` 内完成；
  - final 综合收益相对 baseline 为正，主指标是 `cut_weight`，同时记录 `quotient_edges`、
    `quotient_p99_out_degree` 和 runtime，不能用 regular 收益替代 final 收益。
- 每个节点必须有 `Sxxxx` id、parent、hypothesis、case set、命令、结果和决策。
- 如果只是修 bug，记录为同一节点下的 patch attempt。
- 如果改变算法假设，必须创建 child node。
- 执行结束必须更新 `memory/search_tree.md` 和 `memory/experiments/EXPxxxx_*.md`。

README 只要求这份指令存在并被执行；具体尝试流程写在 `INSTRUCTIONS.md`。

## 必须支持的真实目标

`testcase/xs-components/src/main/scala/cases/XsIcacheReplacerLarge.scala` 是 harness
早期真实目标，但只作为 `cases/regular/XsIcacheReplacerLarge/` case，不承担最终门禁角色。

完整 Xiangshan compute DAG 作为最终门禁 case，用户后续加入 `cases/final/`。

要求：

- 用户在 harness 外生成并手工加入该 case 的 `compute-op-dag.v1`。
- `tgp_validate_graph` 能验证该导出图。
- `tgp_run_experiment` 能在该图上完成一次算法执行、validation、score。
- 当该图被放入 `cases/final/` 时，`tgp_run_experiment` 必须支持 `--time-limit-sec 600` 的硬超时运行。
- 最终门禁必须记录运行时与 score；10 分钟内未完成则该节点验收失败。
- final case 不要求 oracle 参考；final gate 只比较 baseline 与 candidate 的固定 score。

建议路径：

```text
cases/regular/XsIcacheReplacerLarge/XsIcacheReplacerLarge.compute-op-dag.json
cases/regular/XsIcacheReplacerLarge/XsIcacheReplacerLarge.oracle.json
cases/regular/XsIcacheReplacerLarge/XsIcacheReplacerLarge.oracle.ckpt
runs/xs_icache_replacer_large/<experiment-run>/
```

## 搭建任务清单

1. 写 `schemas/compute-op-dag.schema.json`。
2. 写 `schemas/partition-result.schema.json`。
3. 写 `CMakeLists.txt`，生成 `tgp_harness` 和 CLI。
4. 写 `include/tgp/graph.hpp`、`partition.hpp`、`algorithm.hpp`。
5. 实现 `lib/graph_io.cpp`。
6. 实现 `lib/validate_graph.cpp`。
7. 实现 `lib/quotient_graph.cpp`。
8. 实现 `lib/validate_partition.cpp`。
9. 实现 `lib/score_partition.cpp`。
10. 实现 CLI：`tgp_validate_graph`、`tgp_validate_partition`、`tgp_score_partition`。
11. 实现 `lib/brute_force_oracle.cpp` 和 `tgp_oracle` 的基础版本。
12. 实现 `lib/experiment.cpp` 和 `tgp_run_experiment`。
13. 建立带 active frontier、parked candidates、closed nodes、family ledger 的 `memory/search_tree.md`
  和 `memory/experiments/`。
14. 确认 `INSTRUCTIONS.md` 可作为每次尝试的执行入口。
15. 准备 Level 0 legality cases，覆盖 DAG、cycle trap、capacity trap。
16. 支持用户手工加入的 `XsIcacheReplacerLarge.compute-op-dag.json` smoke。
17. 预留 `cases/final/` 用于完整 Xiangshan 最终门禁，并在运行入口支持 10 分钟硬超时。

## 验收标准

harness 初版完成的标准：

- 所有 CLI 可由 CMake 构建。
- `tgp_validate_graph` 能验证手写小图和用户手工加入的 `XsIcacheReplacerLarge` 图。
- `tgp_validate_partition` 能拒绝缺 node、重复 node、超容量、商图 cycle。
- `tgp_score_partition` 输出固定指标 JSON。
- 用户显式要求时，`tgp_oracle` 至少能对 tiny cases 证明最优，并支持 checkpoint 参数。
- `tgp_run_experiment` 能完成一次算法执行、validation、score、日志写出，并支持可选硬超时。
- `INSTRUCTIONS.md` 明确要求每次尝试生成一个 search tree 节点。
- README 不包含具体后续算法方向，只描述 harness 边界、搭建要求和验收标准。
