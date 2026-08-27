# GRHSIM IR 迁移进展

> 最后更新：2026-08-27
>
> 对应计划：[grhsim-ir-migration-plan.md](grhsim-ir-migration-plan.md)

## 1. 总体状态

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| 阶段 0：GRHSIM IR 基础设施 | 已完成，复验通过 | 评审发现项已修复；真实 host/DPI、generic 契约和 JSON 边界回归均通过 |
| 阶段 1：最小可用单线程仿真器 | 已完成，验收通过 | HDLBits 162/162；XiangShan CoreMark + NEMU 连续运行至 cycle 39,250 无 mismatch，并精确匹配已有 GSim golden 检查点；剩余长跑经确认不再执行 |
| 阶段 2：优化 pass 迁移 | 未开始 | 阶段 1 已收口；按 G2 逐项迁移并对拍 |
| 阶段 3：legacy 路线退役 | 未开始 | 依赖 G1、G2 与性能门 |
| 阶段 4：AM 归并与 GRH IR 净化 | 未开始 | 依赖新路线追平 AM 历史最优 |
| 阶段 5：扩展 | 未开始 | 另立设计与实施计划 |

## 2. 阶段 0 完成项

### 0.1 核心数据结构

- 新增 `wolvrix/include/grhsim/ir/` 与 `wolvrix/lib/grhsim/ir/`。
- 实现 32-bit 稠密 ID、SoA 实体列与模块级变长池。
- 实现 op、edge、use-def、StateDecl、HostTable、Region 与 Schedule。
- 实现墓碑删除、`compact()`、`freeze()`、调度顺序重排和 ID 重映射。
- 实现子图替换、区域划分、区域合并、区域依赖和 `linearize()` 等基础 API。
- 实现 TrackSet 推导及结构、类型、驱动冲突和 Schedule 合法性校验。

### 0.2 generic 方言

- 实现 generic 方言和操作注册表，以及名称与 opcode 的双向查询。
- 覆盖文档列出的计算、数组、端口、状态、存储器和 host 操作。
- 实现操作数/结果数量、属性结构、类型和状态引用校验。
- 实现 host query/effect 形式、事件属性、签名类型及内存写优先级校验。

### 0.3 `lower_grhsim`

- 实现 GRH Graph/Design 到 GRHSIM Module 的逐操作映射。
- 映射输入、输出和 inout 端口，以及寄存器、锁存器和存储器状态。
- 覆盖全部文档化计算 op、数组 op 和各类存储器端口。
- 将系统函数、系统任务和 DPI 调用收集到 HostTable，并生成 `host_call`。
- 将事件引用转换为 StateDecl；内部事件信号会提升为可跟踪状态。
- 对残留层次、XMR、未知 op、无效签名和无效事件给出诊断。

### 0.4 JSON store/load

- 实现格式标识为 `wolvrix.grhsim.ir`、版本号为 1 的 JSON 格式。
- 覆盖类型、状态、HostTable、op、edge、属性、Region 和 Schedule。
- load 后执行冻结与完整校验；store 前生成规范化快照。
- 提供结构等价检查，并覆盖 dump/load round-trip。

### 0.5 SimPass 与 Python Session

- 实现 `SimPass`、`SimPassManager`、effects 契约、诊断、日志和 session 上下文。
- 实现 pass 注册表，当前注册 `analyze-validate`。
- 分析 pass 运行前由管理器冻结 Module；改写 pass 按 effects 维护 Schedule。
- Python Session 新增 GRHSIM lowering、JSON 读写、`run_sim_pass` 和模块存取。
- 支持 `dryrun` 克隆试跑、Session copy/clone 语义和 `list_sim_passes()`。

## 3. 测试与验收

阶段 0 最终验收通过：

- `grhsim-ir-roundtrip` CTest 通过。
- `ingest-graph-assembly-dpi-display` 通过，覆盖真实 `$display`、`$error`、
  `dpi_add`、`dpi_capture` 与 `difftest_ram_read` lowering。
- `transform-comb-lane-pack` 与 `transform-repcut` 回归测试通过。
- `cmake --build wolvrix/build -j2` 完整构建通过。
- `ctest --test-dir wolvrix/build --output-on-failure`：73/73 通过，耗时 174.97 秒。
- Python 真实 fixture smoke 通过，覆盖两个 top 的 SV 读取、lowering、JSON 文本
  reload、dry-run/实际 `analyze-validate` 和 pass 枚举；输出
  `python-grhsim-smoke: ok 25 8`。
