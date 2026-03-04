# RepCut Pass 实现文档

## 1. 概述

本文档描述如何在 grh-ir 上实现 RepCut 超图划分算法。Repcut 是一种将 RTL 电路划分为 k 个独立分区的算法，通过复制少量重叠逻辑来切断跨分区依赖。

### 1.1 前置条件

- 电路已经经过 `hier-flatten` pass 处理，成为单一平化图
- 电路已经经过 `strip-debug` pass 处理，移除了 debug 相关操作（kSystemTask, kDpicCall 等）
- 电路已经经过 `comb-loop-elim` pass 处理，消除了组合逻辑环

### 1.2 GRH IR 语义约定

**Sink 节点**（划分入口）：
- Output Values（`valueIsOutput = true`，含 inout 的 out/oe）
- kRegisterWritePort / kLatchWritePort / kMemoryWritePort

**Source 边界**（遍历停止点）：
- Input Values（`valueIsInput = true`，含 inout 的 in）
- kRegisterReadPort / kLatchReadPort
- kConstant

**关键差异**（与 Essent 实现对比）：
- **kMemoryReadPort 不是 Source 边界**！Memory 读口不作为截断点，因为 memory 读必须与写口同分区
- **kRegisterReadPort / kLatchReadPort 是 Source 边界**，其输出可跨分区被其他 sink 使用
- **组合逻辑锥穿过 kMemoryReadPort** 继续向上遍历，直到遇到真正的 Source 边界

**ASC (Atomic Sink Cluster)**：
- 不可分割的 sink 集合，同一 ASC 内的所有 sink 必须在同一分区
- 保证同一状态元素（register/latch/memory）的所有端口在同一分区内
- 构建规则见第 4.1 节

### 1.3 算法流程

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Flattened GRH  │ ──→ │  Build Trees    │ ──→ │  Build Pieces   │
│  Graph          │     │  (依赖树收集)    │     │  (节点聚类)      │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                         ↓
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Reconstruct    │ ←── │  KaHyPar        │ ←── │  Build HyperGraph│
│  Partitions     │     │  Partitioning   │     │  (超图构建)      │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

## 2. 核心数据结构

### 2.1 节点索引

```cpp
using NodeId = uint32_t;
static constexpr NodeId INVALID_NODE = std::numeric_limits<NodeId>::max();

// 将 OperationId 映射到连续的节点索引
std::unordered_map<OperationId, NodeId, OperationIdHash> opToNode_;
std::vector<OperationId> nodeToOp_;
```

### 2.2 ASC (Atomic Sink Cluster)

```cpp
struct ASC {
    std::vector<NodeId> sinks;                           // 该 ASC 内的所有 sink 节点索引
    std::unordered_set<NodeId> combOps;                  // 逻辑锥内的组合操作
    std::unordered_set<ValueId, ValueIdHash> values;     // 逻辑锥内的所有 value
    uint32_t weight = 0;                                 // 总权重（用于负载均衡）
};

std::vector<ASC> ascs_;                                // asc_id -> ASC
std::unordered_map<NodeId, AscId> sinkToAsc_;          // sink_node -> asc_id
```

### 2.3 Piece 结构

```cpp
// Piece = 具有相同 ASC ID 集合的连通节点
// 注意：这里用 ASC ID 替代了 Essent 实现中的 Tree ID
using PieceId = uint32_t;
std::vector<std::unordered_set<NodeId>> pieces_;       // piece_id -> node_ids
std::vector<PieceId> nodeToPiece_;                     // node_id -> piece_id
std::vector<std::vector<AscId>> pieceToAscs_;          // piece_id -> asc_ids
```

### 2.4 超图结构

```cpp
struct HyperGraph {
    // 超图顶点 = ASCs（不可分割的原子单位）
    // 注意：顶点对应 ASC，而不是单个 sink
    std::vector<uint32_t> nodeWeights;                 // asc_id -> weight
    
    // 超边 = Non-ASC Pieces（被多个 ASC 共享的组合逻辑）
    struct HyperEdge {
        std::vector<AscId> nodes;                      // 连接的 ASC IDs
        uint32_t weight;
    };
    std::vector<HyperEdge> edges;
};
```

## 3. 算法步骤详解

### 3.1 Step 1: 识别 Sink 节点并构建 ASC（buildASCs）

**目标**：识别所有 sink 节点，构建 ASC（Atomic Sink Cluster），为每个 ASC 收集组合逻辑锥

**Sink 节点定义（GRH IR 口径）**：
| 类型 | 定义 |
|:---|:---|
| Output Value | Graph 的输出端口 Value（`valueIsOutput = true`，包含 inout 的 out 分量） |
| kRegisterWritePort | 寄存器写端口 |
| kLatchWritePort | 锁存器写端口 |
| kMemoryWritePort | 存储器写端口 |

**Source 节点定义（GRH IR 口径，遍历边界）**：
| 类型 | 定义 |
|:---|:---|
| Input Value | Graph 的输入端口 Value（`valueIsInput = true`，包含 inout 的 in 分量） |
| kRegisterReadPort | 寄存器读端口 |
| kLatchReadPort | 锁存器读端口 |
| kConstant | 常量 Operation |

**重要区别**：
- **kMemoryReadPort 不是 Source 边界**！memory 读口不作为截断点，因为 memory 读必须与写口同分区（通过 ASC 机制保证）
- **kRegisterReadPort / kLatchReadPort 是 Source 边界**，其输出可跨分区被其他 sink 使用
- 组合逻辑锥穿过 kMemoryReadPort 继续向上遍历

**ASC 构建规则**：
1. **写口合并规则**：共享同一 `regSymbol`/`latchSymbol`/`memSymbol` 的 write port 必须同 ASC
2. **mem 不可分规则**：若某个 sink 的组合逻辑锥中包含指向某个 kMemory 的 kMemoryReadPort，则该 sink 与该 memory 的所有 kMemoryWritePort 必须归并到同一个 ASC

