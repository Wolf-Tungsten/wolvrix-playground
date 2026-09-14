# NO00026：减少重复计算与提交工作

- Node：`dependency_execution_20260914_01`。
- 当前阶段：`ACCEPTED`，内存武装和直接提交、布尔子图、宽常量等尝试均已否定并撤销；普通状态副本共享经完整路线与六次交替复测接受。
- 根基线 `55ab2d1`，子模块基线 `9a841ece3ff4767a132f86191cbd83be0c0a66ca`
  （NO00025）；开始时两个工作区均干净。本节点完成后才集中提交。

## IDEA 与证据计划

当前独立相位 compute 42.329203 s（73.46%），commit 14.443843 s（25.07%），
publication 0.774273 s。优先研究计算的依赖和重复求值：现有 activity 只在
supernode 粒度跳过工作，一个输入变化可重算其余稳定子图。先刷新 NO00025
平坦热点，检查静态依赖与可消除成本，再在实现前记录具体机制、覆盖、预期
收益和证伪标准。此前已否定的 mux 条件链、局部结果转发、bool 包装和通知阈值
不作为本次微调方向。诊断与筛选不混入正式统计。

## BASELINE 与预注册

- 复用 NO00025 完整生成/fresh 编译的 `flow-memory-final`，emu SHA-256 已复核
  为 `24f375e911695f8a1b504dcde9dc222c3a01f7552dfdca3345a1239857eabbfd`。
- XiangShan `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`，top SimTop，DIFFTEST/NEMU；
  CoreMark SHA-256 `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`。
- 50000 cycles，CPU 2，`XS_EMU_THREADS=1`、`XS_NUM_CORES=1`，waveform、commit/RAM
  trace 关闭。生成/编译按主机 32 CPU 使用 32 jobs；仿真期间不构建。
- 固定 NO00025 正式均值 **57.548667 s** 为止损参考，仿真截止 **86.323 s**
  （1.5 倍，毫秒取整）。生成与编译均从 Make 启动计时，预装 1800 s 进程组 KILL；
  超时记 TIMEOUT_KILLED 并隔离不完整产物，仿真超时记 REGRESSION_KILLED。
- 正式预注册 `old1/new1/old2/new2/old3/new3`，同一 shell 连续串行执行。
  Host 为主指标，另记 emu 墙钟、退出与等价性；两组各三次有效样本，全部保留。
  报告均值、样本标准差、效应量及单侧精确 Mann–Whitney U，要求 `max(new)<min(old)`。
  INVALID 作废并记录、补跑；不能把筛选或跨窗口历史值作为收益证据。
- 精确终点：73580 instructions、cycleCnt 49996、PC `0x80001312`、guest cycles 50001。
  非零、crash、assertion、mismatch 或输入不一致均 INVALID，确认失败即终止。
- 筛选可恢复 flat GRH；最终必须完整 SV→C++、独立 fresh 编译，各 <1800 s。
  冻结 RTL、GRH 和 GRH pass 不改，不按模块名触发；gsim 配置不变，复用 20.640 s。
- 临时产物与命令记录在 `ptmp/no00026_dependency_execution_20260914_01/`，
  必要证据整理入本文，不提交生成代码、日志、profile、波形和二进制。
- 本节点仅在 ACCEPTED 后结束；失败尝试继续同节点修正。NO00026 收尾需更新
  NO00024–26 三节点定期复盘、goal 与索引。

## IDEA：拆分互不相关的激活依赖组

刷新当前 NO00025：Host **58.249 s**、emu 墙钟 **58.28 s**，exit 0/0、精确
50k NEMU 终点 PASS。200 Hz 平坦采样 11654 samples：compute tasks **67.813626%**、
commit tasks **20.053201%**、evaluator **2.668612%**、main-other **8.555003%**、
external **0.729363%**，其余 unresolved/unmapped 0.180195%。compute 分散在
2361 个任务，前十仅 380 samples（3.26%），不支持单任务专用优化。

现有 merge 的最后 DP segmentation 会把互不相连的节点装进同一 supernode，
节省 activity bit 和外部输入边，却令一个输入变化时重算无关子图。机制是在
现有 supernode 内按节点建立无向依赖分量：直接生产者/消费者必须同组，共享
同一非恒定外部 ValueId 的消费者也同组，其余分开激活。含 DPI、system 或其他
副作用的 supernode 保持原分组和顺序。组内节点保留拓扑顺序，跨组没有数据边，
已有 mapping/layout/schedule 自动生成各组的 boundary、activity 与发布关系。

例如 `u=f(a); v=g(b)` 原来共享一个 activity bit，a 变化会重算 f 和 g；现在
分别通知 f、g。`u=f(a); v=g(a)` 则同组，避免对同一触发源重复调度。外部常量
不构成运行期共同触发；内部常量的数据边保留，以保持首次初始化拓扑关系。
不缓存值、不新增 helper、不克隆源码、不改冻结 GRH 或 RTL，不按模块名触发。

静态对照只有 1606 个交换操作数重复和 1 个重复 memRead，重复源读取不是当前
主要机会。忽略常量的纯操作连通性粗上界覆盖 25744 units / 2806525 ops，
但不能把这些当作最终独立组或动态节省；正式机制还保留共享输入与副作用组。
初始局部目标 **5–20% Host**，绝对上界受 compute 约 68% 平坦占比约束。
新增 activity、任务和通知开销可能抵消节省；筛选无改善、正确性或时间失败均
证伪本次尝试，在同节点改进机制。最终必须六次交替全秩分离才接受。

## IMPLEMENTED：第一版独立依赖分组

最终静态规则预计拆分 **8869** 个 supernode，覆盖 **957006** 个操作，新增
**149232** 个活动单元，涉及 2465 个原 compute task。新增单元中包含细小读源，
这是主要反证风险：通知/活动位可能比跳过计算更贵，必须由筛选实测决定。
实现位于 `cpu.st.merge-compute-supernodes` 最终 segmentation 之后，先在原
cluster 内 union 直接依赖及相同外部动态值的消费者，再按首次节点位置稳定输出
各分量；整组含副作用时保留。语义 op/value/state、初始化和 helper ABI 均不变。
已有独立输入映射测试改为要求分别激活，mapping 与 schedule suite 已通过；
完整 emitter suite **60.46 s** 通过，IR/mapping/schedule 各 **0.01 s** 通过。

## REJECTED：独立分量的活动成本超过收益

| 筛选版本 | 恢复生成 Make s | fresh 编译 Make s | old/new Host s | old/new emu 墙钟 s | 相对 old 变慢 |
|---|---:|---:|---|---|---:|
| 全部分量 | 102.48 | 236.01 | 57.262 / 62.904 | 57.29 / 62.93 | 9.852957% |
| 所有分量至少 16 ops | 98.34 | 236.37 | 56.278 / 57.081 | 56.31 / 57.11 | 1.426845% |
| 所有分量至少 64 ops | 98.17 | 230.32 | 56.427 / 58.294 | 56.46 / 58.32 | 3.308700% |

全部生成/编译与六次筛选仿真 exit 0，50k NEMU 精确终点均 PASS；截止均未触发。
这三版均未执行完整 SV 路线或正式六次统计。第二版仅在原 cluster 的所有独立组
均至少 16 ops 时拆分；第三版门槛为 64 ops，意在摊薄小组活动成本。
第一版 compute 单元 **36189→185421**，活动字 **4524→23178**，tasks
**5036→5316**；第二版单元 38804、活动字 4851、tasks 5170；第三版单元
36239、活动字 4530、tasks 5042，仅新增 50 个单元。后两版未另外执行
小模型测试；第一版已有完整测试，后两版有 XiangShan 的完整 50k 筛选检查。

通知元数据、代码组织及调度开销抵消潜在跳过收益，单对筛选没有支持正向假设。
不把静态可拆分数量解释为动态跳过量，也不继续循环分量阈值。三版及仅服务
该尝试的测试改动全部撤销，原 mapping 恢复。分析中一次将 serialized kind 3/4
反向解释得到空的大小统计，经 enum 和序列化交叉检查纠正；未用于方案收益判断。

## IDEA/IMPLEMENTED：活动字只分派置位 lane

