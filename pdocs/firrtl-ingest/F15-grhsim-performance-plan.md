# F15：GrhSIM 相对 GSIM 的生成性能差距与优化优先级

建立日期：2026-11-02。

状态：核心实现已完成，整机 A/B 测量仍待在冻结香山输入上执行。本文只使用
[F13](F13-grh-performance-plan.md)、[F14](F14-gsim-performance.md) 及其引用日志和当前源码，
未新增整机性能测量，也不预先承诺定量收益。

## 1. 结论：主要差距在重复化简和大图数据搬运，不在 C++ emitter

两次试跑使用同一份 1,671,325,062-byte `SimTop.fir`，SHA-256 均为
`cc46aae1a379d9e62132b76b0702685ba67761c87815067f770b0743d7dc754a`，
范围都只到 FIRRTL→C++，不含生成代码的编译、链接和仿真：

- GSIM 在 **778.590 s** 完成，发布 244 个 C++ 文件。
- GrhSIM 在 **2400.008 s** 被硬截止，仍停在首次后端 `grhsim-simplify`，
  C++ 文件为 0。此时已用时间是 GSIM 完整生成时间的 **3.08 倍**，但这不是
  真实端到端倍率；GrhSIM 的实际完成时间和倍率仍未知。
- GrhSIM 的普通 GRH `simplify` 单项就为 **1060.191 s**，已经超过 GSIM 整条
  FIRRTL→C++ 路线。普通 simplify 与尚未完成的后端 simplify 合计至少
  **1329.739 s，占已用预算 55.4%**，是第一优化对象。
- 两条路线并不等价：GrhSIM 还包含 mixed ingest、完整 GRH/GrhSIM 变换、
  node annotations、显式校验、checkpoint 和 IR 转换；GSIM 直接消费 FIRRTL。
  因此下表用于定位成本，不用于证明可以删除某个语义 pass 或减少优化轮次。

### F13 已用 40 分钟预算的去向

| 阶段 | 秒数 | 占 2400.008 s |
| --- | ---: | ---: |
| 普通 GRH simplify | 1060.191 | 44.2% |
| hier-flatten | 381.999 | 15.9% |
| FIRRTL/mixed ingest | 272.581 | 11.4% |
| 首次后端 grhsim-simplify（未完成，仅已观察部分） | 269.548 | 11.2% |
| 其他前序/后序 pass、comb-loop、两次 verify、memory-init-check | 295.555 | 12.3% |
| flat checkpoint + grh-to-grhsim | 113.218 | 4.7% |
| 启动及阶段间未归属时间 | 6.916 | 0.3% |

GSIM 的 101.8 GiB 最大 RSS 与 GrhSIM 的 107.044 GiB 单进程 VmHWM 同量级，
两次记录也都没有 OOM。现有证据不能把 3 倍以上的时间差简单解释为内存不足；
但大对象复制、字符串校验和缓存不友好仍可能转化为 CPU 成本，需要按 F15.2 测量。

## 2. 为什么慢

### 2.1 固定点以整图 pass 为调度单位，并在两种 IR 上重复执行

普通 `simplify` 每轮调用 const-fold、redundant-elim，按需调用 DCE；
即使只有一个局部改写，下一轮仍重新进入整图 pass。F13 首轮为 603.358 s，
后七轮仍需 **456.833 s**，八轮全部 `changed=1`，达到上限并不代表收敛。

当前源码中，const-fold 虽有内部折叠 worklist，但每次调用仍包含
`collectConstants`、全图初始化、`simplifySlices`、`simplifyUnsignedComparisons`
和 `eliminateDeadConstants` 等扫描（`wolvrix/lib/transform/const_fold.cpp:1629`）。
redundant-elim 每次重新计算拓扑 rank 并扫描全部 op
（`wolvrix/lib/transform/redundant_elim.cpp:516`）。普通 simplify 只在这些
pass 之间传递一个布尔 dirty 标志（`wolvrix/lib/transform/simplify.cpp:55`），
没有传递“哪些 op/value 变脏”。

转换后又在 GrhSIM IR 上执行 fold/share、DCE、used-bits 和拓扑排序。首次后端
simplify 已完成两轮就用了 234.732 s，其中 fold/share 为 184.787 s；
两轮都仍有变化。每个变化轮还会重排全部 member、重建 owner groups，并重新执行
`orderedOperations`（`wolvrix/lib/transform/grhsim/simplify.cpp:433`）。
默认 flow 在 converted、pack、recover-masked-OR 和 nonsink partition 后最多可
四次调用该 pass，每次上限八轮（`scripts/grhsim_flow.py:181`）。F13 尚未走完第一次，
所以 269.548 s 只是后端成本下限。