**算法**：
```cpp
void buildASCs() {
    // 1. 识别所有 sink 节点
    std::vector<NodeId> allSinks;
    
    // - Output Values (包括 inout 的 out/oe)
    for (const auto& port : graph_->outputPorts()) {
        sinkValues_.push_back(port.value);
    }
    for (const auto& port : graph_->inoutPorts()) {
        sinkValues_.push_back(port.out);
        sinkValues_.push_back(port.oe);
    }
    
    // - Write Port Operations
    for (const auto opId : graph_->operations()) {
        Operation op = graph_->getOperation(opId);
        if (isSinkOpKind(op.kind())) {
            allSinks.push_back(opToNode_[opId]);
        }
    }
    
    // 2. 使用并查集合并 ASC
    DisjointSet dsu(allSinks.size());
    
    // 索引：symbol -> sink indices
    std::unordered_map<std::string, std::vector<size_t>> regWriteSinks;
    std::unordered_map<std::string, std::vector<size_t>> latchWriteSinks;
    std::unordered_map<std::string, std::vector<size_t>> memWriteSinks;
    
    for (size_t i = 0; i < allSinks.size(); ++i) {
        Operation op = graph_->getOperation(nodeToOp_[allSinks[i]]);
        if (auto sym = getAttrString(op, "regSymbol")) {
            regWriteSinks[*sym].push_back(i);
        } else if (auto sym = getAttrString(op, "latchSymbol")) {
            latchWriteSinks[*sym].push_back(i);
        } else if (auto sym = getAttrString(op, "memSymbol")) {
            memWriteSinks[*sym].push_back(i);
        }
    }
    
    // 写口合并规则
    auto unionGroup = [&](const auto& groups) {
        for (const auto& [sym, indices] : groups) {
            if (indices.size() < 2) continue;
            size_t root = indices[0];
            for (size_t i = 1; i < indices.size(); ++i) {
                dsu.unite(root, indices[i]);
            }
        }
    };
    unionGroup(regWriteSinks);
    unionGroup(latchWriteSinks);
    unionGroup(memWriteSinks);
    
    // mem 不可分规则：先为每个 sink 收集逻辑锥中的 memSymbol
    std::vector<std::unordered_set<std::string>> sinkMemSymbols(allSinks.size());
    for (size_t i = 0; i < allSinks.size(); ++i) {
        collectConeMemSymbols(allSinks[i], sinkMemSymbols[i]);
        // 与对应的 memory write port 合并
        for (const auto& memSym : sinkMemSymbols[i]) {
            auto it = memWriteSinks.find(memSym);
            if (it != memWriteSinks.end()) {
                for (size_t writeIdx : it->second) {
                    dsu.unite(i, writeIdx);
                }
            }
        }
    }
    
    // 3. 生成 ASC 结构
    std::unordered_map<size_t, AscId> ascIdByRoot;
    for (size_t i = 0; i < allSinks.size(); ++i) {
        size_t root = dsu.find(i);
        auto it = ascIdByRoot.find(root);
        if (it == ascIdByRoot.end()) {
            AscId newId = ascs_.size();
            ascIdByRoot[root] = newId;
            ascs_.push_back(ASC{});
            it = ascIdByRoot.find(root);
        }
        ascs_[it->second].sinks.push_back(allSinks[i]);
        sinkToAsc_[allSinks[i]] = it->second;
    }
    
    // 4. 为每个 ASC 收集组合逻辑锥
    for (AscId aid = 0; aid < ascs_.size(); ++aid) {
        for (NodeId sink : ascs_[aid].sinks) {
            collectCone(sink, ascs_[aid]);
        }
    }
}

void collectConeMemSymbols(NodeId sink, std::unordered_set<std::string>& memSymbols) {
    // 仅收集逻辑锥中出现的 kMemoryReadPort 的 memSymbol
    // 不深入遍历，仅用于 ASC 合并决策
    std::unordered_set<NodeId> visited;
    std::function<void(ValueId)> traverse = [&](ValueId value) {
        if (isSourceValue(value)) return;
        
        OperationId defOp = graph_->valueDef(value);
        if (!defOp.valid()) return;
        
        NodeId node = opToNode_[defOp];
        if (visited.count(node)) return;
        visited.insert(node);
        
        Operation op = graph_->getOperation(defOp);
        if (op.kind() == kMemoryReadPort) {
            if (auto sym = getAttrString(op, "memSymbol")) {
                memSymbols.insert(*sym);
            }
        }
        
        if (isCombOp(op)) {
            for (const auto operand : op.operands()) {
                traverse(operand);
            }
        }
    };
    
    // 从 sink 的输入开始遍历
    Operation sinkOp = graph_->getOperation(nodeToOp_[sink]);
    for (const auto operand : sinkOp.operands()) {
        traverse(operand);
    }
}

void collectCone(NodeId sink, ASC& asc) {
    std::function<void(ValueId)> traverse = [&](ValueId value) {
        if (isSourceValue(value)) {
            asc.values.insert(value);
            return;
        }
        
        OperationId defOp = graph_->valueDef(value);
        if (!defOp.valid()) return;
        
        NodeId node = opToNode_[defOp];
        if (asc.combOps.count(node)) return;  // 已访问
        
        Operation op = graph_->getOperation(defOp);
        if (!isCombOp(op)) return;
        
        asc.combOps.insert(node);
        asc.values.insert(value);
        
        for (const auto operand : op.operands()) {
            traverse(operand);
        }
    };
    
    // 从 sink 的输入开始遍历
    Operation sinkOp = graph_->getOperation(nodeToOp_[sink]);
    for (const auto operand : sinkOp.operands()) {
        traverse(operand);
    }
}

bool isSinkOpKind(OperationKind kind) {
    switch (kind) {
        case kRegisterWritePort:
        case kLatchWritePort:
        case kMemoryWritePort:
            return true;
        default:
            return false;
    }
}

bool isSourceValue(ValueId value) {
    // Input Value（包括普通 input 和 inout 的 in 分量）
    if (graph_->valueIsInput(value)) return true;
    
    OperationId defOp = graph_->valueDef(value);
    if (!defOp.valid()) return true;
    
    Operation op = graph_->getOperation(defOp);
    if (op.kind() == kConstant) return true;
    if (op.kind() == kRegisterReadPort) return true;
    if (op.kind() == kLatchReadPort) return true;
    
    // kMemoryReadPort 不是 Source 边界
    return false;
}

bool isCombOp(const Operation& op) {
    if (opHasEvents(op)) return false;
    
    switch (op.kind()) {
        case kConstant:
        case kAdd: case kSub: case kMul: case kDiv: case kMod:
        case kEq: case kNe: case kLt: case kLe: case kGt: case kGe:
        case kAnd: case kOr: case kXor: case kXnor: case kNot:
        case kLogicAnd: case kLogicOr: case kLogicNot:
        case kReduceAnd: case kReduceOr: case kReduceXor:
        case kReduceNor: case kReduceNand: case kReduceXnor:
        case kShl: case kLShr: case kAShr:
        case kMux: case kAssign: case kConcat: case kReplicate:
        case kSliceStatic: case kSliceDynamic: case kSliceArray:
        case kMemoryReadPort:  // 不是 source 边界，但作为组合逻辑节点
            return true;
        case kSystemFunction: {
            auto sideEffects = getAttrBool(op, "hasSideEffects");
            return !sideEffects || !*sideEffects;
        }
        default:
            return false;
    }
}
```

**关键规则**：
- **超图顶点 = ASC**，而不是单个 sink
- ASC 是不可分割的原子单位，同一 ASC 的所有 sink 必须在同一分区
- 写口合并规则和 mem 不可分规则保证状态元素完整性
- kMemoryReadPort 不是 Source 边界，穿过它继续遍历

### 3.2 Step 2: 构建 Pieces（initPieces）

**目标**：将属于相同 ASC ID 集合的连通节点聚类为 piece

**与 Essent 实现的区别**：
- Essent：基于 Tree（单个 sink）构建 pieces
- **本实现：基于 ASC（多个 sink 的集合）构建 pieces**

