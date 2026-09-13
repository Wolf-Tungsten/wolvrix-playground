# NO00025：标量内存单元仅在变化时写入 shadow

- Node：`compute_demand_20260914_01`。
- 最终阶段：`ACCEPTED`。正式六次新均值 **57.548667 s**、旧均值 **58.759000 s**，
  降低 **2.059826%**，三次新均快于三次旧，U=0、单侧精确 p=0.05；完整生成
  **605.49 s**、fresh 编译 **232.94 s**，50k NEMU 与聚焦正确性门槛均通过。
- 根基线 `d7e4a81`；子模块基线 `8b5675de1a1c3e21338cf2b73cbf3fbdbf166b3c`
  （NO00024）。开始时两个工作区均干净。
- 保留实现的最终子模块 commit：`9a841ece3ff4767a132f86191cbd83be0c0a66ca`。只在全部验收
  完成后集中提交；根仓库同次归档保存该指针、报告、goal 与索引。

## IDEA 与证据计划

NO00024 独立相位 compute 41.433633 s（71.73%）、commit 14.684130 s（25.42%），
publication 1.565766 s，100102 evals / 201258 rounds。先刷新其平坦动态热点，
检查被激活任务内部的依赖与条件覆盖，寻找按需求执行子图或减少重复状态访问的
机制。具体创新点、覆盖、局部目标、收益上界和证伪标准在实现前记录。
不重复已否定的局部转发、bool 包装和通知分支/汇聚微调。

## BASELINE 与预注册

- 复用 NO00024 完整生成/fresh 编译的 `flow-constants-final` 对照，emu SHA-256
  `13a7006af3c842128770c08dc43fba624b6b48066a73faeba57c1d535bdd45f2` 已复核。
- XiangShan `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`、SimTop、DIFFTEST/NEMU。
  输入 CoreMark SHA-256 已复核为
  `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`。
- 50,000 cycles、CPU 2、`XS_EMU_THREADS=1`、`XS_NUM_CORES=1`；waveform、commit/RAM
  trace 关闭；编译使用 32 jobs。冻结 RTL、GRH、GRH pass 不变，按通用语义触发。
- 运行前固定 NO00024 正式均值 **58.417667 s** 为止损参考，仿真截止
  **87.627 s**（1.5 倍，毫秒取整）。生成和编译从 Make 启动计墙钟，各预装
  1800 s 进程组 KILL。超时否定该次尝试并隔离不完整产物。恢复 flat IR 仅供筛选，
  最终重新完整 SV→C++ 和 fresh 编译，两项各须小于 1800 s。
- 正式顺序预注册为 `old1/new1/old2/new2/old3/new3`，同窗口连续串行，期间不构建。
  Host 为主指标，保留 emu 墙钟、退出与等价性，报告均值、样本标准差、效应量与
  单侧精确 Mann–Whitney U。要求 `max(new)<min(old)`；全部有效样本保留，INVALID
  记录原因后补跑。诊断/筛选不进入正式统计。
- 精确 50k 终点为 73580 instructions、cycleCnt 49996、PC `0x80001312`、guest
  cycles 50001。非零、assertion、mismatch 或输入不一致均 INVALID，确认失败即停止。
- gsim 配置不变，复用已归档 20.640 s，不重跑。
- 命令、日志和临时产物在 `ptmp/no00025_compute_demand_20260914_01/`；必要证据
  在报告正文整理，不提交生成代码、日志、profile 或二进制。
- 本节点取得真实收益并完成全部门槛后才集中提交；任何单次失败继续在同节点修正。

## IDEA：mux 分支独占计算链按需求执行

刷新 NO00024 平坦采样：Host **59.401 s**、11884 samples（200 Hz），compute
**63.934702%**、commit **20.304611%**、evaluator **3.130259%**、main-other
**9.861999%**、external **2.583305%**；其余 unresolved/unmapped 共 0.185123%。
compute 覆盖 2329 个任务，前十合计 347 samples（2.92%），最大单个任务仅
0.370246%。50k 精确 NEMU 终点通过，采样只作诊断，不进入正式统计。