相比之下，GSIM 主流程将 constant analysis、alias analysis、commonExpr 等组织为
一次主要的全图阶段，在阶段间做死节点清理（`reference/gsim/src/main.cpp:313`），
没有普通 GRH/GrhSIM 两套全局固定点。这是两者 pipeline 形状的重要差别，
不是单纯的 C++ emitter 差别。

### 2.2 通用 GRH 保留了丰富的拥有型元数据，热点操作反复复制、排序和校验

FIRRTL node key 是包含 module、instance path、node 和 field path 的长 canonical
JSON 字符串。每个 op 的 members/origins/roots 仍以 `vector<string>` 保存。
`read` 复制这些 vector，`unite` 拼接后再 `normalize`，`write` 又做 key 校验、
排序去重和属性写回（`wolvrix/lib/ingest/node_attributes.cpp:226`）。flatten 则对
每个实例的关联执行 parse、路径限定、重新编码和写回
（`wolvrix/lib/ingest/node_attributes.cpp:340`）。

F13 已消除多处完整 Operation 快照和不必要深复制，但没有改变上述拥有型表示。
此外，每次普通 const-fold 都调用 `requireValid`，每次 redundant-elim 都调用
`scanAttributeErrors`；八轮意味着至多 16 次全图 node-attribute 校验，尚未计入
独立 `grh.verify`。CSE 功能签名虽排除 node attrs，合并时仍要读取、合并并重新
规范化这些字符串。

这些成本有方向性证据：历史同结构 fixture 中，annotations off→on 的 flatten 为
0.455→1.148 s，simplify 为 1.546→10.141 s；这只能说明 fixture 上元数据路径昂贵，
不能外推整机占比。F13 的 flat GRH 仍有 **12,286,806,235 bytes**，说明后续必须
直接测量属性字节数、校验次数和分配成本，而不能继续只凭 wall time 猜测。

### 2.3 前端和层次展开是第二梯队成本，当前模块 lowering 仍按共享事务串行执行

ingest 272.581 s、flatten 381.999 s，合计已占预算 27.3%。GSIM 日志明确显示
10 线程解析，parse 为 5.213 s、AST2Graph/Init 为 71.278 s；这些数字不包含
GrhSIM 的全部 mixed 语义和校验，不能拿来要求同时间完成，但说明并行是可利用的
实现差别。

GrhSIM 的 `Transaction::ensureFirrtl` 递归解析依赖、调用 `lowerModule`，并直接
修改共享 `design_`、`interfaces_` 和诊断状态（`wolvrix/lib/ingest/mixed.cpp:574`）。
因此不能把现有递归函数直接扔进线程池；需要先把可并行的纯模块工作与确定性发布
分开。F12 的历史 profile 也把主要 ingest 成本定位在 lowering、interface resolve
和 linked verify，而非单纯 lexer，所以仅并行字符串解析不会解决主要问题。

## 3. 三个最值得做的优化点

优先级按当前已观察成本、影响的阶段数量和可保持语义的实现路径排序。
三项都必须保留 full pipeline、annotations、全部默认优化和校验；不能用 bringup、
减少轮次、关闭 checkpoint 或从 checkpoint 续跑来制造收益。

### F15.1（P0）：把两级 simplify 改为跨 pass 的增量 dirty-worklist，并查明未收敛原因

**目标：消除“局部修改、整图重跑”，同时保留所有 rewrite 和既有收敛上限。**

1. 先增加聚合计数，按轮记录各 rewrite 的访问/命中/实际修改数、op/value 净变化、
   worklist 入队数、拓扑重建、常量解析、CSE key 构造和 node 合并次数。
   当前只有 `changed=1`，必须区分长依赖链的正常传播、同一 op 被重复改写，以及
   A→B→A 振荡；八轮打满不应直接当成“电路需要八轮”。
2. 普通 GRH 首轮仍完整播种；后续把 const-fold、redundant-elim、DCE 接到共享的
   op/value dirty 集合。改写后只唤醒新 op、users、定义邻近点和受影响的声明/端口根；
   DCE 沿反向活性增量传播。队列顺序必须确定，不能因为 hash 遍历顺序改变结果。
3. 让 const-fold 的 slice/comparison/dead-constant 子阶段消费对应 dirty kind，
   不在每次调用时全部扫描。拓扑 rank、常量表和 CSE 表按图版本复用；不能安全增量
   维护的结构才在 dirty 区域或明确边界重建，而不是每个布尔 dirty 后整图重建。
