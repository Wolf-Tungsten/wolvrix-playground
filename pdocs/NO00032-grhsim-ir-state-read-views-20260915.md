# NO00032：状态访问粒度与同控制位寄存器打包

日期：2026-09-15–16。最终判定：**ACCEPTED（F）**；尝试A–E已否定并撤回。

根基线 `137a316b1863b9bde7bed0b09bab7a3f400d2734`，wolvrix 基线
`c924a18da6f900c9fe8f343df38e77ec8109b711`（NO00031）；节点启动时两仓库干净。
本节点尚未提交任何阶段版本。旧构建复用 NO00031 的完整 SV 生成产物，正式性能
仍须在本节点同一窗口重测，不能用历史 118.631667 s 均值代替对照。

当前保留的实现F是GrhSIM IR `grhsim.pack-bit-registers`：将66935个同控制bit
寄存器打包为4433个word，协同既有CPU标量concat/slice/read/write发射路径，
减少62502个逐bit提交写口。正式六次交替old/new均值为118.153000/109.970333 s，
降低6.925484%，max(new)110.288 < min(old)117.343，U=0、单侧精确p=0.05。
六次NEMU和精确100k终点一致；完整SV生成704.68 s、fresh编译215.90 s均达标。
前面的读视图拆分A–E均撤回，只保留分析工具与失败证据。新实现与边界说明见
[pack-bit-registers](../wolvrix/docs/grhsim_ir/passes/pack-bit-registers.md)。

## 初始假设与证伪方法（A–E已否定）

NO00031 的当前版本独立诊断有 23498 个样本，其中 compute task 16296
（69.350583%）、commit task 4313（18.354754%），2858 个 compute task 有采样。
热点分散，尚不足以把剩余对 gsim 的 2.525959 倍差距归结为某个 helper。

CPU emitter 已将只被 compute 使用的部分 state.read 结果直接别名到状态对象；
但同一 read 同时用于 compute 与 commit 时，整个值被迫保留提交前快照。
本次探索在 GrhSIM IR 中分开计算视图和提交快照，让 compute 的消费者直接读取
已发布状态，commit 的消费者继续读取原有快照。创新机制是按相位使用拆分同一
状态读取的物化要求，避免所有消费者承担最严格的生命周期要求。
首先审计真实覆盖面；若现有别名已覆盖绝大多数读，或拆分并不能减少动态成本，
则记录为节点内被否定假设并继续寻找覆盖主要成本的机制。

局部探索目标 1–5%，不是接受硬阈值；静态候选数不等于动态收益。状态在 compute
期间稳定，commit 读取必须保持提交前值；事件值、history、初始化、写口顺序与
所有副作用不变。不修改冻结 GRH、GRH pass、XiangShan 或基准测试源，不按模块名
选择候选。宽 helper 如需修改，必须沿用 legacy 的调用方缓冲区策略。

## 验证预注册

所有流程经 Makefile，日志与临时产物位于
`ptmp/no00032_state-read-views_20260915`；每次实验目录与 RUN_ID 唯一。
完整 SV→C++、fresh C++ 编译各用 `timeout --signal=KILL 1800s` 包住进程组，
截止时杀死并隔离未完成产物。仿真以当前归档 new Host 均值 **118.631667 s**
作为预选比较值，1.5 倍截止 **177.9475005 s**。

CPU2、XS_NUM_CORES=1、XS_EMU_THREADS=1、100000 cycles，CoreMark 两次迭代，
NEMU 对拍，waveform/trace/profile 关闭。独立筛选 old/new 一对；通过后独立执行
old1/new1/old2/new2/old3/new3。主指标 Host，辅指标 emu wall；要求全部 new
小于全部 old（U=0，单侧精确 p=0.05），报告均值、样本 SD 和效应量。
任何失败、超时或 endpoint 不同均不得作为性能证据。此预注册在完整生成、编译
或性能实验启动前写入；以下随证据更新。

## BASELINE：状态读物化审计

通过 `make analyze_grhsim_state_reads` 读取确切 old IR/mapping。共有 **167484**
个 state.read，其中 **113956** 个源状态在投影中，**13777** 个结果需要 commit
或 commit event 快照，现有 emitter 可别名 **102077** 个。全部读取对象都通过
普通状态引用证明；额外 **51630** 个非投影、非快照读取可安全扩大别名资格。
其中 **29244** 个在原mapping中属于boundary，其余为local；不能将全部51630
都称为跨分区物化。原投影资格只涉及是否需要继续收敛，不能据此推导读值必须复制。
**5540** 个读混用了 compute 与 snapshot，覆盖 **88998** 个 distinct
compute 使用者。这些都是静态覆盖面，不是调用频率或时间占比。

