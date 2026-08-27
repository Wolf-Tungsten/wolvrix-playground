# grhsim 路线迁移到 GRHSIM IR 的计划

> 目标架构见 `wolvrix/docs/grhsim/`（仿真模型、GRHSIM IR、pass 系统、
> generic 方言、单线程 flow）。本文只排迁移步骤与验收门。

## 1. 现状

同时存在两条仿真路线，公共前端是 GRH 归一化 pass 链：

- **legacy 路线**（当前生产路线）：`scripts/wolvrix_xs_grhsim.py` /
  `wolvrix_hdlbits_grhsim.py` → GRH 归一化（xmr-resolve … simplify →
  reg-to-mem → lane-aggregate → stats）→ `array-lower` 展开数组 op →
  `activity-schedule`（划分与调度产物写 session，不经 IR）→
  `lib/emit/grhsim_cpp.cpp`（约 23.4k 行）发 C++ 静态库。
- **AM 路线**（tes 优化对象）：`scripts/wolvrix_xs_grhsim_am.py` 复用归一化
  到 post-stats JSON（保留数组形态）→ C++ 二进制 `grhsim-am-lower-json`
  （`wolvrix/lib/grhsim/am/` 约 25k 行，自有 program/graph IR 与 emitter）。
  其设计文档已过时（`wolvrix/docs/grhsim/deprecated/`）。

迁移动机（即新架构要解决的问题）：

- 仿真优化藏在 emitter 与 session 私有数据里（batch 划分、SoA 布局、位宽
  打包、fullpass 特化、activity 调度全在 grhsim_cpp.cpp 内部）；
- 仿真导向 op（`kArray*`、`kMemoryReadAllPort`、`kMemoryWriteLanesPort`）
  寄生在 GRH IR，还需要 `array-lower` 兜底展开；
- 两条路线两套 IR 两套 emitter，优化经验无法复用。

终点形态：`wolvrix/docs/grhsim/flow/single-threaded.md` 的 9 步编排——
GRH 归一化照旧，`lower_grhsim` 之后一切优化都是 GRHSIM IR 上的显式 pass，
emitter 只按 Schedule 打印代码。

## 2. 迁移原则

- **先加后删**：新路线平行建设，旧路线全程可用；每道验收门都以旧路线为
  参照，新路线全绿之前不删任何旧代码。
- **正确性先行，性能门禁分级**：阶段 1 只要求正确；阶段 2 每个 pass 不得
  引入回归；阶段 3 前新路线性能不低于 legacy 单线程路线；阶段 4 追平 AM
  历史最优后才动 AM。
- **GRH 归一化不动**：xmr-resolve、hier-flatten、comb-loop-elim、simplify、
  reg-to-mem 等语义归一化 pass 留在 GRH IR；迁移只涉及仿真导向部分。

## 3. 组件去向

| 现有组件 | 去向 |
| --- | --- |
| GRH 归一化 pass（xmr-resolve / memory-read-retime / multidriven-guard / blackbox-guard / latch-transparent-read / hier-flatten / comb-loop-elim / simplify / memory-init-check / reg-to-mem） | 留在 GRH IR，不动 |
| `activity-schedule`（产物写 session） | 迁为 GRHSIM 的 `partition-activity` + `schedule-topo`，产物物化到 Schedule |
| lane-aggregate / comb-lane-pack 的 array 模式 | 语义在 GRHSIM IR 上由 `rewrite-array-views` 重建；GRH 侧保留到 AM 退役后删除 |
| `array-lower` | 仅 legacy 消费，随 legacy 退役删除 |
| `grhsim_cpp.cpp` | 拆解：SoA/位宽打包 → `specialize-storage-cpu`；fullpass 特化、batch 划分 → 显式 pass 或 emitter 工程选项；发码骨架与运行时库由新 emitter 继承；完成后退役 |
| `lib/grhsim/am/` + `grhsim-am-lower-json` | 优化点逐个以 pass 重建；tes 切换后退役 |
| tests/emit/test_emit_grhsim_cpp | 新 emitter 建立对等测试后退役 |
| tes/grhsim-am-coremark/evaluator.py | 阶段 4 切换输入到新路线 |

## 4. 阶段计划

### 阶段 0：GRHSIM IR 基础设施（纯新增）

- 0.1 核心数据结构：`wolvrix/lib/grhsim/ir/` + `include/grhsim/ir/`，按
  `grhsim-ir-impl.md`（32-bit 稠密 ID、SoA + 池化、Schedule 结构、
  墓碑 + compact）。
- 0.2 generic 方言注册表：op/类型/属性的结构定义与校验（按
  `dialect/generic.md`），不含语义实现。
- 0.3 `lower_grhsim`：GRH Module → GRHSIM Module 逐操作直译（映射表见
  generic.md §3）；系统任务与 DPI 收集为 H 表（`host_call`）。
- 0.4 GRHSIM JSON store/load：调试、resume、测试夹具用。
- 0.5 SimPass 框架与注册表（`grhsim-ir-pipeline.md` §2-4）+ pybind 扩展：
  GRHSIM Module 读写、`run_sim_pass`、pipeline 编排（§5）。当前 pybind
  只有逐 pass `run_pass`、无图写 API，需补齐。

验收：round-trip ctest（构 GRH 图 → lower → dump/load 结构等价）；
现有测试全绿（纯新增，无回归风险）。

