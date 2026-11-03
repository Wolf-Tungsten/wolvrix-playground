# F15：ingest 到 hier-flatten 的 perf 热点分析

日期：2026-11-03。范围为原始香山 FIRRTL/mixed ingest、full 默认 GRH 前缀，
截止于 hier-flatten 返回；lower_threads=10，annotations on，F13 harness/include。

## 主要发现

最突出的成本是 **mimalloc 在分配慢路径周期性扫描整个线程 heap**。
hier-flatten 中 `mi_heap_collect_ex` 与 `_mi_page_free_collect` 两个函数自身合计
占 **58.90%** 用户 CPU 样本；所有 mimalloc 函数自身合计为 **65.63%**。
这已经是展平阶段首要优化对象。另有两类独立成本：ingest 的字符串/符号表查找，
以及展平前默认 pass 的完整 Operation 快照复制。

以下全部为各阶段内部的 **self 用户 CPU 占比**，不是墙钟占比。
同一阶段不同函数的 self 可相加；包含子调用的 inclusive 会重叠，不能直接相加。

| 阶段 | 热点函数 | self 占比 | sampled CPU 秒 |
| --- | --- | ---: | ---: |
| hier-flatten | `mi_heap_collect_ex` | 47.59% | 129.075 |
| hier-flatten | `_mi_page_free_collect` | 11.31% | 30.668 |
| hier-flatten | SymbolTable 字符串 hash lookup，`_M_find_tr<string_view>` | 6.38% | 17.296 |
| hier-flatten | `mi_new` | 4.19% | 11.357 |
| ingest | `__memcmp_evex_movbe` | 10.58% | 28.653 |
| ingest | SymbolTable 字符串 hash lookup，`_M_find_tr<string_view>` | 6.22% | 16.839 |
| ingest | `mi_new` | 6.12% | 16.558 |
| ingest | `std::_Hash_bytes` | 4.86% | 13.161 |
| ingest | `Lowerer::run` | 3.20% | 8.668 |
| ingest | `Semantics::expression` | 2.49% | 6.729 |
| 展平前八个 pass | `__memmove_avx512_unaligned_erms` | 17.05% | 16.055 |
| 展平前八个 pass | `mi_new` | 8.37% | 7.879 |
| 展平前八个 pass | `Graph::operationFromBuilder` | 5.53% | 5.211 |
| 展平前八个 pass | `Graph::opKind` | 5.50% | 5.176 |
| 展平前八个 pass | `std::_Hash_bytes` | 5.36% | 5.045 |

## 1. 首要问题：大堆上的周期性全页扫描

slang 的 `source/util/Util.cpp:13` 引入 `mimalloc-new-delete.h`，因此全局
C++ `new/delete`，包括 GRH STL 容器的分配释放，都走 mimalloc。
当前 skbuild 配置为 `SLANG_USE_MIMALLOC=ON`。

源码链如下，mimalloc 源码在 `wolvrix/build/skbuild/_deps/mimalloc-src/`：

```text
operator new → mi_new → 分配慢路径 _mi_malloc_generic
  page.c:1009–1012：累计默认 10,000 次 generic 分配后 mi_heap_collect(heap, false)
    → mi_heap_collect_ex（heap.c:124）
      → mi_heap_visit_pages（heap.c:163）：遍历当前线程 heap 全部页面
        → mi_heap_page_collect（heap.c:97）
          → _mi_page_free_collect
```

不是每次 `new` 都计入这个阈值；它针对 generic 分配慢路径。
默认阈值来自 `options.c:165` 的 `generic_collect=10000`。

指令级核验排除了“最近符号误归”的解释：`mi_heap_collect_ex` 符号边界为
`0x2ec12e0`、长度 `0x367`，其 25,686 个 flat 样本中 **25,522 个位于 +0x2b4**，
约 **128.251 sampled CPU 秒**。该位置正是 **MI_NORMAL 分支**读取 page next、
调用 `_mi_page_free_collect(page,false)`、检查 used 并继续遍历的循环。
force purge 和 abandon 分支不是主要采样位置。

`_mi_page_free_collect` 约 **88.3%** 样本在 `thread_free/local_free` 元数据读取与
检查处，主要样本不在 `lock cmpxchg`。这些 CPU-clock IP 样本证明执行集中在
页链及 free-list 元数据维护，不能单独推导硬件 cache-miss 率。