生成代码先计算 mux 的两条输入链，再选择结果。候选只将同一 helper/chunk 内、
恰有一次全局 operand 使用、结果仅在本地 frame 的纯 logic compute 移入其 mux
分支，并向上递归涵盖同样满足独占条件的依赖。例：`a=f(x); b=g(y); z=mux(c,a,b)`
变为 `if(c){a=f(x);}else{b=g(y);} z=mux(c,a,b)`。条件依赖提前完成；边界值、
共享值、状态读、内存读、DPI、history 和输出等保留执行。嵌套 mux 可继续按选择
执行其独占链；不复制生产者，不跨 helper，不增加运行期缓存或值比较。

创新点是利用 def-use 独占性构造控制依赖，消除未选分支的实际求值；只改 emitter，
IR、映射、布局、调度及 helper ABI 保留。未选本地 slot 保持既有 frame 初始化值，
只有选中分支的逻辑结果参与 mux；通知只由原 consumer 结果变化产生。
初始收益目标 **3–12% Host**，绝对理论上界受 compute 约 64% 平坦占比约束；
真正覆盖与跳过率还需静态统计和筛选测量，不将静态 op 数当作动态节省。
若分支开销/编译器原有折叠抵消收益，或正确性/时间门槛失败，则否定该次尝试并
在本节点修正。聚焦测试需覆盖嵌套选择、共享依赖、相同两臂、跨 helper、宽值、
首次 eval/reinit 与反复切换；现有多时钟、状态/内存、DPI 与 Verilator 回归保留。

## IMPLEMENTED：chunk 内独占链条件执行

emitter 先统计全模型 operand 使用次数，在各 chunk 内选取单用、local、无通知的
纯 logic 生产者，再从 mux 两臂递归标记延迟链；按需求深度优先发射，条件依赖先
完成，其他根仍保留原拓扑顺序。运行期不新增缓存、标志或逐值比较。

原 emitter suite **58.32 s** 通过；新增独立 scoreboard 后 emitter **61.34 s**，
schedule **0.01 s**、IR/mapping 各 **0.01 s** 通过。三种分区/helper 配置分别
完成 **65536 evals / 4 init**，覆盖随机 64/129 位输入、嵌套 mux、相同两臂、
共享值及重复使用、helper 边界、首次 eval/reinit、重复 eval；single-consumer DPI
虽仅出现在 mux 一臂，仍按原时钟采样并调用。新增生成测试启用 ASan/UBSan；既有
Verilator、宽值、状态/内存和多时钟回归也全部通过。

对冻结 GrhSIM checkpoint 的静态上界分析找到 **19234** 个 chunk、**481275** 个
有独占输入链的 mux、**1090120** 个链内操作，其中宽结果 **12154** 个。
主要是 452519 mux、225902 or、193665 and、48346 concat、35896 sliceStatic、
30191 add、27566 eq。该分析尚包含 442 个常量，最终 emitter 另外排除已在使用点
特化的标量常量和通知站点，实际覆盖以生成诊断为准。统计 nested cone 长度时
各根可重叠，1090120 使用 chunk 内集合去重，不能把各长度桶相加当成独立 op 数。
分析最初误用 supernode 自身 phase（其值为 None，实际 phase 由祖先给出）得到
零覆盖；核对序列化和分区结构后修正，无重复仿真或性能样本变化。

筛选恢复生成 **105.40 s**（Make 墙钟，内部 91.439 s），exit 0，1800 s 截止
未触发；恢复 flat IR 的时间不代替最终完整 SV 生成门槛。排除 412 个不可变标量
常量后实际静态覆盖 **1089708** 个操作、**481259** 个 mux。生成源码按条件标记
逐文件计数验证 481259 个条件站点，落在 **3400** 个 task；5193 个源文件中仅
这 3400 个 task 改变，evaluator、header/runtime、init 和 Makefile 逐字节相同。
C++ 总文本 1238337396→1277458312 bytes（+3.16%），changed 通知引用数量
2045025 不变；条件的额外读取使源码 accessor 引用增加，不能据此断言动态 load
增加或减少。

