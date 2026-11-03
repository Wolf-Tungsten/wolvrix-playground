# F16：ingest 到 hier-flatten 的实施与性能证据

日期：2026-11-03。状态：三项实现与验收已完成；F16.3 的额外整体提速未证实。
范围、实现要求与退出条件见
[F16 计划](F16-ingest-flatten-performance-plan.md)，原始热点见
[F15 perf 分析](F15-ingest-flatten-perf.md)。

## 1. 计时范围与输入身份

以下计时均从原始 FIRRTL/mixed ingest 开始，执行生产路线的八个前置 pass，
截止于 hier-flatten 返回。`lower_threads=10`，CPU affinity 为 0–31，
annotations on，沿用 F13 harness/include。连续总墙钟包含阶段间协调开销，
不含图 JSON 序列化；每行均来自独立进程的无 perf 单次运行。

冻结 FIRRTL 为 `ptmp/xs/rtl/rtl/SimTop.fir`，大小
1,671,325,062 bytes，SHA-256：
`cc46aae1a379d9e62132b76b0702685ba67761c87815067f770b0743d7dc754a`。
完整 manifest、实际加载 native 库及运行配置保存在各运行目录中。

## 2. 已完成的逐项计时

| 运行目录 / 配置 | ingest | 八个前置 pass | hier-flatten | 连续总墙钟 | 全前缀峰值 RSS KiB |
| --- | ---: | ---: | ---: | ---: | ---: |
| `baseline-1`：F15 库，默认扫描间隔 10,000 | 143.497 s | 91.736 s | 278.151 s | 513.804 s | 116,947,020 |
| `generic-1m-1`：同库，环境覆盖为 1,000,000 | 140.081 s | 80.964 s | 122.647 s | 344.188 s | 116,784,428 |
| `allocator-off-1`：关闭 slang 全局分配器替换 | 208.885 s | 138.813 s | 197.006 s | 545.395 s | 151,663,992 |
| `snapshots-1`：项目默认间隔 1,000,000，消除只读 Operation 快照 | 139.547 s | 49.041 s | 123.650 s | 312.630 s | 117,140,592 |
| `final-1`：再加入 F16.3 字符串/符号查询优化 | 136.207 s | 50.002 s | 122.350 s | 309.073 s | 117,124,028 |

原始记录分别为
[baseline-1/timing.json](../../ptmp/firrtl-ingest/F16/baseline-1/timing.json)、
[generic-1m-1/timing.json](../../ptmp/firrtl-ingest/F16/generic-1m-1/timing.json)、
[allocator-off-1/timing.json](../../ptmp/firrtl-ingest/F16/allocator-off-1/timing.json) 和
[snapshots-1/timing.json](../../ptmp/firrtl-ingest/F16/snapshots-1/timing.json) 和
[final-1/timing.json](../../ptmp/firrtl-ingest/F16/final-1/timing.json)。
这些数据用于定位逐项变化；正式收益采用下文基线和最终候选各三次运行的
中位数及范围。

实际核心库 SHA-256：

| 变体 | `libwolvrix-lib.so` SHA-256 |
| --- | --- |
| baseline / generic-1m | `0af21d2d3727098a81432810ddebd05ca6a2a20262465331e48d2df34d1cb165` |
| allocator-off | `70edd9fafa7e178711089e65a4a17b3c8eef190aaa1d32ec664400ba22d98bc4` |
| snapshots | `8ce89fd7d2ee8012a6d12490e61338363f47c249d3c695942f1f73842f6de925` |
| final（F16.1–3） | `fa8add5b4551148a8e7cf9331daf2122f8a123d447a26729442227fb692b7064` |

### 正式重复计时

基线和最终版各三个独立进程，均关闭 perf、时间戳采样和图保存。
汇总检查确认各组 native 库、allocator 环境/有效配置、输入、CPU affinity、
生产 pass 参数和有序诊断一致，`equal=true`。
旧基线不含 allocator 查询 API，有效配置字段为 `null`；其 10,000 间隔依据
冻结版本默认值及清空环境的对照，未直接读取运行期选项。最终版的新 API
在三轮均实际报告 1,000,000。

