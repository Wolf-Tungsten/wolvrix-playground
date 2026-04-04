# Comb Loop Elimination Pass 设计文档

## 概述

`comb-loop-elim` 是一个用于检测并消除组合逻辑环路的 Transform Pass。该 Pass 工作在 hier-flatten 之后，对扁平化后的单一层级图进行分析，识别组合逻辑环路并尝试修复。

## 目标

1. **检测所有组合逻辑环路**：基于组合依赖图做 SCC（强连通分量）检测，覆盖所有环路（包括与任何 source 不连通的环路）
2. **区分伪环路与真环路**：
   - **伪环路 (False Loop)**：由于值复用 (value sharing) 或位宽汇合导致的虚假环路，先通过位宽范围分析识别，**若可拆分则必须拆分 value**
   - **真环路 (True Loop)**：实际的组合逻辑反馈，需要记录到 scratchpad 供后续处理
3. **可选并行化**：SCC 检测可选多图并行（或分区并行），但不作为正确性前提
4. **串行修复**：环路消除阶段串行执行，确保修复顺序一致性

## 背景：什么是组合逻辑环路

### 真环路 (True Combinational Loop)

```verilog
// 真环路示例：实际存在的组合逻辑反馈
module true_loop (
    input  wire a,
    output wire y
);
    wire x;
    assign x = a ^ y;  // x 依赖 y
    assign y = ~x;      // y 依赖 x - 形成真环路
endmodule
```

真环路是实际的硬件反馈路径，无法在纯组合逻辑中打破，需要：
- 插入寄存器打断环路
- 或者记录到 scratchpad 由人工或后续 pass 处理

### 伪环路 (False Loop)

#### 类型 1：Slice 导致的部分位宽伪环路（主要场景）

```verilog
// 伪环路示例：部分位宽赋值，实际无环路
module slice_false_loop (
    input  wire [7:4] a_high,   // a[7:4] 是独立输入
    input  wire [7:4] b_high,   // b[7:4] 是独立输入
    output wire [7:0] a,
    output wire [7:0] b
);
    // a[3:0] 和 b[3:0] 互相依赖，但 a[7:4] 和 b[7:4] 是独立的
    assign b[3:0] = a[7:4];     // b[3:0] 只依赖 a[7:4]
    assign a[3:0] = b[3:0];     // a[3:0] 只依赖 b[3:0]
    assign a[7:4] = a_high;
    assign b[7:4] = b_high;
endmodule
```

**关键特征**：
- 看似 `a ↔ b` 形成了环路
- 实际上 `a[7:4]` 和 `b[7:4]` 来自独立输入
- 只有低 4 位存在交叉赋值，没有真正的反馈路径

**检测方法**：
- 环路检测时记录每个 value 的位宽范围
- 如果发现环路上的 value 在 GRH 中已被拆分为独立的 slice（如 `kSliceStatic` 结果）
- 检查是否存在实际的位宽重叠导致的依赖



## 算法设计

### 阶段 1：组合边界识别（切断不可分析/时序边）

组合环路只可能由**组合依赖边**形成。需要先识别**组合边界**，将以下情况视为**依赖图的边界**（不向其内部追踪依赖）：

| 节点类型 | Operation Kind | 说明 |
|---------|---------------|------|
| 输入端口 | (隐式 source) | Graph 的 input port values（无定义 op） |
| 常量 | `kConstant` | 编译时常量值 |
| 寄存器读端口 | `kRegisterReadPort` | 时序逻辑输出，对组合逻辑而言是 source |
| 锁存器读端口 | `kLatchReadPort` | 时序逻辑输出 |
| DPI-C 调用结果 | `kDpicCall` | 外部函数调用结果 |

```cpp
bool isBoundaryOp(OperationKind kind) {
    switch (kind) {
        case kConstant:
        case kRegisterReadPort:
        case kLatchReadPort:
        case kDpicCall:
            return true;
        default:
            return false;
    }
}
```

提醒：`kMemoryReadPort` **不是** source，它有 addr 输入，必须建立 `addr -> data` 依赖边（不追踪内部存储状态）。

### 阶段 2：组合依赖图 + SCC 环路检测

#### 2.1 构建组合依赖图

以 **Value 为节点** 建图。对每个 **组合** operation，增加从 **operand → result** 的依赖边。对边界 op（`isBoundaryOp`）不添加依赖边，从而**切断不可分析/时序边**。

```cpp
// 组合依赖图：Value -> 其直接依赖的后继 Value
std::unordered_map<ValueId, std::vector<ValueId>, ValueIdHash> succ;

for (auto opId : graph.operations()) {
    auto op = graph.getOperation(opId);
    if (isBoundaryOp(op.kind())) {
        continue; // 切断边界，不向内追踪
    }

    // 仅对有 result 的组合 op 添加依赖边
    for (auto result : op.results()) {
        for (auto operand : op.operands()) {
            succ[operand].push_back(result);
        }
    }
}
```

#### 2.2 SCC 检测