将同一次基线 profile PC 映射到这些改变的 task（未重跑）得到 **5790/11884
samples = 48.720969%**，涉及 1843 个 sampled changed tasks。这给出本方案
任务本体覆盖的粗上界；其中仍含 eager/shared 计算及通知，不能将 48.72% 全部
视为可删除成本，也未计入可能从 task 调用的外部 helper 变化。

## REJECTED：首版 eager mux 汇合

独立 fresh 32-job 筛选编译 **231.96 s**，exit 0，1800 s 截止未触发；ELF text
120437197→119538329 bytes（−0.75%）。筛选 old Host/emu 墙钟 **58.828/58.86 s**，
new **63.545/63.57 s**，Make/emu exit 均 0/0，均通过精确 50k NEMU 终点，未触发
87.627 s 止损。单对新版本慢 **8.018291%**，否定本实现的初始收益假设；不进入
正式六次统计，也不据此完成节点。该次未执行完整 SV 生成及正式六次交替。

首版在条件块之后仍调用原 mux 表达式，编译器可能生成额外选择/合流操作，且将
很短的标量链也移入分支。下一次先将 mux 结果写回直接放入所选分支，检查是否
能消去重复选择；仍沿用单用/local/同 chunk 的语义约束，并重新筛选。当前所有
结果保留，尚无 ACCEPTED 结论。

### 第二次尝试：所选分支直接物化结果

保留相同的条件链选择规则，将 consumer 的规范化与 changed 更新直接移入真/假
分支，每次只执行一次选中结果的物化。标量仍按 operand 原位宽、signedness 到
result 位宽转换；宽值复用既有 helper 的掩码/截断语义，两个输入均指向所选值，
不新增 helper ABI 或宽值临时对象。目标是在同一机制内消去首版的重复 mux 合流，
重新运行聚焦测试和独立筛选；仍需获得收益后才开始正式完整门槛。

第二版 emitter suite **61.09 s** 通过。补充 signed 5-bit 到 unsigned 64-bit
扩展、unsigned 64-bit 到 signed 5-bit 截断后，三配置 scoreboard 全通过；完整
emitter suite **112.20 s**（与筛选模型编译并发，非性能基线）。第二版恢复生成
**100.46 s**（内部 89.563 s），exit 0；源文件仍只改变同一批 3400 个 task。
结果写回在两臂各有一个源码站点、每次只执行一臂，C++ 文本为 1309235807 bytes；
静态 changed 引用增加到 2149481，并不表示动态通知次数增加。
第二版筛选 old/new Host **59.097/62.085 s**，新版本慢 **5.056094%**；虽然比首版
8.018291% 退化减小，仍否定该次尝试，未进入正式统计。原因是大量 <=64 位标量
分支的控制流成本可能高于省下的算术，且直接写回仍需生成两套转换代码。下一次仅允许
宽值（>64 bit）独占链，保留标量 eager 路径，以提高每个分支的计算粒度并限制代码
膨胀；不修改既有宽值 helper ABI，mux 沿用既有返回数组的 helper，未新增此类 helper。

第三版仅宽值（>64 bit）链后，筛选 old/new Host **57.923/58.686 s**，新版本慢
**1.317266%**；两次均 NEMU PASS、恢复生成 Make 墙钟 **104.78 s**（内部
90.854 s）、fresh 编译 **228.41 s**。
退化已接近窗口噪声但没有正收益，故不进入正式六次。下一版按 chunk 内延迟的宽值
操作总数至少四个筛选，减少短块分支成本（实际并非逐链长度门槛，先前口头描述
过于简化）。

### 第四次尝试与正式六次：REJECTED

第四版通过 emitter suite **61.39 s**；恢复生成 Make **99.97 s**（内部
89.319 s）、fresh 编译 **229.06 s**。筛选 old/new Host **58.587/58.421 s**，
仅降低 **0.28334%**；两次精确 50k NEMU PASS。2882 个条件站点落在 217 个
task，5193 个文件中仅这 217 个 task 改变；源码 +0.06224%。该微弱单对信号
未当作接受依据，继续完整门槛与正式六次。