**算法**：
```cpp
void initPieces() {
    // 1. 建立 node -> ASCs 映射（节点属于哪些 ASC 的逻辑锥）
    nodeToAscs_.resize(numNodes_);
    for (AscId aid = 0; aid < ascs_.size(); ++aid) {
        // ASC 的所有 sink 节点
        for (NodeId sink : ascs_[aid].sinks) {
            nodeToAscs_[sink].push_back(aid);
        }
        // ASC 的组合逻辑锥内的所有节点
        for (NodeId node : ascs_[aid].combOps) {
            nodeToAscs_[node].push_back(aid);
        }
    }
    
    // 2. 为每个 ASC 创建 piece（ASC Piece）
    nodeToPiece_.assign(numNodes_, INVALID_PIECE);
    for (AscId aid = 0; aid < ascs_.size(); ++aid) {
        pieces_.emplace_back();
        pieceToAscs_.emplace_back();
        // 从 ASC 的第一个 sink 开始扩展
        findPiece(ascs_[aid].sinks[0], aid);
    }
    
    // 3. 为剩余节点创建 pieces（Non-ASC Pieces）
    for (NodeId node = 0; node < numNodes_; ++node) {
        if (nodeToPiece_[node] == INVALID_PIECE) {
            PieceId pid = pieces_.size();
            pieces_.emplace_back();
            pieceToAscs_.emplace_back();
            findPiece(node, pid);
        }
    }
}

void findPiece(NodeId seed, PieceId pid) {
    if (nodeToPiece_[seed] != INVALID_PIECE) return;
    
    pieces_[pid].insert(seed);
    nodeToPiece_[seed] = pid;
    pieceToAscs_[pid] = nodeToAscs_[seed];
    
    // 找到连通的、具有相同 ASC 集合的节点
    for (NodeId neighbor : getNeighbors(seed)) {
        if (nodeToPiece_[neighbor] == INVALID_PIECE && 
            nodeToAscs_[neighbor] == nodeToAscs_[seed]) {
            findPiece(neighbor, pid);
        }
    }
}
```

**Piece 分类**：
- **ASC Pieces**：`pieces_[0..ascs_.size()-1]`，每个对应一个 ASC，包含 ASC 的所有 sink 和其逻辑锥
- **Non-ASC Pieces**：`pieces_[ascs_.size()..]`，被多个 ASC 共享的组合逻辑，将变成超边

### 3.3 Step 3: 计算节点权重（calculateNodeWeight）

**目标**：为每个 operation 计算计算代价

**两种可选方案**：

#### 方案 A：简化权重表（参考 hrbcut）
实现简单，适用于快速原型：

```cpp
uint32_t calculateNodeWeight(NodeId node) {
    if (nodeWeights_[node] != UINT32_MAX) {
        return nodeWeights_[node];
    }
    
    Operation op = graph_->getOperation(nodeToOp_[node]);
    uint32_t weight = 0;
    
    switch (op.kind()) {
        case kConstant:
            weight = 1;
            break;
        case kAdd: case kSub:
            weight = 2;
            break;
        case kMul:
            weight = 4;
            break;
        case kDiv: case kMod:
            weight = 6;
            break;
        case kMux: {
            int32_t width = getResultWidth(op);
            int32_t nWords = (width + 63) / 64;
            weight = nWords * 6;  // 来自 Essent 经验值
            break;
        }
        // ... 其他操作类型
        default:
            weight = 1;
    }
    
    nodeWeights_[node] = weight;
    return weight;
}
```

#### 方案 B：Essent/RepCut 原始模型（更精确）
基于 FIRRTL IR 的启发式模型，参考 `tmp/essent/src/main/scala/ThreadPartitioner.scala`：

```cpp
uint32_t calculateNodeWeight(NodeId node) {
    Operation op = graph_->getOperation(nodeToOp_[node]);
    
    switch (op.kind()) {
        // 算术运算（基于位宽）
        case kAdd: case kSub: {
            int32_t width = getMaxOperandWidth(op);
            if (width <= 64) weight = 2;
            else if (width <= 128) weight = 8;
            else if (width <= 256) weight = 16;
            else weight = 30;
            break;
        }
        
        case kMul: {
            int32_t width = getMaxOperandWidth(op);
            int32_t minWidth = getMinOperandWidth(op);
            if (width <= 64) {
                if (minWidth <= 8) weight = 1;
                else if (minWidth <= 16) weight = 9;
                else weight = 25;
            } else {
                weight = 25;
            }
            break;
        }
        
        // 比较运算
        case kEq: case kNe: case kLt: case kLe: case kGt: case kGe: {
            int32_t width = getMaxOperandWidth(op);
            if (width <= 64) weight = 1;
            else if (width <= 128) weight = 3;
            else weight = 5;
            break;
        }
        
        // 移位运算
        case kShl: case kLShr: case kAShr:
            weight = 2;
            break;
            
        // 位运算（按字计算）
        case kAnd: case kOr: case kXor: case kNot: {
            int32_t width = getResultWidth(op);
            int32_t nWords = (width + 63) / 64;
            weight = (width <= 64) ? 2 : nWords * 2;
            break;
        }
        
        // Mux（按字计算）
        case kMux: {
            int32_t width = getResultWidth(op);
            int32_t nWords = (width + 63) / 64;
            weight = nWords * 6;  // Essent 经验值
            break;
        }
        
        // 常量（基于位宽）
        case kConstant: {
            int32_t width = getResultWidth(op);
            weight = width;  // 字面量权重 = 位宽
            break;
        }
        
        // 寄存器/锁存器/内存写端口
        case kRegisterWritePort:
        case kLatchWritePort: {
            int32_t width = getOperandWidth(op, /*data operand*/ 1);
            if (width <= 64) weight = 2;
            else weight = (width + 63) / 64 + 1;
            break;
        }
        case kMemoryWritePort: {
            // MemWrite = 1 + wrEn权重 + wrData权重
            weight = 1 + calculateExprWeight(op.operands()[0]) 
                       + calculateExprWeight(op.operands()[1]);
            break;
        }
        
        // 引用类型（依赖已在别处计算）
        case kXMRRead:
            weight = 0;
            break;
            
        default:
            weight = 2;
    }
    
    return weight;
}

// 辅助函数：计算表达式权重（用于递归计算子表达式）
uint32_t calculateExprWeight(ValueId value) {
    OperationId defOp = graph_->valueDef(value);
    if (!defOp.valid()) return 0;
    
    Operation op = graph_->getOperation(defOp);
    
    // Reference 类型权重为 0（依赖处理）
    if (op.kind() == kConstant) {
        int32_t width = graph_->valueWidth(value);
        return width;
    }
    
    // 递归计算操作权重
    return calculateNodeWeight(opToNode_[defOp]);
}
```

**建议**：
- 初期实现可使用**方案 A**（简化版）
- 后期优化可切换到**方案 B**（Essent 原始模型），以获得更精确的负载均衡

### 3.4 Step 4: 计算 Piece 权重（calculatePieceWeight）

**目标**：递归累加 piece 内部所有节点的代价

