# GrhSIM 计划

本文替换旧版 `grhsim-cpp` 重构计划，目标从“继续调 supernode / 执行模型细节”切换为“先把调试基础设施补齐”。在没有足够调试能力之前，继续靠手工插桩追单点错误，效率太低，也不利于后续定位 XiangShan 这类大设计上的语义偏差。

## 1. 总目标

本轮只做三件事：

- 为 `grhsim-cpp` 集成可选波形输出能力，优先支持 `declaredSymbol`
- 为生成出来的 C++ 附加足够直接的调试注释，能从生成代码快速反查到 `value` / `op` / `srcLoc`
- 新增 `emitValueDeps`，输出“每个 value 直接受哪些 Reg / Mem / Latch / IO symbol 影响”的索引数据

这里的重点不是先修某一个 XiangShan bug，而是把后续所有 bug 的定位成本降下来。

## 2. 非目标

本轮先不做：

- 不重写 `activity-schedule`
- 不改 supernode DP / replication / refine 算法
- 不要求一次性把全部 runtime trace 都做成可视化
- 不尝试把所有中间临时值都写进波形
- 不引入新的“调试专用执行模式”去改变仿真语义

原则是：先把观测能力做出来，而且默认关闭，不影响正常 emit 和运行时性能。

## 3. 能力一：集成 libfst，支持可配置波形

### 3.1 目标

`emitGrhsim` 新增调试参数，决定生成出来的模型是否具备 FST 波形输出能力。第一阶段只记录 `declaredSymbol` 对应的 value，不追求全量 value。

### 3.2 范围

- 集成 `libfst`
- 在 CMake 中提供明确开关
- 在 `emit_grhsim_cpp(...)` 和脚本入口里透传参数
- 生成代码时按开关决定是否带波形 runtime
- 运行时支持：
  - `open fst`
  - 注册波形句柄
  - 按 cycle / eval dump
  - 正常 close

### 3.3 第一阶段记录对象

第一阶段只记录和 `declaredSymbol` 直接关联的对象：

- graph 中声明过的普通 `value`
- 对应 state 的可观察当前值
- 必要时包含顶层 IO

先不记录：

- supernode 内纯局部 temporary
- `state_shadow`
- `evt_edge`
- emitter 内部 scratch

### 3.4 配置建议

建议拆成两个层次：

- 构建期开关：是否编译进 `libfst`
- emit 开关：当前这次 emit 是否真的生成波形支持

emit 侧建议至少支持：

- `waveform=off`
- `waveform=declared-symbols`

必要时再扩展：

- `waveform-output=<path>`
- `waveform-start-cycle=<n>`
- `waveform-stop-cycle=<n>`

### 3.5 设计约束

- 默认关闭
- 关闭时生成代码不应额外引入热路径分支
- 开启后，波形采样点要稳定，不能因为 supernode 重复执行导致同一时刻语义混乱
- 优先按“提交后 / eval 边界后”的稳定值采样，避免把 fixed-point 中间毛刺直接写成参考波形

### 3.6 验收标准

- 小型 HDLBits 用例可生成 `.fst`
- 可用 `tools/fst_tools` 正常读取
- XiangShan `grhsim` 可按开关编出带波形版本
- 至少能稳定看到当前已知排障需要的 `declaredSymbol`

## 4. 能力二：生成 C++ 调试注释与映射信息

### 4.1 目标

当前 `grhsim_SimTop_sched_xxxx.cpp` 里只有槽位索引和 `_op_xxx` 这种符号，人工排查成本很高。需要在 emit 时把“这段代码对应哪个 GRH 实体”直接写出来。

### 4.2 注释粒度

建议至少覆盖两层：

- supernode / batch 级注释
- op / value 级注释

建议内容：

- supernode id
- batch id
- op id
- op kind
- result value id
- operand value id
- symbol 名
- `srcLoc`

### 4.3 输出形式

第一阶段直接写到生成的 `.cpp` / `.hpp` 注释里，优先便于人肉读代码。

建议补一份 sidecar 索引文件，便于脚本检索：

- `grhsim_debug_map.jsonl`

每行一条记录，至少包含：

- `file`
- `line`
- `supernode`
- `op_id`
- `value_id`
- `symbol`
- `op_kind`
- `src`

这样后续可以直接：

- 从断点文件行号反查 GRH 实体
- 从 `value_id` / `op_id` 正向搜到生成代码位置
- 从 `srcLoc` 反查该语句附近所有 emit 片段

### 4.4 设计约束

- 注释信息默认可以开启，因为只影响生成文件体积，不影响运行时语义
- sidecar 索引建议默认生成，便于工具使用
- 注释格式要稳定，不要每轮都变，避免影响后续脚本