完整 SV→C++ Make 墙钟 **597.07 s**（内部 591.368 s），fresh 32-job 编译
**231.14 s**，各 exit 0，预装 1800 s 截止均未触发；round-trip 通过。此时未
核验其 flat GRH 与冻结基线逐字节关系，因此不将此项声明为已通过。

| 正式 RUN_ID 后缀 | 启动（2026-09-14 +08） | Host s | emu 墙钟 s | Make/emu 退出 | 等价性 |
|---|---|---:|---:|---|---|
| demand_old1 | 01:59:16 | 58.916 | 58.95 | 0/0 | PASS |
| demand_new1 | 02:00:40 | 59.113 | 59.14 | 0/0 | PASS |
| demand_old2 | 02:02:03 | 57.941 | 57.97 | 0/0 | PASS |
| demand_new2 | 02:03:20 | 58.436 | 58.46 | 0/0 | PASS |
| demand_old3 | 02:04:33 | 58.824 | 58.85 | 0/0 | PASS |
| demand_new3 | 02:05:49 | 59.253 | 59.28 | 0/0 | PASS |

结束 02:06:48；串行但人工调度引入 15–26 s 间隔，没有同期构建，全部六次保留。
每次 73580 instructions、cycleCnt 49996、PC 0x80001312、guest cycles 50001。
old/new 均值 **58.560333/58.934000 s**、样本标准差 **0.538327/0.436924 s**；
新均值反而慢 **0.638088%**，old−new Cohen's d **−0.762189**、U_new **7**、
改善方向单侧精确 p **0.9**。`max(new)=59.253 > min(old)=57.941`，明确不能
接受。不再继续此方向的宽度/长度参数微调，四次 mux 尝试代码、文档和测试均已
撤销至基线；生成物与差异仅在 ptmp 保留。本节点继续探索，不以失败结束。

## IDEA：内存单元写入在变化前避免 staging

同次基线采样 `cpu_stage_cell` 占 **3.315382%**，是最大的独立 runtime helper；
读源码发现任何使能写入都会先复制 visible cell 到 shadow、加入 pending，再执行
mask，最后由 publication 比较。即便 mask 为零或新值等于旧值仍付出此成本。
新机制在 scalar cell 的写端口先对当前版本（dirty 时 shadow，否则 visible）
求 masked next，未变立即返回；仅首次变化才入队，直接写 next，避免初始化拷贝。
沿用已有标量 state 的 `cpu_write_scalar` 分配/覆盖策略，保留 cell dirty key、
端口顺序和 memory-reader publication 通知，不改宽值 helper ABI。

支持 memWrite 的 enable/index/data/mask/event 与 memFill/序列写的全量更新；
必须覆盖同 cell 多端口、覆写后恢复初值、零 mask、符号/位宽规范化、不同 cell
与 out-of-range，以及 delayed publication。只按 two-state logic 1–64 bit 触发。
预期 Host 降低 **2–8%**，helper 平坦占比本身给约 3.3% 的直接消除上界，额外
收益可能来自减少 pending publication；若 no-op 比例低或比较成本抵消则证伪。

## IMPLEMENTED：标量 cell 写前检查

实现覆盖 scalar memWrite/memFill/memWriteSeq，采用 `cpu_write_cell<T,Width>`，
只有 next 不等于当前版本时才创建 pending，沿用原 cell key、publication 和
按地址激活读者的路径。对照 legacy 的 scalar memory 实现同样先求 masked next
再比较，区别在于此 IR 后端必须保留 shadow 以满足多端口顺序。宽值保留旧路径，
新增 helper 只处理标量，没有新数组返回值或 wide copy，既有宽值 helper ABI 不变。

基线 checkpoint 中 memWrite **37208** 个，scalar **33134** 个；memFill **158/158**，
memWriteSeq **433/434**。合计 **33725/37800** 个内存写操作进入新路径，主要元素
位宽为 1 bit（11998 ops）、64 bit（4542）、8 bit（3426），当前 XiangShan 覆盖
均无符号，聚焦回归另验证 signed。最初分析把 array elementType 当成 width 字段
导致 KeyError，核对序列化字段位置修正；未运行仿真、不影响样本。

