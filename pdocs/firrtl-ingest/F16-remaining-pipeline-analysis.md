# F16 后续：ingest 到 flatten 的剩余流程成本

日期：2026-11-03。基于现有 F16 perf、一次 node 关闭实验及当前源码审计；
本轮没有重新采样或实施下述生产代码改造。node 开启采样不能直接充当关闭组的热点分解。

## 1. 需要同时改变 ingest 和 flatten

[node 消融](F16-node-attribute-ablation.md)得到：
`205.778 s = ingest 113.013 + 前置 23.957 + flatten 68.411 + 协调约 0.397`。
相对 GSIM Init 的差距由开启组 4.033× 变为关闭组 **2.690×**。
关闭组要达到 76.491 s，还要减少 **129.287 s（62.8%）**。

即便 flatten 完全归零，仍需 137.367 s；即便 ingest 完全归零，仍需
92.764 s；前置 pass 全部归零也仍需 181.821 s。因此只优化一段或删除若干
pass 无法达到这一目标。当前应优先减少串行重复分析与逐实例重复构图。

## 2. ingest：重复解析与完整语义分析

当前调用链：

```text
indexFile：Lexer 仍扫描全部 module body token
  → validate：串行 parseModule 每个模块，AST 随即丢弃
  → resolveFirrtlInterfaces：再次 parse 可达模块，保存到 parsedModules_
      → 每模块 Semantics::analyze(true)
  → 线程池 lowerModule：重新建立 Semantics，analyze(false) 后构建 GRH
  → 主线程链接、组合环处理、GrhVerify
```

源码：`lib/ingest/firrtl.cpp:143–146`、`firrtl/parser.cpp:812–839`、
`ingest/mixed.cpp:311–324/373–402`、`firrtl/lower.cpp:1123–1131`。
现有 AST cache 已避免 resolve→lower 重复 parse；遗漏的是 validate→resolve。
另外 `validate()` 对每条 statement/expression 构造分类字符串并累计 constructs map，
而生产 ingest 只消费 success/diagnostics。该统计应留给显式 census 工作流，
生产路线可跳过。index 的 token 扫描见 `firrtl/parser.cpp:520–530`。

`Semantics::analyze(true)` 并非只看接口：`firrtl/semantic.cpp:800–825`
同样执行 collect、memory port 推断、所有 statements、约束求解与 guard 归一化。
true 主要允许未知宽度并延后严格检查；lowering 又重建同类分析结果。

优先改法：

1. 第一次完整语法验证即填充现有 AST cache；不可达模块仍做原语法验证，
   可达 AST 移交后续阶段复用。模块解析也可复用线程池，保持按源码模块顺序
   报告错误，并控制缓存生命周期。
2. 分离接口约束摘要、层次 width/Reset 收敛和最终严格语义校验，避免为接口阶段
   生成后续不会使用的完整 connection/effect/guard 数据。对边界完全确定的模块
   建安全快路；未知宽度、Reset 和 mixed 依赖仍走完整推断。
3. 让模块内严格分析和 lowering 消费同一份已完成的语义结果。不能把旧 Semantics
   指针直接缓存复用：接口表更新会使其借用的 port 指针及内部 width/Reset 状态过期。
   也不能同时长期保留所有模块的完整语义对象而不测内存。

F16 开启组现有采样：ingest 用户 CPU 中主线程约 **91.035 s**，10 个 worker
约 **167.573 s**；worker 主要在 ingest 后 49.263–86.164 s 活跃，最忙/最闲
worker 总 CPU 为 35.950/14.106 s。池已实际接近 10 核执行，前后串行段及长尾
限制整体收益。以上不是关闭组的分阶段秒数，也不足以诊断锁等待。

尾部还有两个可直接处理的串行边界：

- `transform/verify.cpp:229` 按 graphOrder 串行运行图内只读验证。可抽出
  verifyGraph，在独立图上并行，再按原顺序合并诊断；跨层 hierarchy/ABI
  检查仍由事务协调者执行。
- `ingest/mixed.cpp:1117–1128` 只要有一个 pending cycle 图，就在整个 design
  上执行 CombLoopElim；已被 lowerer 证明无本地环的 FIRRTL 图也重新建邻接表。
  可保留随图修改失效的证明，仅处理 pending 和未证明的 SV/adapter 图，或每图
  并行；flatten 后的跨层检查继续保留。空环的快速退出已经存在，不能将其
  重新登记为待实现优化。

补充改动是保留 ID 分配/发布顺序，仅按 AST 大小或 body 字节数从大到小提交任务。
当前 `mixed.cpp:562–573` 按模块名顺序提交；GSIM `src/firParser.cpp:143–145/67`
已采用大任务优先。该改动针对长尾，不能加速主线程前后段。

## 3. flatten：第二次图物化与大量小分配