旧 ELF SHA256 为 `53824635c5ea5be9d271c7470a7749dfa5bd7f4c6b7d3ea79c966842b885d241`；
CoreMark 与 NEMU 分别为
`c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`、
`094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`，与 NO00031 一致。
主机有32逻辑CPU、187 GiB内存；生成安装与编译使用32 jobs，仿真固定CPU2。

## A–E实现记录：计算视图与 emit 协作（代码已撤回）

当时新增 `split-state-reads`（已撤回），在 CSE、
clone 和 bitwise-predicates 之后运行。原 read 和所有 commit operands 保持，
新增一个同状态同类型 read 供 compute 使用；unknown op 保守留在原 read。
两态普通状态证明排除 history 和其他对象引用形式，不依赖状态名或模块名。
map 随 semantic revision 失效后重建。CPU emitter 复用普通状态证明，将非投影
计算视图也别名到已发布状态，并复用 state fanout 激活消费者；不改变收敛投影。
XiangShan 可用 `XS_WOLF_GRHSIM_IR_SPLIT_STATE_READS=0` 关闭拆分；该开关不关闭
emitter 的普通状态证明，完整 old 对照仍由冻结基线构建提供。

小例子 `q=3; r<=q; q<=5`：提交时 r 必须读快照3，下一 compute 轮的 q 视图读5。
不引入新的宽值 helper，129位直接引用已有状态缓冲区；commit 仍按原路径保留快照。

IR 测试覆盖混合/单相位用途、signed5/129位、四态、带参数read、history排除，
检查原commit操作数、实体数量、revision、幂等和JSON往返。生成C++测试在普通
映射和单操作helper两种配置运行独立scoreboard：每种98304次检查、3次init，
覆盖同边沿两级流水、1/5/64/129位、直接输出和xor、非投影状态的下降沿DPI观察，
以及连续关闭可观察状态更新时的非投影通知，启用ASan/UBSan。

前两轮完整emitter回归在新夹具因无定宽字面量`'1`失败（52.84/51.83 s），
已用显式129位全一常量修正；没有XiangShan性能数据，也没有修改生产literal规则。
第三轮 `make test_grhsim_cpu_emit test_grhsim_cpu_schedule` 通过：75.79/0.01 s；
IR/mapping此前各0.01 s通过。小范围分类完善将`state.memRead`地址列入compute用途，
随后的最终源码补验全部通过：IR/mapping各0.01 s，emit79.74 s，schedule0.01 s。
`make run_hdlbits_grhsim_ir DUT=086/097 SKIP_PY_INSTALL=1` 也分别通过 byte-enable
16位寄存器和带reset的下降沿寄存器验证。测试源与冻结GRH均未修改。

完整SV生成完成，目录`flow-views-a`、RUN_ID=`no00032_views_a_generate`，
Make wall **672.64 s**、内部 **657.704 s**，exit0，低于1800s；未复用flat GRH，
fresh-session IR roundtrip逐字节一致。flat GRH与old的SHA256同为
`518f41485197156a91ff13df2eacb72f23dd63fec9bbc29fd0a6ffe1b8ace923`。
新增pass耗时 **0.502 s**。fresh编译及筛选结果见下节。

## 尝试A：IR拆分与emit扩大别名（REJECTED）

尝试A的完整生成/编译分别为 **672.64 s / 221.84 s**，均exit0；IR fresh
roundtrip逐字节一致，flat GRH保持同一SHA256。state-read比较工具确认新增
5540个read、重接89081个计算operands，210641个commit操作逐项不变，
boundary values **875735→878052（+2317）**。静态反汇编中compute指令
15,033,251→14,810,652（−1.48%），但commit指令2,925,709→3,056,171
（+4.46%），commit calls +30.04%；这解释了不能从静态compute下降推断总收益。