原 emitter suite **59.32 s** 通过。新增回归直接检查 clean/dirty no-op 无额外
pending、两个 row 独立入队、visible 延迟发布、恢复原值抵消、旧 stage_cell 与
新 helper 交互；完整 eval scoreboard 覆盖 10 组 1/5/8/13/32/64 位有/无符号
类型、多端口交叠/分离 mask、超范围地址、重复 init、所有 row 的读通知。
筛选恢复 Make **111.12 s**（内部 97.330 s），exit 0，截止未触发。

新增 scoreboard 与完整 emitter suite **124.30 s** 通过（与模型编译并发，仅功能
验证）；schedule **0.04 s**、IR **0.04 s**、mapping **0.05 s** 通过。新增测试共
**153630 evals**，ASan/UBSan 开启；已有混合 memFill/memWriteSeq、宽值与
Verilator 差分均通过。候选筛选 fresh 32-job 编译 **238.51 s**，exit 0。
5193 个文件中改变 **416 个 commit task + header**；compute/evaluator/init/runtime
源文件不变，C++ 总文本 1238337396→1229464636 bytes。accessor 及 changed 源码
引用计数不变；真正改变的是 helper 何时分配 pending 和写 shadow。

## SCREEN：标量 cell 写前检查

筛选 fresh 32-job 编译 **238.51 s** 已通过。old/new 单对 Host **58.671/57.570 s**，
emu 墙钟 **58.70/57.60 s**，均 exit 0、50k NEMU PASS；new 比 old 快 **1.876566%**。
该结果仅用于进入正式验证，不作为接受依据。当前实现通过聚焦回归、静态覆盖和
筛选，下一步完整生成、编译及六次交替均基于同一代码版本。

## VALIDATION：内存方案完整生成

`no00025_memory_full_generate` 从 SV 起步，Make 墙钟 **605.49 s**（内部
595.949 s），exit 0，1800 s 截止未触发；目标 C++ 后还包含 checkpoint round-trip，
因此是生成边界的保守上界。正式 flat GRH 与 NO00024 冻结文件用 `cmp` 确认
**逐字节相同**；XiangShan 工作区干净。正式/筛选 **5193** 个 C++/header/Makefile
文件逐字节相同。正式构建独立 fresh，不复制筛选二进制。
GrhSIM checkpoint 的字段比较全部相同，再由 `cmp` 确认整个 JSON 逐字节相同，
明确表明此次变更只涉及 emit 的执行路径，未改变 IR、映射或调度。

正式六次沿用预注册 old/new 三对，RUN_ID 为 `no00025_memory_old1/new1/old2/new2/old3/new3`，
在同一 shell 中连续执行，避免前次人工调度间隔。主指标 Host、统计口径和
87.627 s 止损全部保持不变；全部有效样本保留，失败按 INVALID 记录补跑。

正式 fresh 32-job 编译 **232.94 s**，exit 0，1800 s 截止未触发；ELF text
**120599885 bytes**（旧 120437197，+0.135081%），没有把代码缩小当作收益条件。
正式 emu SHA-256 `24f375e911695f8a1b504dcde9dc222c3a01f7552dfdca3345a1239857eabbfd`；
筛选 emu SHA-256 `3b51fa23fee8b9f70e2401d998958bee3a474c9a7b6f407950adce409cc93eca`，
二者源代码一致而是独立 fresh 构建，二进制哈希不相同，未将两者混为同一 artifact。
正式与筛选 text/data/bss 均相同；编译器 clang 22.1.2、模型 flags `-std=c++20 -O3`。
旧二进制与 CoreMark SHA-256 在正式启动前再次匹配预注册值。

## VALIDATED：内存方案正式六次交替

2026-09-14 UTC+08:00，RUN_ID 前缀 `no00025_memory_`，严格连续 old/new 三对。
全部六次有效，未补跑、未筛掉样本，期间未构建或执行其他实验。

