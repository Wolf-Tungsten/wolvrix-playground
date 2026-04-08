# GrhSIM Cpp Emit 草案

## 1. 目标

### 1.1 目标产物

`cpp emit` 消费单个已规范化的 GRH graph 及其 `activity-schedule` 结果，生成 GrhSIM 单线程仿真器的 C++ 源码与配套构建文件。

生成结果需要满足：

1. 以极致仿真性能为首要目标。
2. 直接服务 GrhSIM 的用户接口：通过与端口同名的 `public` 成员访问输入、输出与 `inout` 接口，并提供 `set_random_seed()`、`init()`、`eval()`。
3. 支持任意位宽 GRH value。
4. 代码量可扩展到大设计，不因单文件过大导致编译器性能恶化。

### 1.2 输入前提

输入 graph 满足：

- 已展平
- 无 XMR
- 无 blackbox
- 无组合逻辑环
- 已完成 `activity-schedule`
- 已完成 `latch-transparent-read`

`cpp emit` 依赖以下 session 数据：

- `<path>.activity_schedule.supernode_to_ops`
- `<path>.activity_schedule.op_to_supernode`
- `<path>.activity_schedule.dag`
- `<path>.activity_schedule.topo_order`
- `<path>.activity_schedule.head_eval_supernodes`
- `<path>.activity_schedule.supernode_event_domains`
- `<path>.activity_schedule.op_event_domains`
- `<path>.activity_schedule.value_event_domains`

### 1.3 非目标

本文不讨论：

- 多线程执行模型
- 外部 JIT
- 与 Verilator 兼容的源码风格

## 2. 总体结构

### 2.1 生成结果

`cpp emit` 输出一组 C++ 编译单元，而不是单个巨型 `.cpp` 文件。核心文件层次：

1. `grhsim_<top>.hpp`
   - 对外类定义
   - 公共类型
   - 状态/活动度布局

2. `grhsim_<top>_runtime.hpp`
   - 位宽辅助类型
   - 宽位运算 helper
   - 小型内联工具

3. `grhsim_<top>_state.cpp`
   - 构造
   - reset/init
   - 输入输出接口
   - `commit_state_updates()`

4. `grhsim_<top>_eval.cpp`
   - `eval()`
   - event-domain 命中计算
   - 首批活动度置位
   - 编译单元级调度入口

5. `grhsim_<top>_sched_<n>.cpp`
   - 一批连续 `supernode` 的求值代码
   - 批内 guard 检查与活动传播

### 2.2 运行时对象模型

生成一个顶层类，例如 `GrhSIM_<top>`，内部包含：

- 输入镜像区
- 输出镜像区
- 当前状态区
- 按 write-port 粒度的状态更新区
- side-effect staging 区
- random seed / random state
- 活动度位图
- event-term 命中位图
- event-domain 命中位图
- 常量区

状态更新区以 write-port 为基本执行单元，而不是按 `kRegister/kMemory/kLatch` 只保留一个抽象 `next-state` 槽。这样才能保留 GRH IR 中多写口、多事件、异步复位拆分后的语义。

`init()` 在首次 `eval()` 前显式调用，用于物化 declaration init、`$random` 初值、memory 内嵌初始化，并建立 `prev_input` / `prev_event` 基线。`eval()` 热路径不承担初始化判断。

热路径要求：

- 无虚函数
- 无异常
- 无动态分配
- 无 `std::vector` 热路径扩容
- 无逐 op 间接分发

## 3. 执行模型

### 3.1 单周期执行

`eval()` 的基本流程：

1. 采集输入变化
2. 对事件值做精确求值；在不超过阈值时额外预计算 `event-term-hit`
3. 由 `event-term-hit` 归约得到本次 `event-domain-set-hit`
4. 首次 `eval()` 直接激活静态入口 `supernode`；后续 `eval()` 按输入变化和上一次 `eval()` 提交后记录的状态变化激活相关入口 `supernode`
5. 按 `topo_order` 执行 `supernode`
6. 执行并提交 write-port / `kSystemTask` / `kDpicCall`
7. 记录下一次 `eval()` 入口所需的状态变化信息
8. 刷新输出镜像

单次 `eval()` 内只进行一次前向求值。`commit_state_updates()` 写入的新状态只对下一次 `eval()` 可见，不在本次 `eval()` 内触发第二轮组合传播。