恢复原分区后，将 compute word 的八个顺序 `if(bit)` 改为非零时
`countr_zero` + switch 分派，只访问活动 lane。每次先消费最低位，运行体内
新增的同字较后 lane 继续执行；已有 emitter 只将较后 lane 写入局部字，当前或
较前 lane 写回持久 flags，仍留到下一轮。最后不足八个单元的 word 使用 default
消费无对应单元的初始化位。DPI/history/局部 frame 和 helper 调用体保留。
IR、mapping、layout 和 schedule 均恢复对照版本；没有新增 helper ABI。

这是运行期稀疏分派实验，目标是减少空 lane 检查；先前口头提及的约 50% 只属于
NO00020 特定 quiescent units 的历史诊断，**不能作为当前空 lane 比例**。当前
没有空 lane 的动态计数，整体 compute 67.81% 也只是粗上界。预期局部 Host
改善 **1–5%**；循环和间接跳转可能比固定八分支更贵，筛选无收益即否定。
聚焦 emitter **60.05 s**、mapping、schedule/IR 各 **0.01 s** 通过。

## REJECTED：set-bit 分派

恢复生成 **101.33 s**，fresh 编译 **249.55 s**，exit 0。同期 old/new Host
**56.349 / 62.540 s**，emu 墙钟 **56.38 / 62.57 s**，新版慢 **10.986885%**，
Make/emu exit 均 0/0，两次精确 50k NEMU 终点 PASS，
未触发截止。全部 4524 compute task 和 header 改变，其余源文件不变；C++ 总文本
1229464636→1229184240 bytes，各 arena 和 changed 源码引用数量相同。
循环/间接分派未改善实际执行成本，否定并全部撤销；未执行完整 SV 路线或正式六次。
checkpoint 除自动生成的事件名称字符串外，operations、states、values、init、
mapping、types、inputs/outputs 等所有字段均相同。字符串变化不作为语义变化证据。

## IDEA：单 bit 复制按字广播

基线共有 9169 个 replicate，9125 个源位宽为 1，其中 392 个结果 >64 位。
宽 bit 复制结果宽度分布：65×69、66×256、76×18、96×3、107×1、113×2、
116×1、117×2、123×1、128×22、163×8、256×1、257×8；消费者引用为
472 and、20 concat、21 xor、7 or、2048 sliceStatic。
同一已完成的基线 profile 中通用 replicate<2,1>/<5,1> helper 共 121/11654 samples
（**1.038270%**）；包含其他源位宽实例、未包含内联成本，不能视为精确可删除比例。

已核对 legacy `replicateWordsExpr` 与 `grhsim_replicate_bit_words_impl`：其专用
bit 路线使用 `0-(bit&1)` 生成全零/全一机器字，再限制最后一字。当前 IR emitter
宽值仍调用逐 bit 插入的通用循环，标量构造重复的 concat 表达式。新机制在 emit
按源位宽识别 bit 广播：标量用 fill & mask，宽值直接写 caller 的现有 local/boundary
slot，每个机器字比较/写回，变化合并到原通知组；不创建返回数组或宽临时副本。
复制数小于结果位宽时高位补零，大于结果位宽时截断；signed bit 仍只读最低位。
例如 `replicate(bit=1, rep=65, width=129)` 产生三个字 `[UINT64_MAX,1,0]`。

创新点是以 uniform bit 语义把 O(rep) bit 插入降为 O(ceil(width/64)) 写入，并
融合旧值比较与物化。scalar/wide 使用同一语义，不改 IR、分区、schedule 或冻结
GRH/RTL。预期 Host **1–4%**，整体上界未知，不能从静态 op 数推导动态收益。
正确性、时间或筛选收益不支持时否定，不继续在相同阈值上循环。

## IMPLEMENTED：bit 广播

scalar 发射 `0-(uint64_t(source)&1)` 与复制/结果位宽掩码；wide 发射同一 fill
到既有 slot，每个输出字恰写一次，并逐字 OR 原值变化。输入先捕获为 uint64_t，
避免 bool/signed 1-bit 的整型提升改变最低位含义。没有改变通用多 bit 复制路径。
原 emitter suite **60.59 s**、IR/mapping/schedule 各 **0.01 s** 通过。

新增逐 bit 独立 scoreboard：unsigned/signed 1-bit 输入，结果 1–4097 位，复制数
小于/等于/大于结果位宽、wide rep=0、尾字和 scalar signed 填充；三配置覆盖
无 helper、同 unit 多 helper、各 op 分离的 boundary 通知。每配置 3072 evals /
4 次 init，覆盖所有 256 个 int8 输入模式及稳定输入重复 eval。ASan/UBSan 启用。
第一轮含 16 种宽度/复制数的 emitter suite **63.77 s** 通过，IR/mapping/schedule
仍各 **0.01 s**；随后补充第 17 种 signed 5-bit 截断，使末端 parity 不恒定，
增强动态通知检查，最终 emitter suite **63.70 s** 通过，三配置均输出
`broadcast PASS evals=3072 resets=4 signed_patterns=256`。总计 9216 evals / 12 init。
同次既有回归包括：scalar CPU/Verilator 4196 samples，wide 3072 samples，
wide state 2048 samples，CDC 10756 samples（1182 simultaneous、20 async resets），
dual RAM 9731 samples（293 simultaneous、424 changed writes、15 async resets），
均 PASS。它们验证多 bit 通用复制及状态/内存/多时钟等既有路径未被破坏。

广播恢复生成 **109.39 s**（内部 95.266 s），exit 0，1800 s 截止未触发。
5193 个源文件中仅 **542** 个 task 改变，evaluator、header/runtime、初始化和
Makefile 全部逐字节相同。C++ 总文本 1229464636→1221522680 bytes，减少
7941956 bytes（0.645969%）；local/boundary/object accessor 源码引用分别
6144786→6068980、5365802→5295744、1472896→1472359，changed 引用仍
2045025。源码重复读取减少不等于运行期同量节省。

checkpoint 字段比较：所有 operations/values/states/types/init、接口及 mapping
全部一致，仅 757275 个字符串中的 **438263** 个自动事件标签不同，两边均严格
匹配 `__event_[0-9]+_[0-9]+`。这些私有名字没有进入 CPU 生成代码（除上述 542
个改动 task，其余代码精确相同），不能将此称为整个 JSON 逐字节相同。
tasks 5036、compute units 36189、activity words 4524、object/boundary/runtime
空间 **25934336 / 2282776 / 5487 bytes** 均保持对照值。

广播筛选 fresh 编译 **235.38 s**，exit 0；ELF text **120599885→120210461
bytes**，data 9344、bss 18416 不变。筛选 emu SHA-256
`d43863457f0d0d6ec74cc1c895f3bcc24907771fd7f40a3612c15198dc6cb85f`。
连续 old/new 的 Host **57.367 / 56.392 s**、emu 墙钟 **57.40 / 56.42 s**，
Make/emu exit 均 0/0，精确 50k NEMU 终点 PASS，未触发 86.323 s 截止。
单对降低 **1.699583%** 支持继续验证，不作为正式收益证据。

随后进入 `flow-broadcast-final` 的完整 SV 路线，预装 1800 s 截止，从 Make
启动计时，禁用 resume；完成后独立 fresh 编译并执行最初预注册的六次交替。

## 完整路线验证

`no00026_broadcast_full_generate` 完整 SV→C++ **612.57 s**（Make 墙钟，内部
606.698 s），exit 0，1800 s 截止未触发。日志明确执行 ingest 与完整既有 GRH
pass 序列。最终 flat GRH 与 NO00025 flat GRH **逐字节相同**，最终整个
GrhSIM checkpoint 也与 NO00025 **逐字节相同**，且 fresh-session round-trip
精确相同。这比筛选恢复路线的“除自动标签外相同”证据更强；冻结 GRH 及其
pass、语义 IR、分区、布局和调度均未被本方案改变。

正式编译在独立目录 fresh 开始，预装 1800 s 截止、32 jobs；未复用筛选对象文件
或二进制。正式启动前复核 old emu、CoreMark、NEMU 的 SHA-256，均与预注册值匹配。
完整路线与筛选路线的 **5193** 个 C++/header/Makefile 文件全部逐字节相同。
正式 fresh 编译 **232.60 s**，exit 0，未触发截止；ELF text/data/bss 与筛选版
精确相同（120210461 / 9344 / 18416 bytes）。正式 emu SHA-256
`93833636ef17cd2a2a9fedf1d467bd4716a14e67cc2041c964cdb2b133dae156`，与筛选
二进制哈希不同，未将两者当作同一 artifact。

