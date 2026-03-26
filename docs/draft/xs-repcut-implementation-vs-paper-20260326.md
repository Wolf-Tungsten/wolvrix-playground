# XiangShan RepCut 现有实现与 RepCut 论文的运行时差异分析（2026-03-26）

## 1. 目的

本文对比：

- 论文 [tmp/repcut_2023.txt](/workspace/wolvrix-playground/tmp/repcut_2023.txt) 中描述的 RepCut 运行时模型
- `tmp/essent` 中的原始 RepCut / ESSENT 实现
- 当前 Wolvrix `repcut pass` 生成的 wrapper / runtime 逻辑

重点分析三部分：

1. `scatter`
2. `gather`
3. `writeback`

以及它们背后的数据模型和同步模型。

## 2. 分析范围与口径

本文分析分两层：

- `tmp/essent` 中原始 RepCut 代码生成器如何实现运行时
- Wolvrix 当前 `repcut` pass 如何重建 wrapper graph，以及 `emit-verilator-repcut-package` 如何生成 C++ runtime

对应源码主要是：

- [tmp/essent/src/main/scala/Compiler.scala](/workspace/wolvrix-playground/tmp/essent/src/main/scala/Compiler.scala)
- [tmp/essent/src/main/scala/Emitter.scala](/workspace/wolvrix-playground/tmp/essent/src/main/scala/Emitter.scala)

- [wolvrix/lib/transform/repcut.cpp](/workspace/wolvrix-playground/wolvrix/lib/transform/repcut.cpp)
- [wolvrix/lib/emit/verilator_repcut_package.cpp](/workspace/wolvrix-playground/wolvrix/lib/emit/verilator_repcut_package.cpp)

当前 workspace 中没有现成生成好的 `wolvi_repcut_verilator_sim*.cpp` 成品文件，因此对 Wolvrix 的部分仍然是“生成模板语义”分析；但对 `tmp/essent`，本文已经直接检查了原始实现代码，而不是只依赖论文文字。

## 3. 论文中的运行时模型

论文对 RepCut 的核心表述有两层。

### 3.1 分区原则

论文明确说，RepCut 通过复制 overlap 的组合逻辑，去掉不经过寄存器的跨分区依赖：

- “only replicate combinational logic nodes”
- “we have shared memory and thus have no need to copy data”

对应原文位置：