独立一对筛选 `screen-a` 按同一CPU2/100k/NEMU配置运行并正确到达终点：
old Host **118.396 s**，new **119.890 s**，new **慢1.261867%**，两次Make/emu
均exit0且无mismatch。n=1+1不作统计接受，候选A正式判定REJECTED；没有运行
正式六次。失败不是正确性失败；commit调用静态增加提示通知路径变重，但这不
足以独立归因动态回退。状态读本身是生成赋值，并不是新增了read函数调用。
该筛选完整结果保存在节点ptmp目录，不能作为成功收益证据。

尝试A源码保留在当前工作区供尝试B复用；节点不会以该失败收尾。

## 尝试B：隔离非投影普通状态别名

2026-09-15 23:26:21启动`flow-views-b`完整SV生成，唯一RUN_ID
`no00032_views_b_generate`；命令同A，增加`XS_WOLF_GRHSIM_IR_SPLIT_STATE_READS=0`。
候选B不改变IR，只测量普通状态证明扩大alias的效果，以区分A的重新分区影响。
完整生成 **657.55 s**（内部651.817 s）、fresh编译 **234.85 s**，均exit0且未
触发截止。B的完整IR checkpoint与NO00031 old逐字节相同，隔离了IR变化。
1800s生成/编译截止与177.9475005s仿真截止保持。

B独立一对筛选old Host **118.621 s** / wall118.65 s，new **120.397 s** /
wall120.43 s，两次Make/emu均exit0、100k精确终点一致且NEMU PASS。new表观慢
**1.497205%**；n=1不能估计稳健效应，未进入正式六次，B作为尝试判定REJECTED。
IR与mapping逐字节相同排除了分区混杂，但不能在无相位诊断下将回退全归因于
通知；它足以否定“只扩大alias即可获得可接受收益”的当前实现选择。

通知审计发现A有364个只含别名读/使用点常量的无工作compute unit。移除这些
空unit的state通知可使3609个source的目标字数2→1、29138个source的3→2；
该统计是静态依赖计数，还没有实现或取得收益。更精确的修正应仅保留实际读者，
对省略物化的别名读不再通知其producer owner，其真正consumer及snapshot
producer仍应被同一state发布唤醒；不能不加区分地删除一个含其他工作的unit。

## 尝试C：消除别名读的冗余producer通知

直接读取的read不会在原producer执行任何物化，但A/B仍将producer通知保留，
再额外通知真实consumer。原单目标通知因此变成多目标，触发`cpu_direct_state_changed`
调用。完整生成源码计数确认old为65481个这种调用站点，A为99069（+33588）、
B为94708（+29227）；A的commit机器码calls也恰增加33588。因此额外调用明确
来自通知，而不是read函数。尚无硬件动态计数，不能把全部1.262%回退归给此项。

C保留IR拆分，将普通状态的compute激活目标按实际读者重建：保留未别名的
read producer；对已别名的read仅添加真实compute consumers。其他history/opaque
状态沿用原目标表，所有commit domain arm、projection及初始化激活保持。
静态依赖审计预期5848个source的目标字2→1、46695个3→2、350个1→0。
此举修正的是物化消除后未同步收缩依赖，不是调节内联阈值。

第一次C emitter/schedule回归通过150.08/0.01 s（同期有B编译，不能作编译性能
比较）；新增强制每op一compute supernode的快照fixture补验与C恢复生成正在执行。
恢复生成经新增`make reemit_grhsim_ir`，从A完整IR重新发射到独立
`flow-views-c-screen`，仅用于筛选，不代替最终完整SV门槛。

C恢复生成32.42 s，fresh编译223.88 s，均exit0。强制分区补验77.66 s通过。
多目标通知站点缩至93272，说明还存在很多真实consumer通知。
独立筛选old Host **117.337 s** / wall117.36 s，new **120.133 s** / wall120.16 s，
Make/emu均0/0且精确100k终点一致、NEMU PASS。new表观慢 **2.382880%**；未进入
正式六次，C判定REJECTED。不能把C与不同窗口A的时间相减估计单项过滤收益。

## 尝试D：普通状态的通知与每轮播种协作

C的真实读者中仍有许多roundSeeds单元。普通状态只在compute之后发布，而每次
compute前必定重播种这些单元；因此状态发布再OR同一个活动位是冗余的。D在C
基础上只对普通状态去掉这些目标，保留history/opaque状态通知与所有domain arm。
若投影状态最后没有通知目标，directCommit直接置`cpu_direct_again=true`，不
调用空目标helper；不取消收敛。基于A mapping审计，另有21639个source可3→1、
14932个source可1→0；D生成源码多目标通知站点为71567，较C少21705。