| 阶段 | 基线中位数（范围） | 最终中位数（范围） |
| --- | ---: | ---: |
| ingest 墙钟 | 143.497 s（143.466–143.666） | 136.207 s（134.964–136.223） |
| 八个前置 pass 墙钟 | 92.057 s（91.736–92.901） | 49.775 s（48.809–50.002） |
| hier-flatten 墙钟 | 278.151 s（274.391–286.727） | 122.404 s（122.350–123.028） |
| 连续总墙钟 | **513.804 s（511.448–522.743）** | **308.525 s（307.602–309.073）** |
| 阶段合计 CPU | 655.742 s（651.424–660.171） | 440.813 s（439.457–446.894） |
| 全前缀峰值 RSS | 116,947,020 KiB（116,636,172–117,217,964） | 116,848,980 KiB（116,735,616–117,124,028） |

连续总墙钟中位数缩短 **39.95%**，速度比 **1.665×**，RSS 中位数变化
**−0.08%**。各阶段中位数单独计算，不能相加重建连续墙钟中位数。
原始汇总为 [summary-baseline.json](../../ptmp/firrtl-ingest/F16/summary-baseline.json)
和 [summary-final.json](../../ptmp/firrtl-ingest/F16/summary-final.json)。

与 F14 GSIM 的 parseFIR 5.213 s + AST2Graph/Init 71.278 s = **76.491 s**
相比，最终连续前缀仍为 **4.033×**。这里保留了原始输入 ingest、mixed
路线及八个前置 pass，没有达到 GSIM 初始构图耗时；两条路线工作不同。
该结论不涉及生成后仿真模型的运行速度。

## 3. F16.1：分配器实验的结论与边界

同库环境覆盖把主要变化集中在 flatten：单次墙钟从 278.151 s 降到
122.647 s，全前缀峰值 RSS 近似持平。关闭 slang 的全局 C++ new/delete
替换虽然也缩短 flatten，但 ingest、前置 pass 和峰值 RSS 均上升，
全前缀为 545.395 s。这组单次实验支持保留 mimalloc 并降低全堆扫描频率。
关闭替换作为构建选项保留，不能由这一组数据推导所有工作负载的最优分配器。

独立的 `perf-generic-1m` 运行使用相同 baseline 核心库并设置
`MIMALLOC_GENERIC_COLLECT=1000000`。flatten 中 `mi_heap_collect_ex` 与
`_mi_page_free_collect` 的 self 样本合计约 **4.43% / 5.106 sampled CPU s**，
F15 默认间隔诊断为 **58.90% / 159.744 sampled CPU s**。新诊断的 flatten
共有 22,913 个样本、115.141 sampled CPU s，报告 lost samples 为 0。
这些为阶段内用户 CPU 采样，不能直接解释为相同比例的墙钟降幅；该 perf
运行也不进入正式重复计时汇总。原始数据见
[flatten self report](../../ptmp/firrtl-ingest/F16/perf-generic-1m/reports/08-hier-flatten.self.txt)
及 [sampling quality](../../ptmp/firrtl-ingest/F16/perf-generic-1m/reports/08-hier-flatten.quality.json)。

项目通过库初始化时的一次默认配置设置，避免在 Design、ingest、flatten
或 worker 执行中修改全局选项。显式环境覆盖继续优先；CMake 默认间隔可配置。
固定阈值降低了本次大图的扫描成本，未来更大 heap 的扫描复杂度仍需测量。

最终源码另外以 `SLANG_USE_MIMALLOC=OFF` 完成安装和 API smoke：有效配置为
`false/false/null`，Python ingest 小图测试 **9/9** 通过，独立库保存在
`native/allocator-off-final-smoke/`。随后通过 Make 恢复 ON，安装核心库与
冻结 final 逐字节一致，SHA 未改变；默认配置也重新核实为 1,000,000。
见 [OFF 小图日志](../../ptmp/firrtl-ingest/F16/logs/ingest-allocator-off-final-smoke.log)
及 [恢复库身份](../../ptmp/firrtl-ingest/F16/logs/sha256-restore-final-on.txt)。