4. 后端 fold/share、used-bits、owner grouping 和拓扑同样按 dirty owner/op 调度。
   pack/recover/partition 后只把其实际改动的集合播种到下一次 simplify，不重复
   发现上一轮已经稳定的区域。所有规则仍可对由依赖传播唤醒的 op 再运行。
5. 为每条规则补充幂等和收敛诊断：稳定图上重复执行必须 `changed=0`；达到八轮时
   输出仍未稳定的 rewrite-kind/top ops，作为修复振荡或规范形的依据，而不是简单
   提高 `max-rounds`。

**为什么第一：** 普通 simplify 后七轮已有 456.833 s 的直接成本，后端又有大量
重复 fold/share 和拓扑工作；该项还覆盖后续 pack/partition 后的多次 simplify。
它不假设首轮 603.358 s 会全部消失，首轮内的表示成本由 F15.2 处理。

**验收：** 相同默认配置下比较逐轮计数、最终 GRH/JSON、annotations、诊断和生成 C++；
覆盖长常量链、alias/slice 链、CSE 合并、DCE 反向传播、状态/效果/端口和跨 owner
边界。先跑现有 Make 原生/flow/FIRRTL 回归，再从冻结输入做完整 A/B，记录是否真正
收敛及各阶段 wall/RSS；不得只报告 pass fixture 加速。

### F15.2（P0）：将 node 属性和 CSE 热数据改为 interned ID/借用视图，校验按版本增量执行

**目标：降低首轮 simplify、flatten 和每次 CSE/rewrite 的字符串、vector 与分配成本。**

1. 在 graph/pass 内建立 canonical node-key intern table，把 members/origins/roots
   表示为稠密 `NodeKeyId` 及小型 ID 集合。字符串每个 graph 只存一份；
   CSE/DCE/alias 合并按 canonical key 的逻辑顺序排序去重（不是按 intern 插入顺序），
   不再复制并重校验所有长字符串。架构已允许中间分析使用不持久化的稠密索引，
   JSON/checkpoint 边界仍按 schema v2 还原原有字符串，不改变 source identity。
2. flatten 的 qualification 改为定义级 key ID + 实例路径的组合缓存；同定义多实例
   复用已解析身份，只计算新的限定 ID。嵌套实例、转义路径、同定义多实例和 64 项
   降级规则保持原语义，只有真正需要诊断、分图或持久化时才物化完整 key。
3. 给 node attrs 建立独立于功能图修改的 revision/valid 标记。在 ingest/JSON load
   做完整校验，rewrite 只校验被改属性，既有显式 `grh.verify` 和最终验证仍保留。
   不得用悬挂的 `string_view` 或仅凭 Graph 指针缓存校验结果；缓存键必须覆盖图身份
   和属性版本。
4. 同步精简功能签名：普通 redundant-elim 的 `OpSignature` 当前拥有 operands、
   attrs 和 shape，后端 `cseKey` 每轮为 op 构造字符串并排序 attrs。改为借用的
   typed key/interned attr ID + 精确相等比较；node/origin 非功能属性继续排除在
   功能 key 外，不能借优化之名改变 CSE 合法性。
5. 在实施前后增加低开销统计：node key 总字节/唯一字节、每 op 平均关联数、
   `read/unite/normalize/write` 次数、全量/增量校验次数、属性相关分配和 RSS。
   若整机 profile 证明主要成本并非属性，再缩小该项范围，不做无证据的全 IR 重写。

**为什么第二：** 它同时作用于 flatten 381.999 s、普通 simplify 首轮 603.358 s、
后续 redundant-elim/CSE 和后端 fold/share，也是 F15.1 增量化后仍会留下的每 op
固定成本。12.29 GB flat GRH 和 fixture 只提供方向，正式收益必须由整机计数和 A/B
确认。

**验收：** schema v2 JSON roundtrip 字节身份、完整 inventory/tombstones、roots/
rootResults、嵌套 qualification、CSE 多源合并、64-association 降级及诊断顺序不变；
annotations on/off 的功能变换保持透明。除现有测试外，必须检查多实例和冻结图首次
修改，记录整机属性字节、峰值 RSS 和各阶段时间。

### F15.3（P1）：将 FIRRTL 模块 lowering 拆成并行纯计算与确定性发布

**目标：缩短 272.581 s ingest，并为后续独立 module/graph 分析复用并行框架。**

1. 保留现有接口固定点和 mixed specialization 的协调逻辑。在接口签名、AST 和
   annotations 可只读共享后，以 module 为任务并行执行 FIRRTL 语义 lowering；
   主线程为最终 `Design` 预创建目标 graph，每个 worker 独占一个 graph 和本地
   arena；共享接口只读，不并行修改 Design 目录或其 symbol table。graph 内符号
   表独立，所属 Design 的 revision 在并行批次边界合并更新。