扫描在 flat 开始后约 20–250 秒持续出现，不是只在阶段终点发生一次。
`Design::deleteGraph`、`Graph::freeze`、`freezeInlineSources` 没有主动调用 collect；
不能把它描述成“每删一个 graph 就显式强制回收”。离线修复展开后，全部 25,686 个
`mi_heap_collect_ex` 叶样本都能追溯到 `_mi_malloc_generic → mi_new`；其中
**98.78%** 可见 `inlineGraphContents`，**98.84%** 可见 `inlineInstanceInfo`，
**1.11%** 可见 `GraphBuilder::freezeImpl/freezeInlineSources`。核心调用链为：

```text
inlineInstanceInfo → inlineGraphContents → 图/容器分配 → mi_new
  → _mi_malloc_generic → mi_heap_collect_ex → 全 heap page 扫描
```

这将主要触发点定位到实例展平构图中的分配；源图冻结也有同一路径。

优先验证方向是分配器集成/周期性回收策略对大 GRH 堆的适配，随后量化剩余图构造成本。
本次只分析，未更改 allocator 选项、图语义或优化轮次，未新增收益声明。

## 2. ingest：字符串查找、分配与串行协调成本

ingest 的 `memcmp`、SymbolTable hash table 操作、`_Hash_bytes` 各自都很显著。
所有 SymbolTable hash table 叶函数合计 **8.33%**，所有 mimalloc 叶函数合计
**12.14%**。这些 self 分类不等于某个单一上层调用的全部成本；例如不能把所有
`memcmp` 都归给 SymbolTable，Semantics 中的声明 map 也使用字符串比较。

源码核对入口为 `grh.cpp:439` 的 `SymbolTable::intern`、`:463` 的 `lookup`，
以及 FIRRTL `Semantics::expression`、`Lowerer::run`。
下一步应减少重复的文本查找与拥有型临时对象，同时保留 symbol/source identity。

线程样本显示：主线程有 **96.744 sampled CPU 秒**，10 个主要 lowering worker
中最忙的一个为 **37.829 秒**，其余约 **14.50–17.26 秒**。
总 ingest CPU / wall 为 **1.98**。10 个 worker 确有执行，整个阶段也包含大量
串行协调、接口解析及最终校验，且 worker 负载不均。此数据不支持把总耗时除以 10；
本次用户 CPU 采样不测 off-CPU 等待，不能由 mutex self 很小推导不存在阻塞。

## 3. 展平前 pass：只读查询构造完整 Operation 快照

`Graph::operationFromBuilder`（`grh.cpp:5303`）返回拥有型 Operation，复制
symbol、operands、results、全部 attrs 与 SrcLoc。默认前置 pass 中仍有多处
先取完整快照再筛 kind，或只为读取一个属性就复制整对象：

- `register_write_normalize.cpp:207` 全图扫描先 `getOperation` 再筛写端口；
  `holdsElement/holdsWhole/readsStorage` 等查询也取完整快照。
- `memory_read_retime.cpp:442` 的 `buildGraphIndex` 全图取快照再分类；
  `:985` 主循环又取快照筛 read-array。
- `mux_tree_fold.cpp:270` 的 `strip` 每级 alias 检查取快照；常量/比较查询、
  mux 树读取和写端口分组中也有同类调用（`:292/332/686/720/877/1689`）。

这些代码与采样中的 `operationFromBuilder`、`AttrKV`/variant/SrcLoc 复制以及
memmove 相吻合。self 数据没有给每个调用点分配全部子调用成本，不能把上述比例
解释成某一条 source line 的独占总成本。

另外，`PassManager::run`（`core/transform.cpp:407`）在 changed pass 后会对
全部 graph 执行 `node::recordRetention`；其 self 在前置 pass 中为 **3.82%**。
正常 retention 路径使用借用视图，不应把 Operation 快照成本归到它。

## 4. 采样配置、质量与复现

- 同一冻结 `SimTop.fir`，1,671,325,062 bytes，SHA256
  `cc46aae1a379d9e62132b76b0702685ba67761c87815067f770b0743d7dc754a`。
- 实际 native 库 SHA256
  `0af21d2d3727098a81432810ddebd05ca6a2a20262465331e48d2df34d1cb165`。
