# GrhSIM现状

## 1. 范围

### 1.1 当前讨论对象

`GrhSIM` 是基于 Wolvrix 和 GRH IR 构建的 C++ 仿真器。当前已落地的是单线程 `full-cycle`、`activity-driven` 执行模型。

用户接口当前为：

1. 构造模型对象
2. 如需固定 `$random`，调用 `set_random_seed(seed)`
3. 调用 `init()`
4. 通过与顶层端口同名的 `public` 成员写输入
5. 调用 `eval()`
6. 直接读取同名 `public` 输出成员

状态更新在本次 `eval()` 末尾提交，对后续一次 `eval()` 生效；当前不做同次 `eval()` replay。

### 1.2 前置条件

当前 GrhSIM 流程依赖以下前置条件：

- 目标 graph 已展平
- 无 `XMR`
- 无 `blackbox`
- 无组合逻辑环
- 已运行 `latch-transparent-read`
- 已运行 `activity-schedule`

其中一部分前提已有代码检查：

- `activity-schedule` 会拒绝层次类 op：`kInstance`、`kBlackbox`、`kXMRRead`、`kXMRWrite`
- `emit_grhsim_cpp` 要求 session 中已有 `activity-schedule` 结果

其余前提目前主要由流程保证。

## 2. Activity Schedule 现状

### 2.1 Pass 入口与参数

`activity-schedule` 以 `-path <graph>` 指定目标 graph。当前默认参数：

- `supernodeMaxSize = 64`
- `enableCoarsen = true`
- `enableChainMerge = true`
- `enableSiblingMerge = true`
- `enableForwardMerge = true`
- `enableRefine = true`
- `refineMaxIter = 4`
- `enableReplication = true`
- `replicationMaxCost = 2`
- `replicationMaxTargets = 8`
- `costModel = edge-cut`

### 2.2 已实现的分图 Phase A

当前 `activity-schedule` 已完整实现分图主流程：

1. `phase A1` 建立划分视图，区分可划分 op、状态读口、稳定边界 op。
2. `phase A2` 以 op 为 seed 初始化 supernode。
3. `phase A3` 做局部粗化，包含 chain merge、sibling merge、forwarder merge。
4. `phase A4` 在 coarse supernode 拓扑序上做连续分段动态规划，目标函数当前固定为 `edge-cut`。
5. `phase A5` 做边界局部 refine，通过相邻分段间 cluster 搬移继续减 cut。
6. `phase A6` 复制低成本边界 op，减少跨 supernode 依赖。
7. `phase A7` 在全部改图结束后统一 `freeze()`，再一次性物化最终映射。

稳定边界 op 当前保留为独立边界，不会被粗化、跨段吞并或复制：

- `kRegisterWritePort`
- `kMemoryWritePort`
- `kLatchWritePort`
- `kSystemTask`
- `kDpicCall`

`phase A7` 采用 `SymbolId -> supernode` 作为中间稳定锚点，待最终 `freeze()` 后再恢复 `OperationId` 级映射；这样可以规避复制和插入 op 导致的 id 漂移。

### 2.3 已实现的 event-domain Phase B

当前 `activity-schedule` 已实现 event-domain 反标：

1. `phase B1` 建立反标起点。当前 sink 包括：
   - `kRegisterWritePort`
   - `kMemoryWritePort`
   - `kLatchWritePort`
   - 无返回值 `kSystemTask`
   - 无返回值 `kDpicCall`
   - 直接驱动 `output` / `inout.out` / `inout.oe` 的 op
2. 从 sink 提取正规 `event-domain-signature`，基本元素为 `(event value, event edge)`，并做稳定排序。
3. `phase B2` 沿 use-def 反向传播，把 `event-domain-set` 标到 op、value、supernode。

`event-domain` 允许为空；空集合表示该 sink 不受事件命中约束，每次 `eval()` 都可进入调度。

### 2.4 当前输出结构

Pass 结果写入 session 的 `<path>.activity_schedule.*`：

- `supernodes`
- `supernode_to_ops`
- `supernode_to_op_symbols`
- `op_to_supernode`
- `op_symbol_to_supernode`
- `dag`
- `value_fanout`
- `topo_order`
- `head_eval_supernodes`
- `op_event_domains`
- `value_event_domains`
- `supernode_event_domains`
- `event_domain_sinks`
- `event_domain_sink_groups`

其中当前 emitter 直接消费的核心数据是：

- `supernode_to_ops`
- `dag`
- `value_fanout`
- `topo_order`
- `head_eval_supernodes`
- `supernode_event_domains`
- `value_event_domains`
- `event_domain_sinks`
- `event_domain_sink_groups`