2. 主线程按既有依赖顺序发布：解析 instance target、应用 annotations、发布
   dependencies/diagnostics，并保留 graph 目录的插入顺序；不复制 FIRRTL graph。
   内部 GraphId 由预创建顺序确定，不属于 JSON 身份。外部 SV 实现、交替
   FIRRTL↔SV 依赖及递归检测仍由事务层串行协调，只并行已证明独立的 FIRRTL 工作。
3. worker 完成后按现有生命周期释放 module AST/临时类型展开，避免并行后把全部
   临时对象同时保留到发布结束。线程数固定并写入 manifest；先测 1/2/4/8/10，
   不把 GSIM 的 10 线程直接当成最佳配置。
4. linked-design verify 若在新 profile 中仍是显著整图成本，再按 graph 并行只读检查，
   诊断归并仍保持原顺序。不要先并行仅十几秒的 lexer，却把主要 lowering/verify
   留在串行路径。

**为什么第三：** ingest 是当前第三大的已完成单阶段，且有清晰的模块级并行边界；
但其绝对成本低于两级 simplify 和 flatten/元数据路径，并行还涉及确定性及内存峰值，
所以排在 F15.1/F15.2 之后。272.581 s 中可并行的比例尚需新 profile 确认，
不宣称线性加速。

**验收：** 1 线程与多线程的完整 design JSON、6,007 条既有诊断及顺序、dependencies、
metadata keys、mixed binding 和 source info 一致；重复运行结果确定。通过现有 ingest、
mixed、FIRRTL target 和 grhsim-flow Make 回归后，再测整机 ingest wall/RSS 和完整
FIRRTL→C++，同时检查并行是否因内存带宽或分配竞争而退化。

## 4. 暂不优先的方向

- **只优化 checkpoint 或 grh-to-grhsim：** 当前两者合计 113.218 s，占已用预算
  4.7%，不是最大差距。最终 checkpoint/roundtrip 尚未走到，后续仍须计时，但不能
  用未知成本替代当前已知热点。
- **只优化 C++ emitter：** F13 尚未进入 emit；GSIM emitter 本身仅 18.361 s。
  当前瓶颈在到达 emitter 之前。
- **单纯减少 RSS 或容器微调：** 两条路线 RSS 同量级，F13 已完成一轮深复制清理。
  下一步应先用 F15.1/F15.2 的计数证明整图调度或属性表示成本，再做容器微调。
- **删除普通 simplify、减少轮次或关闭 annotations：** 这改变既定验收配置，
  不是本次建议。需要修的是重复调度和数据表示，不是绕过功能与优化要求。

## 5. 推荐实施顺序与共同门禁

按 **F15.1 计数与收敛诊断 → F15.1 增量调度 → F15.2 属性表示 → F15.3 并行 ingest**
推进。前两项可以使用同一份普通/后端 simplify profile，但代码改动和 A/B 应分开，
避免无法归因。

所有性能实验使用同一冻结 FIRRTL、harness、源码/安装库身份、CPU/线程配置和 full
默认选项；保留原始输入开始的单一总计时。每个候选至少记录阶段 wall、峰值 RSS、
op/value/attribute 计数、收敛轮数、诊断和最终产物身份。功能门禁继续通过项目
Makefile 运行，性能证据及临时产物放入 `ptmp/firrtl-ingest/F15/`。

## 6. 实施记录

2026-11-02 已完成三项实现的可回归部分：

- F15.1 在普通 GRH simplify 中加入共享 graph-level dirty worklist。首轮完整播种；const-fold、redundant-elim 和 DCE 只消费上游实际修改的 graph，并按既有依赖关系重新入队。GrhSIM simplify 在 owner 分组上维护确定性的 dirty-owner 集合，改写后唤醒当前 owner、结果 users 和输入 producers；稳定 owner 会被跳过。每轮日志记录 worklist、候选/命中、删除、op/value delta、owner 访问/跳过和达到上限时的未收敛 pass。GrhSIM 的 fold/canonicalize/mux/CSE/node merge/DCE/topology 计数仍由 `WOLVRIX_GRHSIM_SIMPLIFY_STATS=1` 开启。
- F15.2 增加按 graph identity/revision 的 node 属性校验缓存，并把 flatten 的限定 key 缓存改为 transient `NodeKeyInterner` ID 表；GrhSIM CSE key 的字符串属性也通过稳定存储的 transient interner 编码，避免每个 key 复制长字符串。JSON schema v2 仍发布原有 canonical 字符串。`WOLVRIX_HIER_FLATTEN_PROFILE=1` 现在同时记录 qualification 命中、唯一 key 和字节数；验证缓存不跨 graph 或 revision 重用。
- F15.3 增加 `FirrtlOptions::lowerThreads`。大于 1 时，事务先发现可达 FIRRTL 模块，由主线程为最终 Design 分配目标 graph，线程池任务各自独占一个 graph 直接 lowering；发布时只把同一个 `unique_ptr<Graph>` 插入目录，不再构造私有 Design 或通过 `importGraph` 复制 FIRRTL 整图。依赖解析、annotation、external/SV binding、诊断和最终 verify 仍在事务发布阶段完成。worker 异常先保存为 `exception_ptr`，由确定性的 `ensureFirrtl` 依赖顺序重新抛出，以保留串行路径的 source-aware 诊断。默认值 1 保持旧调用，Python request 支持 `firrtl.lower_threads`。