D第一次回归在44.01 s因旧结构断言要求私有状态发出单目标通知而失败。该fixture
的唯一真实读者是每轮播种的DPI任务，新增机制正确删除通知。已改为检查不发通知，
保留原runtime scoreboard（每次eval仅一次DPI、观察提交前值、4次init和随机mask），
并重新执行完整回归。没有放宽行为检查。D从A checkpoint恢复生成到
`flow-views-d-screen`，仍只用于筛选；如最终保留必须做完整SV/fresh编译验证。

D补验通过：emitter151.19 s、schedule0.02 s（同期有编译）；筛选fresh编译
227.01 s，exit0。B/C/D三个独立old/new筛选按顺序运行，每个目录独立预注册，
不并行编译/采样/机器码分析。最终保留版本仍须独立六次交替复测，不能将三种
候选的样本混为new组。

D筛选old Host **118.291 s** / wall118.32 s，new **119.298 s** / wall119.33 s，
两次Make/emu均0/0、精确100k终点一致、NEMU PASS；表观慢 **0.851290%**。
D未进入正式六次，作为尝试判定REJECTED。通知减少仍没有换来本次筛选净收益。

## 尝试E：保留非投影紧凑读取，拆分投影视图并精确通知

A–D共同扩大了非投影状态的直接object读取。即使省掉读赋值，也扩大了真实
消费者直接访问的对象工作集和状态通知；D移除冗余通知后仍未见净收益。
E撤回这一选择，保留原投影资格，让非投影读继续使用紧凑local/boundary槽，
同时保留IR快照/视图拆分与C/D的实际读者通知重建、每轮播种协作。
E的多目标通知站点65687，比old65481仅多206；emitter76.89 s、schedule0.01 s
回归通过，恢复生成32.04 s，筛选编译正在进行。
这不是已证明的cache-miss归因；为辨别成本，先对D做独立phase/CPU采样，
诊断不加入未插桩性能数据，完成前不并行编译。

D诊断完成：Host120.384 s、emu wall120.42 s，100k精确终点/NEMU PASS。
evals200102、rounds402258与old相同；compute90.218585 s、commit27.877947 s、
publish1.742197 s、eval119.979450 s、model_step119.890613 s。200Hz采样24080个，
compute16454（68.330565%）、commit4551（18.899502%）；通知helper323个
（1.341362%），old归档为210/23498（0.893693%）。两个诊断不同窗口且各一次，
不能将差值视为独立因果效应；剩余成本仍分散。E恢复生成和编译在诊断退出后才启动。

顺带审计单写口`regWrite/latchWrite`的数据是否为同状态保持分支mux，只有64个
一位单用户mux（全部hold在true分支）。覆盖太小，静态否定此处反馈mux方向的
大收益假设，未实现、未跑性能，不作为节点完成结果。

E筛选fresh编译221.70 s，exit0；old Host **118.450 s** / wall118.48 s，new
**121.560 s** / wall121.59 s，Make/emu均0/0、精确100k终点一致、NEMU PASS。
表观慢 **2.625580%**，未进入正式六次，E判定REJECTED。至此停止读视图拆分路线，
不继续该方向的参数微调；保留全部过程证据。

## 尝试F：同控制位寄存器打包

新的状态访问机制从减少执行粒度入手：对相同写使能、掩码、事件及历史初值的
普通单写口一位寄存器，在GrhSIM IR中打包为至多64位状态，合并数据concat与
一次提交，再将读拆为bit slice。可望减少逐位write活动、对象存储和通知；风险
是打包导致无关bit变化唤醒所有读者，必须由筛选验证。先审计实际覆盖与类型/
history/初始化约束。实现还要求两个目标处于相同quiescenceProjection类别，
避免私有bit与投影bit合并后改变求值轮次；目标为unsigned、两态width1，history
为私有单引用且常量初值已知。保守排除随机/未知初值、signed、四态、多写口及
共享/可观察history。data可不同，enable、mask、按序event值/边沿/历史初值必须
相同。两个bit初值(q0=0,q1=1)合为`2'd2`，data concat为`{d1,d0}`，掩码为
`{2{mask}}`，读q0/q1分别为packed[0]/packed[1]。原来的全部数据依赖都仍在compute
相位求值，commit单次写入packed，保留同边沿旧值快照。

