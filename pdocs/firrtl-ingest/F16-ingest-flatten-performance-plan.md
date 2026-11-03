# F16：ingest 到 hier-flatten 的三项性能修复

建立日期：2026-11-03。

状态：已完成实现与验收（2026-11-03）。承接 [F15 perf 分析](F15-ingest-flatten-perf.md)，按
**F16.1 分配器策略 → F16.2 Operation 快照消除 → F16.3 字符串/符号表查询优化**
推进；每项独立修改、验证和计时，最后复测组合结果。

## 1. 范围与基线

范围从原始 FIRRTL/mixed ingest 开始，经过八个默认前置 pass，截止于
hier-flatten 返回。沿用 F15 的固定线程池和 direct-publish 实现，
`lower_threads=10`、CPU affinity 0–31、F13 harness/include、annotations on。
保留全部前置 pass、参数、符号/来源信息、语义检查和诊断顺序。
本阶段聚焦构图前缀；simplify 和生成后仿真运行时的性能另行验证。

冻结输入为 `ptmp/xs/rtl/rtl/SimTop.fir`，1,671,325,062 bytes，SHA-256：
`cc46aae1a379d9e62132b76b0702685ba67761c87815067f770b0743d7dc754a`。
F15 当前基线 native 库 SHA-256：
`0af21d2d3727098a81432810ddebd05ca6a2a20262465331e48d2df34d1cb165`。

| 已有证据 | ingest | 前置 pass | hier-flatten | 连续总墙钟 |
| --- | ---: | ---: | ---: | ---: |
| F15 当前实现，无 perf，单次 | 163.850 s | 95.048 s | 314.402 s | 573.786 s |
| F15 同库 perf 诊断，单次 | 143.614 s | 94.358 s | 286.169 s | 524.612 s |

两次运行之间没有 native 性能修改，差值不代表优化收益。旧实现的
731.761 s ingest 不作为 F16 基线。正式收益需要新建同配置的成对对照。
F15 上述 10T 及 perf 运行的比较仅核对 timing、配置、诊断等，未比较完整图；
F16 的完整图等价验收需单独完成。

## 2. F16.1：修复分配器策略与大图工作负载不匹配

依据：flatten 中 `mi_heap_collect_ex` 与 `_mi_page_free_collect` 的 self
用户 CPU 样本合计为 58.90%。主要调用来自实例展开构图的分配慢路径，
周期性遍历当前线程 heap 的全部页面。

实施：

1. 用同一二进制对照默认 `generic_collect=10000` 与
   `MIMALLOC_GENERIC_COLLECT=1000000`，验证降低扫描频率后的阶段耗时、RSS
   和 perf 变化。本地版本将参数限制在 [1, 1,000,000]；0 会变为 1，
   不能用来禁用回收。
2. 对照构建 `SLANG_USE_MIMALLOC=OFF`。由 `wolvrix/CMakeLists.txt` 在
   `add_subdirectory(external/slang)` 前管理配置，检查已有 CMake cache
   和实际安装库，重启进程测量。关闭的是 slang 引入的全局 C++ new/delete
   替换；slang BumpAllocator 的分块和指针推进机制继续保留。
3. 根据完整前缀耗时和峰值 RSS 选择正式策略。若关闭全局替换整体更好，
   将其作为项目默认并保留显式开启选项。若保留 mimalloc，须说明回收策略
   的选择依据及内存代价；固定阈值降频实验不能代替长期策略评估。

验收：实际配置和加载库身份可核对；完整图与诊断保持一致；重新采样确认
周期性全堆扫描成本的变化，报告各阶段和总耗时，避免把成本转移到其他阶段。
58.90% 是 flatten 的用户 CPU 占比，不是预先承诺的墙钟降幅。

## 3. F16.2：消除前置 pass 的只读 Operation 快照