### 3.2 Supernode 执行

每个 `supernode` 的执行模型：

```text
if (event_domain_hit && activity_bit) {
    clear_activity_bit();
    eval_ops_in_supernode();
    propagate_activity_to_successors();
}
```

生成代码时不做逐 op 通用调度器。每个 `supernode` 直接展开为一段连续代码。活动位按 singular BFS / worklist 方式消耗；一个 `supernode` 在一次 `eval()` 中至多执行一次。

### 3.3 事件相关 op 执行

GRH IR 中以下 op 直接承载复杂时序语义：

- `kRegisterWritePort`
- `kMemoryWritePort`
- `kLatchWritePort`
- `kSystemTask`
- `kDpicCall`

emit 需要保留它们的 write/call 粒度，不提前把多个事件域、多个 write-port 折叠成单一“寄存器更新动作”。

对 `kRegisterWritePort` 和 `kMemoryWritePort`：

- `eventEdge` 可以包含多个事件项
- 同一存储对象可以拥有多个 write-port
- reset / enable 优先级已编码在 `updateCond` 与 `nextValue` 相关组合逻辑中
- 若同一 `eval()` 中同一存储对象的多个 write-port 同时生效，GrhSIM 不保证提交顺序；该行为直接暴露 RTL 本身的竞争风险

当前实现中，`kMemoryWritePort` 的提交路径进一步做以下专门化：

- 写地址在 `supernode` 求值时先归一化为待提交行号
- 若 `rowCount` 是 2 的幂，行号直接走低位掩码
- 若地址位宽可静态证明不越界，行号直接走无比较路径
- 其他情况走通用索引 helper；越界写入按 no-op 处理
- 常量全 0 mask 直接消去该写口的实际提交
- 常量全 1 mask 走整行覆盖路径
- 动态宽位 mask 走原地 word masked apply，不再先构造临时 merged 值

对 `kSystemTask` 和 `kDpicCall`：

- `eventEdge` 仅描述触发边沿
- `procKind`、`hasTiming` 仍影响其运行时行为与调度位置

`kSystemTask` 进一步按以下规则执行：

- `initial + !hasTiming` 仅在第一次 `eval()` 中执行
- `initial + hasTiming`、`always*` 仍按 `callCond && exactEventExpr` 执行
- `final` 不进入常规 `eval()` 路径，在析构阶段统一执行
- `display/write/strobe`、`info/warning/error/fatal`、`finish/stop`、`dumpfile/dumpvars`、`fwrite/fdisplay/fflush/fclose` 已支持
- 文本输出采用 SystemVerilog 风格格式化；已覆盖常用 `%d/%u/%h/%x/%b/%o/%s/%c/%f/%e/%g/%t/%%`
- `strobe` 在本次 `eval()` 的状态提交后统一刷新
- `fatal/finish/stop` 在运行时记录退出码，并在刷新输出、执行 `final`、关闭文件句柄后直接终止宿主进程
- `dumpfile/dumpvars` 当前记录运行时配置，不在本阶段生成波形文件
- 文件句柄由 GrhSIM 运行时内部维护，不暴露宿主预绑定接口
- `kSystemFunction($fopen)` 负责创建文件句柄；`0` 表示打开失败，`1/2` 预留为 `stdout/stderr`，运行时新分配句柄从 `3` 开始
- `fwrite/fdisplay/fflush/fclose` 统一消费该句柄表；`fflush()` 无参时刷新 `stdout/stderr` 与全部已打开文件，`fclose(handle)` 关闭对应表项并释放句柄
- `kSystemFunction($ferror)` 若进入输入范围，与 `$fopen` 和文件类 system task 共用同一文件表项状态

`kDpicCall` 进一步按以下规则执行：

- 已覆盖 `input/output/return`
- 已覆盖 `Logic/Real/String` 参数与结果
- 已覆盖宽位 `Logic` 输入/输出
- call 实参与结果按 `kDpicImport` 名字匹配，不依赖 call 内部顺序与 import 顺序一致
- emit 阶段会校验 `targetImportSymbol`、参数分组、结果个数、类型位宽、`eventEdge` 与事件输入个数
- `inout` 不在当前输入范围内，出现即报错

对 `kLatchWritePort`：

