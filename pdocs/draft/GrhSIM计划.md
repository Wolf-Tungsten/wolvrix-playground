# GrhSIM 计划

## 当前新增问题

`build/hdlbits-grhsim/grhtb_118` 及同类宽总线 / 规则切片样例生成的 C++ 代码体量明显偏大，已经开始拖慢编译：

- `grhtb_118`
  - `grhsim_top_module_sched_3.cpp` 约 `24475` 行 / `1.18 MB`
  - `grhsim_top_module_state.cpp` 约 `10281` 行 / `321 KB`
  - `grhsim_top_module.hpp` 约 `10246` 行 / `411 KB`

抽样看，当前膨胀主要不是调度框架本身，而是 emitter 把大量重复的小操作逐条内联展开：

- 重复的 `cast + slice + trunc` 链被逐条发射成独立临时值
- 大量常量赋值、单比特提取、规则位切片没有聚合
- `state.cpp` / `hpp` 仍为每个临时值生成独立字段，导致声明区同步膨胀
- activity-schedule 的复制优化会减少跨 supernode 依赖，但也可能放大最终代码体积

本轮已经完成的部分：

- 多 operand、全 scalar 的 `kConcat` 已转为 emitter 侧 loop/helper 发射，详见 `pdocs/draft/GrhSIM现状.md`

当前剩余的主要膨胀来源已不再是这部分 concat 展开，而是更广泛的切片、位提取、临时值落字段等模式。

### 已确认的 XS `SimTop` 体积爆炸根因（2026-04-10）

对 `build/xs/grhsim/grhsim_emit/grhsim_SimTop_state.cpp` 的现场排查显示，这次不是单纯“字段太多”或“调度文件偏大”，而是 `state.cpp` 在 `init()` 中生成了海量 event baseline 初始化代码：

- `grhsim_SimTop_state.cpp` 实际大小约 `816 GB`
- `grhsim_SimTop.hpp` 中共有 `512091` 个 `prev_evt_*` 字段
- 这些字段对应所有 event-sensitive op 的 previous-sample 缓存，覆盖：
  - `385719` 个 `kRegisterWritePort`
  - `3628` 个 `kMemoryWritePort`
  - `7237` 个 `kSystemTask`
  - `6527` 个 `kDpicCall`
  - `410` 个 `kLatchWritePort`
- 其中仅 `mem-to-reg` 的 `lower_write_port` 就产生了 `74384` 个额外 `kRegisterWritePort`

根因已经确认，不是单一因素，而是下面几项叠加：

1. `registerEventSamples(...)` 会为每个 event-sensitive op 的每个 event operand 单独创建一个 `prev_evt_*` 字段。
2. `init()` 生成这些字段的初值时，不是引用现成的 `val_*` / 已物化中间值，而是对 sample 当前值调用 `pureExprForValue(...)`，把整棵组合表达式递归内联成源码。
3. `pureExprForValue(...)` 的 cache 作用域仅限“单个 sample 初始化”；每次生成下一条 `prev_evt_* = ...;` 时都会重新建一套 cache，同一个巨大子表达式不能跨 sample 复用。
4. `mem-to-reg` 会把 SRAM 写口拆成大量 `kRegisterWritePort`；这些新写口继续保留 `eventEdge`，于是 previous-sample 数量被进一步放大。
5. 很多 event operand 不是简单的 `clock`，而是复杂派生时钟 / 门控时钟，例如 `...$_rcg_out_clock`。这类值本身就由很深的组合逻辑定义，一旦被 `pureExprForValue(...)` 展开，就会形成超长单行表达式。

这会形成典型的乘法放大：

- 单个复杂 event operand 的表达式树已经很大
- 相同 operand 会被数百个写口复用
- 但 emitter 在 `init()` 里会把它们分别重新展开，而不是共享引用

抽样中，像 `cpu$l_soc$core_with_l2$core$frontend$inner_bpu$tage$tables_7$tage_entry_sram_bank3_way0$_rcg_out_clock` 这样的门控时钟，在图里有 `516` 个 users；同类结构在多个 table / bank 上重复出现。最终结果就是 `init()` 中出现几十万条 `prev_evt_* = <超长表达式>;`，把 `state.cpp` 直接推到百 GB 级。

因此，这一类问题的优先修复方向已经明确，不应继续只盯着“局部 helper 化”：

- `prev_evt` 应按 sample `ValueId` 去重，而不是按 op 私有字段重复保存
- `init()` 不应对 event baseline 使用全量 `pureExprForValue(...)` 内联
- event baseline 应优先引用已物化值，或改成首轮 `eval()` 后刷新
- 对高复杂度表达式必须设置物化阈值，禁止无限制源码展开
- `mem-to-reg` 之后的 event-sensitive 写口数量需要进入 GrhSIM 代码体积预算

