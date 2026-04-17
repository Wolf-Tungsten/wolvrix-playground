# GrhSIM 向 GSim 性能形态对齐计划草稿

## 背景

当前 XiangShan `grhsim` 的运行时性能明显落后于 `gsim`。已有静态分析表明，核心差异不在外层活动调度框架，而在以下几个方面：

- `grhsim` 的 supernode body 普遍更重，单次激活后执行的组合逻辑动作更多
- `grhsim` 仍然把 active-word 外露成大量 `eval_batch_*` 函数，而 `gsim` 已经收敛为更简单的 `subStep` 模式
- `grhsim` 的 emitted cpp 拆分过细，文件数远高于 `gsim`
- `grhsim` 仍然大量依赖 `slot` 形式保存 value，限制了编译器优化

基于当前分析，下一阶段希望围绕“向 `gsim` 的代码生成与执行形态对齐”做一次结构性重构。

## 总目标

在不改变 `grhsim` 正确执行语义的前提下，重构 emitter 和运行时数据组织方式，让生成代码更接近 `gsim` 的高性能形态，重点改善：

- `eval_batch_*` / supernode body 的执行成本
- emitted cpp 的编译和链接开销
- 编译器对组合逻辑本体的优化空间

## 三个主方向

### 1. 收缩 supernode 的最大 op 数

目的不是机械地让 supernode 数和 `gsim` 完全一致，而是主动降低单个 supernode body 的复杂度，使其更利于：

- 编译器进行局部优化
- 控制单个 batch / subStep 的代码体积
- 降低 I-cache 和分支预测压力

需要明确：

- `grhsim op` 和 `gsim node` 语义不一致，不能直接用数量做一一对应
- 这里的目标是让 `grhsim` 自身的 supernode 更轻，而不是追求某个表面统计值完全对齐

### 2. 调整 emit 的分 batch / 分文件策略

当前 `grhsim` 的 emitted cpp 文件拆分明显比 `gsim` 更细，导致：

- 编译调度和头文件开销更大
- 单个优化单元过小，不利于编译器做跨 batch 的简单优化
- 总体构建体验较差

这一阶段希望直接让 `grhsim` 的生成形态收敛到 `gsim` 类似的 `subStep` 模式：

- active-word 继续只作为内部调度粒度存在
- 不再对外生成一大组 `eval_batch_*`
- 对外只保留更少的 `subStepN()`
- 每个 `subStep` 内再容纳多个 active-word 处理段

然后再把多个 `subStep` 打包进更少的 emitted cpp 文件中，使文件粒度更接近 `gsim`，同时保留现有的运行时调度语义。

重点：

- 优先改生成形态和 cpp file packing，而不是先改 runtime active-word 语义
- 允许运行时仍按现有 active-word 方式调度
- 主要改善编译规模和编译器可见性

### 3. 学习 GSim 的 value 组织方式，减少 slot

当前 `grhsim` 的大量 value 仍然通过 `value_*_slots_[]` 这类池化结构访问，问题是：

- 索引访问重
- alias 分析困难
- 编译器更难做 CSE / DSE / 标量替换 / 寄存器分配优化

下一阶段希望改成更接近 `gsim` 的混合模型：

- supernode 内临时值优先变成局部变量
- 跨 supernode、跨周期、需要持久保存的 value 优先成为明确命名的顶层 typed value
- `state` / `memory` / `shadow` / `evt_edge` 继续独立管理

目标不是把一切都升成顶层成员，而是去掉不必要的 `slot` 中转，让 emitted cpp 对编译器更友好。

## 非目标

本轮计划先不做：

- 不把 `grhsim` 的 supernode 数机械调到和 `gsim` 完全相同
- 不要求 runtime scheduling 语义先发生根本变化
- 不要求一次性重写整个 activity-schedule / DP / replication 框架
- 不在本轮计划中承诺直接修复所有 XiangShan 正确性问题

## 建议执行顺序

### 第一阶段

- 先引入 `subStep` 模式
- 再改 emit 的分文件 / packing 策略
- 让外部执行入口收敛为 `subStepN()`
- 让多个 active-word 处理段进入同一个 `subStep`
- 再让多个 `subStep` 进入同一个 emitted cpp
- 先改善构建体积和编译器可见性

### 第二阶段

- 重构 value storage
- 同 supernode temporary 优先局部化
- 持久 value 去 slot 化，改成更明确的顶层 typed value

### 第三阶段

- 在新的 emit/storage 形态下重新调 supernode 最大 op
- 重新观察 supernode 规模、batch 体积、编译时间和运行时 perf

## 验收思路

这轮更关注趋势和结构改进，而不是单一硬指标。

希望看到的结果包括：

- 外露的 `eval_batch_*` 形态消失，对外收敛为 `subStepN()`
- emitted cpp 文件数明显下降
- `value_*_slots_[]` 的静态访问量明显下降
- 热点 `subStep` 本体的 perf 占比下降
- 单次 `eval` 的平均耗时有持续改善趋势

## 约束

- 不能破坏现有 `grhsim` 的执行语义
- 不能为了减少 slot 而错误跨越 side-effect / commit / event 边界
- 代码中不要把“计划术语”直接写进实现逻辑
