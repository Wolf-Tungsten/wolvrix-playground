# topo-graph-partition-harness

## 目标

`topo-graph-partition-harness` 是一个 C++20 harness，用于把 `activity-schedule`
导出的 compute DAG 作为固定输入，统一完成图读取、合法性检查、划分结果检查、评分、
实验运行和搜索树记录。oracle 是可选参考流程，只在用户显式要求时运行。

边界必须清楚：harness 只消费已经放入 `cases/` 的 compute DAG 文件。它不能在本目录内
调用 wolvrix、xs-components、Scala/Chisel、GRH emit 或 `activity-schedule` 导出流程。
真实 case 由用户在 harness 外生成并手工加入 `cases/`。
oracle 结果也不是普通 experiment 的默认产物；只有用户显式要求运行 oracle 时，才把
oracle 输出放在对应 case 旁边作为参考资料。

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
- 每个 search tree 节点的日常迭代必须覆盖当前非 final case manifest 的全部评分；
  只有常规 case 汇总有收益且无关键回退，才允许触发最终门禁。
- 搜索节点可以声明重点观察的 case，但重点 case 只能用于解释结果和定位回退，不能作为评分集合。
  节点生成时必须先冻结完整 routine manifest，后续 baseline、candidate、delta 和决策都以该 manifest
  的全部 case 为准。
- `cases/final/` 下的完整 Xiangshan 大图不参与每轮迭代；它只在某个节点已经通过小 case / 常规 case 门禁后，
  作为最终验收门禁单独运行。
- 常规 manifest 和 final manifest 都必须使用同一份 baseline 与候选算法逐 case 对比。
  任一 case 缺失、未评分、validation 失败、超时或只在少量 case 上变好，都不能把节点判定为成功。
- 每个 search tree 节点必须产出 full-case score matrix，逐 case 记录 baseline、candidate、delta、
  validation 状态和运行状态；没有矩阵或矩阵缺行的节点无效。
- 节点成功的默认主判据是全 manifest 聚合 `sum_cut_weight` 下降，同时 quotient 复杂度和 runtime
  不出现预先未声明的关键回退；不能在看结果后临时剔除失败 case、只统计通过 case、只看重点 case，
  或改用子集平均。
- 只要任何 routine case 缺 baseline、缺 candidate、缺 score、未通过固定 validation、超时或运行崩溃，
  该搜索节点就不能记为成功。混合结果只能进入 `branch` 或 `reject`，不能把少数 case 的收益包装成整体收益。
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
    small/
    sampled/
    real/
      <case>.compute-op-dag.json
      <case>.oracle.json        # optional, user-requested reference
      <case>.oracle.ckpt        # optional, user-requested checkpoint
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
`runs/` 只允许存放普通 experiment 的 config、partition result、score 和 log，不允许存放
producer 侧生成物。oracle 产物不放在普通 `runs/`；用户显式要求运行 oracle 时，输出放在
对应 `cases/` 目录下，作为该 case 的参考资料。

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
    "edge_weight": "boundary_activation_edges",
    "node_weight": "op_count"
  },
  "nodes": [
    {
      "id": 0,
      "op_id": 123,
      "kind": "kAnd",
      "symbol": "optional.stable.name",
      "weight": 1,
      "topo_pos": 0,
      "attrs": {
        "bit_width": 1,
        "compute_node_id": 0
      }
    }
  ],
  "edges": [
    {
      "src": 0,
      "dst": 1,
      "weight": 3,
      "values": [456, 457, 458]
    }
  ]
}
```

必备语义：

- `nodes[].id` 是连续整数，范围 `[0, n)`。
- `nodes[].weight` 是容量约束使用的节点权重。
- `nodes[].topo_pos` 是 `activity-schedule` 导出的稳定 topo 位置。
- `edges[].weight` 是割边代价，初期对齐 boundary activation edge 数量。
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
      "max_node_weight": 128
    }
  },
  "constraints": {
    "max_node_weight": 128,
    "allow_oversize_singleton": true
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
        uint32_t weight = 1;
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
        uint32_t maxNodeWeight = 0;
        bool allowOversizeSingleton = true;
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
- node weight 为正整数。
- 无自环。
- 输入图是 DAG。
- `topo_pos` 覆盖全部节点，并且每条边满足 `topo_pos[src] < topo_pos[dst]`。
- 如果存在 `values`，同一 `(src, dst)` 下 value id 不重复。

CLI：

```bash
tgp_validate_graph --graph cases/real/foo.compute-op-dag.json
```

### `validate_partition`

检查项：

- assignment 覆盖全部节点。
- 每个 node 恰好出现一次。
- part id canonicalize 后连续。
- 每个 part 非空。
- part weight 不超过 `max_node_weight`。
- 单节点 weight 超过上限时，只允许形成 singleton part。
- 每个原图 edge 要么在 part 内部，要么形成商图 edge。
- 商图去重后必须是 DAG。
- `part_order_hint` 如存在，必须能被验证为合法 topo order；否则忽略并重新计算。

CLI：

```bash
tgp_validate_partition \
  --graph cases/real/foo.compute-op-dag.json \
  --partition runs/foo/result.json
