# NO0038 GSim `Init -> graphPartition` 阶段变化记录（2026-04-28）

> 归档编号：`NO0038`。目录顺序见 [`README.md`](./README.md)。

这份记录回答一个具体问题：当前仓库这份 `SimTop` 输入上，`gsim` 从“刚建好图”到“最终 `graphPartition`”之间，图规模是怎么变化的，尤其是 `NODE_REG_SRC` 在各阶段如何演化。

先给结论：

- `Init`（`AST2Graph` 刚结束）时，`NODE_REG_SRC = 197268`。
- 最终 `graphPartition` 时，`NODE_REG_SRC = 148954`。
- 但中间不是单调下降；在 `TopoSort` 阶段采样点，`NODE_REG_SRC` 先涨到 `284855`。
- 最终 `graphPartition` 不再改变节点集合，只把 `supernode_count` 从 `2708056` 压到 `48437`。

## 1. 数据来源与口径

分析直接使用现成 stage stats：

- `Init`:
  - [`../../build/xs/ir_compare/SimTop_0Init_Stats.json`](../../build/xs/ir_compare/SimTop_0Init_Stats.json)
- `TopoSort -> graphPartition`:
  - [`../../build/xs/ir_compare/stage_probe/`](../../build/xs/ir_compare/stage_probe/)

对应 `gsim` pipeline 顺序见：

- [`reference/gsim/src/main.cpp`](../../reference/gsim/src/main.cpp)

这里要注意一个口径细节：

- `Init` 是 `AST2Graph()` 返回后的采样点。
- `TopoSort` 采样点发生在 `splitArray()`、`detectLoop()`、`topoSort()` 全部完成之后。
- 因此 `Init -> TopoSort` 这一段统计变化，是 `splitArray + detectLoop + topoSort` 的合并结果，不是 `topoSort` 单独造成的变化。

同时，`topoSort()` 本身只重排 supernode 顺序，不增删节点，代码见：

- [`reference/gsim/src/topoSort.cpp`](../../reference/gsim/src/topoSort.cpp)

所以如果只问“`TopoSort` 前后节点数会不会因为排序本身变化”，答案是否定的；真正把图做大的是排序之前的变换。

## 2. 全阶段快照

| Stage | Node Count | Supernode Count | NODE_REG_SRC | NODE_REG_DST | NODE_OTHERS | Edge Count | Dep Edge Count |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `Init` | `7826232` | `7826218` | `197268` | `197268` | `7413352` | `12660722` | `13136262` |
| `TopoSort` | `9631690` | `9631676` | `284855` | `284855` | `9043636` | `14458895` | `15178409` |
| `RemoveDeadNodes0` | `6012332` | `6012318` | `156110` | `156110` | `5685533` | `8835953` | `9344089` |
| `ExprOpt` | `6012332` | `6012318` | `156110` | `156110` | `5685533` | `8831005` | `9339102` |
| `UsedBits` | `6012332` | `6012318` | `156110` | `156110` | `5685533` | `8831005` | `9339102` |
| `SplitNodes` | `6035170` | `6035156` | `158285` | `158285` | `5704021` | `8833328` | `9344284` |
| `AfterSplitNodes` | `6035170` | `6035156` | `158285` | `158285` | `5704021` | `8833328` | `9344284` |
| `RemoveDeadNodes1` | `5913684` | `5913670` | `158055` | `158055` | `5582995` | `8685302` | `9195375` |
| `ConstantAnalysis` | `5016688` | `5016674` | `152005` | `151925` | `4698857` | `7474168` | `7861967` |
| `RemoveDeadNodes2` | `4869979` | `4869965` | `148954` | `148874` | `4558292` | `7301701` | `7679148` |
| `AliasAnalysis` | `3135224` | `3135210` | `148954` | `148874` | `2823537` | `5553552` | `6026212` |
| `PatternDetect` | `3131578` | `3131564` | `148954` | `148874` | `2819891` | `5549906` | `6022665` |
| `CommonExpr` | `2731632` | `2731618` | `148954` | `148874` | `2419945` | `4943431` | `5395261` |
| `RemoveDeadNodes3` | `2708070` | `2708056` | `148954` | `148874` | `2396383` | `4902060` | `5352002` |
| `graphPartition` | `2708070` | `48437` | `148954` | `148874` | `2396383` | `4902060` | `5352002` |