GSIM `src/AST2Graph.cpp:820–829` 的实例访问直接递归向同一张 graph 构图。
当前路线先构建模块 GRH，再在 `hier_flatten.cpp:1284–1637` 按实例逐 value/op
创建顶层 GRH，重新建立符号、属性、源码位置和双向边。

关闭组诊断确认 flatten 开始时 **10,040 个源图全部串行 freeze**，之后再克隆、
最后删除源图。freeze 能降低克隆期内存，不能未经测量就撤销；它也不是现有
采样中已证明的首要热点。

| 已确认的数据搬运 | 位置 | 建议改法 |
| --- | --- | --- |
| SymbolTable map/deque 各拥有一份字符串 | `core/grh.cpp:465–473` | 单份稳定字符串存储加索引，保留名称、碰撞和 ID 顺序 |
| 每个 op 分配 operands、operandUseIndices、results、attrs | `core/grh.hpp:577`，`hier_flatten.cpp:1530` | 批量追加连续 op/value/edge 数据，一次建立 use-list |
| 每个 op 独立分配实例路径 vector/string，即使 node 关闭 | `hier_flatten.cpp:1570–1593` | ScopeId 加共享路径表，API/导出时恢复 originModules 原格式 |
| SrcLoc 含四个 owning string，value/op 克隆均复制 | `core/grh.hpp:131`，`hier_flatten.cpp:1317/1538` | 不可变位置表加 SrcLocId，保留原来源信息 |
| 同 definition 每实例重建声明集、端口名称映射 | `hier_flatten.cpp:908/958/1003/1210` | 按 definition 缓存端口绑定、声明与属性重写计划 |

已有开启组 perf 中，flatten 的符号插入 self 为 **17.457 CPU s**，mi_new
为 **11.226 s**，freezeImpl self 为 **3.256 s**。这些证据支持继续优化 hash、
分配和数据布局；不能把它们直接换算成关闭组可节省的墙钟。

建议主改造是 **definition 展开计划＋批量实例化**：预先确定 value/op 映射、
端口绑定及 payload 大小，在最终图分配 ID 区间，批量写入并统一建 use-list。
后续 worker 可以写互不重叠的块，再按确定顺序发布；直接并发修改同一个 top
builder/symbol table/revision 不具备这一条件。
全过程保留 declared symbols、XMR、端口类型转换、DPI 复用、generate groups、
来源和原诊断；避免重新引入私有 Design→importGraph 的整图复制。

更大的选择是 FIRRTL 特化的紧凑规范化模板直接实例化成最终 GRH，减少模块
builder→frozen source→top builder 的一整轮中间物化。应先复用模块级规范化，
再评估该路线，不能为省 flatten 而把重复分析移到每个实例。

## 4. 前置 pass：重复全图检查与模块内流水

`core/transform.cpp:382–397` 在**每个 pass 之前**遍历所有 op 检查 dialect，
随后 pass 本体再遍历；即使 node 关闭，该预检仍存在。可在 Graph 维护 operation
kind/dialect 计数或可靠失效的缓存，在增删/改 kind 时更新，使准入检查只看摘要。
该预检在 PassManager 内置 timer 之外，但本次外层计时包含它。

`mux-tree-fold → register-write-normalize → mux-tree-fold(guarded_writes)`
有真实数据依赖：normalizer 重建 writer/mux/enable，第二轮还恢复 guarded 多写口，
不能直接删除。可提取 graph-local kernel，同一模块保持这三段的顺序，模块间
复用线程池；按原 pass/graph 顺序合并诊断并保留失败边界。`memory-read-retime`
同样以单图为处理边界。禁止并发调用共享 PassManager/context。

fold 内部 read/write/pad/dead 等阶段还可以复用按 kind 的候选索引，并随改写更新。
当前关闭组前置总计约 24 s，这些优化有意义，但其单独收益存在明确上界。

## 5. GSIM 计时终点与实施顺序

GSIM `main.cpp:311–322` 在 Init 后才执行 splitArray、detectLoop、topoSort、
inferAllWidth；F14 日志分别为 43.515/8.509/11.000/25.271 s。
GrhSIM ingest 已完成宽度/类型分析、模块 cycle 处理和 linked GRH verify。
76.491 s 可以继续作为目标，但两个终点不是严格相同的工作集合。
后续同时报告构图和必要检查耗时，避免仅把工作挪出计时区间来声称加速。

建议实施顺序：**解析/语义分析去重与串行检查并行化 → 共享字符串/来源表示及
批量 flatten → 前置 pass 候选索引与模块并行**。大任务优先调度、operand backlink
预留、dialect 摘要可作为先行小改动，但不将其当作消除全部差距的方案。

下一轮计时应在同输入、同功能配置下逐项核对，轻量探索按用户要求每个候选
只测一次，复用已有基线；不预设上述改动的收益。完整图、来源与诊断等价检查
按改动范围单独执行。node 关闭只作为本次定位工具，没有修改生产默认策略。