- 没有 `eventEdge`
- 语义是 `always_latch`
- 透明读语义已由 `latch-transparent-read` 前置规整，emit 只需处理显式化后的读写关系

对超出预计算阈值的 `event-domain`：

- 仅放弃 guard 侧的 event-domain 预计算优化
- 相关 `supernode` 在 guard 上按该 domain 恒命中处理
- `kRegisterWritePort` / `kMemoryWritePort` / `kSystemTask` / `kDpicCall` 仍需在其自身代码路径中按精确事件谓词决定是否生效

### 3.4 批执行

为降低函数调用和编译器 IR 规模，调度以“批”为单位发射：

- 一个批包含一段连续 `supernode`
- 一个批对应一个 `eval_batch_<n>()`
- 当前实现中，一个批对应一个 `grhsim_<top>_sched_<n>.cpp`
- 切分参数由 `sched_batch_max_ops` 与 `sched_batch_max_estimated_lines` 控制
- `sched_<n>.cpp` 的发射可由 `emit_parallelism` 并行执行

顶层 `eval()` 调用顺序固定：

```text
eval_batch_0();
eval_batch_1();
...
eval_batch_k();
```

## 4. 数据表示

### 4.1 Logic 值的分层位宽表示

Logic 类型的任意位宽不采用单一大整数类型。按宽度分层：

1. `1..64 bit`
   - 直接用 `uint64_t`

2. `65..128 bit`
   - 用两个 `uint64_t`

3. `129..256 bit`
   - 用固定长度 `uint64_t[N]`
   - 优先让编译器展开

4. `>256 bit`
   - 用连续 word buffer
   - 配合 helper 按 word 循环

核心原则：

- 热门小位宽走标量 fast path
- 中等位宽走固定长度 fast path
- 超宽位宽走通用 word path
- 当前实现中，`slice` / `concat` / `replicate` / `shift` 相关宽位 helper 已优先走按 word 路径，避免逐 bit 搬运
- 当前实现中，宽位 `mul/div/mod` 已补入单字操作数 fast path
- 当前实现中，宽位 `mul/div/mod` 对任意位宽 power-of-two 操作数已补入移位 fast path
- 当前实现中，`65..128 bit` 的 `add/sub/compare/mul/div/mod` 已补入 `unsigned __int128` fast path

### 4.2 Logic/Real/String 表示

GRH `ValueType` 不只有位向量，还包括：

- `Logic`
- `Real`
- `String`

因此运行时数据表示不能只覆盖二态位向量。

对 `Logic`：

- 全部按二值逻辑处理
- 小宽走标量或定长 word fast path
- 宽位走通用 word helper

对 `Real`：

- 直接映射到原生浮点存储
- DPI / system task 实参按 `Real` 路径传递

对 `String`：

- 只在确有使用的 value 上分配存储
- 不进入位向量 helper
- 主要服务 `kSystemTask` / `kDpicCall`

### 4.3 Value 存储

每个 GRH value 在 emit 后对应一个确定存储位点：

- 小宽二态值：标量成员或批局部临时
- 中宽值：固定成员数组
- 超宽值：统一 arena 上的固定偏移
- `Real/String`：独立类型存储槽

不在运行时为 value 建对象。value 只是静态偏移和类型信息。

### 4.4 宽位规范化

所有结果写回前必须做宽度规范化：

- `<=64 bit`：按 mask 截断
- `>64 bit`：最后一个 word 按高位 mask 截断

这样可保证：

- 比较语义稳定
- 有符号操作的高位不污染
- 活动度比较可直接按存储位宽做 word compare

### 4.5 有符号语义

位模式与 signedness 分离。signedness 只影响：

- 有符号比较
- 算术右移
- 除法 / 取模
- 扩展语义

普通按位运算、拼接、切片、活动度比较都按原始位模式执行。

## 5. 运算发射

### 5.1 发射原则

每类 op 至少提供两级实现：

1. 小位宽内联 fast path
2. 宽位 helper path

对 `Logic` 类型，进一步区分：

1. 二态 fast path
2. 宽位 helper path

生成代码优先写成目标值原位更新，减少临时对象。

### 5.2 常见运算策略

- `kAssign`
  - 标量直接赋值
  - 宽位走 `copy_words`