依据：`Graph::operationFromBuilder` 会复制 symbol、operands、results、
attrs 和 SrcLoc。前置 pass 的 memmove、分配及 Operation 快照构造均为热点。

实施：

- 优先处理 `register_write_normalize.cpp`、`memory_read_retime.cpp` 和
  `mux_tree_fold.cpp` 中先取完整 `getOperation()` 再筛选 kind 的扫描，
  以及只读一个属性或沿 alias 查询时的完整快照。
- 先用 `opKind()` 筛选，再按需使用 `opOperands()`、`opResults()`、
  `opAttrs()` 等借用接口；只复制确实需要拥有的数据。
- 跨 mutation 使用的字段或 ID 单独保存，覆盖首次 thaw、容器重分配和
  删除导致的视图失效，保留 attrs、SrcLoc、错误路径和变换顺序。

验收：相关变换回归和完整图对照通过；前置 pass 的快照/复制热点与阶段
耗时分别记录。`node::recordRetention` 的正常路径已使用借用视图，
不将这些 Operation 复制成本归因于 retention。

## 4. F16.3：减少 ingest 与 flatten 的重复字符串查询

依据：ingest 和 flatten 的 SymbolTable hash lookup、字符串 hash/比较
均有显著样本；全部 memcmp 成本不能直接归给 SymbolTable。

实施：

- 检查 `Graph::internSymbol`、`SymbolTable::intern/lookup` 及其热调用方，
  合并可避免的重复查找、hash 和拥有型临时字符串构造。
- 图内热映射优先使用 `SymbolId/ValueId/OperationId`；跨图采用显式映射，
  保持各图 ID 的作用域。缓存按图及生命周期管理，不引入全局共享热点。
- 保留符号冲突处理、插入顺序、内部名称生成、annotations、source identity
  和按序诊断；来源字符串仍按原格式发布。

验收：符号冲突与串并行确定性回归通过，完整图及诊断一致；重新采样量化
字符串查询/分配变化，并检查 ingest 串行协调与 worker 负载是否仍限制收益。

## 5. 验证、计时与交付

所有构建、安装、测试和脚本工作流均经项目 Makefile；缺少入口时先新增
Make target。日志、临时脚本和性能产物统一放在 `ptmp/firrtl-ingest/F16/`。

- 按“基线 → F16.1 → F16.2 → F16.3”分别保存源码/实际 native 库身份、
  allocator 配置、输入 manifest、CPU/线程配置及阶段 wall、CPU、峰值 RSS。
  正式计时关闭 perf，基线和最终候选至少各测三次并报告中位数与波动。
- 正确性至少比较 ingest 和 flatten 终点的完整图、全部有序 diagnostics、
  dependencies、metadata 和来源信息。计时之外单独完成图保存/比较，
  不将仅 timing 的核对记为图等价。独立 `--prefix-identity` Make 入口
  保存两个终点，`--through-flatten` 保持纯计时。
- 按改动运行 `test_ingest_driver`、`test_transform_simplify`、
  `test_transform_memory_read_retime`、`test_firrtl_node_attributes`、
  `test_firrtl_cse_scope` 及相关 fixture；最终运行 `test_wolvrix`、
  `test_ingest_python`、`test_xs_firrtl_workflow` 和 `test_grhsim_flow`。
  分配器调整还需覆盖 SV/mixed 路线，防止只改善 FIRRTL 单一路径。
- 复用 F15 benchmark/perf 入口并将工作目录显式指向 F16；需要新增选项时
  补相应工作流回归。最终重新采样三阶段，核对热点和绝对 CPU 成本的变化。
- 提交三项实施记录、逐项及组合性能对照、正确性证据和剩余热点；
  与 F14 的 76.491 s 比较采用原始输入到展平完成的连续总墙钟，说明路线
  工作差异，不省略前置 pass，也不据此推断生成后仿真速度。