基础IR/mapping通过；首次完整生成C++回归在新增测试主程序的`svBit`未声明处失败，
改为`std::uint8_t`后完整回归95.50 s通过。每种普通/单op分区有24576次scoreboard
检查、3次init，包含2/64/130位分块、同边沿反馈流水、可变enable/mask、正负与
混合事件、history初值0/1、非投影DPI完整轨迹与未改写模型比较，并使用ASan/UBSan。
后续补入signed/随机/未知初值及history/多写口排除回归并通过。再补7种结构排除
（四态target/history/event/mask、signed enable、参数化read、非bit target），
最终完整emitter回归105.33 s通过；未通过emit支持的四态形式仅做mapping/pass结构
检查，不伪称运行了四态C++仿真。

真实XiangShan应用结果是66935 bit→4433 word，减少62502个regWrite；提交总ops
210641→148139，新增compute concat/read/replicate共13299。首次恢复工具误用了
默认target_batch_count=64，其522个task产物仅用于发现配置不一致，已隔离为
`flow-pack-f-batch64-unused`，未编译或测速。工具已显式设为基线0，重新生成
`flow-pack-f-screen`；筛选通过之前不宣称性能收益，恢复时间不用于完整SV门槛。

按0配置恢复/emit45.10 s、fresh编译224.46 s，exit0；4944个task，object25714368
bytes、boundary2186824 bytes。补充排除条件的IR/mapping/emit/schedule全部通过
（0.01/0.01/174.43/0.02 s，emit与fresh编译同期运行所以不比较其耗时）。安装更新后
HDLBits086/097通过；第一次跳过安装时未知pass错误仅是旧Python安装，未产生有效
HDLBits结果。独立screen-f按old/new启动，未启用profile或并行构建。

F筛选old Host118.513 s/wall118.54 s、new Host108.736 s/wall108.76 s，Make/emu
均0/0，精确100k终点一致且Difftest enabled、无mismatch。表观降低8.249728%；单对
不是正式统计接受证据。继续F同一实现的完整SV生成和全新编译，之后独立六次交替。

### F的静态覆盖与因果边界

| 指标 | NO00031 old | F检查点 |
|---|---:|---:|
| semantic operations / values | 3994535 / 3770137 | 3945332 / 3783436 |
| states | 464343 | 313107 |
| state.read / regWrite | 167484 / 172432 | 104982 / 109930 |
| concat / sliceStatic / replicate | 227704 / 132796 / 8965 | 232137 / 199731 / 13398 |
| boundary values / bytes | 875735 / 2204184 | 835511 / 2186824 |
| object bytes / runtime bytes | 25862312 / 5425 | 25714368 / 5414 |
| tasks / round seeds | 4972 / 312 | 4944 / 315 |
| ELF text bytes | 110552534 | 105403692 |
| compute native instructions / conditional jumps / calls | 15033251 / 666606 / 65260 | 15202092 / 670261 / 63646 |
| commit native instructions / conditional jumps / calls | 2925709 / 539754 / 111753 | 2135503 / 374355 / 79661 |

状态减少151236，包括62502个目标及88734个冗余history；state.read净少62502，
因为66935个旧read转slice并新增4433个packed read。compute增加13299个ops，
同时减少62502个commit ops，所以总ops净少49203；不能将全部总op减少都归为
计算简化。boundary值少40224，boundary存储仅少17360 bytes，说明槽数量与
字节量是不同维度。commit静态指令少790206（27.01%）、条件跳转少165399
（30.64%），compute静态指令反而多168841（1.12%）。ELF text少5148842 bytes。
该形态符合把逐bit提交开销转成少量字级提交的机制；静态指令不是动态执行次数，
不能直接将静态百分比当作耗时归因。后续独立profile检查收益主要来自哪个相位。

### F完整SV路线