对 `succ` 执行 Tarjan / Kosaraju：
- **SCC size > 1** => 组合环路候选
- **SCC size == 1 且存在自环** => 组合环路候选

```cpp
std::vector<Scc> sccs = tarjanScc(succ);
for (const auto& scc : sccs) {
    bool hasSelfLoop = (scc.size() == 1) && hasEdge(scc[0], scc[0]);
    if (scc.size() > 1 || hasSelfLoop) {
        collectLoopInfo(scc);
    }
}
```

#### 2.3 并行化策略（可选）

SCC 本身是线性的；并行化更适合**多图并行**（多个 Graph 同时处理）。若必须单图并行，可先按连通域分区后分别跑 SCC，再合并结果，但优先保证正确性与简洁性。

### 阶段 3：伪环路与真环路区分（位宽范围分析）

SCC 仅表示**值级别的环路候选**。为了区分 slice 造成的伪环路，需要引入**位宽范围依赖**。

```cpp
struct LoopInfo {
    std::vector<ValueId> loopValues;   // SCC 内的 value
    std::vector<OperationId> loopOps;  // SCC 内相关 op（可选）
    bool isFalseLoop = false;
};
```

#### 3.1 位宽范围依赖建模

对 SCC 内的操作，构建**位宽范围依赖边** `(src_value, src_range) -> (dst_value, dst_range)`：

- `kSliceStatic`：只连接切片范围
- `kConcat`：按拼接位置连接对应范围
- `kAssign`/`kBitcast`/`kWire`：全范围映射
- 其它算术/逻辑 op：**保守处理为全范围映射**（避免漏报）

#### 3.2 伪环路判定

若在 SCC 内不存在**任何“同一 value 的位宽重叠环路”**，则判定为伪环路；否则为真环路。核心判断是**重叠范围**，而不是“是否有任意不重叠切片”。

```cpp
bool isSliceFalseLoop(const LoopInfo& loop, const Graph& graph) {
    auto rangeGraph = buildRangeGraph(loop, graph); // (value, range) 节点
    auto rangeSccs = tarjanScc(rangeGraph);

    for (const auto& scc : rangeSccs) {
        if (!hasRangeCycle(scc)) continue;
        if (hasOverlapOnSameValue(scc)) {
            return false; // 真环路：存在位宽重叠
        }
    }
    return true; // 仅在 disjoint range 上成环 -> 伪环路
}
```

**保守原则**：若 SCC 内包含无法精确映射位宽的 op，或分析不完整，则直接判定为真环路，避免漏报。



### 阶段 4：串行环路处理

#### 4.1 伪环路处理（必须拆分）

伪环路被识别后，**若存在可行的 value 拆分方案则必须执行**。目标是将隐式共享的值拆成显式的 `kSliceStatic + kConcat` 结构，确保后续 pass 不再误判。

拆分原则：
- 仅在位宽范围分析给出**无重叠依赖**的前提下拆分
- 拆分必须保持语义等价（仅结构重写）
- 若无法构造等价拆分（例如范围映射不完整），则**保守降级为真环路**并记录
 - 若 `fixFalseLoops=false`（仅用于调试），则不做拆分，直接按真环路处理



#### 4.2 真环路处理

真环路无法自动修复，需要**记录到 scratchpad 并输出详细 warning 诊断**（含图名、SCC 内 value/op、尽可能多的位置信息与依赖摘要），便于后续人工处理：

```cpp
struct CombLoopReport {
    std::string graphName;
    std::vector<ValueId> loopValues;
    std::vector<OperationId> loopOps;
    std::optional<SrcLoc> sourceLocation;
    std::string description;
};

void recordTrueLoop(const LoopInfo& loop, const Graph& graph) {
    CombLoopReport report;
    report.graphName = graph.symbol();
    report.loopValues = loop.loopValues;
    report.loopOps = loop.loopOps;
    
    // 获取源位置信息
    for (auto val : loop.loopValues) {
        auto value = graph.getValue(val);
        if (value.srcLoc()) {
            report.sourceLocation = value.srcLoc();
            break;
        }
    }
    
    report.description = generateLoopDescription(loop, graph);

    // 输出 warning 诊断（示意）
    emitWarning(buildCombLoopDiag(report));
    
    // 记录到 scratchpad
    auto existing = getScratchpad<std::vector<CombLoopReport>>("comb_loops");
    if (existing) {
        existing->push_back(report);
    } else {
        setScratchpad("comb_loops", std::vector<CombLoopReport>{report});
    }
}
```

## Pass 接口设计

### 头文件