```

### `score_partition`

固定指标：

| 指标 | 说明 |
| --- | --- |
| `cut_weight` | 所有跨 part 原图边的权重和 |
| `cut_edges` | 跨 part 原图边条数 |
| `parts` | part 数 |
| `max_part_weight` | 最大 part weight |
| `mean_part_weight` | 平均 part weight |
| `p90_part_weight` | part weight p90 |
| `quotient_edges` | 商图去重边数 |
| `quotient_avg_out_degree` | 商图平均出度 |
| `quotient_p99_out_degree` | 商图 p99 出度 |
| `runtime_ms` | 算法报告的运行时间 |

CLI：

```bash
tgp_score_partition \
  --graph cases/real/foo.compute-op-dag.json \
  --partition runs/foo/result.json \
  --out runs/foo/score.json
```

### `brute_force_oracle`

oracle 是 harness 固定模块，用于小图最优证明，也用于真实图上的长跑上界、下界、
checkpoint 和局部证明。oracle 不属于默认 experiment workflow；只有用户显式要求时才运行。
其输出应和输入 case 放在一起，作为后续算法尝试的参考基准。

要求：

- 使用同一份 `validate_partition` 和 `score_partition`。
- 支持 `--threads`、`--time-limit-sec`、`--checkpoint`、`--resume`。
- 搜索状态必须可序列化。
- 输出必须区分 `optimal=true`、`optimal=false but bounded`、`timeout without bound`。
- 超时也必须输出 incumbent、lower bound、gap、frontier 摘要。
- `XsIcacheReplacerLarge` 导出的 compute DAG 必须能进入 oracle 路径。

CLI：

```bash
tgp_oracle \
  --graph cases/real/foo.compute-op-dag.json \
  --max-node-weight 128 \
  --threads 32 \
  --time-limit-sec 86400 \
  --checkpoint cases/real/foo.oracle.ckpt \
  --out cases/real/foo.oracle.json
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
  --graph cases/real/foo.compute-op-dag.json \
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
- 用户在 harness 外生成真实图后，手工把 `*.compute-op-dag.json` 放入 `cases/real/`。
- 未来完整 Xiangshan 最终门禁图放入 `cases/final/`，不混入日常迭代 case 集。
- case 文件必须可由 `tgp_validate_graph` 验证。
- case 文件应记录节点数、边数、权重总和等 summary stats。
- node id 必须稳定对应 producer 侧 compute node，方便 harness 报告定位。

oracle 参考资料的来源规则：

- oracle 只在用户显式要求时运行。
- oracle 输出放在对应 case 同目录下，例如 `foo.oracle.json` 和 `foo.oracle.ckpt`。
- 普通算法尝试可以引用已有 oracle 参考资料，但不能要求每次尝试都重新运行 oracle。
- 如果没有 oracle 参考资料，实验记录应写明 `oracle: not requested`。