## 首轮六次：正确性通过，统计未接受

2026-09-14 09:05:31–09:11:12（UTC+8）按预注册顺序连续执行：

| 顺序 / RUN_ID 后缀 | Host s | emu 墙钟 s | Make/emu exit | 50k NEMU |
|---|---:|---:|---|---|
| old1 | 56.391 | 56.42 | 0/0 | PASS |
| new1 | 56.057 | 56.08 | 0/0 | PASS |
| old2 | 57.273 | 57.30 | 0/0 | PASS |
| new2 | 56.966 | 56.99 | 0/0 | PASS |
| old3 | 57.386 | 57.41 | 0/0 | PASS |
| new3 | 56.850 | 56.88 | 0/0 | PASS |

RUN_ID 均以前缀 `no00026_broadcast_` 开始。六次输入、配置及精确终点均符合
预注册，未触发截止，没有作废样本。old/new 均值 **57.016667 / 56.624333 s**，
样本标准差 **0.544781 / 0.494737 s**，均值降低 **0.688103%**，old−new
Cohen's d **0.753964**。`max(new)=56.966 > min(old)=56.391`，U=2、单侧
精确 p=0.20，不能接受。虽然三对 new 均更快，前一对也比后两对整体更快，
不能删除第一对或以配对方向替代文档的秩次门槛。

追加验证在启动前固定：保留实现与两个完整构建，连续执行
`old4/new4/old5/new5/old6/new6`，仍以该新窗口的三新/三旧 Host 全秩分离为
接受必要条件，报告所有十二次而不挑选任意六次。止损线仍为 **86.323 s**，
CPU/输入/单线程/trace/计时和有效性规则不变，期间不构建、不采样。追加是
文档允许的噪声澄清；本版只追加这一组六次，若仍未分离则改进机制，不反复
重跑直到偶然显著。两窗口分开报告，不混合跨窗口均值作收益证据。

## REJECTED：仅 bit 广播的追加六次仍未排除噪声

2026-09-14 09:16:42–09:22:23（UTC+8）执行预注册的唯一追加组：

| 顺序 / RUN_ID 后缀 | Host s | emu 墙钟 s | Make/emu exit | 50k NEMU |
|---|---:|---:|---|---|
| old4 | 56.828 | 56.86 | 0/0 | PASS |
| new4 | 55.938 | 55.97 | 0/0 | PASS |
| old5 | 57.358 | 57.39 | 0/0 | PASS |
| new5 | 57.238 | 57.27 | 0/0 | PASS |
| old6 | 56.457 | 56.48 | 0/0 | PASS |
| new6 | 57.053 | 57.08 | 0/0 | PASS |

RUN_ID 前缀仍为 `no00026_broadcast_`。六次精确终点 PASS，无无效样本或截止。
old/new 均值 **56.881000 / 56.743000 s**、样本标准差 **0.452832 / 0.703260 s**，
降低 **0.242612%**，old−new Cohen's d **0.233324**；U=4、单侧精确 p=0.50，
`max(new)=57.238 > min(old)=56.457`。两组十二次全部保留，各窗口均无法证明
真实提升，单独广播假设被否定，不再追加相同版本复测。完成的生成/编译及正确性
验证仍是该版证据，不能作为后续扩展实现的完整路线验收。

## IDEA：按输出字一次组装 concat，并融合变化检测

当前基线有 **9633** 个宽 concat，其中 **5539** 个只有标量输入；合计
**96222** 个源存储字、**30075** 个输出字，结果范围 65–79263 bit。
现有 legacy insert 本身已经按字移动，不能误称其逐 bit 算法；主要待消除的是
按输入片段多次 clear/OR 同一输出字，以及 tracked concat 的临时宽数组、整值
比较和复制。上面的 bit 广播只覆盖 392 个宽 op，独立样本占比约 1%，覆盖有限。

新机制在 emitter 根据 concat 每个 operand 的位宽及位置，预先将各源片段映射到
目的机器字；每个输出字形成一个 unsigned shift/mask/OR 表达式，只比较并写入
已有 local/boundary 槽一次，将差异合并到原通知组。例如 `{a:5,b:64}` 的低字
为 b，高字为 `uint64_t(a)&31`；`{a:5,b:65}` 的低字为 b[0]，高字为
`(b[1]&1)|((uint64_t(a)&31)<<1)`。超过结果位宽的高位截断，超出源总位宽的
结果高位补零，signed 操作数仅按原位模式拼接，padding 不参与。操作数与结果
拥有独立槽，保留已有无别名约束；不引入宽临时副本、helper ABI 或动态元数据。

这是将 bit 广播的输出字物化策略推广到普通 concat 的机制修正，暂保留广播作为
同方向组成部分；整个候选仍须对 NO00025 基线证明收益，不能将单独广播记为成功。
不改 IR、分区、调度、冻结 GRH 或 RTL，不按模块名触发。局部目标 **2–6% Host**，
动态覆盖上界未知，不能从静态字数直接推导节省。编译器可能已消除部分中间写入，
展开表达式也可能增加代码量，故筛选无收益或正确性/时间失败即否定。先以独立
逐 bit scoreboard 覆盖跨字、padding、signed、截断/补零和三种通知配置，再恢复
生成/fresh 编译/old-new 筛选；支持后重做完整 SV 路线与预注册六次。
所有截止和固定资源沿用本节点预注册值，实验 RUN_ID 使用 `no00026_word_assembly_*`。

静态分析首次误用 serialized type 的下标（读取到了字符串），脚本立即 TypeError
退出、无有效统计；与现有 mask 分析和类型格式核对后改用 width 字段重新运行。
以上数字均来自修正后的成功分析。

## IMPLEMENTED：输出字组装

保留 bit 广播，并将宽 concat 的输入片段在发射时按源字、目的字边界切开。
每段最大 64 bit，所有 shift 严格小于 64；输出表达式只读输入既有槽，目的字
仅写一次，并融合原值比较。没有返回宽数组或新的运行期 helper。当前改动只在
CPU emitter 及其单元测试/文档，未改变冻结源码和 IR/映射机制。

新增独立逐 bit scoreboard，12 种拼接覆盖 65–4097 bit、有符号 5/129 bit 输入、
源字 padding、重复源、对齐/非对齐拼接、截断和补零。三种配置分别为同单元无
helper、多 helper、逐 op 分区；每配置 3072 eval / 4 init，包含稳定输入重复
eval，每种实测消费者变化 **517** 次，防止仅检查恒定 parity。

测试准备的首轮因同一 `auto` 声明混合 InputId/ValueId 编译失败，拆分声明修正。
第二轮因测试构造了既有 emitter 不支持的单 operand concat，在 emission 阶段
失败；改成两个 operand 的等价截断/边界测试，不扩大 opcode 支持范围。第三轮
新旧全部广播/拼接 scoreboard 已通过，但命令覆盖 PATH 导致既有 external-call
测试找不到 rg 而 exit 127；恢复原 PATH 后重新运行完整聚焦目标。这些失败没有
进入 XiangShan 仿真或性能统计。

最终完整聚焦目标均通过：CPU emitter **67.33 s**，IR/mapping/schedule 各
**0.01 s**。此时开始 `flow-word-assembly-screen` 的恢复生成与独立 fresh
32-job 编译，之后按 old/new 连续筛选；编译及仿真均保留原预装截止。

## REJECTED：输出字组装回退

`no00026_word_assembly_screen_generate` 恢复生成 **106.19 s**（内部 **92.037 s**），
fresh 32-job 编译 **230.35 s**，Make exit 均 0，1800 s 截止未触发。
连续 old/new Host **56.915 / 58.924 s**，emu 墙钟 **56.94 / 58.95 s**，
Make/emu exit 均 0/0，50k NEMU 精确终点全部 PASS，未触发 **86.323 s** 截止。
新版慢 **3.529825%**，没有支持假设。源片段 clear/OR 和宽数组的静态减少没有
换来运行收益；编译器优化后的代码形状、比较与搬运开销仍须用测量判断，不能
据此将回退直接归因于单一原因。未执行本版完整 SV 路线或正式六次。