- `kConcat`
  - 小宽度直接移位拼接
  - 宽位按片段拷贝到目标 bit range

- `kSliceStatic`
  - 常量边界直接编译成移位/掩码或 word copy

- `kSliceDynamic`
  - 小宽度用分支较少的 shift-mask
  - 宽位用通用 bit extractor

- `kMux`
  - 标量用三目
  - 宽位按条件选择源 buffer

- 比较类
  - 标量直接比较
  - 宽位从高 word 到低 word 比较

- 逻辑/位运算
  - 标量直接运算
  - 宽位按 word 循环

- `kAdd/kSub`
  - 标量直接运算
  - 宽位用 carry/borrow 链

- 移位类
  - 常量移位优先静态展开
  - 变量移位走 word-shift + intra-word shift

- reduction
  - 标量走 builtin
  - 宽位分 word 归约

- `Real`
  - 直接映射到原生浮点运算

- `String`
  - 不参与位向量 helper
  - 仅在相关 op 中按专用路径处理

### 5.3 大位宽辅助库

运行时 helper 需要足够小而专，不引入通用 bigint 依赖。最少包括：

- `copy_words`
- `clear_words`
- `equal_words`
- `and/or/xor/not_words`
- `add_words`
- `sub_words`
- `cmp_unsigned_words`
- `cmp_signed_words`
- `shift_left_words`
- `shift_right_logical_words`
- `shift_right_arith_words`
- `extract_bits`
- `insert_bits`

helper 设计原则：

- API 面向固定 `uint64_t*`
- 不分配内存
- 不隐藏宽度规范化
- 允许 emit 端在已知宽度下直接绕过 helper

## 6. 活动度实现

### 6.1 活动度存储

活动度按 `supernode` 编号存成紧凑 bitset：

- `supernode_active_curr`

`supernode` 在被取出执行时立即清掉自身活动位。若本节点求值导致跨 `supernode` 边界的输入值发生变化，则对其后继 `supernode` 置位。

### 6.2 值变化判定

活动传播的根本条件是“某个后继读取到的输入 value 被修改”。发射时需要为每条跨 `supernode` 边记录传播规则：

- 二态标量值：`old != new`
- 宽位值：按对应 helper 比较

`activity-schedule` 需要输出 `boundary value -> succ supernode` 的 fanout 信息。emit 时只在该 `boundary value` 真实变化后激活对应后继，不能用“当前 supernode 内任意值变化就激活全部 DAG 后继”的粗粒度规则代替。

对同一后继 `supernode`，多个输入变化可 OR 到同一个活动位。

### 6.3 声明类 op 上的活动度传播

`kRegister`、`kMemory`、`kLatch` 自身不参与组合调度，但活动度必须跨越它们的声明语义传播。

传播分两类：

1. 同周期组合传播
   - 不穿越声明 op
   - 组合路径只在 read-port 结果到 write-port 输入之间传播

2. 跨周期状态传播
   - `kRegisterWritePort` / `kMemoryWritePort` 在提交后更新声明类存储
   - 若声明类存储内容发生变化，则记录对应 `head-eval supernode` 为下一次 `eval()` 的入口激活源

3. `kLatch` 特殊处理
   - `latch-transparent-read` 已把透明读影响显式化到组合图
   - emit 只需处理规整后的锁存器状态更新与下一次 `eval()` 的入口激活

因此，声明类 op 在运行时扮演“状态容器”，而不是调度节点。

### 6.4 状态变化粒度

为兼顾性能，状态变化粒度按存储类型区分：

1. `kRegister`
   - 一个 dirty bit

2. `kLatch`
   - 一个 dirty bit

3. `kMemory`
   - 一个整体 dirty bit
   - 任一 write-port 提交后只要 memory 内容发生变化，就激活依赖该 memory read 结果的 `head-eval supernode`

不做行级 dirty 跟踪，也不在 `eval()` 后扫描 memory 地址相关信息。

### 6.5 声明类到 head supernode 的映射

emit 时需要预先建立：

- 输入 value -> `head-eval supernode` 集合
- 状态读口 result -> `head-eval supernode` 集合
- `kRegister/kLatch` -> 依赖其 read-port 的 `head-eval supernode` 集合
- `kMemoryReadPort` -> 对应 `head-eval supernode` 集合
- `kMemory` -> 依赖其 read-port 的 `head-eval supernode` 集合

