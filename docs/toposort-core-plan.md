# 高性能拓扑排序 Core 组件实现草案

## 当前状态（2026-04-03）

该草案的首版实现已经落地，代码位置：

- `wolvrix/include/core/toposort.hpp`
- `wolvrix/lib/core/toposort.cpp`
- `wolvrix/tests/core/test_toposort.cpp`

当前已经完成：

- `TopoDag<NodeType, Hash, Eq>` 主体接口。
- `addNode()` 自动去重与重复节点报错策略。
- `addEdge()` 自动补节点。
- 排序前集中边去重：`uint64_t` 打包边 + `sort/unique`。
- CSR 邻接结构构建。
- Kahn 分层拓扑排序。
- `std::vector<std::vector<NodeType>>` 分层结果输出。
- `TopoDagBuilder + LocalBuilder + finalize()` 的多线程构图接口骨架。
- CTest 用例接线。

已经验证的测试点：

- 重复节点去重。
- 重复节点报错。
- 重复边去重。
- 多层 DAG 分层结果。
- 环检测报错。
- `TopoDagBuilder` 合并后的构图与排序行为。

本次实际落地时，对草案做了一个语义收敛：

- `DuplicateNodePolicy` 只作用于显式 `addNode()`。
- `addEdge()` 在内部“确保端点存在”时会复用已有节点，不会因为端点已存在而报错。

这样处理是必要的；否则只要多条边共享同一个端点，正常 DAG 构图就会被误判为“重复节点错误”。

## 目标

- 作为 `wolvrix` 的 `core` 基础组件落地，建议文件位置：
  - `wolvrix/include/core/toposort.hpp`
  - `wolvrix/lib/core/toposort.cpp`
- 支持用户传入可复制、可判断相等的自定义 `NodeType`。
- `addNode` 时自动去重，并支持“重复节点报错”开关。
- 支持 `addEdge(NodeType fromNode, NodeType toNode)`。
- 提供适合 100M 级节点的大规模高性能拓扑排序。
- 结果按“层”返回：外层是拓扑序层级，内层是同一层上的节点数组。

## 非目标

- 首版不支持删点、删边。
- 首版不保证同层节点的稳定顺序；如需稳定顺序，后续可加可选开关。
- 首版默认单线程构图、单线程排序，先把单机吞吐和内存模型做扎实。

## 建议 API

```cpp
namespace wolvrix {

enum class DuplicateNodePolicy {
    kIgnore,
    kError,
};

struct TopoSortOptions {
    DuplicateNodePolicy duplicateNodePolicy = DuplicateNodePolicy::kIgnore;
    bool throwOnCycle = true;
};

template <typename NodeType,
          typename Hash = std::hash<NodeType>,
          typename Eq = std::equal_to<NodeType>>
class TopoDag {
public:
    using NodeId = uint32_t;
    using EdgeOffset = uint64_t;

    explicit TopoDag(TopoSortOptions options = {});

    void reserveNodes(size_t n);
    void reserveEdges(size_t m);

    NodeId addNode(const NodeType& node);
    void addEdge(const NodeType& fromNode, const NodeType& toNode);

    size_t nodeCount() const;
    size_t edgeCount() const;

    // 执行拓扑排序，返回按层分组后的节点结果。
    std::vector<std::vector<NodeType>> toposort() const;
};

} // namespace wolvrix
```

## 行为约定

### 1. 节点去重

- 内部维护 `unordered_map<NodeType, NodeId, Hash, Eq>`。
- `addNode(node)`：
  - 若节点首次出现：分配新 `NodeId`，写入节点池。
  - 若节点重复出现且策略为 `kIgnore`：直接返回已有 `NodeId`。
  - 若节点重复出现且策略为 `kError`：抛出 `runtime_error`。

### 2. 加边

- `addEdge(fromNode, toNode)` 内部先调用 `addNode`，因此用户无需手动预注册节点。
- `fromNode == toNode` 时可直接视为自环；真正检测是否为 DAG，统一在 `toposort()` 阶段完成。
- 逻辑语义上要求边去重：多次添加同一条 `from -> to`，最终图中只保留一条边。
- 边去重不建议放在 `addEdge` 热路径中，而建议延迟到 `toposort()` 前统一完成。

### 3. 返回结果

- 对外语义：返回 `std::vector<std::vector<NodeType>>`。
- 结果示例：

```cpp
[
  [A, B],
  [C, D, E],
  [F]
]
```

- 含义：
  - 第 0 层节点入度为 0。
  - 第 1 层节点依赖于前面层。
  - 同一层节点彼此不存在未满足的前驱关系。

## 内部实现建议

### 总体思路：两阶段

为了兼顾“大规模构图”和“高性能排序”，组件建议分成两个阶段：

1. 构图阶段
   - 维护节点去重表。
   - 追加写入原始边列表 `rawEdges_`。

2. 排序阶段
   - 在 `toposort()` 内先对原始边做集中去重，再一次性转成 CSR 邻接结构。
   - 基于 CSR + Kahn 分层算法执行拓扑排序。

这样做的原因是：