```cpp
#ifndef WOLVRIX_TRANSFORM_COMB_LOOP_ELIM_HPP
#define WOLVRIX_TRANSFORM_COMB_LOOP_ELIM_HPP

#include "core/transform.hpp"
#include <cstddef>

namespace wolvrix::lib::transform
{

    struct CombLoopElimOptions
    {
        // 最大分析节点数（0 表示不限制）
        size_t maxAnalysisNodes = 0;
        
        // 并行线程数（0 表示使用硬件并发数）
        size_t numThreads = 0;
        
        // 是否对可拆分的伪环路强制 value 拆分（生产默认必须为 true）
        bool fixFalseLoops = true;
        
        // 伪环路“修复”的最大迭代次数（仅在启用强制拆分时使用）
        size_t maxFixIterations = 100;
        
        // 遇到真环路时是否标记 pass 失败
        bool failOnTrueLoop = false;
    };

    class CombLoopElimPass : public Pass
    {
    public:
        CombLoopElimPass();
        explicit CombLoopElimPass(CombLoopElimOptions options);

        PassResult run() override;

    private:
        CombLoopElimOptions options_;
    };

} // namespace wolvrix::lib::transform

#endif // WOLVRIX_TRANSFORM_COMB_LOOP_ELIM_HPP
```

### Pass Pipeline 位置

```
ingest -> xmr-resolve -> hier-flatten -> comb-loop-elim -> simplify -> emit
                                          ^^^^^^^^^^^^^^
                                          插入位置
```

在 `PassManager` 中的配置示例：

```cpp
// 默认 pipeline
pm.addPass(std::make_unique<XmrResolvePass>());
pm.addPass(std::make_unique<HierFlattenPass>());
pm.addPass(std::make_unique<CombLoopElimPass>());  // 新插入
pm.addPass(std::make_unique<SimplifyPass>());
```

## 实现步骤

### 步骤 1：基础数据结构

1. 定义 `LoopInfo` 结构体
2. 实现组合依赖图构建
3. 实现组合边界识别

### 步骤 2：SCC 环路检测

1. 实现 Tarjan / Kosaraju 检测器
2. 可选多图并行调度
3. 直接以 SCC 作为环路候选（无需去重）

### 步骤 3：环路分类

1. 实现伪环路判定算法
2. 实现真环路识别

### 步骤 4：处理逻辑

1. 对可拆分伪环路执行强制 value 拆分
2. 无法拆分的伪环路保守视为真环路并记录
3. 实现真环路记录到 scratchpad

### 步骤 5：Pass 集成

1. 实现 `CombLoopElimPass` 类
2. 添加命令行选项支持
3. 编写单元测试

## 统计与日志

建议输出以下统计信息：

```
[comb-loop-elim] graph=my_module
[comb-loop-elim]   boundary values: 15
[comb-loop-elim]   loops detected: 3
[comb-loop-elim]     false loops: 2 (split)
[comb-loop-elim]     true loops: 1 (recorded to scratchpad)
[comb-loop-elim]   values split: 3
[comb-loop-elim]   fix iterations: 2
```

## 附录：Slice 伪环路在 GRH 中的具体表现

用户提到的场景：
```verilog
wire [7:0] a,b; 
assign b[3:0]  = a[7:4]; 
assign a[3:0] = b[3:0];
```

在 GRH 中，这会表示为：

```
Value: a (8-bit)
  - definingOp: concat(a_high_slice, a_low_from_b)
  
Value: b (8-bit)
  - definingOp: concat(b_high_slice, b_low_from_a)

Operation: a_low_from_a = kSliceStatic(a, 7, 4)   // a[7:4]
Operation: a_low_assign = kAssign(a_low_from_b)
Operation: a_low_from_b = kSliceStatic(b, 3, 0)   // b[3:0]

Operation: b_low_from_b = kSliceStatic(b, 7, 4)   // b[7:4]  
Operation: b_low_assign = kAssign(b_low_from_a)
Operation: b_low_from_a = kSliceStatic(a, 3, 0)   // a[3:0]

// 依赖关系：
// b[3:0] -> depends on a[7:4]
// a[3:0] -> depends on b[3:0]
// 
// 注意：a[7:4] 和 b[7:4] 是独立的 source，不会形成环路
```

**检测关键**：
- 环路上的 value 如果是 `kSliceStatic` 的结果
- 基于位宽范围构建依赖边，检查同一 value 是否存在**重叠范围的环路**
- 若仅在不重叠范围上成环 → 伪环路
- 若存在重叠范围或范围不可精确映射 → 真环路（保守）

## 风险与注意事项

1. **性能风险**：大规模图的 SCC/位宽范围分析可能消耗较多内存，需要设置节点上限或分区策略
2. **修复顺序**：多个环路共享 value 时，修复顺序可能影响结果，需要确定性的排序策略
3. **拆分失败降级**：伪环路若无法构造等价拆分，需要保守降级为真环路并记录
4. **并发安全**：并行处理多图/分区时需避免共享状态竞争
5. **与后续 Pass 的交互**：value 拆分可能产生额外的 assign 操作，需要确保 simplify pass 能够正确处理

## 测试策略

1. **单元测试**：
   - 简单真环路检测
   - 简单伪环路检测与强制拆分
   - 伪环路拆分失败降级为真环路
   - 多环路交织场景

2. **集成测试**：
   - HDLBits 测试集验证
   - OpenC910 等大型设计验证

3. **性能测试**：
   - 大规模图的检测性能
   - 并行加速比测试