按约定撤销全部输出字组装与 bit 广播实现，以及只服务于这些尝试的测试和后端
文档；子模块工作区已恢复 NO00025 基线。失败版本差异与临时测试保存在 ptmp，
不提交生成产物或失败实现，过程数据完整留在本报告。节点未完成，继续寻找
能消除实际计算的语义机制。

## IDEA：有限输入布尔子图语义共享

恢复 NO00025 后转向消除计算本身。静态 width=1 的主要操作有 and **705065**、
or **390324**、logicAnd **245253**、logicOr **144198**、not **90635**、logicNot
**80283**、mux **202449**、xor **24620**，eq/ne **705/1056**；合计 **1884588**。
这是位宽候选数，尚未扣除 signed/非两态，不表示重复数。当前 CSE 只接受相同
opcode、有序 operands 和参数，无法共享跨 opcode 或不同布尔结构的同一函数。

机制：对无符号两态 1-bit 的无副作用、无参数 and/or/xor/xnor/not、逻辑与或非、
eq/ne 和 mux，在拓扑处理时合并输入支持集。最多六个变量的子图可用一个 uint64
真值表精确表示；超过六个变量时以直接输入为新边界，不指数扩展。删掉真值表中
无关的输入后，以有序 ValueId 支持集与表作为共享 key；恒等表直接引用输入，
等价表共享先前代表 op，其他 op 保留，再由已有 mapping 重建依赖和调度。
例如 `not(not(a))` 引用 a，`not(and(a,b))` 与 `or(not(a),not(b))` 共用一值。
原代表的逻辑和结果类型不改，不创建运行期 LUT、缓存、helper 或模块名特判。

创新点是由精确结构 CSE 扩展为有界子图函数等价，不是发射 bool 包装简化。
unsigned1 限制保证每个输入只有 0/1；signed1、宽类型、四态、带参数、自定义
op、状态/输入读取及副作用本体不匹配。支持集含原值依赖，先前代表必定拓扑在前，
不会新增组合环；现有有环区域保留。初始化、DPI、commit 和冻结 GRH/RTL 不改。
共享可能改变分区与活动传播，需完整 NEMU 和小模型 exhaustive 检查。

局部 Host 目标 **5–15%**，粗上界为 compute 平坦占比 67.81%，实际可共享数量
与动态收益待测。六变量对应单个 64-bit 表，是算法的表示边界；不循环调参。
若重复覆盖低、调度开销超过少算收益、生成超时或正确性失败即证伪。先聚焦测试、
恢复生成/fresh 编译与同窗口 old/new 筛选，支持后完整 SV 路线及六次交替。
沿用 **86.323 s** 仿真截止、**1800 s** 生成/编译截止与固定配置，RUN_ID 使用
`no00026_boolean_*`。前述失败源码已全部撤销，不把广播或拼接收益混入本版。

## IMPLEMENTED：布尔子图共享及穷举验证

实现扩展现有 `canonicalize_compute.cpp`，不改 emitter/runtime/IR 定义或冻结
GRH pass。现有拓扑处理、assignment 消除及精确 CSE 保留；仅合格布尔计算进入
支持集/真值表归一化，先消除无关变量再查找等价代表。超过六变量时直接输入重建
边界，避免指数内存增长；恒等式引用真实 ValueId（包括 generation）。

新增 IR 测试对 400 个随机布尔 DAG 节点的全部 256 种八输入取值，用独立逐 op
解释器比较优化前后所有输出（102400 个输出比较），并验证 JSON round-trip。
另验证 signed1、unsigned8、四态1、带参数和组合环保持不变。生成 C++ 测试
两种 mapping 各 8192 eval / 4 init，覆盖全256输入、稳定重复 eval、德摩根、
吸收、双重取反、逻辑/位操作等价、eq/xnor/ne/xor、mux 两种结构、六输入奇偶
校验及八输入边界；ASan/UBSan 启用。既有 Verilator 的标量、宽值、状态、
CDC/双口 RAM 测试也仍在 canonicalize-compute 后执行。

第一轮 CPU emitter **62.88 s**、IR/mapping/schedule 各 **0.01 s** 全部通过；
增加随机/类型测试并保留 ValueId generation 后最终 IR **0.02 s**、CPU emitter
**63.18 s**、mapping/schedule 各 **0.01 s** 全部通过。没有仿真 INVALID。
随后开始独立 `flow-boolean-screen`：恢复生成、fresh 32-job 编译、连续 old/new
筛选，全部沿用已预装的截止。

## 布尔第一版筛选与机制补全

恢复生成 **107.09 s**（内部92.947 s，canonicalize4.804 s）、fresh编译
**242.12 s**，exit0。连续old/new Host **56.686 / 56.347 s**、emu墙钟
**56.72 / 56.37 s**，Make/emu0/0，精确50k NEMU PASS，截止未触发。
单对降低 **0.598031%** 仅支持弱正向，不作为接受证据；本版未做完整SV/正式六次。

操作/值各删除 **23160**，operations4095805→4072645，values3850751→3827591；
tasks5036→4949，boundary2282776→2281136 bytes，runtime5487→5400 bytes，
states/init records均保持508487。text120599885→120091653 bytes。
归并后新增 **1827** 个无消费者纯compute结果（and351、logicAnd258、or558、
not516、logicOr50、mux66、xor20、reduceOr4、logicNot4）；基线只有一个无用
input read、没有无消费者compute。初版未删除这些子图，也把不可变bit常量当作
独立输入，限制了支持集内的恒等化。这是机制缺口，进入补全版而非重复测量该版。

补全：将单参数的无符号两态1-bit `core.compute.constant` 按既有两态常量语义
解析为无输入的表0/1（bool/int或可解析SV字面量；未知位投影0），允许常量约束
在布尔子图中传播。归并后对比改写前后使用数，只递归清除**因本次改写而新近
失去所有用户**的纯两态compute；原本无人使用的操作、状态/input/memory读取、
初始化、副作用和环均保留。将恒等归并与失去用途的生产者清理结合，删除实际
执行子图，不增加运行期求值。新增常量/死分支验证，再按新RUN_ID
`no00026_boolean_complete_*` 筛选；目标、截止和最终六次门槛不变。

补全版测试首轮在新fixture emission失败，诊断确认现有CPU emitter对保留下来的
bool `value` 参数报 `CPU emit parameter has wrong type: value`；第二轮仅增加
诊断复现相同错误。fixture先建立字符串0/1代表，再让bool/int/未知位形式参与
归一化，测试常量变体合并到这些可发射代表；不改动无关的emitter参数处理。
最终 emitter **63.18 s**、IR **0.02 s**、mapping/schedule各 **0.01 s** 全部通过，
另覆盖常量mux、常量零、整数低位、未知位投影和吸收后递归失去用途的生产者。
失败仅在聚焦测试，没有产生性能样本。

## REJECTED：布尔常量与递归清理扩展回退

补全版恢复生成 **102.69 s**（内部91.362 s，canonicalize4.812 s），fresh编译
**234.56 s**，exit0，tasks4876。连续old/new Host **56.814 / 57.628 s**，emu
墙钟 **56.84 / 57.66 s**，Make/emu0/0，精确50k NEMU全部PASS，截止未触发。
回退 **1.432745%**，不支持保留该扩展；未进行补全版完整SV路线或正式六次。
已撤销常量表传播、递归新死计算清理及专用测试，恢复最初布尔子图共享版本。
不能把较少task或理论上失去用途的计算当作动态收益。

最初版本有一对弱正向筛选，尚未被正式统计判定；现在固定该源码版本独立验收。
预注册顺序 `no00026_boolean_final_old1/new1/old2/new2/old3/new3`（每项均带完整
前缀），全新完整SV目录 `flow-boolean-final`，1800s生成/编译进程组截止；
正式比较对NO00025原始old flow，不对失败补全版。原固定CPU2、单线程、输入、
trace关闭、86.323s仿真截止和精确终点要求不变，同一shell连续执行全部六次，
不混入前面的筛选样本。最终必须`max(new)<min(old)`，否则该版本不能接受。

## REJECTED：布尔函数共享正式六次未通过