`flow-pack-final`完整SV→C++ Make wall704.68 s（内部693.715 s）、exit0，fresh-session
IR JSON往返逐字节一致。没有resume flat GRH；fresh编译215.90 s、exit0，达标。
独立formal-f六次交替按预注册old1/new1/old2/new2/old3/new3开始。
flat GRH SHA256仍为518f41485197156a91ff13df2eacb72f23dd63fec9bbc29fd0a6ffe1b8ace923，
与old一致。打包pass本身1.415 s；两轮mapping及再次schedule的成本已包含在704.68 s。
完整生成与筛选的全部C++/header/runtime/Makefile逐字节一致，初次目录diff显示的31项
差异全部是正在编译的`.o.tmp`临时文件，排除编译产物后0差异。
完整模型、往返模型和筛选模型三者SHA256均为
`8f9eac36234d87308cd81795101d7c0f963c814575b5d77fb9c8a5a1a55cddf6`。
正式new ELF SHA256为
`5848c381f680088609a2c62deb28790ce54790684ca88dd2e60161efdb2d8652`；
与old、镜像和NEMU一起在首次运行前写入预注册。测量完成前不更换二进制。

### F正式交替测量

| 顺序 | Host s | emu wall s | Make/emu exit | 精确100k终点与NEMU |
|---|---:|---:|---|---|
| old1 | 118.545 | 118.58 | 0/0 | PASS |
| new1 | 110.056 | 110.08 | 0/0 | PASS |
| old2 | 118.571 | 118.60 | 0/0 | PASS |
| new2 | 109.567 | 109.60 | 0/0 | PASS |
| old3 | 117.343 | 117.37 | 0/0 | PASS |
| new3 | 110.288 | 110.32 | 0/0 | PASS |

六次按原预注册执行，无INVALID或补跑，无并行编译、采样或诊断。每次终点都是
instrCnt240349、cycleCnt99996、IPC2.403586、guest100001、PC0x80000c0c；
harness cycles/max_cycles均100000，Difftest enabled且无mismatch。

old均值118.153000 s、样本SD0.701601 s；new均值109.970333 s、样本SD0.368055 s。
净少8.182667 s，按`1-mean(new)/mean(old)`降低6.925484%。全部new小于全部old，
max(new)110.288 < min(old)117.343，最近间隔7.055 s；Mann-Whitney U(new)=0，
3+3标签20种排列的单侧精确p=1/20=0.05，Cliff delta(new-old)=-1，
Cohen d(new-old)=-14.605987。emu wall均值old118.183333/new110.000000 s，与Host
口径一致。old3比前两次低约1.2 s，仍保持完全秩次分离；不删除漂移样本或使用
更好看的筛选8.249728%代替正式结果。该统计证明本配置本窗口的净收益，不证明
其他工作负载收益，也不把单次profile当作相位间独立因果实验。

按正式new均值计算，距gsim归档46.965 s仍高63.005333 s、为其2.341538倍。
gsim的instrCnt238550、cycleCnt99998、PC0x80000b40与IR对应终点不同，但沿用
既定各路线100k对拍通过的比较配置；没有重跑gsim，也没有用其旧窗口时间参与
本节点显著性检验。

### F独立诊断与剩余主要成本

正式测量结束后串行执行old、新完整构建的独立200Hz profile，各一次，CPU2、
100k、单线程、NEMU和相同截止不变，另开启runtime phase timing。两次均exit0、
精确终点通过，以下数据没有加入正式Host均值。

| 诊断指标 | old | F |
|---|---:|---:|
| Host / emu wall s | 118.697 / 118.74 | 109.221 / 109.26 |
| eval调用 / 总round | 200102 / 402258 | 200102 / 402258 |
| eval s | 118.295987 | 108.824618 |
| compute s | 89.643240 | 85.587425 |
| commit s | 26.859805 | 21.449732 |
| publish s | 1.650709 | 1.647505 |
| 总样本 | 23743 | 21846 |
| compute task样本 | 16304（68.668660%） | 15631（71.550856%） |
| commit task样本 | 4507（18.982437%） | 3343（15.302573%） |
| 通用direct-state通知样本 | 224（0.943436%） | 141（0.645427%） |

同一批语义求值的轮次没有变化；诊断commit少5.410073 s（20.14%），compute少
4.055815 s（4.52%），publish基本不变。与静态提交代码收缩共同支持：**大量
同控制bit仍以独立写口、活动位与通知执行，是已确认可消减的成本来源**。打包
不仅改变IR实体数，还让现有emit按word执行一份masked write，并减少提交侧
活动位扫描；compute的状态读取/活动传播也随新依赖重新组织。无法用这两次
诊断独立区分寄存器打包、history合并、分区变化和缓存效应的各自贡献；不将
诊断相位差值等同正式6.925484%的净收益分解。