| 后缀 | 启动 | Host s | emu 墙钟 s | Make/emu 退出 | 等价性 |
|---|---|---:|---:|---|---|
| old1 | 02:36:00 | 58.594 | 58.62 | 0/0 | PASS |
| new1 | 02:36:59 | 57.602 | 57.63 | 0/0 | PASS |
| old2 | 02:37:57 | 58.895 | 58.92 | 0/0 | PASS |
| new2 | 02:38:56 | 57.388 | 57.42 | 0/0 | PASS |
| old3 | 02:39:53 | 58.788 | 58.82 | 0/0 | PASS |
| new3 | 02:40:52 | 57.656 | 57.68 | 0/0 | PASS |

窗口结束 02:41:50。六次 DIFFTEST/NEMU 均启用，73580 instructions、cycleCnt
49996、PC `0x80001312`、guest cycles 50001，未触发 87.627 s 截止，没有
crash/assertion/mismatch。Host 为主指标，emu 墙钟只覆盖 emu 执行区间。

| Host 统计量 | old | new |
|---|---:|---:|
| 均值 s | 58.759000 | 57.548667 |
| 样本标准差 s（n−1） | 0.152581 | 0.141737 |
| 最小值 s | 58.594 | 57.388 |
| 最大值 s | 58.895 | 57.656 |

平均节省 **1.210333 s**，`(old_mean-new_mean)/old_mean` 为 **2.059826%**。
合并标准差采用 `sqrt((sd_old²+sd_new²)/2)`，old−new Cohen's d **8.219088**。
`max(new)=57.656 < min(old)=58.594`，间隔 **0.938 s**。U_new=0，枚举六选三
共 20 种标签分配，改善方向单侧精确 p=1/20=**0.05**。三对分别节省
**0.992/1.507/1.132 s**，均为正；满足预注册的全秩分离门槛。小样本结论限于
此机器、此工作负载和本次规定门槛，不外推为所有模型固定降低 2.06%。

接受的是内存写前检查这一个机制。此前第四版 mux 的六次是另一实现，已完整
归档为 REJECTED，不混入本组对照；其他筛选/插桩也不进入统计。内存方案的正式
收益落在其 2–8% 预期带下沿。没有动态 no-op 计数，不能据静态覆盖或 helper
profile 将 1.210333 s 精确分摊到少拷贝、少入队或少 publication；正确性测试
直接证明无变化写入不产生 pending，正式交替证明最终 Host 改善。

## 完整 Make 复现命令

以下为内存方案正式流程；每个 stage 只能在相应独立空目录/唯一 RUN_ID 下启动。
env 变量与参数和执行记录一致，源码实验版本为节点开始基线加本报告描述的最终
CPU emitter 差异；保留实现的 commit 记录在报告开头。