## 指令文档

必须维护：

```text
topo-graph-partition-harness/INSTRUCTIONS.md
```

用途：

- 作为之后每次算法尝试的固定执行指令。
- 一次执行只创建一个新的 search tree 节点。
- 每次执行必须先枚举并覆盖当前非 final case manifest，再在常规 case 成功时触发 `cases/final/`
  的最终门禁。
- 每次执行必须把常规 manifest 和 final manifest 分别固化，并在实验文档中记录每个 case
  的路径、graph summary、验证状态、运行时间和 score。
- 每个阶段都必须有可比较的 baseline。baseline 可以来自 parent 节点，也可以来自专门的 baseline
  节点，但必须覆盖同一份 stage manifest；缺 baseline 时只能先补 baseline，不能宣称候选算法成功。
- 候选算法必须对 stage manifest 内每个 case 生成 `result.json`、`score.json` 和 `log.md`。
  缺任何 case、跳过任何 case、只记录子集分数，节点都必须保持 invalid 或 rejected。
- 节点可以声明本次尝试预计最可能影响哪些 case，但该声明不能改变执行范围。执行范围永远是冻结后的完整
  routine manifest；重点 case 只允许作为 interpretation 线索。
- 成功判定必须基于两级门禁：先看常规 manifest 的全量聚合收益，再看 final gate 的运行时与最终得分。
  常规门禁必须对每个 case 都有 baseline/candidate/delta 行，并从完整矩阵计算聚合值；不能只挑少量 case
  评分后宣称成功。
- 默认成功条件：
  - routine manifest 全部 case graph validation 成功；
  - baseline 与 candidate 都覆盖全部 routine case；
  - candidate partition validation 和 score 全部成功；
  - candidate 的 `sum_cut_weight` 严格小于 baseline；
  - `sum_quotient_edges`、`quotient_p99_out_degree` 和 `max_runtime_ms` 没有超过节点开始前声明的回退预算；
  - 对任何单 case 回退都有记录、解释和后续分支决策，且这些回退不能抵消整体收益或突破预算；
  - 如果 `cases/final/` 存在 case，则 final gate 也必须全部通过。
- 每个节点必须有 `Sxxxx` id、parent、hypothesis、case set、命令、结果和决策。
- 如果只是修 bug，记录为同一节点下的 patch attempt。
- 如果改变算法假设，必须创建 child node。
- 执行结束必须更新 `memory/search_tree.md` 和 `memory/experiments/EXPxxxx_*.md`。

README 只要求这份指令存在并被执行；具体尝试流程写在 `INSTRUCTIONS.md`。

## 必须支持的真实目标

`testcase/xs-components/src/main/scala/cases/XsIcacheReplacerLarge.scala` 是 harness
早期真实目标，但只作为常规 real/smoke case，不承担最终门禁角色。

完整 Xiangshan compute DAG 作为最终门禁 case，用户后续加入 `cases/final/`。

要求：

- 用户在 harness 外生成并手工加入该 case 的 `compute-op-dag.v1`。
- `tgp_validate_graph` 能验证该导出图。
- `tgp_run_experiment` 能在该图上完成一次算法执行、validation、score。
- 当该图被放入 `cases/final/` 时，`tgp_run_experiment` 必须支持 `--time-limit-sec 600` 的硬超时运行。
- 最终门禁必须记录运行时与 score；10 分钟内未完成则该节点验收失败。
- 当用户显式要求 oracle 时，`tgp_oracle` 能在该图上启动长跑，并输出 incumbent、
  lower bound、gap、checkpoint 到 `cases/real/` 参考文件。
- 即使无法证明全局最优，也不能把该 case 排除在用户显式要求的 oracle 路径外。

建议路径：

```text
cases/real/XsIcacheReplacerLarge.compute-op-dag.json
cases/real/XsIcacheReplacerLarge.oracle.json
cases/real/XsIcacheReplacerLarge.oracle.ckpt
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