## 优化目标

目标不是单纯减少 op 数，而是降低最终 C++ 源码体积和编译时间，优先关注：

1. 减少 `sched_*.cpp` 的重复模板化表达式
2. 减少 `hpp` / `state.cpp` 中的临时值字段数量
3. 在不明显损伤运行时性能的前提下，控制 activity replication 带来的代码放大

## 计划项

### 1. emit 前结构归一化：如新增 GrhSIM pass，必须放在 `activity-schedule` 之前

这里要明确区分两类事情：

- 如果会修改 IR 图结构，增删 op / value，或改写依赖边，那么它必须发生在 `activity-schedule` 之前
- 如果只是改变最终 C++ 的写法，例如发循环、共享 helper、局部变量替代字段，那么它不应该做成 pass，而应留在 emitter 内部

原因很直接：`activity-schedule` 产出的 `supernode_to_ops`、`value_fanout`、`topo_order`、`state_read_supernodes` 都绑定当前 IR。任何在其后改图的 pass，都会把现有调度结果搞失效。

因此，凡是“主要为了降低 GrhSIM 生成代码体积 / 编译时间”的图级优化，如果不适合并入通用 `simplify`，可以单独做成 GrhSIM 专用 pre-schedule pass，但不能放在 schedule 之后。

建议新增一个独立 pass，例如：

- `grhsim-pack`
  或
- `grhsim-codegen-normalize`

这类 pass 的职责是：

- 识别“同一输入上大量规则 bit-slice / nibble-slice”的模式，重塑成更利于 emitter 发循环 / helper 的形态
- 识别批量重复的位提取、规则切片、规则拼接模式
- 为后续 emitter 模式化发射保留足够的结构信息，而不是继续逐 op 硬展开
- 让 `activity-schedule` 直接在这种更稳定、更紧凑的图上做划分，而不是先按膨胀图调度、再事后改图

边界要求：

- 该 pass 可以显式以“降低 GrhSIM C++ 代码体积”为目标
- 但不应破坏通用 IR 的基本可理解性和后续调试性
- pass 若改图，必须在当前流程中的 `activity-schedule` 之前
- `activity-schedule` 之后只允许做不改图的 emitter-local 优化，不再新增会破坏调度结果的后处理 pass

### 2. 继续扩大 emitter 级别的模式化发射覆盖面

已完成的第一步是“多 operand scalar concat helper 化”；当前剩余需要继续推进的模式包括：

- 对“从一个宽向量按固定步长切出很多小段”的模式，发成 `for` 循环
- 对“批量 1-bit 提取”模式，发成共享 helper，而不是 N 份 `cast_words + slice_words`
- 对大批量常量赋值，优先生成静态表或统一初始化逻辑
- 对结构一致、仅索引不同的赋值块，支持 emit-time 模板化

### 3. 收缩临时值存储面

当前很多临时值即使只在单个 supernode 内短暂使用，也会进入类字段：

- 区分“跨 batch / 跨轮次持久值”和“单 supernode 局部临时值”
- 对只在单个 batch 内单次求值使用的中间值，优先发成局部变量，不进入 `hpp` / `state.cpp`
- 对可由源值即时重算的 trivial 临时值，不单独保留字段

### 4. 给 activity replication 增加代码体积约束

当前 replication 主要优化 cut / 活动传播，但对代码体积不敏感。需要补：

- 复制前估算新增 emit 体积
- 对高展开成本 op 降低复制倾向
- 在 `edge-cut` 之外引入“体积惩罚项”或单独阈值
- 让 `118` 及同类“复制后大面积重复 slice/cast 链”的图不过度膨胀

### 5. 建立体积与编译时间基准

后续优化需要有稳定量化指标，至少记录：

- 每个 DUT 的 `hpp` / `state.cpp` / `sched_*.cpp` 行数与字节数
- `g++ -O3` 编译单文件耗时
- supernode 数、replication clone 数、最终 op 数
- 重点跟踪 `118`，并增加 1~2 个宽总线类样例作为回归基准

## 实施顺序

建议按下面顺序推进：

1. 先补基准统计，确认到底是 emit 展开、field 数量，还是 replication 主导
2. 先做“局部临时值不落 field”这一层，通常风险最低、收益直接
3. 再做切片 / 位提取模式化发射，优先打掉 `118` 和同类宽总线样例的主要重复块
4. 最后再回头调整 activity replication 的成本模型

## 完成标准

至少满足下面条件，才认为这轮优化完成：

- `grhtb_118` 与新增宽总线回归样例的最大 `sched_*.cpp` 行数明显下降
- `grhsim_top_module.hpp` 与 `grhsim_top_module_state.cpp` 体积同步下降
- 编译时间可感知缩短
- HDLBits GrhTB 全量回归不退化