退出条件：三项均有实现或基于实验的明确处置、正确性验证和独立性能记录；
最终候选完成重复计时及 perf 复核。未完成或未改善的项如实登记，
不预设已达到 GSIM 构图耗时。

## 6. 实施记录

2026-11-03 已保存 F15 有效 native 基线及未剥离符号库，位于
`ptmp/firrtl-ingest/F16/native/baseline/`；基线 SHA 与第 1 节一致。
首轮无采样连续前缀为 **513.804 s**：ingest **143.497 s**、前置 pass
**91.736 s**、flatten **278.151 s**，峰值 **116,947,020 KiB**。
这是三次基线重复中的第一轮，暂不据此计算正式收益。

新增 `benchmark_f16_firrtl_prefix`、`verify_f16_firrtl_prefix`、
`compare_f16_firrtl_prefix`、`summarize_f16_firrtl_prefix` 和
`snapshot_f16_native` Make 入口。独立的 `--prefix-identity` 模式保存
ingest/flatten 两终点完整图 hash、metadata、来源身份和有序诊断；
正式 `--through-flatten` 计时路线继续排除图序列化；回归结果见下文。

### F16.1 分配器选择

| 配置，均为单次 | ingest | 前置 pass | flatten | 连续总墙钟 | 峰值 RSS KiB |
| --- | ---: | ---: | ---: | ---: | ---: |
| 当前库，默认 10,000 | 143.497 s | 91.736 s | 278.151 s | 513.804 s | 116,947,020 |
| 同库，环境设置 1,000,000 | 140.081 s | 80.964 s | 122.647 s | 344.188 s | 116,784,428 |
| 关闭 slang 全局替换 | 208.885 s | 138.813 s | 197.006 s | 545.395 s | 151,663,992 |

以上均为无 perf 的原始输入连续前缀。关闭替换使总耗时和峰值内存上升，
因此保留 mimalloc。独立的同库 1,000,000 阈值 perf 运行中，两个 collect
函数的 self 合计由 58.90% / 159.744 sampled CPU s 降至约
4.43% / 5.106 sampled CPU s；该诊断轮不纳入正式重复计时汇总。
逐项对照为单次，最终组合的收益由下文三轮计时及完整图验证确认。

正式策略在项目自有 `core/allocator.cpp` 中于库初始化时执行一次
`mi_option_set_default`，默认间隔由 CMake 的
`WOLVRIX_MIMALLOC_GENERIC_COLLECT=1000000` 管理，限制在 [1, 1000000]。
显式 `MIMALLOC_GENERIC_COLLECT` 仍优先；每 100 次 generic 分配的延迟释放
维护保持原实现。当前大图的内存对照支持这一扫描频率取舍；更大 heap 的
扫描复杂度仍需关注，后续若再次成为主热点再评估增量维护策略。

默认策略只作用于非 IMPORTED 的 bundled `mimalloc-static`，其 options
为库私有符号；不在 Design、ingest、flatten 或工作线程运行期间写全局选项。
系统/共享 mimalloc 的进程策略由调用方配置；`SLANG_USE_MIMALLOC=OFF`
继续作为构建选项。私有 Python 诊断入口记录实际生效配置，不扩展 Session API。
新进程回归已核实默认、45000、0、2000000 分别报告 1000000、45000、1、1000000。

### F16.2 当前验证

三类 pass 的只读快照已改为字段借用。跨 mutation 保存必要的 ID、
事件签名、字符串与拥有型 SrcLoc；最终 `copyWrite` 保留必要源快照。
新增 Graph 端口布局查询重载，与 Operation/GraphView 共用无复制规则。