```cpp
uint32_t calculatePieceWeight(PieceId pid) {
    const auto& piece = pieces_[pid];
    
    // 找出 piece 内部的 sink 节点（在 piece 内无出边）
    std::vector<NodeId> pieceSinks;
    for (NodeId node : piece) {
        bool hasOutEdgeInPiece = false;
        for (NodeId succ : outNeighbors_[node]) {
            if (piece.count(succ)) {
                hasOutEdgeInPiece = true;
                break;
            }
        }
        if (!hasOutEdgeInPiece) {
            pieceSinks.push_back(node);
        }
    }
    
    // 从每个内部 sink 递归收集权重
    std::unordered_set<NodeId> visited;
    std::function<uint32_t(NodeId)> stmtWeight = [&](NodeId node) -> uint32_t {
        if (visited.count(node)) return 0;
        visited.insert(node);
        
        uint32_t w = calculateNodeWeight(node);
        
        // 累加依赖的权重
        for (NodeId pred : inNeighbors_[node]) {
            if (piece.count(pred)) {
                w += stmtWeight(pred);
            }
        }
        return w;
    };
    
    uint32_t totalWeight = 0;
    for (NodeId sink : pieceSinks) {
        totalWeight += stmtWeight(sink);
    }
    
    // KaHyPar 要求权重至少为 1
    return std::max(totalWeight, 1u);
}
```

### 3.5 Step 5: 构建超图（buildHyperGraph）

**目标**：构建用于 KaHyPar 的超图

**关键设计**：
- **超图顶点 = ASCs**（不可分割的原子单位）
- **超边 = Non-ASC Pieces**（被多个 ASC 共享的组合逻辑）

```cpp
void buildHyperGraph() {
    // 1. 计算所有 piece 的权重
    std::vector<uint32_t> pieceWeights;
    pieceWeights.reserve(pieces_.size());
    for (PieceId pid = 0; pid < pieces_.size(); ++pid) {
        pieceWeights.push_back(calculatePieceWeight(pid));
    }
    
    // 2. 计算每个 piece 连接的 ASC 数量（pin count）
    std::vector<uint32_t> piecePinCount;
    piecePinCount.reserve(pieces_.size());
    for (PieceId pid = 0; pid < pieces_.size(); ++pid) {
        // 取 piece 中任意节点查其 ASC 集合
        NodeId anyNode = *pieces_[pid].begin();
        piecePinCount.push_back(nodeToAscs_[anyNode].size());
    }
    
    // 3. 添加超图顶点（对应 ASC Pieces）
    // 注意：顶点对应 ASC，而不是单个 sink
    for (AscId aid = 0; aid < ascs_.size(); ++aid) {
        uint32_t weight = pieceWeights[aid];
        
        // 收集与 ASC 中节点相连的其他 pieces
        std::unordered_set<PieceId> connectPieces;
        for (NodeId node : ascs_[aid].sinks) {
            connectPieces.insert(nodeToPiece_[node]);
        }
        for (NodeId node : ascs_[aid].combOps) {
            connectPieces.insert(nodeToPiece_[node]);
        }
        connectPieces.erase(aid);  // 排除自身
        
        // 分摊祖先 pieces 的权重
        uint32_t分摊Weight = 0;
        for (PieceId pid : connectPieces) {
            uint32_t pinCount = piecePinCount[pid];
            if (pinCount > 0) {
                分摊Weight += pieceWeights[pid] / pinCount;
            }
        }
        
        hg_.nodeWeights.push_back(weight + 分摊Weight);
    }
    
    // 4. 添加超边（对应 Non-ASC Pieces）
    // 这些 pieces 被多个 ASC 共享，成为超边
    for (PieceId pid = ascs_.size(); pid < pieces_.size(); ++pid) {
        HyperEdge edge;
        edge.weight = pieceWeights[pid];
        
        // 该 piece 连接到哪些 ASC
        NodeId anyNode = *pieces_[pid].begin();
        edge.nodes = nodeToAscs_[anyNode];  // ASC IDs
        
        if (!edge.nodes.empty()) {
            hg_.edges.push_back(std::move(edge));
        }
    }
}
```

### 3.6 Step 6: 输出 hMETIS 格式

```cpp
void writeTohMetis(const std::string& filename) {
    std::ofstream file(filename);
    
    // Header: <边数> <顶点数> <格式>
    // 格式 11 表示带权重的图
    file << hg_.edges.size() << " " << hg_.nodeWeights.size() << " 11\n";
    
    // 超边（每条一行）
    for (const auto& edge : hg_.edges) {
        file << edge.weight;
        // hMETIS 使用 1-indexed
        for (AscId aid : edge.nodes) {
            file << " " << (aid + 1);
        }
        file << "\n";
    }
    
    // 顶点权重（每个一行）
    for (uint32_t weight : hg_.nodeWeights) {
        file << weight << "\n";
    }
}
```

### 3.7 Step 7: 调用 KaHyPar

```cpp
void runKaHyPar(int desiredParts, const std::string& hmetisFile) {
    std::string configFile = outputDir_ + "/KaHyPar.config";
    writeKaHyParConfig(configFile);
    
    std::vector<std::string> cmd = {
        "KaHyPar",
        "-h", hmetisFile,
        "-k", std::to_string(desiredParts),
        "-e", "0.015",  // imbalance factor
        "-p", configFile,
        "--seed", "-1",
        "-w", "true",
        "--mode", "direct",
        "--objective", "km1"
    };
    
    // 执行命令
    int result = std::system(join(cmd, " ").c_str());
    if (result != 0) {
        throw std::runtime_error("KaHyPar failed");
    }
}
```

### 3.8 Step 8: 解析划分结果并重建分区

```cpp
void parsePartitionResult(const std::string& resultFile) {
    std::ifstream file(resultFile);
    std::vector<int> partResult;
    
    std::string line;
    while (std::getline(file, line)) {
        partResult.push_back(std::stoi(line));
    }
    
    // 重建分区
    int numParts = *std::max_element(partResult.begin(), partResult.end()) + 1;
    partitions_.resize(numParts);
    
    // 每个超图顶点对应一个 ASC，将其所有成员加入对应分区
    for (size_t i = 0; i < partResult.size(); ++i) {
        if (i < ascs_.size()) {
            int partId = partResult[i];
            ASC& asc = ascs_[i];
            
            // 添加 ASC 的所有 sink 节点
            for (NodeId sink : asc.sinks) {
                partitions_[partId].insert(sink);
            }
            
            // 添加 ASC 逻辑锥内的所有组合操作
            for (NodeId node : asc.combOps) {
                partitions_[partId].insert(node);
            }
        }
    }
}
```

## 4. 分区重建

### 4.1 创建分区子图与跨分区端口

本节描述如何基于 ASC 划分结果创建分区子图，并处理跨分区访问的 Source 节点。

基于 ASC 划分结果创建分区子图：