### 4.5 验收标准

- 任取一个 `sched_*.cpp` 中的赋值语句，都能直接看到其 `value/op/srcLoc` 背景
- 能从已知的 `value_bool_slots_[N]` 或 `_op_xxx` 快速映射回 GRH
- 文本检索或脚本检索都足够直接

## 5. 能力三：新增 emitValueDeps

### 5.1 目标

需要一个静态依赖索引，回答这个问题：

“某个 `value`，直接受哪些 Reg / Mem / Latch / IO symbol 影响？”

这里强调的是可快速检索的直接观测信息，不是一次性打印整棵完整 cone。

### 5.2 输出语义

对每个 value，给出它的“直接状态来源集合”：

- Reg symbol
- Mem symbol
- Latch symbol
- IO symbol

如果一个 value 只由组合逻辑构成，但上游最终来自多个状态 / IO，就把这些根符号并列列出来。

这份数据主要用于：

- 从错误 value 逆向收敛到关键状态边界
- 快速判断两个 value 是否受同一批状态驱动
- 辅助决定后续插桩该打在哪些 state / IO 上

### 5.3 推荐输出格式

建议至少输出两份：

- `value_deps.tsv`
- `value_deps.jsonl`

`tsv` 方便命令行搜索、排序、抽样。

`jsonl` 方便后续 Python / C++ 工具消费。

每条记录建议包含：

- `value_id`
- `symbol`
- `width`
- `def_op`
- `src_loc`
- `reg_symbols`
- `mem_symbols`
- `latch_symbols`
- `io_symbols`

### 5.4 语义边界

本轮先做静态直接依赖汇总，不做：

- 时序路径分类
- 条件概率或活跃性分析
- 依赖深度排序
- 哪个依赖在某个 cycle 实际生效

也就是说，它回答的是“可能直接影响这个 value 的状态根集合”，不是“这一次错值究竟是谁造成的”。

### 5.5 验收标准

- 能对指定 graph 输出完整依赖索引
- 能从已知错值快速查到其上游 Reg / Mem / Latch / IO 集合
- XiangShan 规模下输出时间和文件体积可接受

## 6. 三项能力之间的关系

这三项能力不是平行孤立的。

推荐的排障顺序应是：

1. 先用 `emitValueDeps` 静态缩小可疑状态范围
2. 再用 C++ 注释 / debug map，快速定位生成代码里的具体赋值点
3. 最后用 FST 波形去看这些 declared symbol 在出错窗口里的真实运行轨迹

这样能把现在“手工改一轮生成文件，编一轮，跑一轮，再 grep 一轮”的流程，变成更稳定的半自动排障路径。

## 7. 实施顺序

建议按下面顺序推进。

### 阶段 A：调试元数据先行

先做：

- C++ 注释
- `grhsim_debug_map.jsonl`
- `emitValueDeps`

原因：

- 这两项不依赖 runtime
- 改动风险低
- 能立刻提升当前插桩排障效率

### 阶段 B：libfst 集成

再做：

- `libfst` 集成
- emit 参数透传
- runtime dump

原因：

- 这部分会碰构建系统和生成 runtime
- 验证链更长
- 但有了前面的 debug map，波形句柄命名和 signal 选取会更清晰

### 阶段 C：脚本与工具整合

最后补：

- 统一脚本入口
- 与 `tools/fst_tools` 的联动示例
- 文档和排障工作流

## 8. 风险点

### 8.1 波形采样时机

如果采样点选错，把 fixed-point 中间瞬态直接写进波形，会制造新的误导。这个问题必须在 runtime 设计里先讲清楚。

### 8.2 生成文件体积

调试注释和 sidecar map 会明显增加 emit 体积。需要控制格式，避免把每条语句注释膨胀到不可读。

### 8.3 依赖索引语义漂移

`emitValueDeps` 必须明确它记录的是“静态状态根集合”，不是动态有效依赖，否则后续很容易误用。

### 8.4 libfst 构建与可移植性

需要保证：

- 不开波形时不引入额外依赖负担
- 没有 `libfst` 时也能正常构建不带波形的 `wolvrix`

## 9. 本轮完成定义

满足以下条件即可认为本轮计划落地：

- `grhsim-cpp` 支持可选 FST 波形，至少覆盖 `declaredSymbol`
- 生成 C++ 中具备稳定可读的 `value/op/srcLoc` 调试注释
- 可输出 `emitValueDeps` 索引文件
- 文档里给出一套基于这三项能力的标准排障流程

到这一步之后，再继续处理 XiangShan `coremark` 这类运行时错误，方法论才算站稳。