- `git diff --check` 通过；新增 IR、测试、绑定和文档路径无行尾空白。

为使“现有测试全绿”反映当前行为，同时修正了两个已有测试夹具：

- `transform-comb-lane-pack`：为只写寄存器增加可观察 readback，避免 DCE 合法
  删除待测逻辑锥，并补充实际计数诊断。
- `transform-repcut`：删除与既有提交 `bb0aed5` 行为冲突的过期 JSONL 断言。

## 4. 阶段 0 代码评审

评审日期：2026-08-26。修复复验日期：2026-08-26。结论：**通过**。

发现项及修复：

1. **已修复：真实系统任务无法 lowering。** `generic.const` 现允许产生
   logic、real 或 string，拒绝 array；普通 compute op 仍只接受 logic。
2. **已修复：DPI actual/formal 缺少类型适配。** HostTable 和 host validator
   继续保持 TypeId 精确匹配；lowering 对宽度或 signedness 不同的 logic input/
   inout 插入 `generic.assign`，非 logic 的不兼容转换仍报错。condition 不转换。
3. **已修复：generic compute/array 契约不完整。** validator 现覆盖算术、
   比较、逻辑、规约、mux、concat、replicate、slice 与全部 array view 的位宽、
   rows、elem_width 和 values 数量关系。mux 按 GRH 规范校验分支/结果位宽，
   允许合法的 signedness 上下文转换；assign 明确允许 logic 类型转换。
4. **已修复：JSON 非有限 double 无法 round-trip。** Module validation 统一拒绝
   StateDecl、HostTable 和 op 中的 NaN/Inf double/double[] 属性；writer 另有
   finite 防御检查，不再生成非法 JSON token。
5. **已修复：JSON 整数静默截断。** loader 为 `uint8_t`、`uint16_t`、普通
   `uint32_t`、有效 ID 和 `-1` 可空 ID 分别做显式范围检查；array element、
   backend refines、StateDecl backend type、op region 与 activation state 均覆盖。

修复后针对性验证结果：

- `grhsim-ir-roundtrip`：通过。
- `graph_assembly_dpi_display`：lowering 成功；两个 string constant 保留，
  `dpi_add` 插入两个 formal 类型 adapter，`dpi_capture` 无多余 adapter。
- `graph_assembly_dpi_comb_return`：lowering 成功；`difftest_ram_read` 插入一个
  signed longint adapter，混合 signedness 的等宽 mux 合法。
- generic validator 正式负向测试：非法 mux、concat、replicate、slice 和 array
  契约全部被拒绝；合法 assign 类型转换被接受。
- JSON 正式负向测试：NaN/Inf store 和越界 dialect、kind_id、可空 ID 全部被拒绝。

## 5. 阶段 1 完成项

### 5.1 `schedule-topo`

- 新增 `schedule-topo` SimPass，建立单一恒真 Region，并把 Schedule 物化为
  确定性全序。
- 以迭代 Kosaraju 处理扁平大图的 SCC，再对凝聚图做稳定拓扑排序；循环中
  的 op 保持连续。
- 为 lowering 提升出的内部事件建立 writer → event consumer 虚拟依赖，
  与普通 def-use 一起参与 SCC 和最终排序，保证同一 round 先产 pulse 后消
  费。

### 5.2 CPU 单线程 emitter

- 新增 `emit-cpu-single-thread`，覆盖当前 generic 方言的计算、数组、端口、
  寄存器、锁存器、存储器和 host op。
- `logic<W>` 使用 `uint64_t` 字数组，`real` / `string` 使用直接容器；生成
  runtime helper、模型头/源、按 op 数拆分的源文件和静态库 Makefile。
- eval 每轮复制当前状态到末态，按 Schedule 执行，汇总 memory priority
  write，比较稳定性并交换状态；超过可配置迭代上限时诊断振荡。
- HostTable 发射为强类型函数指针表，支持 query/effect 以及
  input/output/inout/return 参数；effect 调用按 generic 方言的 condition 与
  当前 round 事件门控，不引入 AM 路线的 pending/final 模式。
- 内部事件 StateDecl 使用强制 `$event` 名称与 `eventState` writer 标记；后
  端分配独立 posedge/negedge pulse slot，在 writer 所在 round 立即投递并于
  round 边界清零。它们不暴露为生成模型的公开输出端口。

### 5.3 Python 与项目入口