新诊断compute约占eval时间78.65%，仍有2760个compute task被采样，最热10个
compute task仅632个样本（2.89%总样本）。热点依然分散；内存cell bool写337
样本（1.54%）、宽replicate259（1.19%）、通用bool pending写245（1.12%）
均不是解释剩余2.34倍差距的单独根因。后续应继续从成组依赖与执行粒度减少
分散compute和状态访问成本；避免把本次机制退化为重复微调64位分块参数。

诊断复现，在上述正式流程结束后执行：

```bash
make profile_grhsim_ir PYTHON=.venv/bin/python \
  GRHSIM_IR_PROFILE_FLOW="$old_flow" GRHSIM_IR_PROFILE_OUTPUT="$node_dir/profile-final-old" \
  GRHSIM_IR_PROFILE_BASELINE_SECONDS=118.631667
make profile_grhsim_ir PYTHON=.venv/bin/python \
  GRHSIM_IR_PROFILE_FLOW="$flow" GRHSIM_IR_PROFILE_OUTPUT="$node_dir/profile-final-new" \
  GRHSIM_IR_PROFILE_BASELINE_SECONDS=118.631667
```

`profile_grhsim_ir`通过Make的run目标设置`LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libprofiler.so`、
`CPUPROFILE_FREQUENCY=200`、`EMU_RUNTIME_PROFILE=1`、`EMU_PHASE_TIMING=1`，
再调用`analyze_grhsim_cpu_profile`检查ELF映射、task边界、终止记录和样本总数。
这些变量只作用于诊断子进程，正式benchmark显式清除采样变量并关闭phase timing。

## 最终判定与归档

F满足完整SV生成/fresh编译各低于1800 s、100k正确性和六次同窗交替秩次门槛，
本节点接受。A–E都仅是节点内REJECTED尝试，没有用失败或筛选代替节点完成。
保留的核心代码只有GrhSIM IR新pass与注册；没有保留A–E emitter改动。新pass
使用现有CPU scalar concat/read/slice/write机制改变发射行为，无新增宽helper
ABI，不修改冻结GRH、现有GRH pass、XiangShan或HDLBits源码，也不按名称选模块。

回归覆盖IR/mapping、schedule、生成模型ASan/UBSan和独立scoreboard/参考轨迹、
JSON fresh reload及幂等性、HDLBits086/097。测试程序是wolvrix新回归，基准测试
源保持原样。report、goal和index随代码集中提交；不提交生成代码、日志、profile、
波形、ELF或ptmp目录。子模块最终实现commit为
`2b320c9`（`feat: pack equivalent bit registers in grhsim ir`），根仓库随后提交
指针和全部档案。本次仅完成NO00032，不启动下一节点。

## 复现命令

根目录执行，生成与编译使用全新目录；old为NO00031归档目录，重建时使用上文
精确基线提交。这里给出完整流程参数，实际结果仅由后续实测表判定。

```bash
node_dir="$PWD/ptmp/no00032_state-read-views_20260915"
old_flow="$PWD/ptmp/no00031_sparse-active-dispatch_20260915/flow-predicates-final"
flow="$node_dir/flow-pack-final"
mkdir -p "$node_dir/work-tmp" "$node_dir/pip-cache"
mkdir "$flow"
export TMPDIR="$node_dir/work-tmp" PIP_CACHE_DIR="$node_dir/pip-cache"
export PATH="$PWD/.venv/bin:/home/gaoruihao/wksp:$PATH"
export WOLF_ENV_SOURCED=1 CMAKE_BUILD_PARALLEL_LEVEL=32 PYTHONDONTWRITEBYTECODE=1

timeout --signal=KILL 1800s /usr/bin/time -f 'wall=%e,exit=%x' \
  -o "$flow/generation.time" make --no-print-directory xs_wolf_grhsim_ir \
  PYTHON="$PWD/.venv/bin/python" XS_NUM_CORES=1 XS_RTL_BUILD=build/xs/rtl \
  XS_DIFFTEST_GEN_DIR=testcase/xiangshan/build/generated-src \
  XS_GRHSIM_IR_BUILD="$flow" XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR="$flow/model" \
  XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0 \
  XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0 \
  XS_WOLF_GRHSIM_IR_PACK_BIT_REGISTERS=1 \
  XS_LOG_DIR="$flow/logs" RUN_ID=no00032_pack_final_generate \
  >"$flow/generation.log" 2>&1

timeout --signal=KILL 1800s /usr/bin/time -f 'wall=%e,exit=%x' \
  -o "$flow/compile.time" make --no-print-directory xs_wolf_grhsim_ir_build_emu \
  PYTHON="$PWD/.venv/bin/python" XS_GRHSIM_IR_BUILD="$flow" \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR="$flow/model" \
  XS_DIFFTEST_GEN_DIR=testcase/xiangshan/build/generated-src \
  XS_NUM_CORES=1 XS_EMU_THREADS=1 EMU_THREADS=1 VM_BUILD_JOBS=32 \
  XS_LOG_DIR="$flow/logs" RUN_ID=no00032_pack_final_compile \
  >"$flow/compile.log" 2>&1

make --no-print-directory benchmark_grhsim_ir PYTHON="$PWD/.venv/bin/python" \
  GRHSIM_IR_BENCH_OLD="$old_flow" GRHSIM_IR_BENCH_NEW="$flow" \
  GRHSIM_IR_BENCH_OUTPUT="$node_dir/formal-f" GRHSIM_IR_BENCH_CPU=2 \
  GRHSIM_IR_BENCH_PAIRS=3 GRHSIM_IR_BENCH_BASELINE_SECONDS=118.631667 \
  >"$node_dir/formal-f.log" 2>&1
```