## 4. F16.2：只读 Operation 快照

`register-write-normalize`、`mux-tree-fold` 与 `memory-read-retime` 的只读扫描
改为先筛 kind，再借用所需字段。跨 mutation 保存必要拥有型数据，覆盖首次
thaw、递归构图增长和删除引起的视图失效。

`snapshots-1` 的前置 pass 单次墙钟为 49.041 s，对照 allocator 调整后的
80.964 s；ingest 和 flatten 变化较小。这支持复制成本主要来自前置 pass
的判断。最终组合三轮及完整图对照已通过，中间库图对照另行记录。

对应日志中 `make test_wolvrix` 为 **81/81**，指定 ingest/transform/node
门禁和 `test_firrtl_comb` 的生成模型执行通过，工作流为 **71/71**。
证据为 [native-snapshots.log](../../ptmp/firrtl-ingest/F16/logs/native-snapshots.log)
及 [workflow-snapshots.log](../../ptmp/firrtl-ingest/F16/logs/workflow-snapshots.log)。
这些结果对应 snapshots 变体，不能代替最终组合版本的回归。

## 5. F16.3：字符串与符号查询

`Graph::internSymbol` 在确认名称不存在后直接插入；内部生成符号用一次
`try_emplace` 检查并插入，碰撞不占用 SymbolId。符号字符串继续由原
SymbolTable 拥有，没有增加全局共享缓存或改变 ID 的分配顺序。

FIRRTL semantic 的声明查询使用透明查找和模块内成功命中缓存，lowerer
为字段路径为空的 Driver 增加索引。两者均借用不会擦除的排序 map 节点；
原 map 继续决定发布和诊断顺序，未命中不会缓存。

flatten 的重命名表改为源 SymbolId 到目标 SymbolId 的映射，每次实例展开
独立创建。字符串属性最终仍发布原格式名称，待解析引用保留拥有型错误文本；
DPI 复用和 generate group 成员也使用显式目标 ID。层次名称预留空间，
无冲突时避免额外复制候选名。

独立代码审查未发现生命周期或图 ID 作用域缺陷。现有回归覆盖长名称、
模块作用域、内部符号碰撞、串并行完整 JSON 和诊断、前向属性、DPI 复用及
pending 错误；补强了 mutable/frozen 源图中每个实例的 generate group
成员 ID 精确断言。最终编译、回归、组合大图等价与三轮性能证据见下文。

独立 `final-1` 为 309.073 s，对照 `snapshots-1` 的 312.630 s，差值较小。
这两个单次数据不足以确认 F16.3 的整体收益，不能将 F16.1/2 的主要改善
归因于字符串缓存；最终采样的绝对 CPU 成本见第 6 节。

## 6. 最终 perf 与剩余热点

最终库从原始输入重新采集 `cpu-clock:u`、199 Hz，安装库 SHA 与冻结
final 一致，未剥离符号库 `.text` 校验通过，allocator 默认 1,000,000。
诊断轮连续前缀为 308.329 s，不纳入正式三轮统计。

| 区间 | 样本数 | sampled 用户 CPU s | 未解析 leaf |
| --- | ---: | ---: | ---: |
| ingest | 51,715 | 259.874 | 10（0.0193%） |
| 前置 pass | 9,868 | 49.588 | 来自 self report，无独立 quality 文件 |
| flatten | 22,771 | 114.427 | 6（0.0263%） |
| 连续前缀 | 84,365 | 423.945 | 29（0.0344%） |

没有 lost samples 或无法解析的采样行，未解析 leaf 不涉及核心库。
以下只使用 self/period，不依赖旧 libdw 的 inclusive 祖先恢复；leaf
解析质量不能证明 DWARF 调用链完整。原始数据位于
[perf-final/reports](../../ptmp/firrtl-ingest/F16/perf-final/reports)。

### 绝对成本变化

表中单位为 sampled 用户 CPU 秒；三列均为独立单次 perf 诊断。