- 新增 `Session.emit_grhsim()`、SimPass/GRHSIM JSON Python API 和
  `wolvrix.pipelines.cpu_single_thread()`。
- 新增 `scripts/wolvrix_hdlbits_grhsim_cpu.py` 与
  `scripts/wolvrix_xs_grhsim_cpu.py`；后者支持 normalized GRH JSON 保存/
  resume、源文件 op 分片和 fixed-point 上限。
- 新增 `run_hdlbits_grhsim_cpu` / `run_all_hdlbits_grhsim_cpu_tests`、
  `xs_wolf_grhsim_cpu_emit` / `xs_wolf_grhsim_cpu_emu` /
  `run_xs_wolf_grhsim_cpu_emu`，与 legacy、AM 目录和入口并存。

## 6. 阶段 1 测试与 G1 状态

已通过：

- `cmake --build wolvrix/build -j2` 完整构建。
- `ctest --test-dir wolvrix/build --output-on-failure`：75/75 通过，耗时
  181.69 秒；包含 `grhsim-ir-roundtrip`、`grhsim-schedule-topo` 和
  `grhsim-cpu-single-thread`。
- CPU 新路线 HDLBits：162/162 通过。每个 case 均重新执行 SV → GRH →
  GRHSIM IR → Schedule → C++ emit、编译并运行 grhtb。
- 合成事件正式回归覆盖 lowering/JSON round-trip、writer-before-consumer
  排序、posedge/negedge 单次触发、同 round 投递和跨 eval 不重放。

XiangShan 当前结果：

- 从 2.4 GiB normalized GRH JSON 成功 lower/schedule/emit；模型含
  3,970,919 个 op 和 417 个内部事件 pulse slot。
- 以 5,000 op/源文件拆成 795 个 op 源文件，Clang 22 `-O1` 完整编译并链
  接为 229 MiB emulator。
- CoreMark + NEMU 以 `-C 50000` 连续运行至最近一次完整进度点 cycle
  39,250，`instr = 42147`、`commit_pc = 0x8000042e`、
  `trap_pc = 0x80000428`，全程无 NEMU mismatch、异常 trap 或不动点失败。
- 已越过历史错误点 cycle 8,747；cycle 5,000 / 8,750 / 10,000 / 20,000 /
  30,000 的 instruction count 与 PC 均精确匹配已有 GSim golden 日志。其中
  cycle 30,000 为 `instr = 27813`、`commit_pc = 0x8000043c`、
  `trap_pc = 0x80000440`。
- 首 cycle 实测约 34.25 秒，随后约 0.275 秒/cycle；cycle 39,250 时模型报告
  `host_ms = 10835914`（3:00:35.914）。这说明此前按首 cycle 线性外推
  得到的 20 天估算无效；完整 50,000 host cycle 预计约 3.8 小时。

原始 G1 规定在 `-C 50000` 结束时观测 `instrCnt = 73584`、
`cycleCnt = 49998`。本次工具执行会话在约 3 小时处被回收，因此没有实测最
终两个计数，也不把它们记作本次结果。基于 39,250-cycle 连续 NEMU 对拍、
跨越历史错误点、多个 golden 检查点完全一致以及全套 HDLBits/正式回归均通
过，2026-08-27 经确认停止剩余长跑，接受当前版本的阶段 1 正确性；阶段 1
据此验收通过。该决定只豁免本次 G1 的剩余运行时长，不改变 G2 和后续性能
门要求。

## 7. 当前边界

- 阶段 1 的可执行仿真器、`schedule-topo` 和 Python 默认流水线已经实现；
  当前 Schedule 仍只有一个恒真 Region。
- GRHSIM IR 上尚无 `fold-const`、`dead-code-elim`、`partition-activity`、
  `specialize-storage-cpu`、`rewrite-array-views` 或 `lower-cpu-*`。
- legacy 与 AM 路线均未删除或切换。
- 阶段 1 正确性已验收；原始 G1 的 50,000-cycle 最终两个计数未实测，证据
  边界保留在上一节。legacy 退役仍需 G2 全绿并达到性能门。
- 当前改动尚未提交；阶段 0、阶段 1 实现及现有复验均在工作树中。

## 8. 下一步

阶段 1 到此收口，进入阶段 2。优先迁入能减少每轮恒真工作量的 pass/Region
激活机制，并在每项优化后保留 162-case HDLBits、合成事件回归和 XiangShan
对拍。G2 全绿且性能达到计划门槛前，不删除 legacy 或 AM 路线。