生成/编译包装器检查非零退出，失败时将整个flow移至独立`-incomplete`目录。
筛选将PAIRS改为1，使用独立`screen-f`目录，不加入正式六次。
benchmark工具预注册顺序、二进制/输入哈希，以`timeout --signal=KILL 177.947500s`
包住emu及其子进程；`/usr/bin/time`只测emu区间，Make墙钟另行记录。失败标记每
0.5秒检查；有效终点须为instrCnt240349、cycleCnt99996、guest100001、PC0x80000c0c、
harness100000 cycles/max_cycles100000，Difftest启用且无mismatch。
正式测量时不并行编译、采样或机器码分析。gsim沿用46.965 s归档，只作距离参照。

静态检查与聚焦验证：

```bash
make analyze_grhsim_state_reads PYTHON=.venv/bin/python \
  GRHSIM_STATE_READ_MODEL="$flow/xiangshan_grhsim_ir.json" \
  GRHSIM_STATE_READ_REFERENCE="$old_flow/xiangshan_grhsim_ir.json" \
  GRHSIM_STATE_READ_SUMMARY=1
make analyze_grhsim_cpu_code PYTHON=.venv/bin/python \
  GRHSIM_CPU_CODE_OLD="$old_flow" GRHSIM_CPU_CODE_NEW="$flow" \
  GRHSIM_CPU_CODE_PHASE_ONLY=1
make test_grhsim_cpu_mapping test_grhsim_cpu_emit test_grhsim_cpu_schedule
make run_hdlbits_grhsim_ir DUT=086 SKIP_PY_INSTALL=1 PYTHON=.venv/bin/python
make run_hdlbits_grhsim_ir DUT=097 SKIP_PY_INSTALL=1 PYTHON=.venv/bin/python
```

恢复检查点的筛选入口（只用于筛选，不替代完整SV）：

```bash
timeout --signal=KILL 1800s /usr/bin/time -f 'wall=%e,exit=%x' \
  -o "$node_dir/reemit-f.time" make --no-print-directory reemit_grhsim_ir \
  PYTHON="$PWD/.venv/bin/python" \
  GRHSIM_REEMIT_MODEL="$old_flow/xiangshan_grhsim_ir.json" \
  GRHSIM_REEMIT_FLOW="$node_dir/flow-pack-f-screen" \
  GRHSIM_REEMIT_PACK_BIT_REGISTERS=1 GRHSIM_REEMIT_CPU_TARGET_BATCH_COUNT=0 \
  >"$node_dir/reemit-f.log" 2>&1
```

首次F筛选安装由reemit目标的`py_install`完成；默认batch64的误配置版本已隔离，
0配置重生成使用`SKIP_PY_INSTALL=1`，因为生产库未变。最终完整生成重新经过
`py_install`。核心和生成代码使用Clang22.1.2，生成C++为`-std=c++20 -O3`；
保持同一旧/新Difftest harness、镜像、NEMU、CPU2及单线程配置。