### 阶段 1：最小可用单线程仿真器（正确性门）

- 1.1 `schedule-topo` 最简形态：单一恒真区域 + 拓扑全序；`S_edge` 同步与
  不动点循环由 emit 模板承担。
- 1.2 `emit-cpu-single-thread`：按 Schedule 逐 op 打印 C++；类型平凡映射
  （`logic<W>` → uint64 字数组，`real` → double）；H 表 → 函数指针表；
  位操作 helper 继承 legacy 运行时库（`_runtime.hpp` 部分按需抽取）。
- 1.3 Python 编排 `wolvrix.pipelines.cpu_single_thread()` 最简版 +
  hdlbits / XiangShan 各一条新脚本入口，与旧脚本并存。

验收门 G1：hdlbits 全套对拍通过；XiangShan coremark difftest 正确
（golden instrCnt=73584 / cycleCnt=49998，nemu 逐指令一致）。
本阶段不要求性能。

### 阶段 2：优化 pass 逐个迁移（每步独立对拍）

- 2.1 `fold-const` / `dead-code-elim`：GRH 侧已有等价物，移植到 GRHSIM
  Module。
- 2.2 `partition-activity`：移植 activity-schedule 的 compute supernode
  构建、commit 事件聚类、memoryWrite priority 排序 → 输出 Region 与激活
  条件。初版 compute 区域恒真（已知限制见 single-threaded.md §6）。
- 2.3 `schedule-topo` 完整版：区域内拓扑序 + 区域偏序 + `linearize()`。
- 2.4 `specialize-storage-cpu`：从 grhsim_cpp.cpp 抽出 SoA 分桶、位宽打
  包、对齐逻辑为显式 pass，填写 StateDecl `backendType`；emitter 改为按
  backendType 直译。
- 2.5 `rewrite-array-views`：lane-aggregate / comb-lane-pack 的数组语义
  在 GRHSIM IR 上以子图替换重建（产 `mem_read_all` / `mem_write_lanes` /
  `array_*`）。GRH 侧 array 模式此阶段保留（AM 仍消费）。
- 2.6 `dialect/cpu.md` 定义 + `lower-cpu-*` 下降 pass；同时回答
  single-threaded.md §6 的"边界值变化"激活条件扩展。

验收门 G2（每个 pass 落地即过一遍）：G1 全部 + 与上一阶段生成代码的
difftest；coremark 运行时间不退化超过 5%。
阶段出口：新路线性能 ≥ legacy 单线程路线。

### 阶段 3：legacy 路线退役（第一次删除）

前提：G1+G2 全绿且性能达标。

- 3.1 退役 `grhsim_cpp.cpp`、`activity-schedule`、`array-lower`、
  tests/emit/test_emit_grhsim_cpp 与旧脚本入口；hdlbits / XiangShan 的
  Makefile 目标切到新脚本。
- 3.2 emitter 工程能力移植确认：sched batch 分文件、PCH、并行写文件等编
  译期工程特性（不影响语义但影响编译时间）在新 emitter 落实后再删。

验收门 G3：全量 ctest + hdlbits + difftest。AM 路线此阶段保持不动。

### 阶段 4：AM 归并与 GRH IR 净化（第二次删除）

- 4.1 AM 优化点逐个评估（tes config 的 emit_args：branchy-mux、
  resize-elision、init-zero-elision、word-activity-guard、
  wide-storage-first-touch、concat-insert-inline/unroll 等）：已有等价物
  的跳过，缺失的以 GRHSIM pass 补建。
- 4.2 tes/grhsim-am-coremark/evaluator.py 输入切到新路线；性能门禁 = 追
  平 AM 历史最优。
- 4.3 退役 `lib/grhsim/am/` 与 `grhsim-am-lower-json`。
- 4.4 GRH IR 净化：删除 `kArray*`（9 个）、`kMemoryReadAllPort`、
  `kMemoryWriteLanesPort`、`kSliceArray` 及 lane-aggregate / comb-lane-pack
  的 array 模式（枚举、字符串表、JSON 读写同步清理）；generic.md §3.4 的
  兼容性说明改为"仅 GRHSIM IR 内部由 rewrite pass 产生"。

注意顺序：GRH 数组 op 是 AM 的输入（post-stats JSON 保留数组形态），所以
4.4 必须在 4.2/4.3 之后，不能并入阶段 3。

### 阶段 5：扩展（另立文档，本计划不细排）

- 多线程 flow：区域偏序的并行解释、epoch 同步；
- corvus 加速器后端方言；
- compute 区域 activity 细化的完整版。

## 5. 风险与开放问题

- **legacy emitter 的手工积累**：23k 行里有大量面向编译时间与运行性能
  的细节（batch 分组、fullpass 特化、事件表达式聚类的精确 dispatch 条
  件）。逐项移植期间性能可能波动，G2 的 5% 容忍度需要实测校准。
- **compute 区域细化**依赖 cpu 方言对激活条件形式的扩展（"边界值变
  化"），是 2.6 的前置设计工作。
- **H 表建模**：legacy 是 if-else 分发系统任务 + 内部 `$random` 状态；新
  IR 的 `host_call` 需要运行时注册机制，阶段 0/1 要定下来。
- **双路线并行期维护成本**：GRH 归一化 pass 的任何改动要同时验证两条路
  线，直到阶段 3/4 完成。