```cpp
void createPartitionGraphs() {
    // 1. 确定每个 ASC 属于哪个分区（基于超图划分结果）
    // partitionResult[i] = ASC i 被分配到的分区 ID
    std::vector<uint32_t> ascPartition = parsePartitionResult(...);
    
    // 2. 确定每个原始操作属于哪个分区
    std::unordered_map<OperationId, uint32_t, OperationIdHash> opPartition;
    
    // ASC 中的所有 sink 节点和其逻辑锥中的组合操作
    for (AscId aid = 0; aid < ascs_.size(); ++aid) {
        uint32_t pid = ascPartition[aid];
        
        // ASC 的所有 sink 节点（NodeId 是 sink 节点索引）
        for (NodeId sinkNode : ascs_[aid].sinks) {
            opPartition[nodeToOp_[sinkNode]] = pid;
        }
        
        // ASC 逻辑锥中的所有组合操作
        for (NodeId node : ascs_[aid].combOps) {
            opPartition[nodeToOp_[node]] = pid;
        }
    }
    
    // 3. 状态元素处理：kRegister/kLatch/kMemory 必须与其所有端口同分区
    // 根据 write port 确定每个状态元素所属分区
    std::unordered_map<std::string, uint32_t> regPartition;
    std::unordered_map<std::string, uint32_t> latchPartition;
    std::unordered_map<std::string, uint32_t> memPartition;
    
    for (AscId aid = 0; aid < ascs_.size(); ++aid) {
        uint32_t pid = ascPartition[aid];
        for (NodeId sinkNode : ascs_[aid].sinks) {
            Operation op = graph_->getOperation(nodeToOp_[sinkNode]);
            if (auto sym = getAttrString(op, "regSymbol")) {
                regPartition[*sym] = pid;
            } else if (auto sym = getAttrString(op, "latchSymbol")) {
                latchPartition[*sym] = pid;
            } else if (auto sym = getAttrString(op, "memSymbol")) {
                memPartition[*sym] = pid;
            }
        }
    }
    
    // 收集所有状态元素信息
    struct StorageInfo {
        OperationId declOp = OperationId::invalid();
        std::vector<OperationId> readPorts;
        std::vector<OperationId> writePorts;
    };
    std::unordered_map<std::string, StorageInfo> regInfos, latchInfos, memInfos;
    
    for (const auto opId : graph_->operations()) {
        Operation op = graph_->getOperation(opId);
        std::string sym;
        switch (op.kind()) {
            case kRegister:
                sym = std::string(op.symbolText());
                if (!sym.empty()) regInfos[sym].declOp = opId;
                break;
            case kRegisterReadPort:
                if (auto s = getAttrString(op, "regSymbol")) 
                    regInfos[*s].readPorts.push_back(opId);
                break;
            case kRegisterWritePort:
                if (auto s = getAttrString(op, "regSymbol"))
                    regInfos[*s].writePorts.push_back(opId);
                break;
            // latch 和 memory 类似...
        }
    }
    
    // 分配状态元素到对应分区
    auto assignStorage = [&](const auto& infos, const auto& partMap) {
        for (const auto& [sym, info] : infos) {
            auto it = partMap.find(sym);
            if (it == partMap.end()) continue;
            uint32_t pid = it->second;
            if (info.declOp.valid()) opPartition[info.declOp] = pid;
            for (auto rp : info.readPorts) opPartition[rp] = pid;
            for (auto wp : info.writePorts) opPartition[wp] = pid;
        }
    };
    assignStorage(regInfos, regPartition);
    assignStorage(latchInfos, latchPartition);
    assignStorage(memInfos, memPartition);
    
    // 4. 确定跨分区 Value（需要添加端口）
    // 根据 hrbcut-pass-plan.md 的语义：
    // - kRegisterReadPort / kLatchReadPort 的结果**允许跨分区使用**
    // - kMemoryReadPort 的结果**不允许**跨分区使用（已由 ASC 保证同分区）
    // - Input Value 也可能需要在分区间传递
    
    struct CrossPartitionValue {
        ValueId value;
        uint32_t srcPart;    // 源分区
        uint32_t dstPart;    // 目标分区
        std::string baseName; // 用于生成端口名
    };
    std::vector<CrossPartitionValue> crossValues;
    
    // 收集所有跨分区的 value
    std::unordered_map<ValueId, uint32_t, ValueIdHash> valueDefPartition;
    for (const auto& [opId, pid] : opPartition) {
        Operation op = graph_->getOperation(opId);
        for (ValueId result : op.results()) {
            valueDefPartition[result] = pid;
        }
    }
    
    for (const auto& [value, defPart] : valueDefPartition) {
        Value val = graph_->getValue(value);
        OperationId defOpId = val.definingOp();
        
        for (const auto& user : val.users()) {
            auto it = opPartition.find(user.operation);
            if (it == opPartition.end()) continue;
            uint32_t usePart = it->second;
            
            if (usePart != defPart) {
                // 检查是否允许跨分区
                bool allowCross = false;
                std::string baseName;
                
                if (defOpId.valid()) {
                    Operation defOp = graph_->getOperation(defOpId);
                    // kRegisterReadPort / kLatchReadPort 允许跨分区
                    if (defOp.kind() == kRegisterReadPort) {
                        allowCross = true;
                        baseName = "repcut_regread_" + std::string(val.symbolText());
                    } else if (defOp.kind() == kLatchReadPort) {
                        allowCross = true;
                        baseName = "repcut_latchread_" + std::string(val.symbolText());
                    }
                    // kMemoryReadPort 不允许跨分区（应该已由 ASC 保证同分区）
                } else if (val.isInput() || val.isInout()) {
                    // Input Value 或 inout 的 in 分量跨分区使用
                    allowCross = true;
                    if (val.isInout()) {
                        baseName = "repcut_inout_" + std::string(val.symbolText());
                    } else {
                        baseName = "repcut_input_" + std::string(val.symbolText());
                    }
                }
                
                if (allowCross) {
                    crossValues.push_back({value, defPart, usePart, baseName});
                } else {
                    // 不应该出现的情况，报告警告
                    warning("Value crosses partition but is not allowed: " + 
                            std::string(val.symbolText()));
                }
            }
        }
    }
    
    // 5. 为每个分区创建子图
    std::vector<std::unique_ptr<Graph>> partGraphs;
    for (uint32_t pid = 0; pid < partitionCount_; ++pid) {
        std::string partName = targetGraph_->symbol() + "_part" + std::to_string(pid);
        Graph& partGraph = design().cloneGraph(targetGraph_->symbol(), partName);
        
        // 清理原有端口
        for (const auto& port : partGraph.inputPorts()) {
            partGraph.removeInputPort(port.name);
        }
        for (const auto& port : partGraph.outputPorts()) {
            partGraph.removeOutputPort(port.name);
        }
        
        // 确定该分区需要保留的操作
        std::unordered_set<OperationId, OperationIdHash> keepOps;
        for (const auto& [opId, p] : opPartition) {
            if (p == pid) keepOps.insert(opId);
        }
        
        // 删除不需要的操作
        for (const auto opId : partGraph.operations()) {
            if (!keepOps.count(opId)) {
                partGraph.eraseOpUnchecked(opId);
            }
        }
        
        partGraphs.push_back(std::move(partGraph));
    }
    
    // 6. 添加跨分区连接端口
    // 为每个跨分区 value 在源分区创建输出端口，在目标分区创建输入端口
    // 端口名称带有 "repcut" 标签，便于识别
    for (const auto& cv : crossValues) {
        Graph& srcGraph = *partGraphs[cv.srcPart];
        Graph& dstGraph = *partGraphs[cv.dstPart];
        
        // 在源分区创建输出端口
        ValueInfo info = captureValueInfo(*graph_, cv.value);
        std::string outPortName = uniquePortName(srcGraph, "repcut_out_" + cv.baseName);
        SymbolId outSym = internUniqueSymbol(srcGraph, outPortName);
        ValueId srcValue = srcGraph.findValue(info.symbol);
        if (srcValue.valid()) {
            srcGraph.bindOutputPort(outPortName, srcValue);
        }
        
        // 在目标分区创建输入端口
        std::string inPortName = uniquePortName(dstGraph, "repcut_in_" + cv.baseName);
        SymbolId inSym = internUniqueSymbol(dstGraph, inPortName);
        ValueId dstValue = dstGraph.createValue(inSym, info.width, info.isSigned, info.type);
        dstGraph.bindInputPort(inPortName, dstValue);
        
        // 记录映射关系，用于顶层模块连接
        crossPartitionLinks_.push_back({
            cv.srcPart, outPortName,
            cv.dstPart, inPortName,
            info
        });
    }
}
```