`make test_wolvrix` **81/81**、工作流 **71/71**、指定 ingest/transform/node
门禁及 `test_firrtl_comb` 的生成模型执行通过。新增回归覆盖冻结图首次 thaw、
递归 gate 增长、长来源属性和 SrcLoc、长名称/作用域/内部符号碰撞。
非法前向 node 引用作为负例保留原诊断，不增加语言语义。
对应 native 为 `native/snapshots/`，SHA-256 为
`8ce89fd7d2ee8012a6d12490e61338363f47c249d3c695942f1f73842f6de925`。
独立无采样大图计时为 ingest **139.547 s**、前置 pass **49.041 s**、
flatten **123.650 s**、连续总墙钟 **312.630 s**，峰值 **117,140,592 KiB**。
其中前置 pass 相比 F16.1 的单次 **80.964 s** 降低，flatten 变化很小；
这是逐项诊断的单次结果；最终组合三轮计时和完整图验证已完成，
该中间库的独立完整图对照另行记录。

所有 native 变体同时保存核心库、Python 扩展、TBB 依赖、CMake cache、源码
diff 和未跟踪源码。冻结包通过 `python -S` 加显式 PYTHONPATH 加载，
避免 editable finder 意外选中当前安装的另一版扩展；实际 SHA 仍由进程报告核实。

### F16.3 与组合验证

符号插入在已知 miss 时跳过重复查询；内部生成名一次检查/插入。
semantic 和 lowerer 使用模块内成功命中索引，借用稳定排序 map 节点，
原容器继续决定输出顺序。flatten 的源/目标符号重命名改为实例内 ID 映射，
待解析属性保留原始错误文本，DPI 复用及 generate group 成员使用目标 ID。

最终核心库 SHA 为
`fa8add5b4551148a8e7cf9331daf2122f8a123d447a26729442227fb692b7064`。
组合版本 C++ **81/81**、工作流 **71/71**、Python ingest **9/9**、
GrhSIM flow **5/5**，指定门禁与 FIRRTL/SV/mixed 生成模型编译执行通过。
新源码的 OFF 构建/API 及 ingest **9/9** smoke 通过，随后恢复 ON 安装，
与冻结 final 库逐字节相同，默认间隔重新核实为 1,000,000。

基线与最终组合在 ingest 和 flatten 的完整 JSON 分别为
**40,949,081,788** 和 **37,922,865,712 bytes**，两终点 SHA 均完全相同。
严格比较同时确认全部 metadata、来源 fingerprint、dependencies、pass
参数和有序 diagnostics 一致。证据位于 `identity-baseline/`、
`identity-final/`、`compare-final.json`，不纳入正式计时汇总。

独立 `final-1` 为 ingest **136.207 s**、前置 pass **50.002 s**、
flatten **122.350 s**、连续墙钟 **309.073 s**。相比 `snapshots-1`
差值很小，未证实 F16.3 的额外整体收益。最终三轮中位数为
**308.525 s（307.602–309.073）**，基线为
**513.804 s（511.448–522.743）**，连续墙钟缩短 **39.95%**，
速度比 **1.665×**，峰值 RSS 中位数变化 **−0.08%**。
最终仍为 F14 GSIM **76.491 s** 的 **4.033×**。

最终 perf 已完成，两个 collect 的 flatten self 合计为
**4.73% / 5.412 sampled CPU s**；前置 pass 的 `operationFromBuilder`
由同库 1M 对照的 **5.432 s** 降到 **0.744 s**，memmove 由
**15.859 s** 降到 **4.070 s**。StringHash 相关 STL self 行合计基本未降，
旧 lookup 成本迁移到 try_emplace，不能据旧函数名消失声称查询成本消失。
ingest worker 窗口存在接近 10 核并行及后段长尾，窗口前后主线程仍有
约 **91 s** sampled 用户 CPU；不能由用户态采样推断等待原因。
F16.1、F16.2 中间变体及最终组合的两个终点完整图、全部 metadata、来源
fingerprint 和有序诊断严格比较均通过。三项实施、逐项实验、最终三轮计时
和 perf 复核满足本计划退出条件；F16.3 额外整体提速未证实，如实保留结论。
详细证据记录于
[F16 实施结果](F16-ingest-flatten-results.md)。