完整SV生成 **607.57 s**（内部596.169s），exit0，checkpoint往返一致。
初始编译已启动时，代理误向仍然存活的包装会话发送Ctrl-C，包装exit130；这是
代理操作失误，不是流程超时或外部中断，不以该次不完整编译作为门槛证据。
随后同一完整生成flow按新的RUN_ID `no00026_boolean_final_build2` 重新调用
编译Make目标，耗时 **229.40 s**、exit0，预装1800s截止未触发。

| 顺序 / RUN_ID 后缀 | Host s | emu墙钟 s | Make/emu exit | 50k NEMU |
|---|---:|---:|---|---|
| old1 | 56.676 | 56.71 | 0/0 | PASS |
| new1 | 57.542 | 57.57 | 0/0 | PASS |
| old2 | 56.365 | 56.39 | 0/0 | PASS |
| new2 | 57.564 | 57.59 | 0/0 | PASS |
| old3 | 57.050 | 57.08 | 0/0 | PASS |
| new3 | 56.585 | 56.61 | 0/0 | PASS |

前缀`no00026_boolean_final_`，所有精确终点、输入与固定配置通过，无无效样本或
仿真截止。old/new均值 **56.697000 / 57.230333 s**，样本标准差
**0.342983 / 0.558983 s**，候选慢 **0.940673%**，old−new Cohen's d
**−1.150083**，U=7、单侧精确p=0.90，`max(new)=57.564>min(old)=56.365`。
新版本三次全部保留；第一版及常量/递归清理扩展均否定，完整撤销代码、专用
测试与后端文档，恢复NO00025。六变量函数去重减少静态操作，未实现净运行收益；
不再重复这一机制的阈值或统计窗口。节点继续，尚未ACCEPTED或提交。

## IDEA：宽常量一次共享物化与消费者特化

基线有 **1114** 个>64bit不可变constant，占 **95112 bytes**，共 **10840** 个
消费者引用：memWrite4085、mux3777、regWrite1163、concat1011、and520、shl110、
sliceArray53、add48、eq26、lshr25、sub22。width范围65–16511，其中514bit516个、
8160bit33个。现有标量常量已使用点特化，但宽常量仍在计算单元内赋值到活动槽，
随后消费者按动态内存操作数读取；编译器无法跨任务认出恒定mask/数据。

机制：emitter为每个宽constant发射一个`inline static constexpr std::array`的
只读类成员，所有消费者引用此固定存储，跳过原赋值和变化通知。每个value保留
原IR/layout槽和调度，所有任务仍初始active，消费者首次即可使用常量；无后续
变化可发布。宽常量只在编译时形成静态只读数据，不返回宽数组或增加运行期副本；
与legacy的caller buffer路线兼容，DPI inout如需修改仍先复制到独立可写临时值。
例如129bit全一常量共享`{UINT64_MAX,UINT64_MAX,1}`，位宽尾字及两态未知位投影
由既有literal解析保持。所有触发基于immutable op/type，不匹配模块名。

目标 **1–5% Host**，动态上界未知；只有1万余引用，覆盖明显小于NO00024标量
常量，不能沿用其收益比例。优势来自跨任务恒定mask/data折叠与省去重复物化，
也可能因静态header/rodata和代码布局增加而不获益。筛选无净改善或时间/正确性
失败即证伪。本节点截止/资源保持，RUN_ID `no00026_wide_constant_*`，先聚焦
验证再筛选；支持后完整SV和正式六次。前述所有失败改动不混入当前候选。

## IMPLEMENTED：宽常量静态存储

emitter收集两态宽constant，生成类内静态constexpr数组并在使用点引用；常量生产
操作和通知分组跳过，不改映射/布局/调度/初始化。生成名称加入保留名称集合，避免
与模型端口碰撞。legacy宽helper的const reference/输入buffer ABI不变。
基线现有全CPU回归 **61.03 s**、IR/mapping/schedule各 **0.01 s** 通过。
新增独立逐bit scoreboard，两种配置（同unit、逐op分区/helper）各3072 eval/
4 init；width65/76/129/257/514/4097，signed129、全一、交替位、X投影、动态
mask/mux与稳定重复eval，ASan/UBSan启用。最终回归结果如下，随后使用独立
`flow-wide-constant-screen`恢复生成和fresh编译，old/new连续筛选。

## REJECTED：宽常量静态存储

最终 emitter suite **63.57 s**，mapping/schedule 各 **0.01 s**，全部通过。
恢复生成 **107.32 s**（内部 93.091 s）、独立 fresh 编译 **235.01 s**，exit 0。
连续筛选 old/new Host **56.307 / 57.657 s**、emu 墙钟 **56.34 / 57.68 s**，
Make/emu exit 均 0/0，精确 50k NEMU 终点 PASS，截止未触发。新版慢约 **2.398%**，
不支持收益假设；未执行该版完整 SV 路线或正式六次。源码、测试、文档改动全部
撤销到 NO00025；不再围绕宽常量物化做局部变体。

后续证据检查转向 commit 的状态访问机制。现有独立采样中 scalar memory helper
约 224/11654 samples、wide masked helper 17/11654 samples；这些不包含内联成本，
不能当作完整 staging 成本或可删除上界。先按唯一写者、提交观察者及位宽统计
可覆盖状态，再确定是否值得实现。

## IDEA：按独占内存行变化武装写端口

进一步统计：37208 memWrite 中 32041 个使用恒定地址，均为唯一的 `(state,row)`；
它们所在内存没有动态地址、memFill/memWriteSeq/memAssign 写者，其中 **31425** 个
元素为 1–64 bit。另有 **1192** 个标量内存的唯一 memWrite，可接受动态地址。
相较之下，宽寄存器唯一写者仅 1149 个 / 28624 bytes，先不扩展该方向。
上述是静态上限，boundary/producer 资格可能进一步减少，不能代替动态覆盖。

新机制把既有 regWrite 的变化武装推广到有独占写入证明的 scalar memWrite：
唯一写者可使用动态地址；多个写者则要求所有地址为规范化后的无符号常量，并只
接受没有碰撞的行。任何整块、序列或未知对象引用排除整块内存；有动态地址且
不止一个写者也排除整块。enable/address/data/mask 四个操作数都必须为两态标量
boundary 快照，生产者沿用既有可发布变化的资格。

每个端口自上次有效边沿求值后，若四个操作数均未变化，同一行不会被其他端口
修改，重做 masked write 必然无效果；可跳过地址计算、dirty/shadow 检查和合并。
例如 row0 仅由 `write(en,0,data,mask,clk)` 写入，首个边沿完成后，data/mask/en
不变时后续 clk 边沿只采样 history；任一输入变化使端口重新武装。若同一 row0
有第二个写者，即使 mask 看似不相交，本版也回退以保留顺序和抵消。

所有实际写入仍沿用 NO00025 staged cell 路径与地址级 publication；没有新 helper
ABI、宽副本或提前 visible 更新。独占行之间的写块可移到武装段，事件 history
仍按原 op 顺序采样。初始全武装；未到有效边沿时不消费武装位；重复 init 清状态。
不改 IR/mapping/调度或冻结 GRH/RTL，触发只依赖语义和写入足迹。

局部目标 **2–8% Host**，粗上界受 commit 约 25% 相位占比约束，实际可删除成本
未知；新增 compute 武装通知可能抵消收益。筛选无净改善、正确性或截止失败则
否定。RUN_ID `no00026_memory_arm_*`，先聚焦测试与恢复生成/fresh 编译筛选；
支持后执行完整 SV 路线及原预注册六次，旧版仍为 NO00025。

## IMPLEMENTED：独占内存行写端口变化武装

emitter 在端口规划时证明完整对象引用和写入足迹，规范化常量行号，分配独占
memWrite 的 port arm bit；四个非事件操作数加入原 compute 变化通知。消费仍使用
原字节扫描、共享边沿和延迟消费规则，武装写体只调用已有 scalar cell helper。
没有修改 helper ABI、生成 runtime header 内容或任何 IR op；现有回归 **61.15 s**
通过，IR/mapping/schedule 各 **0.01 s**。