- 构图阶段只做顺序 append，吞吐高。
- 边去重延迟到排序前统一处理，避免在构图阶段维护超大边哈希集合。
- 排序阶段使用连续内存，遍历局部性更好。
- 不需要在每个节点上维护大量小 `vector`，能显著降低 100M 级场景的碎片和分配器开销。

### 推荐数据结构

```cpp
std::vector<NodeType> nodes_;
std::unordered_map<NodeType, NodeId, Hash, Eq> nodeToId_;
std::vector<uint64_t> rawEdges_;
```

`toposort()` 内部临时构造：

```cpp
std::vector<EdgeOffset> rowOffsets; // size = nodeCount + 1
std::vector<NodeId> colIndices;     // size = edgeCount
std::vector<uint32_t> indegree;     // size = nodeCount
std::vector<NodeId> frontier;
std::vector<NodeId> nextFrontier;
```

### 为什么 `NodeId` 用 32 位

- 100M 节点远小于 `2^32`，`uint32_t` 足够。
- 边终点数组 `colIndices` 往往是最大内存块，使用 32 位能显著节省内存。
- 边偏移 `rowOffsets` 仍建议使用 `uint64_t`，因为边数可能超过 32 位范围。

## 拓扑排序算法草案

### 1. 边去重

建议把每条边编码为一个 64 位整数：

```cpp
uint64_t packed = (uint64_t(from) << 32) | uint64_t(to);
```

`addEdge()` 阶段只做 `rawEdges_.push_back(packed)`。  
`toposort()` 开始时，对 `rawEdges_` 做一次集中去重，得到唯一边集。

建议路线：

1. 首版直接对 `rawEdges_` 排序后 `unique`。
2. 若后续边规模继续增大，再替换为基数排序或并行排序实现。

这样做的好处是：

- `addEdge()` 仍然保持顺序 append，高吞吐。
- 边去重语义可以保证。
- 去重后再计算入度，避免重复边把入度虚增。

### 2. 构造 CSR

对“去重后的边集”做两遍线性扫描：

1. 统计每个节点的出度和入度。
2. 对出度做前缀和，生成 `rowOffsets`。
3. 再扫一遍唯一边集，把终点写入 `colIndices`。

时间复杂度 `O(V + E)`，空间复杂度 `O(V + E)`。

### 3. Kahn 分层拓扑排序

1. 找出所有入度为 0 的节点，作为第一层 `frontier`。
2. 处理当前层所有节点：
   - 依次扫描其所有出边。
   - 对终点执行 `--indegree[v]`。
   - 若某个终点入度降为 0，放入 `nextFrontier`。
3. 当前层处理结束后，把该层节点记入结果。
4. `frontier.swap(nextFrontier)`，继续下一层。
5. 若最终处理节点数小于 `nodeCount`，则图中存在环。

### 4. 结果组织

内部建议先保存：

```cpp
std::vector<NodeId> orderedIds;
std::vector<size_t> levelOffsets;
```

最后再一次性 materialize 为：

```cpp
std::vector<std::vector<NodeType>>
```

这样可以避免排序过程中频繁构造大量小 `vector<NodeType>`，把二维数组的构造推迟到最后一步。

## 性能要点

### 1. 预留容量

- 提供 `reserveNodes()` / `reserveEdges()`。
- 在超大图场景下，这两个接口非常重要，可以显著减少 rehash 和扩容成本。

### 2. 边去重不放在热路径

- 不建议在 `addEdge()` 上维护 `unordered_set<pair<NodeId, NodeId>>` 之类的在线去重结构。
- 对 100M 级图，在线去重通常会带来更高的哈希内存、更多随机访问和更差的构图吞吐。
- 更合理的方式是：构图阶段只收集边，排序阶段集中去重。

### 3. 排序阶段不再碰 `NodeType` 哈希

- `toposort()` 只操作 `NodeId`、`indegree`、CSR 邻接表。
- 这样可以把排序成本稳定在整数数组扫描上，而不是用户自定义对象的哈希和比较上。

### 4. 避免碎片化

- 不采用 `vector<vector<NodeId>> adjacency` 这种每点一个容器的布局。
- 统一转成 CSR，可显著减少内存碎片和 allocator 压力。

### 5. 结果延迟物化

- 排序内部先保存 `NodeId` 层级结果，最后再转换成 `NodeType` 二维数组。
- 对大 `NodeType` 场景，这一步可以后续进一步扩展为“返回 `NodeId` 视图 + 按需物化”。

## 多线程构图建议

### 结论

- 构图过程可以做多线程。
- 但不建议首选“多个线程同时写一个共享 `TopoDag` 实例”的接口形态。
- 对 100M 级节点，更推荐“每线程本地构图，最后统一 `finalize` 合并”的两阶段方案。

### 为什么不建议共享对象并发写入

如果直接把下面这类接口做成线程安全：

```cpp
dag.addNode(node);
dag.addEdge(from, to);
```

实现上通常需要：

- 一个支持并发插入和查重的全局节点表。
- 一个支持并发追加的全局边容器，或者额外的锁分片机制。
- 复杂的同步约束，确保构图阶段和排序阶段不会并发冲突。

