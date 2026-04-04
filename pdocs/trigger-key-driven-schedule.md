# 触发键驱动的静态调度方案

## 1. 目标

为后续仿真器准备一套静态调度计划，使运行时 `eval()` 不必全图重算，而是只执行本拍必需的操作。

这里的“触发键驱动”是指调度分组与运行时执行门控，不再以 module 或 `always` block 为中心，而是围绕：

- 可观察 `sink op`
- 触发键
- 共享组合逻辑锥

来构造更细粒度的静态执行组。

运行时模型仍然对齐 Verilator 风格：

```cpp
void eval();
```

但 `eval()` 内部不再以“模块/always block”为单位调度，而是以预先构建好的 `TKDGroup` 为单位调度。

核心优化目标：

- output 相关逻辑始终可得
- 事件判定逻辑先算
- 只有对应事件真正触发时，才计算该事件组下的 reg/mem 写口数据逻辑锥
- 多个事件组共享的公共逻辑只计算一次

## 2. 概念梳理

### 2.1 `op` 是最小调度单元

本方案以 `op` 为最小调度单元，而不是以 module、`always` block 或 process 为最小调度单元。

这意味着：

- 静态分析、分组、拓扑排序都围绕 `op` 展开
- 运行时是否执行某段逻辑，也以“某个 `op` 是否落在本次要执行的 `TKDGroup` 中”为准
- `value` 只是依赖边上的数据载体，不单独参与调度；某个 `value` 被计算出来，等价于其定义 `op` 已经执行

除非后文显式说明，否则一个 `op` 不会再被拆成更细粒度的调度片段。

### 2.2 `sink op`

本方案把“会产生可观察效果，或其结果必须在本拍对外可见”的 `op` 统称为 `sink op`。

当前 `sink op` 至少包括：

- storage write sink：
  - `kRegisterWritePort`
  - `kMemoryWritePort`
  - `kLatchWritePort`
- effect sink：
  - 无返回值的 `kDpicCall`
  - `kSystemTask`
- top-level observable sink：
  - 其 result 直接连接到 top-level `output` port value 的任何 `op`
  - 其 result 直接连接到 top-level `inout` 的 `out` value 的任何 `op`
  - 其 result 直接连接到 top-level `inout` 的 `oe` value 的任何 `op`

这里补一条边界说明：

- `inout` 不仅有输出值 `out`，还有输出使能 `oe`；`oe` 同样影响外部可观察行为，因此也必须视为 sink
- 这里的“直接连接”必须严格按 port 绑定关系判断，而不是按传递闭包判断；否则 top-level 可观察值的整个上游组合锥都会被提前并入 `sink op`，后续再基于 `sink op` 扩张 `TKDGroup` 就失去分层意义
- 若调度输入 graph 仍允许 `kXMRWrite` 存在，那么它本质上也是 side-effect sink，也应并入 `sink op` 集合；若本方案前置要求先完成 `xmr-resolve`，则可暂不纳入当前正文

### 2.3 触发键

每个事件敏感的 `sink op` 都有一个触发键（`TriggerKey`）。

触发键有两种形态：

- 空键：记作空串，表示该 `op` 不依赖边沿触发事件
- 非空键：记作一串连续的二元组

```text
<valId1, posedge><valId2, negedge>...
```

其中每个二元组表示一个事件项：

- `valId`：事件信号对应的 value id
- `eventEdge`：边沿类型，目前取值为 `posedge` 或 `negedge`

之所以叫“键”而不叫“签名”，是因为这里更关心它是否可规范化、可判等、可去重、可作为分组索引，而不是保留某段原始语法外观。

为了判断两个触发键是否等价，需要先把它规范化。规范化规则定义为：

1. 把触发键展开成若干个 `(valId, eventEdge)` 二元组
2. 先按 `valId` 升序排序
3. 对相同 `valId`，再按 `eventEdge` 排序；本文固定 `negedge < posedge`
4. 对完全相同的二元组去重
5. 规范化后的二元组序列作为该触发键的唯一表示

因此，两个触发键相等，当且仅当它们规范化后的二元组序列完全相同。

补充约束：

- 同一 `valId` 的 `posedge` 和 `negedge` 是两个不同事件项，不能互相去重
- 空触发键的规范形式仍为空触发键

### 2.4 调度组：`TKDGroup`

`TKDGroup`（Trigger-Key-Driven Group）是 `op` 的集合，也是运行时的直接调度单位。

`TKDGroup` 不是“某个时钟域”的同义词。更准确地说，它是结合可观察 sink、触发键和共享逻辑后得到的调度组。

一个 `TKDGroup` 只表达“这批 `op` 被一起调度”，不改变 `op` 之间原有的数据依赖关系；组内执行顺序仍由后续静态排序确定。

对 `TKDGroup`，先给出两个基础约束：

- 任意两个 `TKDGroup` 不相交
- 任意一个 `op` 至多属于一个 `TKDGroup`

也就是说，`TKDGroup` 在当前草案中构成参与本调度方案的 `op` 集合上的一个不交划分。