定向门禁均通过项目 Makefile：`test_transform_simplify`、`test_firrtl_node_attributes`、`test_firrtl_cse_scope`、`test_grhsim_transforms`、`test_ingest_driver`。ingest-driver 比较 `lowerThreads=1` 与重复 `lowerThreads=2/4` 的 `firrtl/comb/parallel.fir` 完整 JSON 和诊断；fixture 包含六个可达模块。`parallel_error.fir` 使模块排序与依赖顺序相反，验证多个 worker 同时失败时的错误顺序和源码位置。线程池版本的其余线程数和完整 FIRRTL→C++ A/B 仍需单独记录，不能由这些小型回归外推收益。

2026-11-03 对同一冻结 `SimTop.fir`（1,671,325,062 bytes，SHA-256
`cc46aae1a379d9e62132b76b0702685ba67761c87815067f770b0743d7dc754a`）完成了
严格 F13 harness/include 配置下的 native FIRRTL/mixed ingest 对照。1 线程固定 CPU 0
为 **301.616 s / 70,150,056 KiB**；放开 CPU 亲和性后的 1 线程为
**272.526 s / 71,159,504 KiB**；2 线程放开亲和性为 **869.533 s /
96,361,172 KiB**；4 线程为 **785.765 s / 96,824,460 KiB**；8 线程为
**747.921 s / 95,542,828 KiB**；10 线程为 **731.761 s / 93,468,600 KiB**。
这些运行使用同一 `threads-{1,2,4,8,10}.json` 配置，只有
`firrtl_options.lower_threads` 不同；2 线程
结果是 **3.19×** 的时间回退并增加约 35% 峰值 RSS，4 线程仍比未固定的 1 线程慢
**2.88×**，8 线程慢 **2.74×** 且峰值 RSS 增加约 34%。这些结果属于旧的分批
`std::async` 实现；没有阶段 profile，尚不能把退化归因于锁、解析、复制或分配中的
某一项。固定 CPU 0 的 1 线程数据与未固定的多线程数据不作直接倍率比较。

原始测量在 `ptmp/firrtl-ingest/F15/strict-threads-{1,2,4,8,10}/` 及
`strict-threads-1-unpinned/`，manifest 分别记录线程数、输入/harness 路径和库身份；
`timing.json` 保存 wall、RSS、6,007 条诊断和线程亲和性。该轮只完成 ingest 阶段，
未生成完整 GrhSIM C++；因此不把负向 ingest 结果外推为完整
FIRRTL→C++ 结论，后续整机 A/B 仍保持待测状态。

线程 manifest 可由 `make prepare_f15_firrtl_manifests` 从同一冻结 FIRRTL 和 F13
harness include 目录重新生成；每次 benchmark 仍使用显式 manifest，避免
`xs_firrtl_inputs` 在测量期间改写输入。`ptmp/firrtl-ingest/F15/strict-thread-comparison.json`
记录 1/2 线程的完整 JSON、诊断、依赖和 metadata 比较，所有内容检查均相等。

2026-11-03 按用户要求将分批 `std::async` 改为事务内固定大小的线程池，worker
通过 mutex/condition_variable 队列动态取任务，执行 lowering 时不持有队列锁；
主线程按固定模块顺序消费 future，继续保留私有 Design 和依赖顺序异常发布。
先前 `invalid-old-native-pool-threads-2` 的 849.866 s 测量仍加载旧安装库
（`SKIP_PY_INSTALL=1`），
因此属于无效的线程池性能证据。线程池性能须在 `make py_install` 后，核对实际加载
库身份再测；该轮当时仍保留私有 Design，未采用共享 Design 或原子化全局 revision。
`parseFirrtlModule` 使用事务级 AST 缓存，可达发现、提交和依赖发布的多次调用命中
同一缓存；先前关于该路径重复解析的归因不成立。benchmark 新增 ingest user/system
CPU 时间，以便与 wall time 一起检查并行利用情况。