```bash
set -euo pipefail
root=$PWD
node=$root/ptmp/no00025_compute_demand_20260914_01
old=$root/ptmp/no00024_sparse_execution_20260913_01/flow-constants-final
flow=$node/flow-memory-final
mkdir -p "$node/tmp" "$node/logs"
export PATH="$root/.venv/bin:/home/gaoruihao/wksp:$PATH"
export WOLF_ENV_SOURCED=1 JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export TMPDIR="$node/tmp" PIP_CACHE_DIR="$node/pip-cache"
export CCACHE_DIR="$root/ptmp/cpu_emit_ccache" CMAKE_BUILD_PARALLEL_LEVEL=32
export LC_ALL=C EMU_RUNTIME_PROFILE=0
common=(PYTHON="$root/.venv/bin/python" XS_NUM_CORES=1 XS_EMU_THREADS=1
  VM_BUILD_JOBS=32 XS_VM_BUILD_JOBS=32 XS_SIM_MAX_CYCLE=50000 XS_EMU_CPU=2
  XS_WAVEFORM=0 XS_WAVEFORM_FULL=0 XS_COMMIT_TRACE=0 XS_RAM_TRACE=0
  XS_PROGRESS_EVERY_CYCLES=0 WOLVRIX_GRHSIM_WAVEFORM=0 WOLVRIX_GRHSIM_PERF=0
  XS_LOG_DIR="$node/logs" XS_GRHSIM_IR_BUILD="$flow"
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR="$flow/model" XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0)
timeout --signal=KILL 1800s make --no-print-directory \
  test_grhsim_cpu_emit test_grhsim_cpu_schedule test_grhsim_cpu_mapping \
  PYTHON="$root/.venv/bin/python" > "$node/test-memory-focused.log" 2>&1
/usr/bin/time -f 'wall_s=%e,user_s=%U,sys_s=%S,exit=%x' -o "$node/no00025_memory_full_generate.make.time" \
  timeout --signal=KILL 1800s make --no-print-directory xs_wolf_grhsim_ir "${common[@]}" \
  XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0 RUN_ID=no00025_memory_full_generate \
  > "$node/no00025_memory_full_generate.log" 2>&1
/usr/bin/time -f 'wall_s=%e,user_s=%U,sys_s=%S,exit=%x' -o "$node/no00025_memory_full_build.make.time" \
  timeout --signal=KILL 1800s make --no-print-directory xs_wolf_grhsim_ir_build_emu "${common[@]}" \
  RUN_ID=no00025_memory_full_build > "$node/no00025_memory_full_build.log" 2>&1
for pair in 1 2 3; do
  for version in old new; do
    run_id="no00025_memory_${version}${pair}"
    run_flow="$flow"
    if [[ "$version" == old ]]; then run_flow="$old"; fi
    make --no-print-directory run_xs_wolf_grhsim_ir_emu "${common[@]}" \
      XS_GRHSIM_IR_BUILD="$run_flow" RUN_ID="$run_id" \
      "XS_EMU_PREFIX=timeout --signal=KILL 87.627s /usr/bin/time -f wall_s=%e,user_s=%U,sys_s=%S,exit=%x -o $node/$run_id.emu.time taskset -c 2 stdbuf -oL -eL" \
      > "$node/$run_id.log" 2>&1
    rg -q 'Difftest enabled' "$node/$run_id.log"
    rg -q 'instrCnt = 73,?580, cycleCnt = 49,?996' "$node/$run_id.log"
    rg -q 'LIMIT at pc = 0x80001312' "$node/$run_id.log"
    rg -q 'Guest cycle spent: 50,?001' "$node/$run_id.log"
    if rg -qi 'mismatch|Assertion.*failed|ABORT|BAD TRAP' "$node/$run_id.log"; then exit 1; fi
  done
done
```

筛选改用 `flow-memory-screen`，生成时设置
`XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=1`、
`XS_WOLF_GRHSIM_IR_FLAT_GRH_JSON="$old/xiangshan_flat_grh.json"`；RUN_ID 前缀
`no00025_memory_screen_`，步骤为 generate/build/old/new。前述四个被否定的 mux
实验分别使用 `flow-demand-screen`、`flow-demand2-screen`、`flow-demand3-wide`、
`flow-demand4-wide4` 及 `no00025_demand[2/3/4]_screen_` 对应前缀，第四次完整
路线使用 `flow-demand-final`、`no00025_demand_full_generate/build`，正式后缀
为 `no00025_demand_old1/new1/old2/new2/old3/new3`。这些是不同源码尝试，当前
保留源码无法复现为相同的被否定版本；其语义差异、数据与决策已在本文说明。

基线 profile 用 old flow，同一 emu prefix 在 `stdbuf` 后附加
`env LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libprofiler.so.0 CPUPROFILE=$node/no00025_baseline_profile.prof CPUPROFILE_FREQUENCY=200`。
解码使用 `make --no-print-directory analyze_grhsim_cpu_profile`
`PYTHON="$root/.venv/bin/python" GRHSIM_CPU_PROFILE="$node/no00025_baseline_profile.prof"`
`GRHSIM_CPU_PROFILE_BINARY="$old/emu/emu" GRHSIM_CPU_PROFILE_MODEL="$old/model/grhsim_SimTop.cpp"`
`GRHSIM_CPU_PROFILE_SAMPLES=11884`。首次漏设 `WOLF_ENV_SOURCED=1` 的分析 Make
被前置环境检查拒绝，补全后成功，没有额外仿真。所有临时路径仅用于复现参数，
证据与分析已整理入本文，正式引用不依赖临时产物。