### 2.5 当前调度语义

当前文档和代码已经对齐为以下语义：

- `supernode` 是调度与代码生成的基本单元
- 一次 `eval()` 内，每个 `supernode` 最多执行一次
- 活动度按跨 `supernode` 边界的 value 变化传播，不按“整个 supernode 任意值变化”粗粒度传播
- `head_eval_supernode` 只用于构建 `eval()` 入口 seed，不参与 guard 条件
- `head_eval_supernode` 当前定义为直接消费 graph 输入或状态读口结果的 supernode
- 拓扑关系使用核心 `toposort` 组件构建

## 3. GrhSIM Cpp Emit 现状

### 3.1 输入与产物

`emit_grhsim_cpp` 直接消费当前内存中的 design 和 session 中的 `activity-schedule` 数据，不做 JSON round-trip。

当前会生成：

- `grhsim_<top>.hpp`
- `grhsim_<top>_runtime.hpp`
- `grhsim_<top>_state.cpp`
- `grhsim_<top>_eval.cpp`
- `grhsim_<top>_sched_<n>.cpp`
- 最小 `Makefile`

调度批已经拆成多个 `sched_<n>.cpp`；发射阶段支持按 `emit_parallelism` 并行生成多个批文件。

### 3.2 当前执行模型

当前 `eval()` 逻辑为：

1. 检测输入变化
2. 预计算 `event-term-hit`
3. 归约得到 `event-domain-hit`
4. 首次 `eval()` 激活首批 seed supernode；后续 `eval()` 根据输入变化和上一轮状态提交记录激活入口 supernode
5. 按拓扑顺序执行 supernode 批
6. 提交 write-port、副作用 op 和状态更新
7. 刷新公开输出

关键点：

- 单次 `eval()` 只做一次前向传播
- 状态写入本轮提交、下轮可见
- 不做同轮 replay、observe cone 或事件闭包重算

### 3.3 当前数据表示

Logic 当前按位宽分层表示：

- `1..64 bit`：标量整型 / `bool`
- `65..128 bit`：优先走 `unsigned __int128` fast path
- `129..256 bit`：固定长度 word 容器
- `>256 bit`：通用 word 数组 helper

当前按二值逻辑处理 `Logic`；`String` 和 `Real` 已有运行时表示与发射路径。

### 3.4 当前已支持的主要语义

- 常见小位宽组合 op 发射
- 宽位运行时表示与基础组合 helper
- signed 语义的系统化落地
- `kRegisterWritePort` 基本提交语义
- `kMemoryWritePort` 基本提交语义，按整体 dirty 建模 memory 活动传播
- `kLatchWritePort` 基本提交语义
- declaration init、memory 初始化、`$random` seed / state
- `kSystemTask` 常用语义，包括文本输出、文件句柄输出、`fflush`、`fclose`、`dumpfile`、`dumpvars`、`info/warning/error/fatal/finish/stop`
- `kSystemFunction` 中与文件句柄相关的常用能力，如 `fopen`、`ferror`
- `kDpicCall` 输入 / 输出 / 返回值路径；当前不支持 `inout` 参数
- `output` 与 `inout` 输出分量建模
- event-domain 预计算与超阈值恒命中降级

对多写口，当前策略是放宽为“不保证顺序”。

### 3.5 当前热路径优化状态

已落地的热路径优化包括：

- `supernode_active_curr_`、`event_term_hit_`、`event_domain_hit_` 静态化为定长数组
- 去掉 `eval()` 入口输入影子复制
- 去掉输出双重镜像，`refresh_outputs()` 直接发布 public 输出
- `event_term_hit_` / `event_domain_hit_` 不再每轮全量清空
- seed 激活按 word mask 合并
- `touched_write_*` 加速 write-port 提交
- 活动位在 supernode 取出执行时立即清理
- 跨 supernode 活动传播基于 `value_fanout`
- batch 内已支持 contiguous topo word-segment 跳过
- 生成代码中保留必要注释和 `op symbol` 锚点

### 3.6 当前验证与使用

当前 HDLBits GrhTB 已迁移 `001..039`，统一入口为：

- `make run_hdlbits_grhsim DUT=xxx`
- `make run_all_hdlbits_grhsim_tests`

当前脚本流程为：

1. `read_sv`
2. `xmr-resolve`
3. `multidriven-guard`
4. `latch-transparent-read`
5. `hier-flatten`
6. `comb-loop-elim`
7. `simplify semantics=2state`
8. `memory-init-check`
9. `activity-schedule`
10. `emit_grhsim_cpp`