- [tmp/repcut_2023.txt:721](/workspace/wolvrix-playground/tmp/repcut_2023.txt#L721)

这意味着论文模型的关键点是：

1. 复制的是组合计算，不是状态数据。
2. 状态数据位于 shared global memory。
3. 跨分区通信被压缩为跨周期的状态更新，而不是周期内的信号来回传递。

### 3.2 每周期执行模型

论文把每个 simulated cycle 切成两个 barrier 分隔的阶段：

1. `Evaluation Phase`
2. `Global Update Phase`

对应原文：

- [tmp/repcut_2023.txt:1053](/workspace/wolvrix-playground/tmp/repcut_2023.txt#L1053)
- [tmp/repcut_2023.txt:1082](/workspace/wolvrix-playground/tmp/repcut_2023.txt#L1082)
- [tmp/repcut_2023.txt:1100](/workspace/wolvrix-playground/tmp/repcut_2023.txt#L1100)

论文中的语义是：

- `Evaluation Phase`：
  - 每个线程从 global copy 读取寄存器和内存状态
  - 在线程私有 local copy 中写出 next-state
  - memory write request 先延迟缓存
- `Evaluation Barrier`
- `Global Update Phase`：
  - 每个线程把 local copy 覆盖回 global copy
  - 执行 deferred memory write
- `Global Update Barrier`

此外，论文强调：

- global state 按线程写入区域做 contiguous layout
- 用 padding 避免 false sharing
- local -> global 提交可以利用 `memcpy` 风格的连续拷贝

对应原文：

- [tmp/repcut_2023.txt:1065](/workspace/wolvrix-playground/tmp/repcut_2023.txt#L1065)
- [tmp/repcut_2023.txt:1086](/workspace/wolvrix-playground/tmp/repcut_2023.txt#L1086)
- [tmp/repcut_2023.txt:2323](/workspace/wolvrix-playground/tmp/repcut_2023.txt#L2323)

## 4. `tmp/essent` 中的原始 RepCut 实现

这部分用于确认论文里的两阶段模型在原始代码中是否真的存在。

### 4.1 ESSENT 明确是 two-phase state update 体系

`README.md` 已经直接说明：

- 无优化的 Essent 使用 two-phase update
- RepCut 分支是 parallel version of Essent

对应位置：

- [tmp/essent/README.md:6](/workspace/wolvrix-playground/tmp/essent/README.md#L6)
- [tmp/essent/README.md:11](/workspace/wolvrix-playground/tmp/essent/README.md#L11)

因此，从代码库定位上，RepCut 不是独立于 Essent 状态机之外的一套模型，而是建立在 Essent 的 state/update 机制上。

### 4.2 原始 RepCut 的 global state 布局

`Compiler.scala` 会生成 `DesignData`，把寄存器和 memory 放进统一的数据结构中。

关键的是，寄存器布局会：

- 按 `writer part / reader part` 重新分组
- 每个 writer part 结尾插入 `padding_*`
- 为每个 part 定义 `PART_*_DATA_HEAD` / `PART_*_DATA_LAST`

对应代码：

- [tmp/essent/src/main/scala/Compiler.scala:95](/workspace/wolvrix-playground/tmp/essent/src/main/scala/Compiler.scala#L95)
- [tmp/essent/src/main/scala/Compiler.scala:165](/workspace/wolvrix-playground/tmp/essent/src/main/scala/Compiler.scala#L165)
- [tmp/essent/src/main/scala/Compiler.scala:177](/workspace/wolvrix-playground/tmp/essent/src/main/scala/Compiler.scala#L177)
- [tmp/essent/src/main/scala/Compiler.scala:204](/workspace/wolvrix-playground/tmp/essent/src/main/scala/Compiler.scala#L204)

这和论文里的：

- contiguous per-thread segment
- padding 避免 false sharing

是直接对应的。

### 4.3 原始 RepCut 的 Evaluation Phase

原始 RepCut 为每个 partition 生成：

- `eval_tp_<pid>()`
- `sync_tp_<pid>()`

其中 `eval_tp_<pid>()` 对应 evaluation 阶段：

- `RegUpdate` 写入 thread-local register data
- `MemWrite` 不立即更新 global memory，而是先写到 thread-local write request 变量

对应代码：

- `eval_tp_<pid>()` 定义：
  - [tmp/essent/src/main/scala/Compiler.scala:1179](/workspace/wolvrix-playground/tmp/essent/src/main/scala/Compiler.scala#L1179)
- thread-local memory write buffering：
  - [tmp/essent/src/main/scala/Compiler.scala:533](/workspace/wolvrix-playground/tmp/essent/src/main/scala/Compiler.scala#L533)
- thread-local register next-state：
  - [tmp/essent/src/main/scala/Compiler.scala:541](/workspace/wolvrix-playground/tmp/essent/src/main/scala/Compiler.scala#L541)

这与论文的：

- local copy
- deferred memory write request

完全一致。

### 4.4 原始 RepCut 的 Global Update Phase

`sync_tp_<pid>()` 对应论文里的 Global Update Phase。

对应代码：

- [tmp/essent/src/main/scala/Compiler.scala:1196](/workspace/wolvrix-playground/tmp/essent/src/main/scala/Compiler.scala#L1196)

在 `writeSyncBody()` 中：

- 对该 part 的寄存器连续区间执行 `std::memcpy`
- 再把 thread-local memory write request 提交到 global memory

对应代码：

- contiguous register segment memcpy：
  - [tmp/essent/src/main/scala/Compiler.scala:493](/workspace/wolvrix-playground/tmp/essent/src/main/scala/Compiler.scala#L493)
- global memory write commit：
  - [tmp/essent/src/main/scala/Compiler.scala:503](/workspace/wolvrix-playground/tmp/essent/src/main/scala/Compiler.scala#L503)

这说明论文中的 Global Update 并不是抽象口号，而是原始代码里的真实执行阶段。

### 4.5 原始 RepCut 的同步模型

原始 RepCut 的 worker 线程入口是：

1. 等待 `eval token`
2. 执行 `eval_tp_<tid>()`
3. 等待 `sync token`
4. 执行 `sync_tp_<tid>()`

对应代码：

- [tmp/essent/src/main/scala/Compiler.scala:328](/workspace/wolvrix-playground/tmp/essent/src/main/scala/Compiler.scala#L328)

顶层 `eval()` 则：

1. 唤醒所有 worker 进入 eval
2. 主线程执行 `eval_tp_0()`
3. 等待所有 worker eval 完成
4. 唤醒所有 worker 进入 sync
5. 主线程执行 `sync_tp_0()`
6. 等待所有 worker sync 完成

对应代码：

- [tmp/essent/src/main/scala/Compiler.scala:1208](/workspace/wolvrix-playground/tmp/essent/src/main/scala/Compiler.scala#L1208)
- [tmp/essent/src/main/scala/Compiler.scala:1218](/workspace/wolvrix-playground/tmp/essent/src/main/scala/Compiler.scala#L1218)
- [tmp/essent/src/main/scala/Compiler.scala:1231](/workspace/wolvrix-playground/tmp/essent/src/main/scala/Compiler.scala#L1231)
- [tmp/essent/src/main/scala/Compiler.scala:1240](/workspace/wolvrix-playground/tmp/essent/src/main/scala/Compiler.scala#L1240)
- [tmp/essent/src/main/scala/Compiler.scala:1246](/workspace/wolvrix-playground/tmp/essent/src/main/scala/Compiler.scala#L1246)

因此，原始 ESSENT / RepCut 的实际执行模型确实是：

- eval phase
- barrier-like wait
- sync/global-update phase
- barrier-like wait

## 5. 当前 Wolvrix 实现的运行时模型

当前实现可以分成两层看。

### 5.1 `repcut pass` 重建的 wrapper graph

`repcut` pass 在 phase-e 中：

- 为每个分区生成独立的 `*_repcut_part*` graph
- 在重建后的 top wrapper 中，为跨分区 value 建立 `repcut_link_*` value
- 再把每个 part 作为实例接回 top wrapper

关键代码位置：

- 创建 top-level cross link values：
  - [wolvrix/lib/transform/repcut.cpp:5204](/workspace/wolvrix-playground/wolvrix/lib/transform/repcut.cpp#L5204)
- 用这些 link value 连接各 part 的输入输出：
  - [wolvrix/lib/transform/repcut.cpp:5350](/workspace/wolvrix-playground/wolvrix/lib/transform/repcut.cpp#L5350)
  - [wolvrix/lib/transform/repcut.cpp:5370](/workspace/wolvrix-playground/wolvrix/lib/transform/repcut.cpp#L5370)
  - [wolvrix/lib/transform/repcut.cpp:5512](/workspace/wolvrix-playground/wolvrix/lib/transform/repcut.cpp#L5512)

这说明当前 pass 的边界模型是：

- 跨分区值被显式建模成 wrapper 中的“连线 value”
- 分区之间仍然通过显式 input/output port 交互

它不是论文里的“共享全局状态数组”，而是“显式边界信号网络”。

### 5.2 当前 emitter 生成的 runtime

runtime 侧会为每条 `unit_to_unit` 边界连线生成两份缓存：

- `signal_*_snapshot_`
- `signal_*_writeback_`

代码位置：

- [wolvrix/lib/emit/verilator_repcut_package.cpp:1362](/workspace/wolvrix-playground/wolvrix/lib/emit/verilator_repcut_package.cpp#L1362)

每个 normal part 的执行函数结构是：

1. `scatter`
2. `eval`
3. `gather`

代码位置：

- [wolvrix/lib/emit/verilator_repcut_package.cpp:1113](/workspace/wolvrix-playground/wolvrix/lib/emit/verilator_repcut_package.cpp#L1113)

整个 step 的结构是：

1. 所有 part 执行 fused `scatter/eval/gather`
2. 全部完成后，统一执行 `commit_writeback_()`

代码位置：

- [wolvrix/lib/emit/verilator_repcut_package.cpp:1748](/workspace/wolvrix-playground/wolvrix/lib/emit/verilator_repcut_package.cpp#L1748)

因此，当前实现的实际模型是：

- 读端从 `snapshot` 读边界值
- 每个 part 在本地对象上执行 `eval()`
- 写端把结果写入 `writeback`
- step 末尾把 `writeback` 批量提交到下一周期的 `snapshot`

这本质上是一个“边界信号双缓冲”模型。

## 6. `scatter / gather / writeback` 的逐项差异

## 5.1 `scatter`

当前代码里的 `scatter`：

- 如果驱动来自 top input，则直接把 top input 成员拷到 unit input
- 如果驱动来自其他 unit，则从 `signal_*_snapshot_` 拷到 unit input
- 如果驱动来自常量，则把常量缓存拷到 unit input

代码位置：

- `snapshot` 作为 unit 输入源：
  - [wolvrix/lib/emit/verilator_repcut_package.cpp:969](/workspace/wolvrix-playground/wolvrix/lib/emit/verilator_repcut_package.cpp#L969)
  - [wolvrix/lib/emit/verilator_repcut_package.cpp:976](/workspace/wolvrix-playground/wolvrix/lib/emit/verilator_repcut_package.cpp#L976)
- 每个 part 执行前做 scatter：
  - [wolvrix/lib/emit/verilator_repcut_package.cpp:1121](/workspace/wolvrix-playground/wolvrix/lib/emit/verilator_repcut_package.cpp#L1121)

原始 ESSENT / 论文里的对应阶段：

- 线程直接从 shared global state 读 register / memory value
- 并不存在一个显式的“先把边界信号灌进每个 partition input port”的散播阶段

对应原文：

- [tmp/repcut_2023.txt:1075](/workspace/wolvrix-playground/tmp/repcut_2023.txt#L1075)
- [tmp/repcut_2023.txt:1100](/workspace/wolvrix-playground/tmp/repcut_2023.txt#L1100)

结论：

- 当前 `scatter` 是“端口级输入装载”
- 原始 ESSENT / 论文模型没有这一步，它是“共享状态直接读取”

所以当前 `scatter` 不是论文概念里的独立阶段，而是 wrapper 为显式边界端口额外引入的运行时开销。

## 5.2 `gather`

当前代码里的 `gather`：

- `unit_to_unit` 输出不会立即写回 `snapshot`
- 而是先写到 `signal_*_writeback_`
- `unit_to_top` 输出则直接更新 top output 成员

代码位置：

- 输出写入 `writeback`：
  - [wolvrix/lib/emit/verilator_repcut_package.cpp:1037](/workspace/wolvrix-playground/wolvrix/lib/emit/verilator_repcut_package.cpp#L1037)
  - [wolvrix/lib/emit/verilator_repcut_package.cpp:1055](/workspace/wolvrix-playground/wolvrix/lib/emit/verilator_repcut_package.cpp#L1055)
- top output 直写：
  - [wolvrix/lib/emit/verilator_repcut_package.cpp:1067](/workspace/wolvrix-playground/wolvrix/lib/emit/verilator_repcut_package.cpp#L1067)
- 每个 part 在 `eval()` 后做 gather：
  - [wolvrix/lib/emit/verilator_repcut_package.cpp:1131](/workspace/wolvrix-playground/wolvrix/lib/emit/verilator_repcut_package.cpp#L1131)

原始 ESSENT / 论文里的对应阶段：

- 线程把 next-state 写入 local copy
- memory writes 只是延迟记录
- 论文没有一个与当前 `gather` 对应的“边界端口发布”概念

对应原文：

- [tmp/repcut_2023.txt:1100](/workspace/wolvrix-playground/tmp/repcut_2023.txt#L1100)

结论：

- 当前 `gather` 的本质是“采样并暂存 partition 输出边界值”
- 原始 ESSENT / 论文中的对应动作是“把 next-state 留在线程本地私有状态里”

两者都在“先不立刻对外可见”这一点上相似，但存储对象完全不同：

- 当前实现存的是边界信号缓存
- 论文存的是线程私有状态副本

## 5.3 `writeback`

当前代码里的 `writeback`：

- 在 step 末尾调用 `commit_writeback_()`
- 把每条跨分区边界的 `writeback` 缓存拷回 `snapshot`
- 供下一周期的 `scatter` 使用

代码位置：

- 生成 writeback 赋值：
  - [wolvrix/lib/emit/verilator_repcut_package.cpp:1148](/workspace/wolvrix-playground/wolvrix/lib/emit/verilator_repcut_package.cpp#L1148)
- `snapshot = writeback`：
  - [wolvrix/lib/emit/verilator_repcut_package.cpp:1153](/workspace/wolvrix-playground/wolvrix/lib/emit/verilator_repcut_package.cpp#L1153)
- 统一 commit：
  - [wolvrix/lib/emit/verilator_repcut_package.cpp:1477](/workspace/wolvrix-playground/wolvrix/lib/emit/verilator_repcut_package.cpp#L1477)
  - [wolvrix/lib/emit/verilator_repcut_package.cpp:1758](/workspace/wolvrix-playground/wolvrix/lib/emit/verilator_repcut_package.cpp#L1758)

原始 ESSENT / 论文里的 Global Update Phase：

- 线程把 local copy 覆盖回 shared global copy
- 同时执行 deferred memory writes
- 然后再过一个 barrier

对应原文：

- [tmp/repcut_2023.txt:1053](/workspace/wolvrix-playground/tmp/repcut_2023.txt#L1053)
- [tmp/repcut_2023.txt:1103](/workspace/wolvrix-playground/tmp/repcut_2023.txt#L1103)

结论：

- 当前 `writeback` 只是“边界缓存提交”
- 原始 ESSENT / 论文里的 `Global Update` 是“完整状态提交”

这是两者最大的语义差异之一。

## 7. 数据模型差异

原始 ESSENT / 论文的数据模型是：

- 一个 shared global state
- 每线程一个 local private next-state
- register/memory 是显式状态对象
- global update 是 local -> global 的状态覆盖

当前 Wolvrix 实现的数据模型是：

- top input / top output 成员
- 每个 part 一个 Verilated model 实例
- 每条跨分区边界一个 `snapshot/writeback` 双缓冲缓存

这说明当前系统并没有实现论文强调的：

1. shared global state 数组
2. contiguous per-thread state layout
3. padding 避免 false sharing
4. `memcpy` 风格 local -> global update

而是实现成了：

1. 显式 wrapper 连线
2. 显式 port-level copy
3. 信号级双缓冲提交

## 8. 同步模型差异

原始 ESSENT / 论文强调的是“每周期两次 barrier”的线程相位模型：

1. Evaluation barrier
2. Global update barrier

对应原文：

- [tmp/repcut_2023.txt:1103](/workspace/wolvrix-playground/tmp/repcut_2023.txt#L1103)
- [tmp/repcut_2023.txt:1108](/workspace/wolvrix-playground/tmp/repcut_2023.txt#L1108)

当前 Wolvrix 代码的线程模型是：

- worker 被唤醒
- 每个 worker 处理自己负责的一组 part
- part 内部自己做 `scatter -> eval -> gather`
- 主线程等待所有 worker 完成
- 再统一做一次 `commit_writeback_()`

代码位置：

- worker 调度：
  - [wolvrix/lib/emit/verilator_repcut_package.cpp:1541](/workspace/wolvrix-playground/wolvrix/lib/emit/verilator_repcut_package.cpp#L1541)
  - [wolvrix/lib/emit/verilator_repcut_package.cpp:1561](/workspace/wolvrix-playground/wolvrix/lib/emit/verilator_repcut_package.cpp#L1561)
  - [wolvrix/lib/emit/verilator_repcut_package.cpp:1573](/workspace/wolvrix-playground/wolvrix/lib/emit/verilator_repcut_package.cpp#L1573)

因此当前实现更像：

- 一次“part batch 完成”的同步
- 然后一次“单线程 writeback 提交”

它没有论文那种：

- 明确的线程并行 global update phase
- 第二个 barrier 上的线程对称提交行为

## 9. 哪些地方仍然继承了论文思路

虽然 runtime 差异很大，但 `repcut pass` 仍然保留了论文的一个核心方向：尽量把跨分区依赖限制在跨周期边界。

当前 phase-e 的 cross-partition 检查规则是：

- `kRegisterReadPort` / `kLatchReadPort`：允许跨分区，且需要端口
- `kMemoryReadPort`：不允许跨分区
- `kConstant`：允许跨分区，不需要端口
- top input/inout input：允许跨分区，且需要端口
- 一般组合值：默认不允许跨分区

代码位置：

- [wolvrix/lib/transform/repcut.cpp:4243](/workspace/wolvrix-playground/wolvrix/lib/transform/repcut.cpp#L4243)
- [wolvrix/lib/transform/repcut.cpp:4253](/workspace/wolvrix-playground/wolvrix/lib/transform/repcut.cpp#L4253)
- [wolvrix/lib/transform/repcut.cpp:4272](/workspace/wolvrix-playground/wolvrix/lib/transform/repcut.cpp#L4272)
- [wolvrix/lib/transform/repcut.cpp:4431](/workspace/wolvrix-playground/wolvrix/lib/transform/repcut.cpp#L4431)

这说明当前实现依然遵循：

- 通过分区和复制，把周期内组合依赖切断
- 把 surviving cross-partition interaction 尽量收敛到边界状态/端口

这一点和论文目标是一致的。

## 10. 最关键的偏离点

把差异压缩成一句话：

- 原始 ESSENT / 论文实现是：

- `RepCut partitioning + shared-state two-phase simulator`

- 当前 Wolvrix 实现是：

- `RepCut partitioning + explicit wrapper wiring + signal-level double buffering`

更具体地说，当前 Wolvrix 相对原始 ESSENT / 论文偏离最大的地方有四个：

1. 论文不需要复制数据，只复制组合逻辑；当前实现显式复制了跨分区边界信号缓存。
2. 论文的 Evaluation 直接读 shared global state；当前实现先做 port-level `scatter`。
3. 论文的 Global Update 提交的是完整状态；当前实现的 `writeback` 只提交边界缓存。
4. 论文强调 per-thread contiguous memory layout 和 false-sharing 控制；当前实现没有这套 shared-state 内存布局。

## 11. 对性能分析的含义

这份差异分析可以直接解释为什么当前 profiling 中会出现明显的：

- `scatter` 热点
- `gather` 热点
- `writeback` 热点

因为这些开销中有相当一部分并不是论文原始模型中的“状态读取 / 状态提交”成本，而是当前 wrapper 形式额外引入的：

- port copy
- signal cache copy
- `snapshot/writeback` 双缓冲维护

尤其是：

- `scatter` 本质上是显式输入装载
- `gather` 本质上是边界输出采样
- `writeback` 本质上是边界缓存提交

这些都比论文里的 shared-state phase model 更偏“信号搬运”。

## 12. 结论

结合 `tmp/essent` 的实际代码后，可以把结论说得更准确：

1. 论文中的两阶段执行模型在 `tmp/essent` 中是有直接代码实现的，不只是论文描述。
2. 原始 ESSENT / RepCut 的核心运行时确实是 `eval_tp + sync_tp`、thread-local next-state、global-state memcpy/update。
3. 当前 Wolvrix 在分区原则上继承了 RepCut，但运行时已经换成了 wrapper 端口网络和 `snapshot/writeback` 双缓冲。
4. 因此当前系统中测到的 `scatter/gather/writeback`，不能直接等同于原始 ESSENT / 论文中的 `Evaluation/Global Update`。

如果后续目标是进一步向论文靠拢，最关键的不是继续微调单个 `scatter` 或 `gather` copy，而是重新审视是否要把当前 runtime 从：

- signal-level wrapper buffering

转向：

- shared-state two-phase update

那会是一次运行时模型级别的改动，而不是局部优化。