## 最终独立相位与节点判定

正式六次结束后的 `no00025_memory_final_phase` 于 02:42:16–02:43:14 运行，
仅 `EMU_RUNTIME_PROFILE=1`，Host **57.794 s**、emu 墙钟 **57.82 s**，Make/emu
exit 0/0，精确 50k NEMU 终点 PASS，未触发 87.627 s 截止。复现使用上面的 run
命令，只改 RUN_ID 并设置该 profile 环境变量；此诊断不进入正式六次统计。

| 相位 | s | eval 总时间占比 |
|---|---:|---:|
| compute | 42.329203 | 73.457748% |
| commit | 14.443843 | 25.065725% |
| publication | 0.774273 | 1.343668% |
| eval 总计 | 57.623878 | 100% |

仍为 **100102 evals / 201258 rounds**，求值轮次结构未变。NO00024 历史相位与
该次来自不同窗口，不直接相减证明分相位收益；当前 publication 已较小，而
compute 仍占主要成本。没有测量动态 no-op 比例，下一步若沿内存路径推进须先
刷新覆盖，不能只按静态 33725 个写操作继续推定收益。

保留实现为 [CPU emitter](../wolvrix/lib/grhsim/backend/cpu_emit.cpp)，验证入口为
[emitter suite](../wolvrix/tests/grhsim/test_cpu_emit.cpp) 和
[memory scoreboard](../wolvrix/tests/grhsim/data/cpu_memory_stage_main.cpp)，通过
[fixture Makefile](../wolvrix/tests/grhsim/data/cpu_memory_stage.mk) 构建运行；语义约束
已更新[CPU 后端文档](../wolvrix/docs/grhsim_ir/backends/cpu.md)。冻结 XiangShan、
GRH 及 GRH pass 未改，按类型和写入语义触发，没有模块名特化或多线程仿真。

节点 **ACCEPTED**：完整生成/编译、聚焦语义、50k 对拍、同期正式六次统计均有
直接证据。四个 mux 实现被否定并撤销，全部失败过程及六次数据保留；没有 INVALID
仿真或截止触发。旧失败尝试第二版编译 **238.83 s**、第三版测试 **61.47 s**
等细节见下表，避免把未归档的日志路径当作证据。

| 筛选尝试 | 生成 Make s | 编译 Make s | old/new Host s | old/new emu 墙钟 s | Make/emu 退出与等价性 |
|---|---:|---:|---|---|---|
| mux 两臂后合流 | 105.40 | 231.96 | 58.828 / 63.545 | 58.86 / 63.57 | 两次 0/0、PASS |
| mux 分支直接写回 | 100.46 | 238.83 | 59.097 / 62.085 | 59.13 / 62.11 | 两次 0/0、PASS |
| 仅宽值独占链 | 104.78 | 228.41 | 57.923 / 58.686 | 57.95 / 58.71 | 两次 0/0、PASS |
| chunk 至少 4 个宽值 op | 99.97 | 229.06 | 58.587 / 58.421 | 58.62 / 58.45 | 两次 0/0、PASS |
| 标量 memory 写前检查 | 111.12 | 238.51 | 58.671 / 57.570 | 58.70 / 57.60 | 两次 0/0、PASS |

所有生成/编译 Make exit 0 且预装 1800 s 截止。前 3 个 mux 尝试止于筛选，
第四个进入完整门槛及正式六次后否定；最终只保留 memory 实现。

当前最佳正式均值 **57.548667 s**，距约 40 s 尚差 **17.548667 s**（约需再降
**30.49%**）；长期性能目标未完成。距 NO00023 定期复盘两节点，本次更新最佳与
已排除方向，下一节点收尾须做三节点复盘。本节点的 mux 全量/直接写回/宽值/短块
门槛均未取得收益，不再循环这些阈值。后续优先考虑基于变化依赖的跨任务计算消除
或内存端口执行机制；先采集对应动态证据，不将跨窗口均值相减或相乘为累计收益。
本节点归档后停止，不启动 NO00026；见[报告索引](grhsim-ir-xiangshan-coremark-50k.index.md)。