这样 `eval()` 开头可以常数时间定位首批激活节点；`commit_state_updates()` 只负责记录下一次 `eval()` 所需的入口激活信息。

## 7. Event-Domain 实现

### 7.1 命中表示

每个正规 `event-domain-signature` 在运行时对应一个布尔位。其基础单元不是“时钟域”，而是规范化后的 `(event value, event edge)`。

`event value` 不要求直接来自输入时钟脚。它可以是从事件 source 出发，经过一段组合逻辑后形成的值。因此 emit 需要为每个 `(event value, event edge)` 识别一段事件预计算逻辑锥。

本次 `eval()`：

- 先对所有基础事件 value 计算 `posedge/negedge` 命中
- 再按签名中的 term 做合取
- 空签名恒命中

因此，复杂时钟、异步复位、多事件敏感列表都统一落在：

- `event-term-hit`
- `event-domain-signature-hit`

而不是单个“clock domain hit”布尔位。

### 7.2 预计算范围控制

事件值允许依赖组合逻辑，也允许依赖 `kRegisterReadPort`、`kLatchReadPort`、`kMemoryReadPort` 等状态读口形成更复杂的锥，例如 gated clock。

事件预计算会冗余求解一部分事件值逻辑锥。若不加约束，错误设计可能把 `clk` 接到大规模组合网络后再形成 `event value`，使每次 `eval()` 的预计算代价失控。

因此 emit 需要提供一个逻辑锥规模阈值，例如：

- `event_precompute_max_ops`

对每个 `(event value, event edge)`：

1. 统计其事件值求值锥中的组合 / 读口相关 op 数
2. 若不超过阈值，则生成预计算代码并参与 `event-term-hit`
3. 若超过阈值，则该 term 不做预计算，依赖它的 `event-domain-signature` 在 guard 侧按恒命中处理

此阈值只影响 guard 预计算，不改变事件敏感 op 自身的精确触发语义；即使 term 未预计算，sink 仍需按精确事件表达式判定是否触发。

### 7.3 Guard 发射

`supernode` guard 直接发射为：

```text
if (supernode_active_curr[id] && supernode_event_domain_hit[id]) { ... }
```

`supernode_event_domain_hit[id]` 可以有两种落地：

1. 预计算 `bool` 数组
2. 对少量 domain 直接内联布尔表达式

默认优先预计算，降低批内重复表达式体积；超过阈值而未预计算的 domain，直接视为 guard 恒命中。

`kSystemTask` / `kDpicCall` 的事件命中除 `eventEdge` 外，还要结合其 `procKind` / `hasTiming` 语义决定是否进入本次调度。

## 8. 编译单元拆分

### 8.1 拆分目标

拆分策略同时服务两个目标：

1. 控制单个翻译单元体积
2. 保持热路径局部性

### 8.2 拆分单位

基本拆分单位不是单个 op，也不是单个 `supernode`，而是连续 `supernode` 批。

每个批按以下预算切分：

- `sched_batch_max_ops`
- `sched_batch_max_estimated_lines`
- `supernode` 内 op kind 的静态发射代价估算

### 8.3 拆分规则

1. 先按 `topo_order` 线性扫描
2. 累积到预算上限后切成一个批
3. 若某个 `supernode` 本身极大，可单独成批
4. 当前实现中，每个批独立落成一个 `sched_<n>.cpp`

预算以“估算 emitted statements / lines”为主，并辅以 op 数上限。

### 8.4 跨编译单元接口

跨 TU 只共享：

- 顶层 simulator 类声明
- 状态布局定义
- helper 头文件
- 批执行函数声明

不在 TU 之间传递大对象。所有批函数直接接收 `this` 或 `SimState&`。

### 8.5 避免编译器退化

需要避免：

- 单个函数过长
- 单个 `.cpp` 过大
- 生成过多模板实例
- 为每个宽度生成完全独立 helper 族

因此：

- helper 以少量通用实现为主
- 批函数大小受控
- 小位宽 fast path 只覆盖高频宽度区间

## 9. 输出接口

### 9.1 用户接口

GrhSIM 对用户暴露的接口保持简单：