## 3. 相邻阶段增量

| From | To | dNode | dSuper | dRegSrc | dRegDst | dOthers | dEdge | dDepEdge |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `Init` | `TopoSort` | `1805458` | `1805458` | `87587` | `87587` | `1630284` | `1798173` | `2042147` |
| `TopoSort` | `RemoveDeadNodes0` | `-3619358` | `-3619358` | `-128745` | `-128745` | `-3358103` | `-5622942` | `-5834320` |
| `RemoveDeadNodes0` | `ExprOpt` | `0` | `0` | `0` | `0` | `0` | `-4948` | `-4987` |
| `ExprOpt` | `UsedBits` | `0` | `0` | `0` | `0` | `0` | `0` | `0` |
| `UsedBits` | `SplitNodes` | `22838` | `22838` | `2175` | `2175` | `18488` | `2323` | `5182` |
| `SplitNodes` | `AfterSplitNodes` | `0` | `0` | `0` | `0` | `0` | `0` | `0` |
| `AfterSplitNodes` | `RemoveDeadNodes1` | `-121486` | `-121486` | `-230` | `-230` | `-121026` | `-148026` | `-148909` |
| `RemoveDeadNodes1` | `ConstantAnalysis` | `-896996` | `-896996` | `-6050` | `-6130` | `-884138` | `-1211134` | `-1333408` |
| `ConstantAnalysis` | `RemoveDeadNodes2` | `-146709` | `-146709` | `-3051` | `-3051` | `-140565` | `-172467` | `-182819` |
| `RemoveDeadNodes2` | `AliasAnalysis` | `-1734755` | `-1734755` | `0` | `0` | `-1734755` | `-1748149` | `-1652936` |
| `AliasAnalysis` | `PatternDetect` | `-3646` | `-3646` | `0` | `0` | `-3646` | `-3646` | `-3547` |
| `PatternDetect` | `CommonExpr` | `-399946` | `-399946` | `0` | `0` | `-399946` | `-606475` | `-627404` |
| `CommonExpr` | `RemoveDeadNodes3` | `-23562` | `-23562` | `0` | `0` | `-23562` | `-41371` | `-43259` |
| `RemoveDeadNodes3` | `graphPartition` | `0` | `-2659619` | `0` | `0` | `0` | `0` | `0` |

## 4. 读数解释

### 4.1 `Init -> TopoSort`：图先膨胀，而不是先收缩

这一段最反直觉：

- `node_count` 从 `7826232` 增到 `9631690`，净增 `1805458`
- `NODE_REG_SRC` 从 `197268` 增到 `284855`，净增 `87587`
- `NODE_REG_DST` 同样净增 `87587`

这说明“刚建好图”之后，`gsim` 在真正进入后续优化前，还会通过 `splitArray()` 等前处理把一部分节点显式拆开。  
因为 `topoSort()` 自身只排序不改集合，所以这段膨胀不能归因于 topo 本身。

### 4.2 第一轮 `RemoveDeadNodes` 是最大的一次瘦身

`TopoSort -> RemoveDeadNodes0`：

- `node_count` 一次性减少 `3619358`
- `NODE_REG_SRC` 减少 `128745`
- `NODE_OTHERS` 减少 `3358103`

这和 [`reference/gsim/src/deadNodes.cpp`](../../reference/gsim/src/deadNodes.cpp) 的实现一致：它从输出、special、external、寄存器更新链等“必须保留”的根开始回溯，把不可达节点整批标死并移除。

### 4.3 `SplitNodes` 会再次局部膨胀

`UsedBits -> SplitNodes`：

- `node_count` 回升 `22838`
- `NODE_REG_SRC` 回升 `2175`
- `NODE_REG_DST` 回升 `2175`

这表示按位宽/切片进一步拆节点时，又引入了一批新的显式节点。也就是说，`gsim` 主线不是单调消元，而是“拆分增大一次，再由后续 passes 回收”。