问题在于：

- 节点自动去重本身就是热点，重复节点较多时锁竞争会明显上升。
- `NodeType` 的哈希与相等比较可能很重，并发下会进一步放大热点。
- 对超大图，随机哈希访问比顺序 append 更伤吞吐和缓存局部性。

因此，共享对象并发写入更适合作为“可选线程安全模式”，不适合作为主推荐路径。

### 推荐方案：并行本地构图 + finalize 合并

建议增加一个 builder 形态：

```cpp
template <typename NodeType,
          typename Hash = std::hash<NodeType>,
          typename Eq = std::equal_to<NodeType>>
class TopoDagBuilder {
public:
    class LocalBuilder {
    public:
        void addNode(const NodeType& node);
        void addEdge(const NodeType& from, const NodeType& to);
    };

    LocalBuilder createLocalBuilder();
    TopoDag<NodeType, Hash, Eq> finalize();
};
```

建议语义：

- 每个工作线程持有自己的 `LocalBuilder`。
- `LocalBuilder` 内部只做本地顺序 append，不做全局同步。
- 所有线程完成后，由 `finalize()` 串行或并行地合并所有本地数据，生成最终 `TopoDag`。

### `LocalBuilder` 内部建议

每个线程本地保存：

```cpp
std::vector<NodeType> localNodes;
std::vector<std::pair<NodeType, NodeType>> localEdges;
```

或在本地先保留更紧凑的中间表示，只要满足：

- 本地写入无锁。
- 最终可以统一做全局节点去重和边重映射。

### `finalize()` 建议流程

1. 汇总所有 `localNodes`，做一次全局节点去重，生成最终 `NodeId`。
2. 建立全局 `nodeToId_` 和 `nodes_`。
3. 扫描所有 `localEdges`，把 `NodeType` 边映射成 `(fromId, toId)`。
4. 把边打包为 `uint64_t`，集中去重。
5. 构造 CSR 邻接结构。
6. 执行后续 `toposort()`。

这个流程和单线程版本兼容，只是把“节点去重、边去重、CSR 构建”前移到了统一收敛阶段。

### 多线程构图的收益点

- 热路径只有线程本地 append，吞吐通常明显好于共享哈希表。
- 节点去重和边去重都可以集中处理，更容易做批量优化。
- 最终内存布局更容易保持规整，便于后续 CSR 构建和拓扑排序。

### 多线程构图的边界

- `finalize()` 会是一次全局同步点。
- 若 `NodeType` 很大，`localEdges` 直接存 `NodeType` 对可能带来较高临时内存占用。
- 如果后续要进一步优化，可继续演进为：
  - 本地节点表先做线程内去重
  - 本地边先做线程内去重
  - `finalize()` 改成分阶段并行 merge

### 首版建议

- 首版文档仍以单线程 `TopoDag` 为主接口。
- 如果确定业务上经常需要并行构图，建议直接设计 `TopoDagBuilder + LocalBuilder + finalize()`，而不是把共享 `TopoDag` 的单条 `addNode/addEdge` 做成重锁并发接口。

## 异常与错误处理

### 重复节点

- 由 `DuplicateNodePolicy` 控制。
- 建议默认 `kIgnore`，因为批量构图时更符合“自动去重”的直觉。

### 环检测

- 若 `processedNodeCount != nodeCount()`，说明存在环。
- 建议默认抛出 `runtime_error("toposort failed: graph contains cycle")`。
- 如后续需要更强诊断，可扩展返回剩余未清零入度节点数量，甚至输出一个小规模环样本。

## 首版落地建议

1. 新增 `wolvrix/include/core/toposort.hpp` 与 `wolvrix/lib/core/toposort.cpp`。
2. 先实现模板接口 + `NodeId/边打包去重/CSR/Kahn` 主路径。
3. 补一个小型文档示例和单元测试：
   - 重复节点去重
   - 重复节点报错
   - 重复边去重
   - 多层 DAG 拓扑结果
   - 自环 / 普通环报错
4. 若后续确实要冲击更大规模，再继续扩展：
   - 可选稳定层内顺序
   - 基数排序 / 并行排序版边去重
   - 并行构图 / 并行分层
   - `NodeId` 结果直出接口

## 本次实施结果

- 已完成 `core` 组件接线，`toposort.cpp` 已纳入 `wolvrix-lib`。
- 已新增 CTest 目标 `core-toposort`。
- 已执行：
  - `cmake --build wolvrix/build --target core-toposort -j4`
  - `ctest --test-dir wolvrix/build --output-on-failure -R '^core-toposort$'`
- 当前结果：`core-toposort` 通过。

## 简短结论

这个组件建议本质上做成一个“节点去重 + 原始边收集 + 排序前集中边去重 + CSR 冻结 + Kahn 分层”的 `core` 基础设施。  
它能直接满足 `NodeType` 去重、`addEdge`、`toposort`、二维层级结果这几个接口需求，同时也比较适合后续扩展到 100M 级节点场景。
