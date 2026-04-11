# GrhSIM 现状

本文只描述当前 `grhsim-cpp emit` 的真实实现结构、运行流程、生成物职责和当前 XS 卡点，目的是让后续调试有共同语境。

## 1. 入口在哪里

- XS 驱动脚本：`scripts/wolvrix_xs_grhsim.py`
- C++ emitter 主实现：`wolvrix/lib/emit/grhsim_cpp.cpp`
- Emit 配置：`wolvrix/include/core/emit.hpp`
- XS make 入口：`Makefile` 的 `xs_wolf_grhsim_emit`

当前 XS 流程里，`grhsim-cpp` 不是直接从 SV 发 C++，而是：

1. 先生成/读取 GRH JSON
2. 跑 `activity-schedule`
3. 再由 `EmitGrhSimCpp` 把带 schedule session 的 GRH 发成 C++

## 2. 端到端流程

### 2.1 Python 侧流程

`scripts/wolvrix_xs_grhsim.py` 当前关键步骤是：

1. 读取前序统计/后处理 JSON
2. 跳过 `mem-to-reg`（默认禁用）
3. 跑 `activity-schedule -path <top> -enable-replication true`
4. 写出 `xs_wolf_grhsim.json`
5. 调 `emit_grhsim_cpp(...)`

其中 `activity-schedule` 会把后续 C++ emit 需要的 session 数据塞进 session store，核心有四类：

- `supernode_to_ops`
- `value_fanout`
- `topo_order`
- `state_read_supernodes`

`grhsim-cpp` 如果拿不到这四类 session 数据，会直接失败，说明它本质上是一个“基于 activity schedule 的 emitter”。

### 2.2 C++ emitter 主流程

`EmitGrhSimCpp::emitImpl(...)` 的大致结构是：

1. 读取 top graph 和 `activity-schedule` session
2. `buildModel(...)`
3. 生成 `runtime.hpp`
4. 生成 `grhsim_<top>.hpp`
5. 生成 `grhsim_<top>_state.cpp`
6. 生成 `grhsim_<top>_eval.cpp`
7. 按 batch 并行生成 `grhsim_<top>_sched_*.cpp`
8. 生成一个简单 Makefile

所有输出文件都走 `LimitedOutputStream`，默认单文件上限是 `4 GiB`。超过后 emit 失败，但保留超限半成品。

## 3. `buildModel(...)` 现在负责什么

这是当前 emit 体积的核心分配器。

### 3.1 它构建的对象

- 输入端口公开字段和 `prev_input_*`
- 输出/双向口公开字段
- 持久状态对象：`state_reg_*` / `state_latch_*` / `state_mem_*`
- staged write 字段：`pending_*`
- event baseline：`prev_evt_*`
- event per-op guard：`seen_evt_*`
- register write conflict 跟踪元数据
- `valueFieldByValue`

### 3.2 当前 value materialize 策略

现在已经不是“所有 graph value 都落成员字段”了。

当前会被物化为 `val_*` 成员字段的主要是：

- 输出口 / inout 可见值
- 跨 supernode 边界传播的 value
- event-sensitive op 的 sampled value
- `dpi` 返回值 / 输出值
- 必须跨阶段保留的少数 system-function 结果，例如 `fopen` / `ferror`

其余同 supernode 内部中间值，现在只保留名字映射，不再进 `.hpp` / `.state.cpp`，而是在 `sched_*.cpp` 里生成局部 `const auto val_*` 临时量。

这一步已经显著降低了 `val_*` 规模。

## 4. 生成文件各自干什么

### 4.1 `grhsim_<top>.hpp`

这是类定义和成员字段总表，主要包含：

- public ports
- `val_*`
- `state_*`
- `pending_*`
- `prev_evt_*`
- `seen_evt_*`
- `eval_batch_*()` 声明

如果头文件很大，通常说明下面几类之一还在爆：

- `val_*`
- `pending_*`
- `state_*`

### 4.2 `grhsim_<top>_state.cpp`

这里放：

- 构造/析构
- `init()`
- `commit_state_updates()`
- `refresh_outputs()`
- system task runtime 辅助实现

它常常是最大文件，因为 `init()` 会线性展开初始化：

- materialized `val_*`
- 所有 `pending_*`
- `prev_input_*`
- `prev_evt_*`

### 4.3 `grhsim_<top>_eval.cpp`

这里放主调度循环：

1. 基于初始 eval 和输入变化设置活动 supernode 位图
2. 反复调用 `eval_batch_*()`
3. 每轮后调用 `commit_state_updates()`
4. 直到 `active_word_count_ == 0`
5. 刷新 event baseline
6. 刷新 outputs
7. 更新 `prev_input_*`

### 4.4 `grhsim_<top>_sched_*.cpp`