### 4.4 `ConstantAnalysis` 之后开始第二轮明显收缩

`RemoveDeadNodes1 -> ConstantAnalysis -> RemoveDeadNodes2` 合计：

- `node_count` 从 `5913684` 降到 `4869979`
- `NODE_REG_SRC` 从 `158055` 降到 `148954`
- `NODE_REG_DST` 从 `158055` 降到 `148874`

这里可以把它理解成：

- `ConstantAnalysis` 先把大量值折成常量或常量驱动形式；
- 随后的 `RemoveDeadNodes2` 再把因此失去用途的节点回收掉。

### 4.5 `AliasAnalysis` 和 `CommonExpr` 主要吃掉的是 `NODE_OTHERS`

`RemoveDeadNodes2 -> AliasAnalysis`：

- `node_count` 直接减少 `1734755`
- `NODE_REG_SRC` / `NODE_REG_DST` 不变
- 减掉的几乎全是 `NODE_OTHERS`

`PatternDetect -> CommonExpr`：

- `node_count` 再减少 `399946`
- 同样主要是 `NODE_OTHERS`

这和实现是吻合的：

- [`reference/gsim/src/aliasAnalysis.cpp`](../../reference/gsim/src/aliasAnalysis.cpp) 只对可判定 alias 的普通值节点做替换和删除。
- [`reference/gsim/src/commonExpr.cpp`](../../reference/gsim/src/commonExpr.cpp) 主要合并重复表达式节点。

所以后段大收缩，更多是“组合值归并”，不是“状态节点继续减少”。

### 4.6 `graphPartition` 只改 supernode，不改 node

最终 `RemoveDeadNodes3 -> graphPartition`：

- `node_count` 完全不变：`2708070 -> 2708070`
- `NODE_REG_SRC` 完全不变：`148954 -> 148954`
- `supernode_count` 从 `2708056` 直接压到 `48437`

也就是说，最终 `graphPartition` 的本质是重组 supernode 边界，而不是再改 node 集合。  
代码上也能直接看到这一点：

- [`reference/gsim/src/graphPartition.cpp`](../../reference/gsim/src/graphPartition.cpp) 中 `graphInitPartition()` 主要是在移动 `node->super`、拼接 `member` 列表、`removeEmptySuper()`、`reconnectSuper()`。

## 5. 只看 `NODE_REG_SRC` 的主线结论

如果只追踪 `NODE_REG_SRC`，那么完整轨迹是：

- `Init`: `197268`
- `TopoSort`: `284855`
- `RemoveDeadNodes0`: `156110`
- `SplitNodes`: `158285`
- `RemoveDeadNodes1`: `158055`
- `ConstantAnalysis`: `152005`
- `RemoveDeadNodes2`: `148954`
- `AliasAnalysis -> graphPartition`: 一直稳定在 `148954`

因此可以把它总结成一句话：

- `NODE_REG_SRC` 不是从头到尾单调减少，而是先因前处理显式化而增加，再被死节点删除和常量传播回收，最后在 `graphPartition` 前就已经稳定下来。

最终相对 `Init` 的净变化：

- `197268 -> 148954`
- 净减少 `48314`
- 降幅 `24.49%`

## 6. 总结

从这份 `SimTop` 样本看，`gsim` 的 `Init -> graphPartition` 主线不是“持续做减法”，而是三段式：

1. `Init -> TopoSort`：
   先扩图，把更多中间值和状态显式化。
2. `RemoveDeadNodes / ConstantAnalysis / AliasAnalysis / CommonExpr`：
   再通过可达性、常量化、别名合并、公共表达式合并把图大幅压缩。
3. `graphPartition`：
   最后不再改节点集合，只把已有节点重新打包进更少的 supernode。

如果后续要继续分析 `gsim` 与 `grhsim` 的差异，这份文档里最值得记住的不是最终绝对数，而是：

- `NODE_REG_SRC` 的峰值出现在早期前处理之后，而不是 `Init` 或最终分区之后。
- 真正决定最终节点规模的，不是 `graphPartition`，而是中间那几轮消元和合并 passes。