线程池 2T 的有效整机测量保存于 `ptmp/firrtl-ingest/F15/pool-threads-2/`。
`make py_install` 成功后核对实际加载的 `libwolvrix-lib.so` SHA-256 为
`47af6414133c0ddfee7a379c4f4a03add3f35288466537b059d038b304301c1f`，与旧分批库
`d62c2f3e180bf1bf69da5ff8bad76599d5282b1ebf1e6a77b4ca0caccd2d5f33` 不同。
同一 32 CPU affinity 下，ingest 为 **676.248 s / 88,071,172 KiB**，相对旧分批 2T
的 869.533 s 减少 **22.23%**，RSS 减少 **8.60%**；这是各一次整机测量。
进程 CPU 时间为 **750.118 s**（user 734.033 s、system 16.085 s），全 ingest 平均
CPU/wall 为 1.109。该总量不能单独定位哪一串行阶段限制了扩展，也不说明队列锁
存在争用。线程池仍慢于此前 1T 的 272.526 s，尚不宣称解决了全部并行 ingest 成本。

完整 JSON 仍为 **40,949,081,788 bytes**，SHA-256 为
`2335818f7b338a14f9feb068cd2521f6f8b26b5768016055ce0b79c36afb1928`；与旧 2T
的 6,007 条诊断（只归一化事务临时目录）、dependencies 和 metadata keys 均一致。
`make compare_xs_firrtl_ingest` 的原始 manifest hash 检查因 `lower_threads` 字段的
JSON 排列位置不同而失败，其他内容检查全部通过；两轮保存的规范化
`manifest.json` 经 `cmp` 确认逐字节一致，不能把格式差异掩盖成原始 hash 相等。
线程池版本通过 `make test_wolvrix`（81/81）和
`make test_xs_firrtl_workflow SKIP_PY_INSTALL=1`（66/66）；定向
`test_ingest_driver` 同样通过。日志在 `ptmp/firrtl-ingest/F15/thread-pool-build/`。

2026-11-03 进一步移除 FIRRTL 私有 Design 和发布阶段的 `importGraph`。
协调线程先为最终 Design 分配所有可达 FIRRTL graph，再向线程池提交独占
`Graph&` 的 lowering 任务。`Design::parallelGraphMutation()` 在作用域入口/出口
更新 revision；worker 内的 owner 通知只读取稳定的 defer 标志，不对全局 revision
做普通递增或 atomic RMW。作用域声明在池之前，因此异常时也先 join 全部 worker，
再恢复串行 revision 更新；作用域内禁止移动 Design、修改图目录或使用 revision
缓存。worker 的 `node::requireValid(graph)` 使用无缓存的 graph 局部校验。

发布阶段仍由 `ensureFirrtl` 按依赖栈重抛失败、绑定 instance、应用 annotations。
`Design::createUnpublishedGraph()` 分配最终 owner 和 ID，但不修改 graphs 哈希表
或 graphOrder；`Design::publishGraph()` 在 `ensureFirrtl` 的原依赖位置移动同一个
`unique_ptr`，连同 SV/ABI graph 和 wrapper 删除操作保留原目录插入历史。
内部 GraphId 由预创建顺序分配，可以与串行路径不同，
完整 JSON 和诊断顺序必须一致。

新回归覆盖纯 FIRRTL、多模块同时失败、FIRRTL→SV→FIRRTL，以及 external 直接
绑定 FIRRTL 的串行与重复 2T/4T 对照；检查完整 JSON、graphOrder、dependencies
和诊断字段。core 回归覆盖两图并发写入、revision 批次失效、异常恢复、嵌套 scope
拒绝，以及未发布 graph 地址/ID 保持、非法发布拒绝和哈希表遍历顺序。
`make test_ingest_driver`、
`make test_wolvrix`（81/81）、`make test_xs_firrtl_workflow SKIP_PY_INSTALL=1`
（66/66）均通过，日志在 `ptmp/firrtl-ingest/F15/direct-build/`。
首轮直接预插目录的中间版本安装 `libwolvrix-lib.so` SHA-256 为
`f16a992ef5ae33c968f0bf37b1152181a6750eb0fbdd44cd7d97c95aa09d108d`。

使用该中间版本同一安装库、同一冻结输入和 CPU 0–31 affinity，顺序执行 1T/2T
测量，配置仅 `lower_threads` 不同：

| 路径 | ingest wall | ingest CPU | 峰值 RSS |
| --- | ---: | ---: | ---: |
| 新库串行 1T | 271.733 s | 272.066 s | 72,116,788 KiB |
| 直接写目标 graph 2T | 177.984 s | 252.698 s | 80,986,180 KiB |
| 先前私有 Design 线程池 2T | 676.248 s | 750.118 s | 88,071,172 KiB |