每个 batch 对应一个 `eval_batch_N()`，内容是：

- 遍历这个 batch 中的 supernode
- 对每个 op 发代码
- 组合 op 直接算值
- 写口 op 不立即写状态，而是写入 `pending_*`
- side-effect op 保持显式边界

这里更接近“调度后的执行体”，不是状态定义处。

## 5. 运行时语义目前是什么

### 5.1 组合求值

组合逻辑按 supernode 拓扑批量执行。

当某个 materialized value 发生变化，且它在 `value_fanout` 中有跨 supernode 后继时，会重新激活后继 supernode。

### 5.2 状态写入

寄存器/锁存器/存储器写口不直接改 `state_*`，而是先写 `pending_*`。

`commit_state_updates()` 统一提交这些 staged write，并在状态真正变化后重新激活对应 reader supernode。

### 5.3 event-sensitive op

event baseline 已经改成按 sampled `ValueId` 共享，不再按 op 私有复制。

但 `seen_evt_*` 仍然按 op 保留，保证同一次 `eval()` 内不会重复触发同一个 event-sensitive op。

## 6. 当前 XS 现场规模

以下数字来自最近一次 XS 运行现场：

- `graph_ops = 10,351,017`
- `graph_values = 12,052,032`
- `supernodes = 1,081,691`
- `xs_wolf_grhsim.json = 6,142,427,027 bytes`
- `grhsim_SimTop.hpp = 153,295,570 bytes`
- `grhsim_SimTop_state.cpp = 4,294,967,296 bytes`

进一步拆分：

- `val_*` in header: `776,642`
- `val_*` init lines in state.cpp: `776,642`
- `pending_*` decl lines in header: `952,164`
- `pending_*` init lines in state.cpp: `951,971`
- `state_*` decl lines in header: `317,063`
- `state_*` init lines in state.cpp: `113,791`
- `prev_evt_*` decl lines in header: `420`
- `prev_evt_*` init lines in state.cpp: `31`

结论很明确：

1. `prev_evt` 爆炸已经基本解决，不再是主瓶颈
2. `val_*` 爆炸已经从约 `1205 万` 降到 `77.7 万`
3. 现在新的最大瓶颈是 `pending_*`
4. `state.cpp` 超限时，文件尾部已经落到 `pending_*` 初始化之后，说明 `init()` 仍然非常重

## 7. 当前真正卡点

不是“4GB 保险失效”，而是 emit 真的还在生成超过 4GB 的 `state.cpp`。

最新现场显示：

- emit 卡在 `write_grhsim_cpp start`
- `state.cpp` 正好打满 4 GiB
- 最新 build log 里还没有看到脚本级 `[FAIL]` / `[EXIT]`

也就是说，现在有两条问题线并行存在：

### 7.1 体积问题

主问题已经从 `prev_evt` 转移到：

- 海量 `pending_*` 字段
- `init()` 里对这些 staged write 的逐字段清零

### 7.2 失败可见性问题

这次日志仍然停在 `write_grhsim_cpp start`，没有落出明确失败尾巴，说明：

- 要么进程在 emitter 内部异常终止
- 要么进程在脚本层之外被杀
- 要么当前调用链还有未覆盖到的 silent exit 路径

这和“为什么日志没有正常收口”是另一条独立调试线。

## 8. 接下来调试时可以直接按这几个问题说

为了避免“指令不够具体”，后续可以直接按下面的粒度给我任务：

### A. 结构压缩类

- 继续压缩 `pending_*`
- 减少 `init()` 清零代码
- 把某类 staged write 从“每写口一组字段”改成“按状态对象共享槽位”
- 只保留会被真正触达的 staged write 元数据

### B. emit 结构类

- 把某类初始化从 `state.cpp` 挪到运行时 lazy init
- 把某类 helper/表项从源码展开改成循环或表驱动
- 把某类 value 从成员字段改回局部临时

### C. 可观测性类

- 把 `write_grhsim_cpp` 的失败路径补出确定日志
- 把当前 emit 分阶段打印到日志
- 打印每个输出文件完成前后的大小和耗时

## 9. 当前最值得优先做的事

如果只看“让 XS 先不过 4GB”，现在最该打的是：

1. `pending_*` 结构收缩
2. `state.cpp:init()` 中 staged write 初始化收缩

如果只看“为什么这次还是静默停住”，最该打的是：

1. `emit_grhsim_cpp` 调用链加阶段日志
2. 确认超限/异常/被杀三类退出路径分别落什么日志

---

一句话总结：

当前 `grhsim-cpp` 已经从“所有 value 全物化”的旧状态，进入了“schedule 驱动、边界 value 物化、内部 value 局部化”的新状态；但 XS 规模下新的主瓶颈已经转移到 `pending_*` 和 `state.cpp:init()`，而不是 `prev_evt_*`。