### 4.2 Source 节点跨分区访问处理

**问题背景**：
- **kRegisterReadPort / kLatchReadPort** 是 Source 边界，但它们的**结果可以跨分区使用**
- **Input Value**（包括 **inout 的 in 分量**）也是 Source，如果只在部分分区使用，需要传递到其他分区
- **kMemoryReadPort 的结果不允许跨分区使用**（由 ASC 保证同分区）

**处理策略**：

```
分区 A (有寄存器 R)          分区 B (使用 R)
┌─────────────────┐         ┌─────────────────┐
│  kRegister      │         │                 │
│     ↓           │         │   [输入端口]    │
│  kRegisterReadPort│       │       ↓         │
│     ↓           │         │   组合逻辑...   │
│ [输出端口] ─────┼────────→│                 │
└─────────────────┘         └─────────────────┘
```

**具体步骤**：

1. **识别跨分区 Source Value**：
   - 遍历所有 value 的使用者（users）
   - 如果定义分区和使用分区不同，且是允许跨分区的类型（kRegisterReadPort/kLatchReadPort/Input/inout.in），则标记为跨分区 value

2. **创建端口**：
   - **源分区**：创建**输出端口**（`bindOutputPort`），连接到 source value
   - **目标分区**：创建**输入端口**（`bindInputPort`），创建新的 value 作为端口 value

3. **顶层模块连接**：
   - 创建新的顶层模块，实例化所有分区子模块
   - 将源分区的输出端口连接到目标分区的输入端口

**示例代码（顶层模块构建）**：

```cpp
void buildTopModule() {
    // 1. 创建顶层模块
    Graph& top = design().createGraph(targetGraph_->symbol());
    
    // 2. 重建原始输入输出端口
    for (const auto& port : graph_->inputPorts()) {
        ValueInfo info = captureValueInfo(*graph_, port.value);
        SymbolId sym = internUniqueSymbol(top, info.symbol);
        ValueId v = top.createValue(sym, info.width, info.isSigned, info.type);
        top.bindInputPort(port.name, v);
    }
    for (const auto& port : graph_->outputPorts()) {
        ValueInfo info = captureValueInfo(*graph_, port.value);
        SymbolId sym = internUniqueSymbol(top, info.symbol);
        ValueId v = top.createValue(sym, info.width, info.isSigned, info.type);
        top.bindOutputPort(port.name, v);
    }
    
    // 3. 实例化分区子模块
    std::vector<OperationId> partInstances;
    for (uint32_t pid = 0; pid < partitionCount_; ++pid) {
        std::string partName = targetGraph_->symbol() + "_part" + std::to_string(pid);
        Graph& part = *partGraphs[pid];
        
        // 构建端口映射
        std::unordered_map<std::string, ValueId> inputMapping;
        std::unordered_map<std::string, ValueId> outputMapping;
        
        // 原始输入端口映射
        for (const auto& port : part.inputPorts()) {
            // 查找对应顶层 value
            ValueId topValue = findCorrespondingTopValue(port.name);
            inputMapping[port.name] = topValue;
        }
        
        // 创建实例
        OperationId inst = buildInstance(top, partName, "part" + std::to_string(pid),
                                         part, inputMapping, outputMapping);
        partInstances.push_back(inst);
    }
    
    // 4. 连接跨分区链接
    for (const auto& link : crossPartitionLinks_) {
        // 从源分区实例的输出获取 value
        ValueId srcValue = getInstanceOutput(partInstances[link.srcPart], link.srcPort);
        // 连接到目标分区实例的输入
        setInstanceInput(partInstances[link.dstPart], link.dstPort, srcValue);
    }
}
```

**注意事项**：

| Source 类型 | 是否可跨分区 | 处理方式 | 说明 |
|:---|:---|:---|:---|
| kRegisterReadPort | ✅ 允许 | 创建输出/输入端口 | 寄存器值可被多个分区读取 |
| kLatchReadPort | ✅ 允许 | 创建输出/输入端口 | 锁存器值可被多个分区读取 |
| Input Value | ✅ 允许 | 创建输出/输入端口 | 原始输入传递到目标分区 |
| inout.in | ✅ 允许 | 创建输出/输入端口 | inout 的输入分量传递到目标分区 |
| kMemoryReadPort | ❌ 不允许 | 报错 | 应由 ASC 保证同分区 |
| kConstant | ✅ 允许 | 复制到各分区 | 常量可直接复制，无需端口 |
```

## 5. Pass 接口

### 5.1 头文件

```cpp
// wolvrix/lib/include/transform/repcut.hpp
#ifndef WOLVRIX_TRANSFORM_REPCUT_HPP
#define WOLVRIX_TRANSFORM_REPCUT_HPP

#include "transform.hpp"
#include <cstddef>
#include <string>

namespace wolvrix::lib::transform {

struct RepcutOptions {
    std::string targetGraphSymbol;           // 目标图符号
    std::size_t partitionCount = 2;          // 分区数量
    double imbalanceFactor = 0.015;          // 不平衡因子
    std::string workDir = ".";               // 工作目录（中间产物目录）
    std::string kaHyParPath = "KaHyPar";     // KaHyPar 可执行文件路径
    bool keepIntermediateFiles = false;      // 是否保留中间文件
};

class RepcutPass : public Pass {
public:
    RepcutPass();
    explicit RepcutPass(RepcutOptions options);
    
    PassResult run() override;
    
private:
    RepcutOptions options_;
    // ... 内部实现细节
};

} // namespace wolvrix::lib::transform

#endif // WOLVRIX_TRANSFORM_REPCUT_HPP
```

### 5.2 注册 Pass

在 `wolvrix/lib/src/transform.cpp` 中添加：

```cpp
#include "transform/repcut.hpp"

// 在 availableTransformPasses() 中添加
return {
    // ... 其他 passes
    "repcut",
};