| 阶段 / self 函数 | F15 默认 10k | 同库 1M | F16 最终 |
| --- | ---: | ---: | ---: |
| ingest：两个 collect 合计 | 8.975 | 0.603 | 0.683 |
| ingest：SymbolTable StringHash 相关 STL 行合计 | 22.563 | 22.342 | 22.663 |
| ingest：memcmp | 28.653 | 28.930 | 21.518 |
| ingest：Hash_bytes | 13.161 | 13.241 | 14.568 |
| 前置 pass：operationFromBuilder | 5.211 | 5.432 | 0.744 |
| 前置 pass：getOperation | 0.136 | 0.030 | 0.005 |
| 前置 pass：memmove | 16.055 | 15.859 | 4.070 |
| 前置 pass：Hash_bytes | 5.045 | 5.236 | 5.181 |
| flatten：两个 collect 合计 | 159.744 | 5.106 | 5.412 |
| flatten：SymbolTable StringHash 相关 STL 行合计 | 17.734 | 17.608 | 18.000 |
| flatten：Hash_bytes | 6.106 | 5.980 | 5.724 |
| flatten：memmove | 5.678 | 5.573 | 5.598 |

F16.1 的主要收益来自降低周期性全堆扫描成本，最终 flatten collect
合计为 **4.73% / 5.412 s**。F16.2 将前置 pass 的快照构造与复制绝对
成本大幅降低；Hash_bytes 的比例随总成本下降而上升，绝对值基本不变。

F16.3 后，旧 SymbolTable 主 lookup 行从 flatten 的 17.171 s 变为
0.437 s，但新的 `try_emplace` 行占 **15.26% / 17.457 s**。
ingest 同样从旧 lookup 16.337 s 迁移到 lookup 1.367 s 和
`try_emplace` 15.744 s。不能把旧函数名消失解释成成本消失：含
`SymbolTable::StringHash` 的 STL self 行合计未降低。
该合计已经包含 lookup/try_emplace，不能再与它们相加；Hash_bytes 和
memcmp 也不能全部归因于 SymbolTable。

本次保留 F16.3 的去重查找、局部索引与 ID 映射，实现和正确性验收完成，
但**未证实其额外整体提速**。正式总收益主要由 F16.1、F16.2 支撑。

### 最终主要 self 热点

| 阶段 | 函数 | self | sampled CPU s |
| --- | --- | ---: | ---: |
| ingest | memcmp | 8.28% | 21.518 |
| ingest | mi_new | 6.40% | 16.643 |
| ingest | SymbolTable try_emplace | 6.06% | 15.744 |
| ingest | Hash_bytes | 5.61% | 14.568 |
| ingest | Lowerer::run | 3.48% | 9.045 |
| 前置 pass | Graph::opKind | 11.43% | 5.668 |
| 前置 pass | Hash_bytes | 10.45% | 5.181 |
| 前置 pass | memmove | 8.21% | 4.070 |
| 前置 pass | node::recordRetention | 6.26% | 3.106 |
| flatten | SymbolTable try_emplace | 15.26% | 17.457 |
| flatten | mi_new | 9.81% | 11.226 |
| flatten | Hash_bytes | 5.00% | 5.724 |
| flatten | memmove | 4.89% | 5.598 |
| flatten | Graph::~Graph | 4.22% | 4.829 |

### ingest 的线程利用情况

最终诊断轮 ingest 墙钟为 136.513 s。基于
`ingest.quality.json` 与 `ingest.samples.txt` 的逐线程 period 汇总：

| 线程 | sampled 用户 CPU s | 占 ingest 用户 CPU |
| --- | ---: | ---: |
| 主线程 | 91.035 | 35.03% |
| 10 个 lowering worker | 167.573 | 64.48% |
| 其余采样线程 | 1.266 | 0.49% |

worker 首样本集中于 ingest 后 **49.263 s**，末样本约 **86.164 s**。
50–55 s、55–60 s 分别累计 **48.372、48.166 s** worker 用户 CPU，
说明池确实接近 10 核并行执行。70–85 s 仅 worker 9532 出现用户 CPU
样本，累计 **14.628 s**；各 worker 总 CPU 最大/最小为
**35.950 / 14.106 s（2.55×）**，有明显长尾。

