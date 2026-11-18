# F33：第二次 DCE 后至第三次 DCE 的功能与性能对齐计划

建立日期：2026-11-18。状态：**F33.1–3 已通过有界功能验证，F33.4 已完成首轮整图对照。F33.5 首轮正式采样完成，第三次 DCE 和连续窗口通过，ConstantAnalysis 超出正式门 0.956 秒。逐项功能归因与 F33.5–6 验收待完成。**

接续已按用户初步接受收尾的[F32](F32-post-dce-pass-alignment-plan.md#936-f32-按用户初步接受收尾2026-11-18)，
将新 SemanticTree / SemanticNode 与 `kCombArrayUpdate` 的支持推进到第三次 DCE。
遵循“先功能，后正式性能验收”；功能测试期间另有强制的 **GSIM 对应 pass 两倍耗时约束**。
一旦超过，终止该轮并先优化这个 pass，再恢复功能对齐，不能原地等待完成。

本文统一记录 F33 的范围、分步交付、测试与超时规则；index 和 steps 仅保留入口。
小例实施记录见§9，香山全图单样本与超时修复见§10，F33.4 首轮全图功能对照见§11，正式性能采样见§12。

## 1. 实施窗口与接受起点

### 1.1 已核实的实际 pass 顺序

```text
GRH：
  第二次 dead-code-elim（不含，只提供 Q0）
    → constant-analysis                 Q1
    → 第三次 dead-code-elim（包含）      Q2
  停止

GSIM：
  第二次 RemoveDeadNodes1（不含，只提供 Q0）
    → ConstantAnalysis                  Q1
    → 第三次 removeDeadNodes（包含）     Q2
  停止
```

**窗口内只有两个 pass**。`AliasAnalysis → PatternDetect → CommonExpr → 第四次 DCE`
都位于第三次 DCE 之后，不属于 F33；方言转换、分图、C++发射与整机仿真也不纳入。
不得为了旧完整flow测试通过而继续执行或开放这些 pass。

顺序依据为[GSIM main.cpp](../../reference/gsim/src/main.cpp)、
[GRH共用flow](../../scripts/grhsim_flow.py)与
[FIRRTL canonical pipeline](../../scripts/wolvrix_xs_grhsim.py)。
`Q0` 语义上接续 F32 的 `P4`，不是沿用旧捕获的版本标签。

### 1.2 版本、输入与继承项

规划起点：主仓库 `7548675a6fb3fcc9cc2d5949bf7bd5f1e5497c07`，
wolvrix `87aeeab95bee9e9c055ae3ba7e3bc38c583fbf1d`，
GSIM `f59b7d71e787e854de550a82b3937957b19ed7d8`。
沿用原始 `build/xs/rtl/rtl/SimTop.fir`，预期SHA-256为
`b313a3ecd154cbd9279b14403709806b95fb136cf44b475e9def46a926ecb26b`；
manifest沿用 `ptmp/semantic-bindings/F26/grh/ingest-request.json`。
实施开始重新校验实际文件、冻结包、依赖、构建配置及工作树身份。

语义继续采用显式 `semantics=2state`，X/Z按现行二值策略逐位解释为0；不通过
篡改原始类型或历史捕获标签实现。直接API原有四态行为兼容性另做回归，不把完整
四态证明加入本轮二值行为验收。

F32接受的是当前结果和性能，未宣称严格全图等价；其未配对Node、未归因删除量、
不完整source端点及U1/U2/U4原样继承，U3不属于当前二值行为门。
F33须在Q0建立这些继承项的实际清单，区分本窗口新增、传播、消失与未证事项。
不把重新通过F32全部历史正式门作为F33启动条件，也不把F32的人工接受当作F33通过。

Q0须从本次接受的F32实现冻结新包后实际生成，不能把package-v25的旧完整库存
重标为当前v31输入。Q0生产前缀包括ingest和F32四pass，只提供输入，单独记录耗时与失败原因。
F33的“两倍约束”及正式性能结论针对窗口内两个pass；不重新优化用户已接受的F32。
涉及前驱的新故障需单列，不能伪装成窗口内超时或自动更换前驱实现。

### 1.3 前驱修改和公共 DCE

本计划的实现范围为ConstantAnalysis、第三次DCE的必要支持、捕获/计时/比较工具和回归。
ingest、第一次/第二次DCE及其前面pass的语义修复仍须独立提出并收到明确批准。
U1/U2/U4没有因本计划自动获得批准。

第三次DCE与前两次共用实现。公共DCE、求值器或Graph helper改动若会改变窗口前
语义或Q0输出，先报告最小复现、建议补丁、影响和验证方法，不能借F33范围直接应用。
必要的性能优化须验证既有诊断/错误检查、Node维护和前态行为不变；不能通过
关闭验证、清空SemanticTree、删除来源、少跑retention或改可观察根来满足耗时约束。

## 2. 规划时核实的实现差距

以下为实施前基线，保留用于核对交付；当前能力和限制见§9，不再代表当前源码状态。

| 项目 | 当前源码情况 | F33工作 |
| --- | --- | --- |
| 支持gate | PassManager目前在修改前拒绝带新树或CombArrayUpdate的`constant-analysis` | 完成功能与负例后，只把支持边界推进到第三次DCE；后续pass继续拒绝 |
| GRH ConstantAnalysis | 普通未分区GRH按拓扑序折叠全部operand已知的纯表达式；无显式二值选项 | 定义二值求值、局部常量推导、状态/数组规则与对应GSIM覆盖；保留独立DCE |
| Node与来源 | 旧`makeConstant`合并operand/producer的SemanticIds；未证明适用于新叶Node合同 | 原位结果身份、真实owner、anchor、输入槽与binding逐项维护；不能把输入owner无条件变成输出owner |
| 组合数组更新 | foldable列表不含`kCombArrayUpdate` | 支持完整及局部可证明的有序更新/投影；保持shape、后写优先和索引/enable语义 |
| GSIM ConstantAnalysis | 除常量表达式外，还有条件简化、寄存器/复位和constantMemory传播，内部移除CONSTANT_NODE并重连 | 不能只做“所有operand常量”就宣称对齐；逐类建立适用能力/差异矩阵与证据 |
| 第三次DCE身份 | GSIM复用`RemoveDeadNodes`阶段名；第一次同名boundary会提前命中stop | 先建立唯一第三DCE事件、停止点与原生timer映射，禁止按字符串猜第几轮 |

实现依据：
[GRH constant_analysis.cpp](../../wolvrix/lib/transform/constant_analysis.cpp)、
[ConstantAnalysisOptions](../../wolvrix/include/transform/constant_analysis.hpp)、
[support gate](../../wolvrix/lib/core/transform.cpp)、
[GSIM constantNode.cpp](../../reference/gsim/src/constantNode.cpp)。
[F23.2](F23-constant-analysis.md)说明普通GRH旧基础，其测试不能替代本轮新树与新op验证。

GSIM在ConstantAnalysis内部移除已证明常量的Node，GRH原位改常量并等显式DCE回收
无用生产者，两端Q1库存不必相同。必须分别记账“常量替代/常量Node退休”与第三DCE
“不可达删除”，以真实值、状态及消费者证据比较，不能只比删除数量或名字比例。
GSIM当前exchange从allNodes收集并只过滤DEAD/SPLITTED，而`removeNodes(CONSTANT_NODE)`
移除的是执行集合成员；两者不能自动等同。F33.0须核对常量状态Node是否仍被导出，
分别记录活跃计算、已内联常量/来源目录与真正退休项，保持可核对的总数，不能
把脱离执行集合的常量记录算作待DCE活Node，也不能无记录地丢弃其来源身份。

## 3. 分阶段交付

| 阶段 | 交付 | 退出条件 |
| --- | --- | --- |
| **F33.0 冻结窗口和Q0** | 起点身份、原始输入、同语义Q0、三边界与两个pass唯一调用标识；继承项和支持矩阵 | Q0真实完整且可验证；第三DCE后停止；不执行AliasAnalysis等后续pass；无历史标签回填 |
| **F33.1 GSIM参考与两倍守卫** | 两个pass的有效GSIM参考、实时时限、失败证据与转优化流程、工具合同测试 | 原生pass尚未返回也能被终止；对应关系正确；缺参考拒绝启动配对功能轮；预算不可自动放宽 |
| **F33.2 组合常量与Node维护** | 二值选项、纯表达式/局部推导、有序CombArrayUpdate与来源/身份维护 | 无树/新树、新op/普通op矩阵及独立oracle通过；无隐式DCE；配对功能轮均未超过2倍 |
| **F33.3 状态、memory与效果** | GSIM对应寄存器/复位、数组与memory常量规则；状态/外部边界反例 | 初值、更新、保持、reset/clock、读写语义证据完整；不安全情形不折叠；能力差异逐项记录 |
| **F33.4 第三DCE与全图功能对照** | Q0→Q1→Q2流水、DCE回收、双端三界全量库存与分步差异台账 | 结构/Node/槽位合法；局部前后值及适用状态oracle通过；新增行为/生命周期差异有结论，未知项明确保留；功能期2倍门满足 |
| **F33.5 正式性能优化与验收** | 功能冻结版本、串行交错双端样本；两个pass及连续窗口统计 | 按§6独立判断三个正式门，不用2倍功能门替代，不混包或隐藏失败 |
| **F33.6 文档与收尾** | 版本、支持矩阵、功能/性能数据、限制、前驱审核与证据目录 | 如实列明各门；未通过保持未完成，或另有用户明确接受范围；不推定接受 |

正常顺序为0→1→2→3→4→5→6。**阶段2–4任一配对功能轮触发2倍门时，立即
插入该pass的性能定位与优化，再返回原功能阶段**；不用等所有功能完成才处理超时。
这属于保证功能测试可推进的性能修复，阶段5仍保留最终正式性能收敛。
每步结束更新本文的实际证据，不以设计完成或编译通过代替退出条件。
正常功能验收要求支持矩阵内独立oracle、结构与生命周期检查通过，无已知反例，
且本窗口新增差异有逐项证据结论；新增unknown不能因已列出就算解决。不能完成
的功能类别或全量证据须明确保持未完成，缩小验收范围需用户另行接受。

## 4. 功能对齐与测试内容

### 4.1 常量和局部推导

- 整数算术、比较、逻辑/归约、signed扩展、截断、移位、concat/slice、零宽及宽于64位。
  检查结果位宽、符号、shape与二值模运算；除零、模零、越界及未定义表达式先明确
  当前运行语义，不能只照搬参考端结果或依赖宿主未定义行为。
- 全常量链、常量选择器Mux带动态未选臂、`x & 0`、`x | 全1`、不可达条件及其他
  GSIM实际支持的局部推导。区分纯值分支和共享的有副作用生产者，不能误删效果。
- `kArrayCreate`、静态/动态读、二维以上shape、整数组/后缀写，以及有序组合更新。
  用带不同元素值的例子检查同址/重叠后写、恒真/恒假enable、动态索引与部分常量区域。
  例：`r=update(base, e=1,i=1,data=7; e=1,i=1,data=9)`的第二组覆盖第一组，
  `r[1]`可证明为9；不能据此把其余仍来自动态base的元素也常量化。
- 二值入口须在正确求值步骤对X/Z清零，而不是先四态运算再只清零结果；测试混合
  known/X/Z literal、常量控制/索引和原始FourState类型标签。四态兼容路径单独保留。

### 4.2 状态、memory与外部效果

状态能否替代为常量需要可观察执行轨迹上的证据，不能仅凭“写入值恒定”。覆盖
初值不同、首拍前读、条件写/保持、自反馈、多个有序writer、同步/异步复位、不同
clock/event、reset优先级和数组逐元素更新。区分CURRENT、NEXT与writer-data。

memory覆盖初始化、read latency/enable、mask、同址读写、多个port与动态地址。
“所有写口写相同常量”不自动证明从初始化开始所有读都为该常量。外部接口、DPI、
assert/printf/exit、sampled system function及纯函数必须区分；不可观察性由显式
第三DCE处理，不能以ConstantAnalysis的局部常量事实吞掉外部效果或clock/reset。
尚无证明的优化保持原图并报告差异，不能称为该类全面支持。

### 4.3 Node、来源与DCE回收

原位改写保留仍表示同一结果的Node/operation/value身份及名字；绑定变化必须跟随
真实operand/result、状态和source projection，不从同名或相同常量猜来源。
记录每次常量替代后删除的输入依赖与保留的source事实；已无用户的旧物理行可等
第三DCE回收，不为使reader通过提前清扫，也不把它们继续导为活动依赖。

第三DCE逐项核对root、活op/value、Node成员/anchor/binding、恒定输出、状态/效果
与零宽边界。新增/退休项有原因和去向；GSIM已常量替代的Node需要查其消费者
是否内联常量，不能仅因Q1缺名字判作漏项。

每个支持类别至少有区分度的正/反例；包含重复operand、多结果producer、深DAG、
高扇出、共享常量及多个逻辑owner，防止错误拓扑递减、递归栈溢出与owner扩散。
复用独立整数/数组/事件oracle，补穷举或有界多周期检查，不能以两个实现互相一致
代替独立预期。退化规模检查按访问量/重算次数约束，并同样受可比pass的2倍门保护。

### 4.4 三边界全图证据

Q0/Q1/Q2分别保存实际Node、完整类型、真实连接与槽位、常量状态/位图、source投影、
split lineage的保留情况、状态/外部效果及原生ID映射。每界校验完整footer/hash、
结构/Node不变式，并单列未解析端点。比较Q0→Q1和Q1→Q2，统计：

| 指标 | 解释 |
| --- | --- |
| 常量替代/表达式简化 | 本pass实际改写与其前后值证据，含Node内联/退休 |
| 第三DCE删除集合 | 两端各自Q1→Q2消失项及可观察根证据，不只相减总数 |
| 同名候选、类型、连接差异 | 用于定位，名称比例不称为语义通过率 |
| 继承/新增/传播/消失项 | Q0已有缺口独立保留，不能按新child/key重复算根因 |
| 功能结论 | 已证明、已复现反例、策略差异、证据不足分别记录；不把unknown当通过 |

F32的全量库存/索引规模大，规划时磁盘约余60GiB。实施阶段0先估算三界capture、
索引、临时SQLite与失败保留的峰值空间，再确定执行路径；不得直接复制三份大库
或启动超出空间的完整索引。可复用身份一致的不可变索引/流式库存，精确记录复用
范围；结构有界抽样只支持局部结论。空间不足先完成有界功能证据并报告全量缺口，
不删F32已接受结果的原始证据，也不假称全图对照已完成。

## 5. 功能期的强制两倍耗时约束

### 5.1 参考与预算

对每个可比fixture/规模/配置，在GRH配对功能轮前取得对应GSIM参考：同源输入、
同窗口起止、二值解释、CPU/线程、构建类型、Node维护配置及冻结版本；两端各走
自身已记录前缀，不能要求两种IR的物理图完全相同。先串行运行3个有效GSIM样本，
取相应pass原生wall time的中位数`R(p)`，锁定：

```text
B(p) = 2 × R(p)
p = ConstantAnalysis 或第三次DCE
```

`R(p)`与`B(p)`必须有限且严格大于0。计时分辨率产生零值时转入下述独立新图
校准batch，不能生成零预算、关闭守卫或以任意常数代替参考。

两个pass分别设预算，不用总和掩盖某个pass超时；也不能套用第二次DCE、F32其他
pass或另一个fixture的历史耗时。参考记录输入/配置/hash、3个原始timer与中位数。
失败、超时、显著资源干扰或不完整timer不进入有效参考。缺参考或身份不匹配时
先补GSIM参考，不能无期限启动GRH配对功能轮。
参考样本也检查`max(3%×中位数, 10ms)`抖动带；超出时先定位环境/测量问题，
不能挑最慢样本或改用更慢版本来增大预算。

小例若短到无法稳定计量，使用同样数量的**独立新图**执行同一pass组成校准batch，
图构造放在计时外，双端按相同batch口径比较；不得重复折叠已变成常量的图。
不得擅加`max(1秒, 2×R)`、沿用180秒固定上限或取更慢参考来放宽两倍要求。
无GSIM对应操作的GRH API负例使用独立测试时限，并标为不可配对项，不冒充2倍门已通过。

### 5.2 实时终止和计时边界

外部supervisor在调用真正开始前取得唯一pass开始事件和monotonic时间，从该次
调用起持续监控。计时包含生产必需的验证、Node/binding/retention、重连和维护；
不包含ingest/窗口前缀、图构造、JSON/TSV导出、跨端比较与profile装卸。
功能oracle和独立导出校验另记时间，不把它们混进对应pass参考。

**运行中已消耗时间达到预算仍未完成，即请求终止该私有进程组**；不等待C++返回、
Python GIL释放或最终timing文件出现。先原子写入超时触发证据，再SIGTERM，
短暂清理宽限后必要时SIGKILL；清理延迟和轮询误差单独记录，不能计作预算加成。
若在采样间隙完成但最终原生耗时`T(p)>B(p)`，仍判为功能期性能阻塞并转优化。
已完成且耗时等于预算不判为超限。

开始/结束事件含run、engine、输入边界、logical pass occurrence和时间。开始后
进度文件暂缺/写坏不能重置计时或关闭deadline；没有可靠结束事件不发布成功边界。
pass结束立即退出该阶段预算，后续慢导出不误判为该pass超时；监控器故障单列失败。
deadline检查的观察延迟上限为250ms，短校准batch使用更短deadline计时；不能只在
可能阻塞的资源采样完成后才检查。资源采样/进度读取须有界或与deadline独立，
记录实际终止请求时间及预算外延迟，不让文件I/O或采样卡住后继续无限运行pass。

RSS/PSI、prefix和导出/比较的有界运行时限独立保留。沿用F32的96GiB RSS、
PSI25%持续8秒作为初始资源守卫，明确其不是硬内存隔离；资源失败不冒充2倍失败。
GSIM自身基线采集也有独立运行时限，参考端卡住时不反过来放宽GRH预算。

### 5.3 超时后的工作顺序

```text
功能轮进入pass
  ├─ 完成且 T ≤ 2R → 校验当前边界，继续功能阶段
  └─ 未完成达到2R，或完成后 T > 2R
       → 保存触发/资源/已完成边界，终止并判该轮未通过
       → 定位该pass热点或复杂度，实施性能优化
       → 跑受影响小例、Node与公共helper回归
       → 从同一有效输入边界重试该功能轮
       → 回到2倍内后继续原功能工作
```

超时图可能已经部分修改，只能作失败诊断，不能当Q1/Q2、合法checkpoint或通过
样本；保留最后完整边界和原始失败记录。不得无改动反复重跑同一个超时，也不得
把预算调大等它结束。若采样profile需要更大开销，必须另起标记清楚且有界的诊断
流程，保留原2倍门失败，不用于替代功能通过或重写阈值。

性能修复优先检查拓扑/固定点重算、重复全图扫描、宽常量复制、Node映射和批量
重连等真实热点。新helper先检查已有实现的数据移动/别名策略；仍遵守项目的
caller提供buffer等约定，不凭接口形式猜收益。每次改动保持功能合同，不能跳过
必要工作满足时限。优化会影响前驱时按§1.3单列审核。

### 5.4 守卫与调用身份必须先验证

当前GSIM第二次DCE原生标签为`RemoveDeadNodes1#0`；第三次复用名称，现状原生
timer对应`RemoveDeadNodes#1`，不能与第一轮`RemoveDeadNodes#0`混配。
`--stop-after-stage=RemoveDeadNodes`会先命中第一轮，因此F33提供明确的第三次
DCE boundary/stop标识`RemoveDeadNodes2`，同时保留旧原生标签与逻辑序号
的映射。GRH整体逻辑身份是`dead-code-elim#2`；分次run_pass原生序号可能重置，
必须以逻辑调用表绑定，不能只按原生`#0`判断轮次。

可复用[F30 PhaseDeadline与进程组清理](../../scripts/f30_resource_guard.py)、
[F32 capture进度/身份](../../scripts/capture_f32_pipeline.py)与原生timer基础；
不能直接复制F32仅针对SplitNodes的固定180秒deadline。
专项至少验证：运行中终止、2倍边界与完成后超限、重复DCE映射、快照耗时不误杀、
事件缺失不关闭deadline、缺/错参考拒绝、私有helper清理、失败证据不覆盖、
Q2后零次调用AliasAnalysis。只有通过这些合同测试后才开始大图功能运行。

## 6. 功能通过后的正式性能验收

功能期两倍门是中断与转优化条件，**不是最终性能目标**。正式验收沿用现有默认
GSIM对齐口径；F32的性能接受只适用于F32，不自动放宽F33：

```text
median(GRH,p) ≤ median(GSIM,p) + max(0.03 × median(GSIM,p), 0.010秒)
p ∈ {ConstantAnalysis, 第三次DCE, 连续两pass窗口}
```

每端至少3个新鲜有效样本，同机固定CPU/线程/配置/输入，串行交错运行，冻结同一
候选实现，不跨包拼接结果。原生两个pass各测，连续窗口另测；窗口从Q0后的第一
调用前到第三DCE返回，包含调用间生产框架/维护，不能只把两个原生timer相加。
prefix单列且不进入窗口；不带trace、export、外部oracle或profiler。
保留必需的生产验证与Node/binding/retention成本。

样本抖动带按`max(3%×中位数, 10ms)`检查；高抖动、资源失败和超时全部保留并
明确判无效，不用减少样本数或加宽门绕过。配置变更/源码修复后重新冻结并收集
完整组。功能期2倍deadline继续作为外层保护，不能因进入正式阶段而无限等待。
未达到默认正式门时继续性能优化，或另行向用户报告实测差距并取得明确接受。

## 7. 工作流、产物与文档

所有build/test/install/Python工作流经项目Make目标执行；缺目标先补目标。
已增加`f33_gsim_build`、`test_f33_passes`、`test_f33_guard`、
`test_f33_capture_contract`和`capture_f33_pipeline`；capture的`--mode=reference`
取得GSIM参考，`--mode=capture --engine=grh --reference=...`执行配对功能轮。
正式性能入口为 `benchmark_f33_performance` 和 `compare_f33_performance`，
比较器合同由 `test_f33_performance_contract` 验证。复用F32工具时保持旧合同与回归，不把F32退出点静默
改为第三DCE。临时日志/冻结包/失败产物统一写`ptmp/firrtl-ingest/F33/`，不提交
生成产物，不写仓库外临时目录。

原生fixture和测试放`wolvrix/tests/transform/`及其data；GSIM小例放其test目录。
实现文档更新`wolvrix/docs/transform/grhsim-transforms.md`及GRH/source相关合同，
并同步主流程支持gate、入口参数和三界停止点。本文持续更新实施和接受记录，
不另立互相矛盾的F33状态文档。

每轮产物至少含：

- manifest：输入/依赖/源码/包/构建/CPU/语义身份，Q0来源与继承项。
- reference：两pass的GSIM原始样本、中位数、2倍预算及映射。
- run：pass开始/结束事件、原生timer、资源采样、guard、成功或失败原因。
- Q0/Q1/Q2：完整边界清单、hash、验证结果、Node转换与差异台账。
- report：功能证据覆盖与未证项、性能三门、已知问题和独立批准记录。

收尾区分实现支持、局部oracle、全量库存对应、逐项差异解释与严格行为证明。
不以同名率代替功能结论，不把继承未知项补写为已证，也不把功能期未超2倍写成
正式性能通过。前驱问题、资源/空间限制和失败保留；不默认清理前阶段冻结证据。

## 8. 本次规划记录

2026-11-18已核对两端主入口、ConstantAnalysis实现、support gate与现有deadline。
F33只覆盖ConstantAnalysis和第三次DCE，分7步推进；功能期逐pass两倍守卫在
功能实施前交付，超限立即转该pass优化，功能收敛后再做正式性能验收。
规划当次未实施或测量；随后F33.1–3实施记录见下节，不回填或改写原始失败证据。

## 9. F33.1–3实施记录（2026-11-18）

### 9.1 当前范围与状态

已实现ConstantAnalysis的新Node/组合数组支持、显式二值选项、初始化状态归纳、
Q0/Q1/Q2捕获、GSIM三样本参考和运行中两倍守卫。生产flow支持推进到第三次DCE；
带新树/新op时AliasAnalysis等后继仍拒绝，未借本轮开启后端。

当前证据是有界fixture和工具合同；F33.1–3已实现，功能、对应fixture两倍门及最终
安装API/flow专项复核均通过，最终有界审计未发现该支持矩阵内的具体剩余阻塞。实际
GRH小例配对曾在第三DCE触发两倍门，已按要求
停止原功能轮并实施原生校准批次入口；匹配新冻结包的组合与状态/memory配对均完成
Q2并回到两倍内。F33.0的完整香山Q0及继承项清单尚未建立；F33.4全图Node/差异
台账、F33.5正式三门和F33.6最终接受均不由这些小例推定通过。

F32接受起点和U1/U2/U4限制沿用§1，未重标旧capture，也未修改ingest或前驱语义。
当前候选冻结为`ptmp/firrtl-ingest/F33/candidate-v4/package`，实际源码、依赖、原生
库和构建身份以该目录`identity.json`及各轮`prepared.json`为准；不能用目录版本名
替代hash核对。参考同时绑定两端实际身份，包或二进制改变后重新取得匹配参考。

### 9.2 实现能力与保留限制

| 类别 | 已实现及直接证据 | 当前限制或GSIM策略差异 |
| --- | --- | --- |
| 纯表达式与二值解释 | 拓扑常量链、算术/比较/逻辑/移位/拼接/切片，signed及129-bit例；X/Z在求值入口逐位清零，原始类型保留；默认API四态路径保留 | 除零/模零保持原图；不采用GSIM宿主未定义行为作为oracle |
| 局部事实 | 恒定selector/equal-arm Mux、and-zero、or-ones、二值multiply-zero、无符号小于0等；宽度/符号负例 | 选择动态臂要求结果宽度/domain一致；未证明的关系或相关索引保持动态 |
| 有序组合数组 | 全量及局部区间事实、后写优先、静态/后缀写、动态索引保守失效；独立有界数组oracle | 动态/相关写不据名称或相同常量猜测；不能因一个投影为常量就常量化其余动态元素 |
| Node与来源 | 原位op/value身份、精确owner和source绑定、选中槽保留，多owner/多结果与FourState部分事实回归；CA不删除op/value | GSIM在CA内部移除执行集合的常量Node，GRH等显式DCE回收；Q1物理数量无需相同，完整跨端归因留F33.4 |
| scalar状态/reset | 从初始化建立归纳不变量、禁用/保持/反馈、不同clock/event及多writer；前边沿/后边沿独立oracle和reset优先级负例 | 必须初值已证明且每个writer保持该初值；只因reset或写payload相同不折叠初值不同的状态 |
| array/memory状态 | 非均匀packed/ranged-fill初始化、动态/静态后缀写、mask、FIRRTL memory-tag数组；多写口同/异址、重叠/互斥mask正负例 | 采用whole-storage证明；一行变化会使整体失去证明，不保证推断其余恒定行；未推断跨writer必然覆盖的机会 |
| 初始化/读语义 | 二值已知Constant/Fill、read-enable及latency pipeline负例；实际FIRRTL十步状态/memory oracle | random/readmem/未覆盖行保持；GSIM constantMemory仅看相同写payload的策略不能替代从初始化开始的轨迹证明 |
| 效果与边界 | sampled time、外部效果、声明及writer保留；纯clog2可折叠；共享多结果效果生产者保留 | 不执行未知外部调用，不以CA代替DCE；未lower的原始memory op不在状态helper支持范围 |

GSIM的F33 snapshot新增`execution-membership.tsv`，明确区分`active_computation`、
`inline_constant_source`、`source_catalog`。捕获器以流式方式核对原生Node ID、
标志/分类及footer计数，避免把仅退出执行集合的常量来源记录当作DCE活Node。
这些库存合法性检查不等于全图行为等价证明。

### 9.3 两倍守卫与独立新图校准

新增`f33_guard.py`和`capture_f33_pipeline.py`。参考至少三个完整GSIM样本；核对
实际input/manifest/source/配置/两端冻结native及原始timer、event、guard hash后，
按每个逻辑pass分别锁定正有限的median×2，不设秒数下限。缺/错参考拒绝GRH启动。
第三DCE唯一stage/stop为`RemoveDeadNodes2`，保留原生timer`RemoveDeadNodes#1`，
对应GRH逻辑`dead-code-elim#2`，不会误配首轮或第二轮DCE。

外部supervisor独立于native/GIL，锁存monotonic开始事件；结束前文件缺失/损坏不能
清空deadline。event读取与资源采样各用独立监控进程，通过匿名pipe通信，父进程
非阻塞有界读取；资源采样/诊断写入卡住不阻塞deadline。默认10ms轮询，短预算
自适应缩短；触发记录实际观察延迟。先写失败证据，再TERM、短宽限后KILL私有
进程组及helper。完成后原生耗时仍大于预算也归`performance-blocked/optimize-pass`；
慢snapshot不计入pass，prefix、导出和overall另有上限，失败/部分边界不作checkpoint。

小例通过显式`--batch-count=N`使用1..256个独立新图。两端全部构造并运行前缀到Q0
后才开始窗口。GSIM为每图独立fork worker；aggregate loop包含实际串行调度/IPC，
snapshot在end之后只导出第一个图并标为代表，绝不重复折叠同一图。
GRH先前Python逐图run_pass造成计时文件/API开销，已增加私有原生
`_run_pass_batch`：预编译选项、准备每图正常PassManager后发native start，再逐图
调用原有manager，end后一次写aggregate timer；生产验证、retention、Node维护均保留。
该入口同时支持N=1，Python参数错误不会被native开始事件误标为pass运行。

初始Unix域socket传输被沙箱拒绝后，两端已改为普通匿名pipe；当前工具合同和真实
GSIM三样本运行均在沙箱内完成。无需为本流程重复无沙箱运行。

### 9.4 已执行验证与失败保留

| 证据目录（均在`ptmp/firrtl-ingest/F33/`） | 结果与可支持结论 |
| --- | --- |
| `native-v6/tests/test.log` | 3/3通过，0.07s：组合/Node、状态/memory及真实FIRRTL pipeline；包含前后独立整数/数组/event oracle、多个writer/mask与reset优先级负例 |
| `regression-v2/tests/test.log` | 最终既有F32/transform/ingest联合20/20通过，4.81s，覆盖当前普通action/批次公共配置；不是重新进行F32正式性能验收。旧v1 20/20记录保留 |
| `sandbox-tools-v2/tool-tests/guard.log` | 21/21通过：运行中终止、精确阈值、完成后超限、损坏事件、采样卡住、private group清理、不可覆盖证据及pipe半帧/短写/积压合同 |
| `sandbox-tools-v6/tool-tests/capture.log` | 12/12通过，0.078s：Q0/Q1/Q2停止点、独立新图batch、配置、membership、实际Python参数映射及native batch接入合同；包含正常info诊断在aggregate action之前的结果解析 |
| `smoke-ref-v5/reference.json` | candidate-v4对应三次GSIM batch16参考通过；仅`f32-pipeline.fir`，不是香山全图 |
| `smoke-grh-v4/summary.json`、`guard.json` | 同身份GRH batch16完整Q2，resource_interference=false；两pass均在对应2倍内 |
| `state-ref-v1/reference.json`、`state-grh-v1/summary.json`、`guard.json` | 真实状态/memory fixture三次GSIM参考及GRH完整Q2，resource_interference=false；两pass均在对应2倍内 |
| `sandbox-tools-v7/tool-tests/native-batch.log` | 实际已安装native batch API 6/6通过，0.006s；参数/预检、独立Session和原生事件/计时合同 |
| `flow-v1/tool-tests/flow.log` | 生产flow专项2/2通过，0.001s；窗口和支持边界保持明确 |

真实FIRRTL测试采用`f33-state-memory.fir`，node_annotations开/关均通过接受的前缀，
确认Q0仍有6个state、2个FIRRTL memory、1个pipeline state，包含2个memory和2个
其他初始化证明候选。十步trace独立要求
scalar/arrayValue/asyncValue/delayedValue始终为0，changingValue依次为
`[0,0,0,5,5,9,9,9,9,255]`；检查CA原位常量化、声明/writer/效果保留、op/value数量
与Node/source绑定不丢失，并检查后继AliasAnalysis仍拒绝。该局部oracle不是整机证明。

状态配对Q0/Q1/Q2的Node数为24/24/12，仅作为有界代表snapshot证据。Q1的`fixed`
保留同一op/value身份改为常量，`changing`和地址pipeline仍为register read，memory
声明保留；这与CA不隐式DCE、后续显式DCE独立回收的分工一致。这里未导出完整物理
结构，数值/事件轨迹来自上述独立native oracle，不冒充F33.4全图对账。

当前两个fixture的锁定参考如下，单位ms；这些是功能期保护阈值，不能称正式性能门：

| 输入/配置 | CA GSIM median | CA 2倍预算 | 第三DCE GSIM median | 第三DCE 2倍预算 |
| --- | ---: | ---: | ---: | ---: |
| `f32-pipeline.fir`、batch16、`smoke-ref-v5` | 0.623896 | 1.247792 | 0.215172 | 0.430344 |
| `f33-state-memory.fir`、batch16、`state-ref-v1` | 0.994960 | 1.989920 | 0.344995 | 0.689990 |

| 对应有效GRH配对 | ConstantAnalysis（ms） | 第三DCE（ms） | 功能期两倍门 |
| --- | --- | --- | --- |
| `smoke-grh-v4` | 0.151513 | 0.190877 | 两pass通过 |
| `state-grh-v1` | 0.934296 | 0.382265 | 两pass通过 |

历史失败保持原样：`smoke-grh-v1`在native dispatch前遇Python参数映射TypeError，
不能作为native性能测量，已修复mapping并补实际安装API回归；`smoke-grh-v2`的CA
为0.945168ms、预算1.301810ms，第三DCE实际aggregate为0.839463ms、预算0.450920ms，
超出0.388543ms（约86.17%）后停止该轮，定位逐图Python调度/计时文件开销并实施上述
native批次优化，重新冻结和取得匹配参考；`smoke-grh-v3`在正常info诊断的
结果解析失败，仅有CA native完成，不作有效checkpoint。当前v4修复解析后完整通过，
没有把旧失败转写为成功或用更大门限覆盖。上述小例耗时不是正式性能结论。

两端原始SHA、3个native计时、冻结build/库配置及events均在对应reference/summary中。
输入SHA分别为`04d6d555a6b37b393845d278bfd19cb5ceb032bfa756ea09d609e5bfbcbab568`和
`ee1ed405ec0c50c0ca11e94410786fa225a6ed48b656a77bfd1e27d1e782e1f7`，不套用到其他输入。

### 9.5 小例阶段退出结论与后续范围

F33.1–3在§9.2已实现支持矩阵及有界fixture范围内完成实现和验证：独立oracle、
Node/来源/效果维护、真实Q0状态候选、两组实际配对与两倍门、安装API/flow合同和
最终既有回归均通过；最终有界审计未发现具体剩余阻塞。保守未优化机会与GSIM
初始化策略差异仍按表保留，不将其扩写为全面优化或严格行为等价。

后续新fixture仍须取得同身份参考，若触发两倍门继续先优化触发pass，不增加预算。
本阶段以fixture为限。后续香山全图执行记录见§10。

## 10. 香山全图单样本与 ConstantAnalysis 超时修复

使用同一份原始 `SimTop.fir`、F26 manifest 和二值语义。按用户指定用一份有效
GSIM 样本设定本次两倍门。GSIM 首次在 Q0 导出阶段触发 96 GiB RSS 守卫，
随后两端采用 F32 全图使用过的 144 GiB RSS 上限。GRH 初测在 ConstantAnalysis
的 139.241 秒上限仍未返回，守卫保留完整 Q0 后终止。
[初测终止记录](../../ptmp/firrtl-ingest/F33/xs-pre-f33-4-v1/grh/guard-trigger.json)

冻结原版的有界采样诊断用时 157.253 秒。状态证明入口、求值、值缓存重哈希与
证明对象析构合计占约 43% 的独占 CPU 样本。修复将状态证明的值缓存改为按图内
值索引访问，单独存放已知位值，并复用求值栈。组合传播保留首轮拓扑扫图，
后续按原拓扑顺序重算受新常量状态读取影响的消费者。两处都保留原有证明规则、
验证和节点维护。新增回归覆盖先证明 A、再由 `A & dynamic` 折叠后证明 B 的链条。
[采样报告](../../ptmp/firrtl-ingest/F33/ca-timeout/baseline/profile/self.txt)
[原生回归](../../ptmp/firrtl-ingest/F33/ca-timeout/tests-final/tests/test.log)

| Pass | GSIM 单样本 | 两倍上限 | 修复后 GRH | GRH / GSIM |
| --- | ---: | ---: | ---: | ---: |
| ConstantAnalysis | 69.620 s | 139.241 s | 75.546 s | 1.085× |
| 第三次 DCE | 38.748 s | 77.497 s | 23.877 s | 0.616× |

复测重新冻结 GRH 包，并核对原 GSIM 样本的输入、构建和运行配置身份。
两项均通过本次单样本守卫，Q0/Q1/Q2 快照均完成 SemanticTree 与产物校验。
GRH 三界分别有 5,625,297、5,625,297、4,803,303 个 Node。初测 Q0 中
5,604,205 个 GRH Node 在 GSIM 有唯一同名候选，占 99.62505091%。
GSIM 记录的 897,273 个内联常量是退出执行集合的 Node，GRH 的诊断计数以操作
为单位。独立诊断确认优化前后均折叠 1,858,258 个组合操作、简化 22,114 个分支，
并折叠 14,841 个状态读取。两端的实际分析覆盖差异仍需结合节点与消费者证据核对。
F33.4 的全量差异台账与 §6 的正式性能验收待执行。
[优化前诊断](../../ptmp/firrtl-ingest/F33/ca-timeout/baseline/summary.json)
[优化后诊断](../../ptmp/firrtl-ingest/F33/ca-timeout/candidate-counts/summary.json)
[节点统计](../../ptmp/firrtl-ingest/F33/xs-pre-f33-4-v1/node-correspondence/summary.json)
[复测快照与计时](../../ptmp/firrtl-ingest/F33/ca-timeout/grh-retest/summary.json)
[复测守卫](../../ptmp/firrtl-ingest/F33/ca-timeout/grh-retest/guard.json)

## 11. F33.4 首轮全图功能对照

本轮扩展 ConstantAnalysis 的局部规则。相同位宽且位图相同的两个常量 mux
分支可原位折叠，保留二值和四态各自的常量语义。二值条件下，类型一致的
`x | 0`、`x & 全1` 和一位无符号 `mux(c, 1, 0)` 可原位改写为
赋值，重用现有来源槽迁移和第三次 DCE。小例验证了宽度不一致、四态限制、
来源槽迁移和独立值预期。独立 DCE 小例验证常量 mux 保留输出 Node，
同时回收三个失去用途的输入 Node。
[回归日志](../../ptmp/firrtl-ingest/F33/f33-4-rules/validation-final/tests/test.log)

用相同的香山输入、构建配置和 GSIM 单样本完成 Q0–Q2 捕获。去掉每轮的
快照身份头后，新旧 GRH 的 Q0 节点、连接、端点和位区间表逐字节一致。
新 GRH 的 Q0→Q1 节点库存也逐字节一致。第三次 DCE 删除了
1,009,108 个 GRH Node，占 Q0 的 17.94%，比改动前多回收 187,114 个。
新旧 Q2 的全量路径集合比较确认只有路径消失，新增为零。
[节点差量](../../ptmp/firrtl-ingest/F33/f33-4-rules/delta/summary.json)

| 全图库存 | Q0 | Q1 | Q2 | 第三次 DCE 删除 |
| --- | ---: | ---: | ---: | ---: |
| 改动前 GRH | 5,625,297 | 5,625,297 | 4,803,303 | 821,994 |
| 改动后 GRH | 5,625,297 | 5,625,297 | 4,616,189 | 1,009,108 |
| GSIM | 5,922,045 | 5,922,045 | 5,775,134 | 146,911 |

GSIM Q2 的 5,775,134 个库存 Node 包含 4,877,861 个执行成员和 897,273 个
内联常量记录。GRH 新增回收的路径中，168,801 个在 GSIM Q2 对应内联常量，
4,670 个对应 GSIM 第三次 DCE 删除项，13,375 个仍在 GSIM Q2 执行集合，
268 个在 GSIM 三界均无同名候选。GRH Q2 剩余 4,616,189 个 Node，其中
4,596,538 个在 GSIM Q2 有唯一同名候选，占 99.5743%。GSIM 执行集合差异
及来源、消费者的逐项归因仍待核对。
[基线生命周期](../../ptmp/firrtl-ingest/F33/f33-4-inventory/lifecycle.json)
[新增回收路径](../../ptmp/firrtl-ingest/F33/f33-4-rules/delta/disappeared.tsv)

香山 ICache 的 `dataArray.io.write.req.bits.entries.padding_0` 在旧 GRH 的
Q1 对应一位 mux。新 GRH 在 Q1 保留同一个 op/value 并改为常量，Q2 回收该
节点。该路径在 GSIM Q2 对应内联常量记录。
[改动前端点](../../ptmp/firrtl-ingest/F33/ca-timeout/grh-retest/Q1/node-endpoints.tsv)
[改动后端点](../../ptmp/firrtl-ingest/F33/f33-4-rules/grh/Q1/node-endpoints.tsv)

GRH 的 ConstantAnalysis 为 74.169 秒，第三次 DCE 为 23.256 秒，分别是
GSIM 单样本的 1.065 倍和 0.600 倍。两项均通过单样本两倍守卫，三界
SemanticTree 与库存产物校验通过。§6 的正式性能验收待执行。
[复测记录](../../ptmp/firrtl-ingest/F33/f33-4-rules/grh/summary.json)
[复测守卫](../../ptmp/firrtl-ingest/F33/f33-4-rules/grh/guard.json)

### 11.1 恒不触发 FIRRTL assert 的第三次 DCE 复测

FIRRTL lowering 现在分别标记 `assert`、`assume`、`cover` 和 intrinsic。新增的
DCE 选项默认关闭，只在 F33 pipeline 的第三次 DCE 开启；它跳过使能位已由
ConstantAnalysis 证明为一位无符号零的 FIRRTL assert 根。小例覆盖了默认保留、
恒禁用 assert 回收，以及动态 assert、assume、intrinsic 保留。
[专项测试](../../ptmp/firrtl-ingest/F33/assert-prune/tests/validation-driver.log)
[lowering 测试](../../ptmp/firrtl-ingest/F33/assert-prune/tests/firrtl-effects.log)

对相同香山输入进行一次 GSIM 单样本和一次有效 GRH Q0–Q2 捕获。首个 GRH
尝试遇到用户级 cgroup 内存压力守卫后中止，未计入结果；保留在独立目录。
有效重跑的 `resource_interference=false`，Q0/Q1/Q2 均通过 SemanticTree 和库存
完整性校验。新旧 Q1、Q2 的规范路径多重集差异均为零，因此该规则在此图上
额外回收 **0 个 GRH Node**。第三次 DCE 总删除量仍为 1,009,108 个 Node。
[全图库存及路径比较](../../ptmp/firrtl-ingest/F33/assert-prune/inventory-summary.json)
[有效捕获](../../ptmp/firrtl-ingest/F33/assert-prune/grh-retry1/summary.json)
[有效守卫](../../ptmp/firrtl-ingest/F33/assert-prune/grh-retry1/guard.json)

| 全图 Node 库存 | Q0 | Q1 | Q2 | 第三次 DCE 删除 |
| --- | ---: | ---: | ---: | ---: |
| 前一版 GRH | 5,625,297 | 5,625,297 | 4,616,189 | 1,009,108 |
| 开启 assert 规则的 GRH | 5,625,297 | 5,625,297 | 4,616,189 | 1,009,108 |
| GSIM | 5,922,045 | 5,922,045 | 5,775,134 | 146,911 |

新 Q2 的 4,616,189 个 GRH Node 中，4,596,538 个在 GSIM Q2 有唯一同名候选，
占 99.5743%，与前一版相同。GRH ConstantAnalysis 为 73.665 秒，是 GSIM
69.620 秒的 1.058 倍；第三次 DCE 为 23.522 秒，是 GSIM 38.748 秒的
0.607 倍。两项均通过单样本两倍门，Q2 停止边界和产物校验通过。

## 12. F33.5 香山全图正式性能采样

在同一台 Ryzen 9 7950X3D 主机上使用原始 `SimTop.fir` 和 F26 manifest，
冻结 Release GRH 包和 GSIM 二进制。两端共享 CPU 亲和集合 0–31，GSIM
以 `NR_THREAD=1` 构建，解析日志确认一个 worker。按 GRH、GSIM 交错串行运行，
每次从输入重新建图。计时窗口内保留生产 pass、Node 和 binding 维护，关闭快照、
trace、export 和 profiler。GRH 从 ConstantAnalysis 调用前计时到第三次 DCE
返回，用两个原生 pass 计时和守卫事件交叉校验。GSIM 使用原生 `F33Window#0`。
两端的前缀和 GRH 的 Q2 返回后额外校验均在窗口之外。
[冻结配置](../../ptmp/firrtl-ingest/F33/phase5/formal-v2/group/group.json)

正式组之前的三次独立 GSIM 校准样本给出 141.880 秒和 75.498 秒的逐 pass
两倍守卫。正式组采用 144 GiB RSS 上限和持续 8 秒的 25% PSI 守卫。
第一次启动在 GSIM 校准前因 runner 字段错误退出。修复后曾以默认十个 GSIM
解析 worker 启动，在校准前缀内中止，再用单解析 worker 建立正式组。
[校准记录](../../ptmp/firrtl-ingest/F33/phase5/formal-v2/group/reference.json)
[首次启动日志](../../ptmp/firrtl-ingest/F33/phase5/formal-v1/launch.log)
[中止轮日志](../../ptmp/firrtl-ingest/F33/phase5/formal-v1-retry1-launch.log)

六个正式样本均完成，守卫均记录 `resource_interference=false`。三个 GRH
样本的两个 pass 均在各自的两倍预算内。六组指标序列均通过各侧的抖动检查。

| 指标 | GRH 中位数 | GSIM 中位数 | GRH / GSIM | 正式上限 | 判定 |
| --- | ---: | ---: | ---: | ---: | --- |
| ConstantAnalysis | 74.477 s | 71.380 s | 1.0434× | 73.521 s | 未通过 |
| 第三次 DCE | 23.354 s | 37.555 s | 0.6218× | 38.682 s | 通过 |
| 连续两 pass 窗口 | 98.113 s | 109.360 s | 0.8972× | 112.640 s | 通过 |

ConstantAnalysis 中位数比 GSIM 多 3.097 秒，超出正式上限 0.956 秒。
F33.5 整体尚未通过正式性能验收。当前数据覆盖冻结候选在本机的执行表现，
尚未量化分析覆盖差异对 0.956 秒缺口的贡献。
[正式样本清单](../../ptmp/firrtl-ingest/F33/phase5/formal-v2/group/results.json)
[正式结果及抖动](../../ptmp/firrtl-ingest/F33/phase5/formal-v2/report/summary.json)
[比较器合同测试](../../ptmp/firrtl-ingest/F33/phase5/compare-validation/tests/compare.log)