// 在 makePass() 中添加
if (normalized == "repcut") {
    RepcutOptions options;
    // 解析参数...
    return std::make_unique<RepcutPass>(options);
}
```

### 5.3 当前实现参数（与代码一致）

`repcut` 当前在 `makePass()` 中支持如下参数：

- `-target-graph <symbol>` / `-target-graph=<symbol>`
- `-graph <symbol>` / `-graph=<symbol>`（`-target-graph` 别名）
- `-partition-count <k>` / `-partition-count=<k>`
- `-imbalance-factor <eps>` / `-imbalance-factor=<eps>`
- `-work-dir <dir>` / `-work-dir=<dir>`
- `-kahypar-path <exe>` / `-kahypar-path=<exe>`
- `-keep-intermediate-files`

说明：

- `partition-count` 必须 `>= 2`
- `imbalance-factor` 必须 `>= 0`
- `imbalance-factor` 通过 KaHyPar 命令行 `-e` 直接生效（与 Essent 调用路径一致）
- 若未启用 `-keep-intermediate-files`，`.hgr/.cfg/.part*` 文件会在成功流程结束后自动清理

### 5.4 典型命令

最小示例：

```bash
transform repcut \
    -target-graph top \
    -partition-count 4 \
    -imbalance-factor 0.015 \
    -work-dir wolvrix/build/artifacts/repcut
```

指定 KaHyPar 可执行路径并保留中间文件：

```bash
transform repcut \
    -target-graph top \
    -partition-count 8 \
    -kahypar-path /usr/local/bin/KaHyPar \
    -work-dir wolvrix/build/artifacts/repcut \
    -keep-intermediate-files