新增独立逐 bit memory scoreboard，两配置（同 compute unit / 分区加 helper），
signed5 数据、任意 8-bit host 输入模式、posedge/negedge、第二时钟、反复 init、
稳定输入长窗口、边沿前输入变化又恢复、enable/零 mask/部分 mask、动态地址与
越界写、同一行碰撞、fill 和 memWriteSeq 回退，以及跨行读取的边沿前快照。
形状检查要求恰好四个合格端口：常量行 0/1/3 和另一个内存的唯一动态写口；
`8'd2` 与 `9'd258` resize 到同一 8-bit 行号必须碰撞回退，范围外常量写口也回退。
每配置 **49156 eval / 4 init**，共 **98312 eval / 8 init**，ASan/UBSan 启用。

首次新增 suite **52.62 s** 失败于测试记分板假设：把原始 memRead 的越界读当作
零值，而现有 emitter 直接读地址，调用方需要有效范围。本方案不修改 memRead；
将测试读地址限制在 0..3，并保留 4..6 的越界写入检查。修正后最终 emitter suite
**64.71 s** 全通过，IR/mapping/schedule 各 **0.01 s**。这次失败不作为性能样本，
也不宣称覆盖原始越界 memRead 行为。

筛选使用独立 `flow-memory-arm-screen`；启动前保证没有 emu 目录或 model `.o/.a`。
对照 emu、CoreMark、NEMU 三个哈希与 BASELINE 匹配；生成/编译各预装 1800 s 截止，
仿真仍为 86.323 s，顺序为 old/new，各一轮。阶段结果完成后登记。

恢复生成 **114.62 s**（内部 100.102 s），exit 0；实际 **32617** 个 memWrite
获得武装资格。`cpu_pflags` **24303→28344 bytes**（+4041），object/boundary/runtime
layout 仍 **25934336 / 2282776 / 5487 bytes**。按目录内 `.cpp/.hpp/Makefile` 文件集
比较，5193 个文件中改变 3881 个 task 和模型 header，evaluator、初始化、runtime
helper 和 Makefile 不变。总文本 **1229852903→1240884322 bytes**（+11031419），
boundary accessor 引用 **5365802→5407733**；这是新增武装比较/通知的静态成本，
不是运行期额外访存计数。编译与筛选结果完成后登记。

## REJECTED：新增内存武装未获得净收益

fresh 编译 **231.75 s**，exit 0；old/new Host **56.775 / 56.796 s**，emu 墙钟
**56.80 / 56.82 s**，Make/emu exit 0/0，精确 50k NEMU 终点均 PASS，无截止触发。
新版约慢 **0.037%**，没有显示净改善，未执行完整 SV 路线或正式六次。新增武装
比较/通知可能抵消省去 cell helper 的效果，但没有相位测量，不能断言抵消来源。
撤销新增内存武装与写块重排，既有寄存器 pflags 和 compute 通知恢复 NO00025。

## IDEA/IMPLEMENTED：独占内存行直接提交

保留独占写入足迹证明，改为每次有效写边沿从 visible cell 求 masked next，变化
时直接写回，并复用原地址匹配规则通知 memRead 单元。覆盖目标仍是 32617 个
标量写口。创新在于按行证明独占性，把原仅限 register 的直接提交推广到内存，
避免每次变化所需的 dirty 查询、shadow 写入、pending 元数据和 publish 比较/复制。
不再增加 compute 的武装通知，不重排写口。

证明依赖于：所有 memRead 发生在 compute，commit 使用 boundary 快照；完整对象
引用只允许 memRead/memWrite；唯一动态写者或多个互不碰撞的恒定行写者；其他
写操作/观察者排除整个数组。混合数组中独占行可 direct，同址冲突行仍 staged。
直接通知只 OR compute flags 并保留 projection 对 `again` 的贡献；观察都在整轮
commit 之后，没有同一行后写者会抵消该通知。比如 `row0<=d; row3<=read(row0)`
仍让 row3 使用边沿前 row0，不读取已更新的 visible cell。常量 row 还须能表示为
主机 size_t；否则整个数组回退，防止截断别名。

新增 helper 只接收 cell 字节偏移、fanout 范围和 projection 的标量参数，调用方
原地写持有的 object buffer；没有返回数组、宽临时副本或新分配。与 legacy/已有
direct-state helper 的 OR 通知策略一致，内存地址比较保持原 publish 规则。
局部目标 **2–6% Host**，可删除成本未知，不能把约 25% commit 全相位当作收益；
代码体积和直接调用可能仍无收益。筛选无改善、正确性或截止失败即否定。
RUN_ID `no00026_memory_direct_*`，仍使用原始 NO00025 对照与相同门槛。

聚焦测试复用独立 bit scoreboard（更名为 memory_commit），shape 检查改为四个
独占 direct 端口，collision/动态共享/fill/sequence 回退和边沿前快照均保留。
新增保留名称冲突检查。先验证再进行恢复生成/fresh 编译的 old/new 筛选；尚未
执行本版完整路线或正式六次。

初次直接提交回归 **64.81 s**，IR/mapping/schedule 各 **0.01 s**。随后将同一
独立 bit scoreboard 扩展到 bool、unsigned64、signed64，连同 signed5 的 inline/
helper 两配置，共 **245780 eval / 20 init**；随机覆盖所有有效 bit、host signed
padding、零/部分/全 mask 和高位符号，ASan/UBSan 启用。最终 emitter suite
**133.57 s** 通过；此时与筛选 C++ 构建并行，因此该测试时间不用于性能比较，
在任何筛选仿真开始前已结束。IR/mapping/schedule 均通过。

本版恢复生成 **105.44 s**（内部 91.223 s），exit 0；实际 direct **32617** 个
写口。5193 个文件中只有 **293** 个 commit task、header 和 driver 共 **295**
个改变；compute tasks、初始化、runtime helper 和 Makefile 不变。`cpu_pflags`
恢复 **24303 bytes**；object/boundary/runtime layout 仍为既有值。源码总文本
**1229852903→1244987375 bytes**；object accessor 引用增加32617，local/boundary
引用保持 **6144689 / 5365802**。driver 差异仅新增地址通知函数；evaluator body
未修改。这些数字描述发射形态，不是已证明的动态节省。

## REJECTED：独占内存行直接提交

fresh 编译 **241.49 s**，exit 0；old/new Host **56.738 / 59.867 s**，emu 墙钟
**56.77 / 59.89 s**，Make/emu exit 均 0/0，精确 50k NEMU 终点 PASS，无截止。
新版慢约 **5.515%**。未执行完整 SV 路线或正式六次；不把通过正确性当作优化成功。
代码膨胀和通知时机变化可能影响缓存，但未采集该版相位，不能明确归因。
全部内存 footprint、直接提交、武装及其测试/文档改动已恢复 NO00025；不继续
围绕这两个单写口机制做局部参数变体。两次失败的完整机制、覆盖和测量保留于本文。

下一步检查普通寄存器副本的共享机会：现有 CSE 只处理纯计算，193497 个普通
标量/宽寄存器与锁存器候选仍保留独立对象。先统计相同类型、确定性初值、写入
数据/使能/mask/事件且无额外观察者的副本，确认规模后再提出安全合并机制。

## IDEA：等价普通状态与读取共享

严格静态筛选发现 **3312** 组、**14640** 个冗余普通状态：完整两态类型一致、
唯一 regWrite/latchWrite、完整非事件及事件操作数一致、全部写参数一致，目标
初值为完全相同的单条 `core.init.const`；每个事件 history 仅由本写口引用，且
两边 history 类型与确定性初值也相同。193497 个候选中 11315 个冗余状态为1bit，
另有64bit374个、512bit34个等。此计数仅为首轮；尚未计算合并读取后纯计算共享
带来的后续等价，不将静态删除数等同于动态收益。

机制是在 GrhSIM 的 canonicalize 阶段保留每组一个状态和写口，把所有同类型
state.read 合并为该状态的单一读取，把消费者改接到同一 value，删除冗余写口、
状态和只属于它的 event history。再次执行已有纯计算 CSE，直到不再发现新的
等价状态。每轮必须实际删除状态才继续，操作顺序无关的既有 CSE 保持不变。
例如 `q0<=d; q1<=d` 且初值、enable、mask、事件完全相同，则共享一个 q 和 read；
依赖 q0/q1 的相同计算可进一步共享。`q0<=q0; q1<=q1` 不因初值相同而直接合并，
因为输入 value 不同；不猜测循环的解，也不做不动点近似。