1. 若需要控制 `$random`，调用 `set_random_seed(seed)`
2. 首次 `eval()` 前调用 `init()`
3. `init()` 同时清空外部输入与 `inout.in`，并重建内部状态、memory、上周期输入/事件快照与调度基线
4. 通过与端口同名的 `public` 成员写入输入，读取输出；`inout` 也通过公开接口成员访问 `in/out/oe`
5. 调用 `eval()`
6. `eval()` 后读取对应 `public` 输出成员；由本次状态提交产生的变化从下一次 `eval()` 开始可见
7. 若需要回到初始快照，再次调用 `init()`

对双沿驱动测试流，若本次有效边沿写入状态，通常需要在后续另一边沿或下一次用户 `eval()` 后再采样依赖该状态的输出。

### 9.2 调试接口

生成器应保留最少但足够的调试锚点：

- `supernode id -> 源 op symbol`
- 状态对象名
- 输入 / 输出 / `inout` 端口名

调试锚点不进入热路径。

## 10. 实现顺序

### 10.1 第一阶段

先打通：

1. 状态布局生成
2. `supernode` 批执行框架
3. 小位宽 fast path
4. 宽位基础 helper
5. register/latch/memory 整体 dirty 活动度传播
6. event-domain 预计算与阈值降级

### 10.2 第二阶段

再补强：

1. 宽位算术优化
2. 编译单元预算模型
3. 批级代码布局优化

## 11. 当前实现缺口 TODO List

按以下剩余列表推进，完成全部条目即视为完成 `cpp emit`。

### 11.1 高优先级

1. 生成代码验证体系扩展。
   当前仅有“生成 + make + harness 运行”的最小回归；尚未形成分层行为测试矩阵。

2. batch 划分与布局优化。
   当前已支持批切分、`eval_batch_<n>()`、多个 `sched_<n>.cpp`、多编译单元输出与 emit 侧并行；尚未细化 cut policy、批间局部性布局与跨 TU 负载均衡。

3. event-value 共享锥进一步优化。
   当前已按 `event value` 建立 `curr_evt_*` 共享缓存，并在 `eval()` 内对事件值闭包按拓扑物化共享临时量，`event-term-hit` 与 sink 的 `exact-event` 会复用同一份事件值与其中间锥；尚未做更激进的公共子图聚类、跨批布局优化与体积 / 寄存器压力联合权衡。

4. 输入前提校验完善。
   当前仅依赖文档约束；尚未系统校验“无组合环 / 无 XMR / 无 blackbox / 已展平”等全部前置条件。

### 11.2 中优先级

1. 输出镜像布局优化。
   当前已支持 `output` 与 `inout.out/oe` 镜像；尚未细化端口分组、布局压缩与更强的缓存局部性优化。

2. session 数据一致性检查。
   当前已消费 `activity-schedule` session 数据；尚未校验其与 graph 最终快照的一致性。

3. head/source 激活策略细化。
   当前已支持输入变化和上一次 `eval()` 提交后的状态变化激活；尚未细化不同 head-source 类型的独立激活策略。

4. event-domain guard 优化。
   当前已支持预计算命中和超阈值恒命中降级；尚未做 domain 聚类后的布局优化与去重发射优化。

5. event 语义性能模型细化。
   当前已支持 `posedge`/`negedge`/变化检测；尚未细化更复杂 event source 组合的性能模型。

6. `kRegisterReadPort` / `kLatchReadPort` 收尾。
   当前已实现基础路径和宽位结果；更细活动传播优化未实现。

7. `kLatchWritePort` 收尾。
   当前已支持规整后的基本提交和宽位路径；更复杂锁存器组合场景未实现。

8. 多写口风险诊断。
   当前已按草案放宽为“不保证顺序”；尚未补专门诊断或风险提示发射。

9. 活动位热路径优化。
   当前草案要求按 singular BFS / worklist 消耗活动位；具体位图、活跃列表或 epoch 方案尚未定稿。

10. 调试锚点扩展。
    当前已保留 `op symbol` 注释和产物级锚点；尚未系统输出 `supernode -> op symbol`、event-domain、state object 对照表。

11. Python 接口测试。
    当前已接入 `emit_grhsim_cpp(...)`；尚未补 Python 侧专门测试。

12. 透明锁存器前置诊断。
    当前已将 `latch-transparent-read` 设为硬前置；尚未在 emit 入口给出明确失败诊断与定位信息。