- perf 7.0.12，`cpu-clock:u -F 199 --call-graph dwarf,8192 --clockid mono`。
- 从原始输入运行一次，阶段用 CLOCK_MONOTONIC 纳秒起止切分；排除阶段外
  JSON 报告写入及进程退出析构，不加载/保存图 checkpoint，不进入 simplify。
- 安装库的整个 `.text` 与未剥离 skbuild 库地址、长度及 SHA 一致；只用后者的
  快照补函数符号，未重编或替换实际测量库。
- 完整区间 **126,600 samples**，采样用户 CPU period **636.181 s**；
  **0 lost samples**，未解析叶符号 period 约 **0.0221%**。
- ingest 有 53,875 samples；flatten 有 53,975 samples，全部在主线程。

本轮带采样的阶段墙钟为 ingest **143.614 s**、前置 pass **94.358 s**、
hier-flatten **286.169 s**，连续端点为 **524.612 s**。这是诊断运行，不能把它与
此前一次 573.786 s 的差值当作优化收益；期间没有改变 native 性能实现。

调用栈还有单独的工具限制：perf/libdw 对该 ELF 的 LOAD bias 有 0x1000 偏差，
原始调用树严重截断；已保留原始结果，并用仅作用于离线 perf 分析进程的适配
恢复真实父栈，未改变叶 IP 或样本 period。原始与修复后的 flat 叶样本文本经
`cmp` 确认逐字节一致。
8 KiB 栈快照仍使远端祖先覆盖不完整：`inlineGraphContents` 自身帧约 3,080 bytes，
`inlineInstanceInfo` 约 1,000 bytes，递归几层即可超出采集长度；已经保存明确的
展开地址越出原始 8 KiB 栈区间的日志。只有约 5.96% 的 collect 样本能追到最外层
`HierFlattenPass::run`，这不代表该 pass 只占 5.96%。因此本文总量使用完整 self
样本，恢复的父调用覆盖用于归属核验，inclusive 只表示可见祖先的下界。

复现采样和原始报告：

```sh
WOLF_ENV_SOURCED=1 make profile_f15_firrtl_ingest PYTHON=.venv/bin/python
WOLF_ENV_SOURCED=1 make report_f15_firrtl_profile PYTHON=.venv/bin/python
```

默认目录为 `ptmp/firrtl-ingest/F15/perf-10t-20261103/`。原始 perf.data 已存在时
驱动拒绝覆盖；重采样应覆写 `F15_FIRRTL_PROFILE_WORK` 为新的项目目录。

证据：`perf.data`、`record.json`、`symbol-identity.json`、`run/profile-stages.json`、
`run/timing.json`、`reports/*.self.txt`、`reports/*.quality.json`、`hotspots.json`。
指令核验见 `README.hotloop.md` 与 `hotloop.*`；离线展开诊断及适配见
`Makefile.unwind-diagnose`、`dwfl-bias-probe.c` 和 `unwind.*`。
展开修复验证与父调用覆盖的机器可读记录为 `unwind-quality.json`，说明为
`README.unwind.md`。
现有 workflow 回归 66/66 通过，日志为 `test-workflow.log`。
与此前同库 10T 运行的原始 manifest、CPU affinity、按序 diagnostics、dependencies、
metadata keys 和输入 SHA 核对全部相等，见 `comparison-timing.json`；此检查不含整图 JSON。

## 5. 与仿真运行时的关系

上述调用发生在模型生成期。默认生成模型的链接入口
`testcase/xiangshan/difftest/grhsim.mk:78` 连接 harness、模型 archive 及系统库，
不链接 libwolvrix/slang/mimalloc；emitter 生成的 Makefile 也按此方式构建模型库。
现有 F13 fixture 驱动的动态依赖与符号检查符合这一点。

因此，当前已经定位到明确的生成期 allocator 性能问题，但不能把这个
`mi_heap_collect_ex` 热点直接外推成生成后仿真运行时的同一个问题。
仿真执行效率及生成模型中的冗余工作应由生成代码和独立 runtime profile 判断。

## 6. 后续修复

2026-11-03 将分配器策略、前置 pass 的 Operation 快照消除、ingest/flatten
字符串与符号表查询优化登记为 **F16.1–F16.3**，按此顺序实施及独立验证。
计划与验收见 [F16-ingest-flatten-performance-plan.md](F16-ingest-flatten-performance-plan.md)。
