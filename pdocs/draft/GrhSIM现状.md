# GrhSIM现状

`pdocs/draft/GrhSIM计划.md` 中提出的这轮调度模型重构目标已经完成，相关设计原则和当前落地语义已经并入本文，不再单独维护计划文档。

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

状态写入当前采用“`propagate` 先暂存、`commit` 后提交”的两阶段模型：write-port 在调度阶段只记录 pending update，`commit_state_updates()` 在一轮调度结束后统一提交；如果提交后状态真实变化，会在同次 `eval()` 内重新激活对应状态读 supernode，直到活动集合收敛为空。因此状态影响可以在同次 `eval()` 内可见。

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

### 2.3 当前静态依赖与入口元数据

当前 `activity-schedule` 不再输出独立的 `event-domain` 调度层，静态依赖模型已经统一为一套 supernode DAG：

1. `value_fanout` 描述 value 跨 supernode 的活动传播目标。
2. `topo_order` 给出 supernode 的静态执行顺序。
3. event-sensitive operand 在静态分析里按普通依赖参与建图，不再单独抽取全局 event-domain。
4. `state_read_supernodes` 把状态符号映射到其读者 supernode 集合，供运行时在状态提交后重新激活依赖该状态的 supernode。

其中 `state_read_supernodes` 的 key 是状态符号名，当前覆盖 `reg` / `latch` / `mem` 的读口；value 是读取该状态的 supernode id 列表，已去重并稳定化。

### 2.4 当前输出结构

Pass 结果写入 session 的 `<path>.activity_schedule.*`：

- `supernode_to_ops`
- `op_to_supernode`
- `value_fanout`
- `topo_order`
- `state_read_supernodes`

其中当前 emitter 直接消费的核心数据是：

- `supernode_to_ops`
- `value_fanout`
- `topo_order`
- `state_read_supernodes`

### 2.5 当前调度语义

当前文档和代码已经对齐为以下语义：

- `supernode` 是调度与代码生成的基本单元
- `activity-schedule` 只负责给出静态 supernode 划分、拓扑序和跨边界传播关系，不再承载事件域调度决策
- 活动度按跨 `supernode` 边界的 value 变化传播，不按“整个 supernode 任意值变化”粗粒度传播
- 当前运行时首次 `eval()` 会直接全量激活全部 supernode
- 后续 `eval()` 的入口 seed 由“外部输入变化”与“状态提交后重新激活读者 supernode”共同决定
- 同一个 `supernode` 在一次 `eval()` 内可以因状态提交再次变活并重复执行，直到达到固定点
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

1. 首次 `eval()` 直接激活全部 supernode；后续 `eval()` 只根据外部输入变化激活相应入口 supernode
2. 在当前活动集合上按拓扑批次执行 supernode，完成一轮 `propagate`
3. `kRegisterWritePort` / `kMemoryWritePort` / `kLatchWritePort` 在 `propagate` 中只暂存 pending update，不直接改写状态
4. 一轮调度结束后执行 `commit_state_updates()`
5. 若某个状态提交后真实变化，则通过 `state_read_supernodes` 重新激活其读者 supernode
6. 重复 “`propagate` -> `commit`” 直到没有活动 supernode
7. 收敛后刷新公开输出，并更新输入基线与事件 sample 基线

关键点：

- 当前 `eval()` 是固定点收敛模型，不是单次单向前传
- 状态写入在本轮 `commit` 后即可继续影响同次 `eval()` 的后续轮次
- 全局 `event-domain-hit` 预计算已移除；事件判断在各个 event-sensitive op 内局部完成
- 事件 sample 按 op 私有字段保存，op 执行后会立即刷新自己的上一采样值，避免同次 `eval()` 重复触发同一边沿

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
- `kRegisterWritePort` 延迟提交语义，提交后可在同次 `eval()` 内继续传播
- `kMemoryWritePort` 延迟提交语义，按状态真实变化重新激活读者 supernode
- `kLatchWritePort` 延迟提交语义，提交后可在同次 `eval()` 内继续传播
- declaration init、memory 初始化、`$random` seed / state
- `kSystemTask` 常用语义，包括文本输出、文件句柄输出、`fflush`、`fclose`、`dumpfile`、`dumpvars`、`info/warning/error/fatal/finish/stop`
- `kSystemFunction` 中与文件句柄相关的常用能力，如 `fopen`、`ferror`
- `kDpicCall` 输入 / 输出 / 返回值路径；当前不支持 `inout` 参数
- `output` 与 `inout` 输出分量建模
- event-sensitive op 的局部 exact-event 检测与 per-op previous-sample 缓存

对多写口，当前策略是放宽为“不保证顺序”。

### 3.5 当前热路径优化状态

已落地的热路径优化包括：

- `supernode_active_curr_` 静态化为定长 bitset 数组
- 去掉 `eval()` 入口输入影子复制
- 去掉输出双重镜像，`refresh_outputs()` 直接发布 public 输出
- seed 激活按 word mask 合并
- `touched_write_*` 加速 pending write 提交
- 活动位在 supernode 取出执行时立即清理
- 跨 supernode 活动传播基于 `value_fanout`
- batch 内已支持 contiguous topo word-segment 跳过
- 事件检测改为 per-op 局部 sample，比全局 event-domain 位图更直接
- 生成代码中保留必要注释和 `op symbol` 锚点
- 多 operand、全 scalar 的 `kConcat` 已增加 emitter 侧模式识别：
  - 同宽 scalar concat 发射为 `grhsim_concat_uniform_scalars_u64/words(...)`
  - 异宽 scalar concat 发射为 `grhsim_concat_scalars_u64/words(...)`
  - helper 内部使用循环完成拼接，不再把整段 `concat_cursor -= ...; grhsim_insert_words(...)` 完全逐元素展开
- 上述 concat helper 化已按 `py_install` 后的实际 GrhSIM 流程验证：
  - `grhtb_043` 的 `sched_*.cpp` 总行数从 `27158` 降到 `26754`
  - `grhtb_118` 的 `sched_*.cpp` 总行数从 `60034` 降到 `59116`

### 3.6 当前验证与使用

当前 HDLBits GrhTB 已迁移 `001..162`，统一入口为：

- `make run_hdlbits_grhsim DUT=xxx`
- `make run_all_hdlbits_grhsim_tests`

已验证 `001..162` 可运行。此前 `103` 的寄存器写回位宽归一化问题与 `127`
的含 `x` 常量发射问题都已修复；当前 GrhSIM 对 `Logic` 继续采用二值语义，
常量中的 `x/z` 位在 emitter 中按 `0` 处理。

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