等价依据是相同初值与逐轮相同转移函数，private histories 保证相同事件判断。
额外状态观察者、多写者、随机/文件初始化、不同历史初值或共享/被观察 history
均回退；保留接口、DPI/system 操作、快照和相位语义。只修改独立 GrhSIM IR，
不修改冻结 GRH/pass 或 RTL，不按模块名匹配，没有新增运行期 helper/宽副本。
局部目标 **2–10% Host**，上界未知；共享造成 fanout 增加、映射变化也可能抵消
收益。小模型等价/筛选/时间失败则否定；通过后完整 SV、fresh 编译与正式六次。
RUN_ID `no00026_state_share_*`，对照、截止与统计规则沿用本节点预注册。

## 复现命令与验证口径

临时实验入口为下列 Make 命令，`root` 为仓库根目录。每个生成/编译使用独立
目录和唯一 RUN_ID；完整路线令 `XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0`，
筛选才设 1 并指定 `old/xiangshan_flat_grh.json`。环境和参数如下，完整路线的
实测值在完成后登记。正式六次在同一 shell 连续执行，运行期间无其他构建或分析。

```bash
set -euo pipefail
root=$PWD
node=$root/ptmp/no00026_dependency_execution_20260914_01
old=$root/ptmp/no00025_compute_demand_20260914_01/flow-memory-final
flow=$node/flow-broadcast-final
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
  test_grhsim_cpu_emit test_grhsim_cpu_mapping test_grhsim_cpu_schedule \
  PYTHON="$root/.venv/bin/python" > "$node/test-bit-broadcast-focused.log" 2>&1
/usr/bin/time -f 'wall_s=%e,user_s=%U,sys_s=%S,exit=%x' -o "$node/no00026_broadcast_full_generate.make.time" \
  timeout --signal=KILL 1800s make --no-print-directory xs_wolf_grhsim_ir "${common[@]}" \
  XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0 RUN_ID=no00026_broadcast_full_generate \
  > "$node/no00026_broadcast_full_generate.log" 2>&1
/usr/bin/time -f 'wall_s=%e,user_s=%U,sys_s=%S,exit=%x' -o "$node/no00026_broadcast_full_build.make.time" \
  timeout --signal=KILL 1800s make --no-print-directory xs_wolf_grhsim_ir_build_emu "${common[@]}" \
  RUN_ID=no00026_broadcast_full_build > "$node/no00026_broadcast_full_build.log" 2>&1
for pair in 1 2 3; do
  for version in old new; do
    run_id="no00026_broadcast_${version}${pair}"
    run_flow="$flow"
    if [[ "$version" == old ]]; then run_flow="$old"; fi
    make --no-print-directory run_xs_wolf_grhsim_ir_emu "${common[@]}" \
      XS_GRHSIM_IR_BUILD="$run_flow" RUN_ID="$run_id" \
      "XS_EMU_PREFIX=timeout --signal=KILL 86.323s /usr/bin/time -f wall_s=%e,user_s=%U,sys_s=%S,exit=%x -o $node/$run_id.emu.time taskset -c 2 stdbuf -oL -eL" \
      > "$node/$run_id.log" 2>&1
    rg -q 'Difftest enabled' "$node/$run_id.log"
    rg -q 'instrCnt = 73,?580, cycleCnt = 49,?996' "$node/$run_id.log"
    rg -q 'LIMIT at pc = 0x80001312' "$node/$run_id.log"
    rg -q 'Guest cycle spent: 50,?001' "$node/$run_id.log"
    if rg -qi 'mismatch|Assertion.*failed|ABORT|BAD TRAP' "$node/$run_id.log"; then exit 1; fi
  done
done
```

实际保存每次 Make 启动/结束时间、完整 shell-quoted 命令、Make exit、emu 时间和
VALID/INVALID 状态；emu 的计时 prefix 安装在 emu 执行处，不将 Make 时间算入 Host。
NEMU `.so` SHA-256 为 `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`。
编译器 clang 22.1.2，生成模型 `-std=c++20 -O3`，32 jobs；`XS_NUM_CORES=1`。

筛选目录分别为 `flow-cones-screen`、`flow-cones-screen2`、`flow-cones-screen3`、
`flow-word-screen`、`flow-broadcast-screen`；RUN_ID 前缀分别为 `no00026_cones_screen`、
`no00026_cones2_screen`、`no00026_cones3_screen`、`no00026_word_screen`、
`no00026_broadcast_screen`，后缀 generate/build/old/new。被否定的版本均已撤销，
当前保留源码不能复现那些二进制；本文记录各版机制与结果，不以临时路径代替分析。

基线采样使用 old flow、RUN_ID `no00026_baseline_profile`，在上述 prefix 的
`stdbuf` 后附 `env LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libprofiler.so.0
CPUPROFILE=$node/no00026_baseline_profile.prof CPUPROFILE_FREQUENCY=200`。
解码使用 `make analyze_grhsim_cpu_profile PYTHON="$root/.venv/bin/python"`
`GRHSIM_CPU_PROFILE="$node/no00026_baseline_profile.prof"`
`GRHSIM_CPU_PROFILE_BINARY="$old/emu/emu" GRHSIM_CPU_PROFILE_MODEL="$old/model/grhsim_SimTop.cpp"`
`GRHSIM_CPU_PROFILE_SAMPLES=11654`，同一环境。最终相位诊断（若执行）只改
RUN_ID 与 `EMU_RUNTIME_PROFILE=1`，不进入正式统计。

## IMPLEMENTED：等价普通状态与读取共享

布尔子图、宽常量和两种独占内存提交尝试均已回退后，保留普通状态共享实现。实现
提交为子模块 `cafaf61`（`perf(grhsim): share equivalent ordinary state`），修改
`lib/grhsim/pass/canonicalize_compute.cpp`、CPU 后端说明及状态共享测试 fixture。
实现位于现有 `grhsim.canonicalize-compute`，先完成原有赋值/纯计算 CSE，再迭代扫描
状态副本。候选必须是 two-state logic、唯一 `regWrite`/`latchWrite`、唯一确定性
单步 `core.init.const`，写操作种类、全部 operands、parameters、事件边沿和私有
history 的类型及初值都相同；对象引用只能是目标写口、对应 `state.read` 和该写口
私有 history。随机、文件、多步初始化、多写者、额外观察者、共享 history 和循环
反馈均回退。每组保留一个 state/write，所有同类型 read 合并到一个 value，副本及
其私有 history 删除；改写后再次运行纯计算 CSE，直到固定点。未增加运行期 helper、
宽值临时副本、IR 类型或调度规则，也没有使用模块名条件。

独立状态 scoreboard 覆盖 unsigned/signed two-state 1、5、64、129 bit，posedge/
negedge、第二事件域、enable/mask、稳定输入重复求值、重复 init、状态依赖链和
排除条件（随机/不同初值、共享或被观察 history、多写者、循环反馈）。两种 mapping
各运行 32772 次求值和 4 次 init；ASan/UBSan 开启，优化模型与未优化参考模型的
完整二进制 trace 相同。聚焦 Make 目标 `test_grhsim_cpu_emit` 用时 67.63 s，
`test_grhsim_cpu_mapping`、`test_grhsim_cpu_schedule` 和 `grhsim-ir-tests` 均通过。

## VALIDATED：完整生成、编译与等价性

筛选恢复生成 `no00026_state_share_screen_generate` 用时 162.53 s，独立 fresh
32-job 编译 `no00026_state_share_screen_build` 用时 239.34 s；两者 Make exit=0，
均远低于 1800 s。筛选版只用于预检，old/new 一次运行分别为 56.92 s/55.52 s，
均通过 50k NEMU 精确终点。正式 flow 从冻结 XiangShan SV 重新执行 ingest 和
全部既有 GRH pass，`no00026_state_share_full_generate` 用时 657.43 s；随后在
无对象文件复用的独立目录执行 `no00026_state_share_full_build`，用时 239.56 s。
两步均 exit=0，均未触发 1800 s 截止。

正式命令固定为以下 Make 目标和参数；完整路线将
`XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0`，筛选只将该参数设为 1 并把
`XS_WOLF_GRHSIM_IR_FLAT_GRH_JSON` 指向 NO00025 flat GRH。环境为
`WOLF_ENV_SOURCED=1`、`JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64`、仓库
`.venv/bin` 和 `/home/gaoruihao/wksp` 在 `PATH`，`TMPDIR`/`PIP_CACHE_DIR`/日志
均位于本节点 `ptmp`，`CMAKE_BUILD_PARALLEL_LEVEL=32`、`LC_ALL=C`、
`EMU_RUNTIME_PROFILE=0`：