```

## 6. 关键实现要点

### 6.1 图遍历方向

- **ASC 逻辑锥收集**：反向遍历（从 ASC 的每个 sink 向上到 source）
- **Piece 构建**：双向遍历（通过邻接关系找连通且 ASC 集合相同的节点）
- **权重计算**：反向遍历（从 piece 内部 sink 向上累加）

### 6.2 缓存策略

- **ASC 逻辑锥缓存**：缓存每个 ASC 的组合逻辑锥（combOps）
- **节点权重缓存**：单个操作节点的权重计算结果缓存
- **Piece 权重缓存**：避免重复计算 piece 总权重

### 6.3 内存优化

- 使用 `std::vector` 存储连续数据（ascs_, pieces_）
- 使用 `std::unordered_set` 存储 ASC 逻辑锥（combOps）和 piece 成员关系
- 使用 NodeId（uint32_t）替代 OperationId 作为内部索引

### 6.4 错误处理

- 检查 KaHyPar 是否安装
- 检查超图是否为空
- 检查划分结果是否有效

## 7. 与 hrbcut 的对比

| 特性 | hrbcut | repcut |
|:---|:---|:---|
| 划分目标 | 2^n 分区 | 任意 k 分区 |
| 算法类型 | 随机采样 + 贪心 | 超图划分（KaHyPar）|
| 负载均衡 | 通过随机采样逼近 | KaHyPar 内部优化 |
| 复制代价 | 通过 overlap 估计 | 通过超边切割优化 |
| 复杂度 | O(n log n) | 依赖 KaHyPar |
| 适用场景 | 快速划分 | 高质量划分 |

### Sink/Source 语义对照

| 场景 | hrbcut | repcut |
|:---|:---|:---|
| **Sink 节点** | Output Values, kRegisterWritePort, kLatchWritePort, kMemoryWritePort | 同 hrbcut |
| **Source 边界** | Input Values, kRegisterReadPort, kLatchReadPort, kConstant | 同 hrbcut |
| **kMemoryReadPort** | **不是 Source 边界**（穿过继续遍历） | **不是 Source 边界**（穿过继续遍历） |
| **kRegisterReadPort** | Source 边界（可跨分区使用） | Source 边界（可跨分区使用） |
| **ASC 构建** | 必须，保证状态元素完整 | 必须，保证状态元素完整 |
| **划分原子单位** | ASC（不可分割） | ASC（不可分割） |
| **超图顶点** | 无超图（直接计算 overlap） | ASC |
| **超边** | 无 | Non-ASC Pieces（被多个 ASC 共享的组合逻辑） |

## 8. 测试建议

1. **单元测试**：
   - 测试 tree 构建正确性
   - 测试 piece 聚类正确性
   - 测试超图权重计算

2. **集成测试**：
   - 小规模电路（<100 节点）
   - 中等规模电路（1K-10K 节点）
   - 大规模电路（>100K 节点）

3. **验证指标**：
   - 分区负载均衡度
   - 复制节点比例
   - 复制权重比例
   - 运行时间

## 9. 参考实现

### 9.1 Essent/RepCut 原始实现
- **权重计算**：`tmp/essent/src/main/scala/ThreadPartitioner.scala` 第 132-321 行
  - 基于 FIRRTL IR 类型的复杂启发式模型
  - 考虑位宽、操作类型、是否为字面量等
- **超图构建**：`tmp/essent/src/main/scala/ThreadPartitioner.scala` 第 354-383 行
  - `initTrees()` / `initPieces()` / `updateHyperGraph()`
- **Piece 权重**：`tmp/essent/src/main/scala/ThreadPartitioner.scala` 第 323-349 行
  - 从 piece 内部 sink 递归收集权重
  - 使用 visited 集合避免重复计数

### 9.2 hrbcut（GRH IR 实现参考）
- **权重模型**：`wolvrix/lib/transform/hrbcut.cpp` 第 303-361 行
  - 简化权重表（参考本文档方案 A）
  - 基于 OperationKind 和位宽
- **ASC 构建**：`wolvrix/lib/transform/hrbcut.cpp` 第 932-1140 行
  - 并查集合并、mem 不可分规则实现
- **分区重建**：`wolvrix/lib/transform/hrbcut.cpp` 第 1504-1888 行
  - 子图创建、端口生成、状态元素处理

### 9.3 关键差异对照

| 方面 | Essent/RepCut | hrbcut | 本文档建议 |
|:---|:---|:---|:---|
| **权重模型** | FIRRTL 启发式 | 简化表 | 可选（方案 A/B）|
| **超图顶点** | Trees（单个 sink）| 无超图 | **ASCs** |
| **Piece 定义** | 相同 Tree 集合 | 无 | 相同 **ASC** 集合 |
| **ASC 概念** | 无 | 有 | 有（必须）|
| **遍历边界** | DefRegister | kRegisterReadPort | **kRegisterReadPort** |

## 10. 分解实施计划（自底向上）

本计划按“先打地基、再拼算法、最后接系统”的方式推进，目标是每个阶段都可独立编译、可独立验证，并尽量复用 hrbcut 的成熟代码路径。

### 10.1 实施原则

1. **先数据结构，后流程编排**：先把 NodeId 映射、邻接索引、缓存框架稳定下来，再接 ASC/Piece/HyperGraph 主流程。
2. **先纯函数模块，后副作用模块**：优先实现可离线测试的计算逻辑（分类、遍历、权重、聚类），最后实现文件 IO、外部命令、图重建。
3. **每阶段都可回归**：每完成一个阶段都加最小可运行测试，避免后期集中排错。
4. **优先最小闭环（MVP）**：先落地方案 A 权重模型+基础 KaHyPar 流程，后续再切换/扩展方案 B。

### 10.2 模块分解

建议在 `wolvrix/lib/transform/repcut.cpp` 内按“内部子模块（静态函数 + 小型 helper struct）”组织；如后续复杂度增加，再拆分为多文件。

| 模块 | 职责 | 输入 | 输出 | 依赖 |
|:---|:---|:---|:---|:---|
| M0. 基础索引层 | 建立 op/value/node 双向索引与邻接关系 | Graph | `opToNode_`, `nodeToOp_`, 邻接表 | 无 |
| M1. 语义判定层 | `isSinkOpKind` / `isSourceValue` / `isCombOp` | Operation/Value | 布尔判定 | M0 |
| M2. ASC 构建层 | sink 收集、并查集合并、logic cone 收集 | 索引+语义判定 | `ascs_`, `sinkToAsc_` | M0-M1 |
| M3. Piece 构建层 | `nodeToAscs_`、连通聚类、`nodeToPiece_` | ASC 结果 | `pieces_`, `pieceToAscs_` | M0-M2 |
| M4. 权重计算层 | node/piece 权重缓存与递归累加 | Piece + Operation | `nodeWeights_`, `pieceWeights` | M0-M3 |
| M5. 超图构建层 | 生成 ASC 顶点和 Non-ASC 超边 | Piece + 权重 | `HyperGraph` | M0-M4 |
| M6. KaHyPar 适配层 | hMETIS 输出、配置生成、命令执行、结果解析 | HyperGraph | `ascPartition` | M5 |
| M7. 分区重建层 | 子图裁剪、跨分区端口、顶层拼接 | `ascPartition` + Graph | 新 top + part graphs | M0-M6 |
| M8. Pass 集成层 | 参数解析、流程编排、诊断输出 | CLI options | PassResult | M0-M7 |

### 10.3 分阶段里程碑（建议执行顺序）

#### Phase A：地基与可观测性（M0-M1）

**目标**：先把“图能看清楚”做扎实。

- A1. 建立 NodeId 压缩映射与邻接索引（in/out neighbors）。
- A2. 实现 `isSinkOpKind` / `isSourceValue` / `isCombOp`，并加断言日志。
- A3. 增加 debug dump 开关（仅开发态）：输出 sink 数、source 命中统计、comb op 分布。

**验收标准**：
- 可在任意 flatten 后图上稳定输出节点总数、边总数、sink/source 统计；无崩溃。

#### Phase B：ASC 与 Piece 闭环（M2-M3）

**目标**：先打通超图之前最关键的数据基础。

- B1. 实现 sink 收集与并查集合并（写口合并 + mem 不可分）。
- B2. 实现 `collectConeMemSymbols` 与 `collectCone`（含去重与边界控制）。
- B3. 实现 `nodeToAscs_` 与 `findPiece`，产出 ASC Piece + Non-ASC Piece。
- B4. 增加一致性检查：
    - 每个 sink 必须属于且仅属于一个 ASC；
    - 每个 node 必须属于且仅属于一个 piece；
    - `pieceToAscs_` 与 `nodeToAscs_` 一致。

**验收标准**：
- 小规模样例可稳定得到非空 ASC/Piece；一致性检查全通过。

#### Phase C：权重与超图闭环（M4-M5）

**目标**：在不依赖 KaHyPar 的情况下，先完成“可计算”的超图。

- C1. 先实现方案 A（简化权重表）并加缓存。
- C2. 实现 piece 权重递归累加（visited 防重复）。
- C3. 构建 HyperGraph（ASC 顶点、Non-ASC 超边、pin count 分摊）。
- C4. 增加超图合法性检查：
    - 顶点数 == ASC 数；
    - 每条超边至少连接 1 个 ASC；
    - 所有权重 >= 1。

**验收标准**：
- 可导出稳定的内存版超图对象（即使尚未落盘/调用 KaHyPar）。

#### Phase D：KaHyPar 集成闭环（M6）

**目标**：打通外部分区器调用链路。

- D1. 实现 hMETIS 文件输出与配置文件生成。
- D2. 实现 KaHyPar 命令执行（含路径、返回码、stderr 诊断）。
- D3. 解析分区结果并映射到 ASC。
- D4. 错误处理分级：
    - 可恢复：超图为空、分区结果不完整；
    - 不可恢复：KaHyPar 不存在/执行失败。

**验收标准**：
- 在安装 KaHyPar 的环境中可得到合法 `ascPartition`；失败时报错可读。

#### Phase E：分区重建与端口拼接（M7）

**目标**：把划分结果真正转回可执行/可导出的 GRH 结构。

- E1. 基于 `ascPartition` 构建 `opPartition`。
- E2. 实现状态元素归属修正（reg/latch/memory 声明+端口同分区）。
- E3. 识别跨分区 value，仅允许白名单类型（reg/latch read + input/inout.in）。
- E4. 创建分区子图端口与顶层连接，记录 `crossPartitionLinks_`。
- E5. 加入约束检查：memory read 跨分区即报错。

**验收标准**：
- 分区后图可通过 emit/store 基础流程；跨分区连接完整、无悬空值。

#### Phase F：Pass 集成与回归（M8）

**目标**：对外提供稳定可用的 `repcut` pass。

- F1. 添加 `repcut.hpp` + pass 注册（`availableTransformPasses()` / `makePass()`）。
- F2. 串联完整 `run()`：前置检查 → ASC/Piece → 超图 → KaHyPar → 重建。
- F3. 增加关键统计日志：ASC 数、piece 数、cut 超边数、复制比例、耗时分布。
- F4. 文档补充实际参数说明与典型命令。

**验收标准**：
- `transform repcut` 可从命令行跑通，并在失败路径返回明确诊断。

### 10.4 测试分层与样例规划

1. **单元层（优先）**
     - `isSourceValue`/`isCombOp` 边界行为（特别是 `kMemoryReadPort`）。
     - ASC 合并规则（写口合并、mem 不可分）。
     - Piece 聚类与一致性检查。

2. **组件层**
     - 权重计算稳定性（缓存命中、不重复计数）。
     - 超图构建合法性（顶点/超边/权重）。
     - hMETIS 导出格式正确性。

3. **集成层**
     - 小型 hdlbits 用例跑通全链路。
     - 中型 openc910/xs 子集样例验证耗时与分区质量。

### 10.5 开发节奏建议（两周样例）

- **第 1-2 天**：Phase A。
- **第 3-5 天**：Phase B。
- **第 6-7 天**：Phase C。
- **第 8-9 天**：Phase D。
- **第 10-12 天**：Phase E。
- **第 13-14 天**：Phase F + 回归与文档收敛。

### 10.6 风险与降级策略

- **KaHyPar 不可用**：先保留 hMETIS 导出，允许离线分区结果回灌（跳过在线调用）。
- **大图性能压力**：优先加缓存与统计，再考虑并行化；先保证正确性。
- **重建阶段复杂度高**：先实现只支持 register/latch read 跨分区，再逐步扩到 input/inout.in。
- **权重模型争议**：默认方案 A，保留选项切换到方案 B（通过 pass 参数控制）。

### 10.7 完成定义（Definition of Done）

满足以下条件可认为 repcut-pass 首版完成：

1. `repcut` pass 已注册并可执行。
2. 对至少一组 hdlbits 样例可稳定产出分区结果并完成图重建。
3. 分区后图满足语义约束（状态元素同分区、禁止 memory read 跨分区）。
4. 关键统计与错误信息可用于定位问题。
5. 文档与实现行为一致（参数、限制、已知问题齐全）。