新 2T 相对同库 1T 耗时减少 **34.50%**（**1.527×**），峰值 RSS 增加
**12.30%**；相对先前私有 Design 线程池 2T，耗时减少 **73.68%**、RSS 减少
**8.04%**。新 2T 全 ingest CPU/wall 为 **1.420**。这些是各一次测量，JSON
保存和哈希在 ingest 计时之外；1T 本轮仅记录 timing，2T 另保存完整 JSON 身份。
原始证据在 `ptmp/firrtl-ingest/F15/direct-threads-{1,2}/`，计算结果在
`direct-build/timing-comparison.json`。去掉线程数字段后的两份 manifest 经 `cmp`
确认相等，规范化控制文件 SHA-256 都为
`de03d63a72a1635cd688dc0fc739fd1b013cd486f31c4b9074b304cdda998e01`。
该轮完整 JSON 的字节身份相等，但诊断比较失败：comb-loop-elim 的模块
警告顺序改变，全部 6,007 条诊断的 inventory 相同。原因是该 pass 遍历
`design.graphs()` 哈希表，仅恢复 graphOrder 不足以恢复哈希表遍历顺序。
因此保留原始失败 `direct-threads-2/comparison.json`；这些数据只代表中间版本，
不能作为最终发布顺序门禁通过的证据。最终实现改用上述 unpublished graph 的
所有权转移，并加入两个独立假环模块的精确诊断顺序回归。
本轮仍只验证 ingest，不代表完整 FIRRTL→C++ A/B 已完成。

最终采用延迟插入 graph 目录的版本重新通过 `test_ingest_driver`、
`test_wolvrix`（81/81）和 `test_xs_firrtl_workflow`（66/66），日志分别为
`direct-build/test-ingest-driver-publish.log`、`test-wolvrix-publish.log`、
`test-workflow-publish.log`。`parallel_diagnostics.fir` 的 `z_loop → a_loop`
依赖顺序与名字排序相反，两个独立假环修复警告在串行与重复 2T/4T 中精确相同。
重新 `make py_install` 后核对实际加载的 `libwolvrix-lib.so` SHA-256 为
`0af21d2d3727098a81432810ddebd05ca6a2a20262465331e48d2df34d1cb165`。
该版本整机证据单独保存在 `direct-publish-threads-{1,2}/`，与前述中间版本区分。

同库最终整机对照如下（各一次、CPU 0–31、同一冻结 manifest 配置，仅线程数不同）：

| 最终路径 | ingest wall | ingest CPU | 峰值 RSS |
| --- | ---: | ---: | ---: |
| 串行 1T | 273.962 s | 274.298 s | 71,148,944 KiB |
| 无整图复制 2T | 183.425 s | 263.144 s | 79,837,368 KiB |

最终 2T 相对同库 1T 耗时减少 **33.05%**（**1.494×**），RSS 增加 **12.21%**；
相对先前私有 Design 线程池 2T，耗时减少 **72.88%**、RSS 减少 **9.35%**。
2T CPU/wall 为 **1.435**。`direct-build/publish-timing-comparison.json` 保存
原始数值和计算；两轮实际加载的 native 库身份相同，6,007 条诊断按序相等
（仅归一化请求临时目录），dependencies、metadata keys 和 CPU affinity 均相等。
`make compare_xs_firrtl_ingest FIRRTL_INGEST_COMPARE_ARGS=--timing-only`
对旧线程池 2T 与最终 2T 的全部检查
通过，证据为 `direct-publish-threads-2/comparison-timing.json`；最终 1T 相对
前一版 1T 的同类比较也通过。这里的 timing-only 比较不代替完整 JSON 身份门禁。

最终 2T 的完整 JSON 仍为 **40,949,081,788 bytes**，SHA-256 为
`2335818f7b338a14f9feb068cd2521f6f8b26b5768016055ce0b79c36afb1928`。
保存和哈希另耗 **113.790 s**，未计入 ingest。随后通过 Makefile 执行完整
`compare_xs_firrtl_ingest`，`direct-publish-threads-2/comparison.json` 中
manifest、CPU affinity、按序 diagnostics、dependencies、metadata keys 和 graph
六项检查全部为 true，`equal=true`、`graph_checked=true`。全流程 FIRRTL→C++
以及更多线程数的整机测量仍未由本轮覆盖。

## 7. 当前线程池 10T：原始 FIRRTL 到 hier-flatten（2026-11-03）