```bash
source env.sh
make --no-print-directory xs_wolf_grhsim_ir \
  PYTHON=$PWD/.venv/bin/python XS_NUM_CORES=1 XS_EMU_THREADS=1 \
  VM_BUILD_JOBS=32 XS_VM_BUILD_JOBS=32 XS_SIM_MAX_CYCLE=50000 XS_EMU_CPU=2 \
  XS_WAVEFORM=0 XS_WAVEFORM_FULL=0 XS_COMMIT_TRACE=0 XS_RAM_TRACE=0 \
  XS_PROGRESS_EVERY_CYCLES=0 WOLVRIX_GRHSIM_WAVEFORM=0 WOLVRIX_GRHSIM_PERF=0 \
  XS_GRHSIM_IR_BUILD=$PWD/ptmp/no00026_dependency_execution_20260914_01/flow-state-share-final \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=$PWD/ptmp/no00026_dependency_execution_20260914_01/flow-state-share-final/model \
  XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0 XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0 \
  RUN_ID=no00026_state_share_full_generate
make --no-print-directory xs_wolf_grhsim_ir_build_emu \
  PYTHON=$PWD/.venv/bin/python XS_NUM_CORES=1 XS_EMU_THREADS=1 \
  VM_BUILD_JOBS=32 XS_VM_BUILD_JOBS=32 XS_SIM_MAX_CYCLE=50000 XS_EMU_CPU=2 \
  XS_WAVEFORM=0 XS_WAVEFORM_FULL=0 XS_COMMIT_TRACE=0 XS_RAM_TRACE=0 \
  XS_PROGRESS_EVERY_CYCLES=0 WOLVRIX_GRHSIM_WAVEFORM=0 WOLVRIX_GRHSIM_PERF=0 \
  XS_GRHSIM_IR_BUILD=$PWD/ptmp/no00026_dependency_execution_20260914_01/flow-state-share-final \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=$PWD/ptmp/no00026_dependency_execution_20260914_01/flow-state-share-final/model \
  XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0 RUN_ID=no00026_state_share_full_build
make --no-print-directory run_xs_wolf_grhsim_ir_emu \
  PYTHON=$PWD/.venv/bin/python XS_NUM_CORES=1 XS_EMU_THREADS=1 XS_EMU_CPU=2 \
  XS_SIM_MAX_CYCLE=50000 XS_WAVEFORM=0 XS_COMMIT_TRACE=0 XS_RAM_TRACE=0 \
  XS_GRHSIM_IR_BUILD=$PWD/ptmp/no00026_dependency_execution_20260914_01/flow-state-share-final \
  RUN_ID=no00026_state_share_final_new1 \
  'XS_EMU_PREFIX=timeout --signal=KILL 86.323s /usr/bin/time -f wall_s=%e,user_s=%U,sys_s=%S,exit=%x -o ptmp/no00026_dependency_execution_20260914_01/no00026_state_share_final_new1.emu.time taskset -c 2 stdbuf -oL -eL'
```

其余五次只按预注册顺序替换 `RUN_ID`，old 运行将
`XS_GRHSIM_IR_BUILD` 改为 NO00025 的 `flow-memory-final`；生成/编译命令外层均
使用 `timeout --signal=KILL 1800s` 和 `/usr/bin/time`，没有在仿真期间构建。

正式 flow 的 flat GRH SHA-256 为
`518f41485197156a91ff13df2eacb72f23dd63fec9bbc29fd0a6ffe1b8ace923`，与 NO00025
完全相同；GrhSIM checkpoint 经过 fresh-session round-trip 后原字节相同。NO00025
到本版 checkpoint 的变化为 states **508487→467657**（删除 40830）、values
**3850751→3762933**（删除 87818）、operations **4095805→3988626**（删除
107179）、operands **9096353→8875618**（删除 220735），object refs
**762914→705901**（删除 57013），init records **508487→467657**（删除 40830）。
生成模型目录中的 tracked `.cpp/.hpp/Makefile` 总字节数
**1229852903→1191791348**（减少 38061555，3.094805%），compute task 文件
**5036→4954**；这描述静态形态，不把删除量直接当作运行期收益。正式 ELF
`text/data/bss = 117467545/9344/18416`，旧版为 `120599885/9344/18416`。

输入 `testcase/xiangshan/ready-to-run/coremark-2-iteration.bin` SHA-256 为
`c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`，NEMU `.so`
SHA-256 为 `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`。
所有运行固定 `XS_NUM_CORES=1`、`XS_EMU_THREADS=1`、`XS_EMU_CPU=2`、50,000
cycles、CPU 2、waveform/commit/RAM trace 关闭，并使用同一输入和 DIFFTEST/NEMU。

## ACCEPTED：六次新旧交替复测

正式执行使用同一 shell 串行顺序
`no00026_state_share_final_old1/new1/old2/new2/old3/new3`，每次均用
`run_xs_wolf_grhsim_ir_emu`，emu 处以 `timeout --signal=KILL 86.323s`、CPU 2
绑定计时；生成和编译不在该计时区间。六次完整数据如下：

| 顺序 / RUN_ID | Host s | emu 墙钟 s | Make/emu exit | NEMU 终点 |
|---|---:|---:|---|---|
| old1 / `no00026_state_share_final_old1` | 57.120 | 57.09 | 0/0 | PASS |
| new1 / `no00026_state_share_final_new1` | 55.590 | 55.57 | 0/0 | PASS |
| old2 / `no00026_state_share_final_old2` | 57.030 | 57.00 | 0/0 | PASS |
| new2 / `no00026_state_share_final_new2` | 55.900 | 55.87 | 0/0 | PASS |
| old3 / `no00026_state_share_final_old3` | 57.380 | 57.35 | 0/0 | PASS |
| new3 / `no00026_state_share_final_new3` | 55.610 | 55.59 | 0/0 | PASS |

Host 均值为 old **57.176667 s**、new **55.700000 s**；样本标准差分别为
**0.181751 s**、**0.173494 s**。new 相对 old 降低 **2.582639%**，合并样本
Cohen's d（old−new）为 **8.311284**。所有新样本都小于所有旧样本：
`max(new)=55.900 < min(old)=57.030`，Mann–Whitney U=0，单侧精确
`p=0.05`，达到规定的三对三全秩分离门槛；没有 INVALID、补跑或截止杀除。
每次日志均记录 `instrCnt=73580`、`cycleCnt=49996`、终点 PC `0x80001312`、
guest cycles `50001`，与预注册等价性完全一致。没有把此前跨窗口筛选值或插桩
诊断混入上述统计。

## 最终判定与三节点复盘

NO00026 达到 `ACCEPTED`：普通状态副本共享在冻结 RTL、GRH 和 GRH pass 不变的
前提下，通过聚焦 exhaustive scoreboard、完整 SV→C++（657.43 s）、独立 fresh
编译（239.56 s）、flat GRH/checkpoint 等价检查和六次新旧交替统计。保留实现的
最终子模块 commit 为 `cafaf61`；失败的独立依赖分组、活动字 set-bit 分派、bit
广播、输出字组装、布尔函数/常量传播、宽常量、内存武装和内存直接提交均已撤销，
其否定数据仍保留在本报告中。当前最佳正式均值 **55.700000 s**，距约 40 s 目标
尚差 **15.700000 s**；本节点未关闭整个 goal，后续节点须由用户再次启动。

NO00024–26 的定期复盘：NO00024 的不可变标量常量特化、NO00025 的标量内存
staging 与本节点的普通状态共享分别在同期六次交替中降低 **3.197601%**、
**2.059826%**、**2.582639%**，当前最佳从 58.417667 s 经 57.548667 s 降到
55.700000 s。三者均只由语义/依赖/读写属性触发，可组合但不能跨窗口相乘累计；
最近三节点没有回到已否定的 helper 和通知阈值微调。剩余主要差距仍在 compute
与 commit 的逐轮执行，下一方向应先重新采集当前相位和动态覆盖，再提出独立的
依赖驱动或批量执行机制，并为新节点重新预选截止线与六次交替顺序。