主线程在 worker 窗口之前和之后分别消耗 **46.015、45.000 s** 用户
CPU，窗口内仅 0.020 s。整体仍受大量主线程工作及 worker 长尾限制。
主线程包含 Lexer、semantic、CombLoopElim、node 检查等实际工作，
不能全部归为协调开销。用户态采样无法确定锁、睡眠或 I/O 等待原因，
也不足以将尾部直接归因于某个模块；模块/任务调度追踪属于后续定位工作。

## 7. 正确性与验收

逐项 timing comparison 均检查通过：manifest、配置、affinity、
输入大小、dependencies、metadata keys、ingest 及前置 pass 的有序诊断一致。
两份报告都明确记录 `graph_checked=false`：
[allocator timing comparison](../../ptmp/firrtl-ingest/F16/comparison-generic-1m-timing.json)、
[snapshot timing comparison](../../ptmp/firrtl-ingest/F16/comparison-snapshots-timing.json)。
独立 correctness 运行已确认 F16.1、F16.2 中间变体及最终组合版本
在两个终点的完整图均与基线一致：

| 终点 | 完整 JSON bytes | 基线、两个中间变体和最终版共同 SHA-256 |
| --- | ---: | --- |
| ingest | 40,949,081,788 | `2335818f7b338a14f9feb068cd2521f6f8b26b5768016055ce0b79c36afb1928` |
| flatten | 37,922,865,712 | `1143a54951c6e0f6e8c061ea82e51b4d6f4a0ff0cdfdde157789f6bb43e3d23c` |

严格比较同时通过全部 metadata、dependencies、来源 fingerprint、输入
manifest、CPU affinity、生产 pass 参数和全部有序 diagnostics 检查，
`graph_checked=true`、`equal=true`。原始证据为
`identity-baseline/`、`identity-final/` 和
[compare-final.log](../../ptmp/firrtl-ingest/F16/logs/compare-final.log)。
有序诊断沿用既有 comparator，仅规范化 `transactions/<request>/` 的请求
临时目录编号；消息、顺序及其余字段保留。完整图 SHA 比较不做文本规范化。
这些 correctness 运行保存并哈希完整 JSON 后删除大文件；阶段时间含图保存
带来的影响，不进入正式性能汇总。两个中间变体的完整图及全部 metadata、
来源 fingerprint、有序诊断也通过严格比较，全部 checks 为 true；见
[compare-generic-1m.log](../../ptmp/firrtl-ingest/F16/logs/compare-generic-1m.log)
和 [compare-snapshots.log](../../ptmp/firrtl-ingest/F16/logs/compare-snapshots.log)。

最终 native 已安装并冻结在 `native/final/`；新进程确认实际加载核心库
SHA 与第 2 节一致，`mimalloc=true`、`project_defaults=true`、
`generic_collect=1000000`。最终门禁为 C++ 全套 **81/81**、FIRRTL 工作流
**71/71**、Python ingest **9/9**、GrhSIM flow **5/5**，指定
ingest/transform/node 测试、FIRRTL comb 和 SV/mixed 生成模型编译执行通过。
原始日志为 [native-final.log](../../ptmp/firrtl-ingest/F16/logs/native-final.log)、
[workflow-final.log](../../ptmp/firrtl-ingest/F16/logs/workflow-final.log) 和
[check-final.log](../../ptmp/firrtl-ingest/F16/logs/check-final.log)。

三项实现/实验处置、逐项完整图及诊断对照、最终组合回归、两组三轮正式
计时和最终 perf 均已完成，满足 F16 退出条件。F16.3 保留去重与局部索引
实现，但不将它计作已证实的额外整体性能收益。

与 F14 的 76.491 s 比较时应使用原始输入到展平完成的连续总墙钟，
并注明两条路线的工作差异。312.630 s 为中间变体单次结果；这些构图
数据不说明生成后仿真模型的运行速度。