用户要求对照 F14 的 `parseFIR 5.213 s + Init 71.278 s = 76.491 s`，
补测当前正确 direct-publish 版本的 10T ingest 与展平。实际加载的 native 库仍为
`0af21d2d3727098a81432810ddebd05ca6a2a20262465331e48d2df34d1cb165`，
使用同一冻结 `SimTop.fir`、F13 harness/include、annotations on 和 CPU 0–31。
本轮为一次测量，从原始输入开始，未加载图 checkpoint。

| 范围 | 墙钟 |
| --- | ---: |
| FIRRTL/mixed ingest，lower_threads=10 | **163.850 s** |
| hier-flatten，现有串行实现 | **314.402 s** |
| 上述两项相加 | **478.252 s，约 7 分 58 秒** |
| flatten 前的八个默认 GRH pass | **95.048 s** |
| 原始输入到 flatten 完成，各阶段时间相加 | **573.300 s** |
| 原始输入到 flatten 完成，连续墙钟 | **573.786 s，约 9 分 34 秒** |

连续墙钟还包括阶段间 metadata 查询、诊断和计时报告写入，约 0.486 s；
没有 JSON checkpoint 保存/哈希。完整前缀峰值 RSS 为 **117,011,540 KiB，
约 111.59 GiB**，ingest 自身峰值为 81,532,576 KiB，约 77.76 GiB。
ingest CPU 时间为 367.740 s；flatten CPU 时间为 314.358 s。

八个前置 pass 与生产 full pipeline 一致，顺序为 xmr-resolve、mux-tree-fold、
register-write-normalize、mux-tree-fold、memory-read-retime、multidriven-guard、
blackbox-guard、latch-transparent-read，保留 `keep_declared_symbols=True` 和两处
`2state` 参数。随后完成 hier-flatten，各阶段均无 error；测量终点为展平完成。

两项相加是 F14 的 76.491 s 的 **6.25 倍**；包含默认前置 pass 的连续墙钟为
**7.50 倍**。这是两条实际路径到构图/展平端点的耗时比较，两边工作内容有差异：
GrhSIM 保留 mixed ingest、node annotations 和校验等工作；GSIM 的 Init 在
`visitInst` 递归进入模块时已向同一 graph 展开实例层次，还包含 clockOptimize、
寄存器/内存整理和 supernode 构建。GSIM 的 10 线程仅用于 parseFIR，之后的
AST2Graph/Init 串行执行；本轮 GrhSIM 的 10 线程用于模块 lowering，hier-flatten
同样串行。

相对同库已有 1T 273.962 s，10T ingest 为 **1.672×**；相对 2T 183.425 s，
耗时缩短 **10.67%**。这些均是各一次记录，不外推为完整 FIRRTL→C++ 加速比。

生产 benchmark 新增 `--through-flatten`，直接复用 `GRH_PIPELINE`，逐项保存计时
和诊断。实际执行：

```sh
WOLF_ENV_SOURCED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
make --no-print-directory benchmark_f15_firrtl_ingest \
  SKIP_PY_INSTALL=1 PYTHON=.venv/bin/python \
  F15_FIRRTL_MANIFEST=ptmp/firrtl-ingest/F15/manifests/threads-10.json \
  F15_FIRRTL_BENCH_WORK=ptmp/firrtl-ingest/F15/direct-publish-threads-10-flatten \
  F15_FIRRTL_BENCH_ARGS=--through-flatten
```

证据位于 `ptmp/firrtl-ingest/F15/direct-publish-threads-10-flatten/`：
`timing.json`、`benchmark.log`、`native-identity.json` 和 `comparison-summary.json`。
与最终 2T 对照的库身份、除线程数外规范化 request、CPU affinity、按序 6,007 条
ingest diagnostics、dependencies 和 metadata keys 均相等。此次没有保存整图 JSON，
不新增 10T 整图字节身份相等的声明。
`make test_xs_firrtl_workflow SKIP_PY_INSTALL=1 PYTHON=.venv/bin/python` 通过
66/66，日志为本轮目录中的 `test-workflow.log`；`git diff --check` 通过。

## 8. ingest 到 hier-flatten 的 perf 热点分析

2026-11-03 按用户要求对当前 10T 原始输入到展平终点执行一次分阶段 perf 采样。
完整分析见 [F15-ingest-flatten-perf.md](F15-ingest-flatten-perf.md)。首要发现是
hier-flatten 的 `mi_heap_collect_ex` 与 `_mi_page_free_collect` 两个叶函数合计
占 58.90% 用户 CPU 样本；另有 ingest 字符串/符号表查找和前置 pass 的完整
Operation 快照复制成本。只增加采样/分析入口，未修改 native 性能实现。
