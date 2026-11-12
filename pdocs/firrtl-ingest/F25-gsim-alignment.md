# F25：同输入 GSIM 对齐矩阵

2026-11-12。目标仍为对齐完整100k仿真性能，保留GrhSIM事件、NBA、多时钟及
中断恢复能力；无PGO，先性能后正确性。主报告为
[F25性能记录](F25-simulation-performance.md)。

## 比较基准与单位

- 原始输入：`build/xs/rtl/rtl/SimTop.fir`，SHA256
  `b313a3ecd154cbd9279b14403709806b95fb136cf44b475e9def46a926ecb26b`。
- GSIM已计时模型：`ptmp/firrtl-ingest/F24/gsim-current-full/build/default-xiangshan/model/`；
  实际编译记录在`F24/gsim-current-compile/`。240个CPP哈希与编译输入清单一致。
- GrhSIM已完整验证基准为v6；v7生成服务840.229s超时，无编译、仿真或正确性
  成绩。其已落地CPP只能作为静态实现检查材料。
- 按同一FIRRTL声明/实例/字段及SemanticTree根配对，再比较表达式、输入/输出
  依赖、owner边界、生成代码和动态成本。GSIM Node/ENode、GRH operation/value、
  activity node及supernode的计数单位不同，不能直接用总数相等判定对齐。

历史F21 `current-lowering`使用同一输入，但producer较旧且部分GSIM split map
已清理；`continuous-state-split-v13`使用不同输入cc46。复用其映射算法和源名
规范，不把这些旧图当作当前生产图的等价证明。

## 已确认的同逻辑差异

| 对象 | GSIM | GrhSIM v6 | 差异起点与成本证据 |
| --- | --- | --- | --- |
| 长日志格式串 | 格式保存在`OP_PRINTF.strVal`，代码直接`gprintf("…", …)` | FIRRTL lower建立`kConstant String`数据值，跨owner发布为string slot，随后SystemTask引用 | 从IR表示进入边界存储/依赖/比较。35个被采样常量与GSIM字面量逐字节SHA相等，覆盖该caller全部486个memcmp样本 |
| RenameTable动态connect | 按端口顺序`if (wen) table[addr] = data` | 每端口全宽payload/mask移位、Not/And/Or、pack/unpack和数组mux | FIRRTL动态组合写lowering；三个owner共1560条链，完整owner预算约1.148s，只是局部候选 |
| 普通寄存器clock依赖 | clock不接入普通数据Node依赖 | 事件存在于完整仿真模型，已隔离clock相关NS分组 | raw clock直接组146 ops降为1 op；原其余145个操作未删除。整体NS仍慢，不能把分组隔离当作性能对齐完成 |
| SSIT地址一热译码 | 同一raddr的64个`raddr == i`与current复制在owner82812 | root15458先发布`1ULL << raddr`，15516/15517再逐bit读取 | 64个输出已按FIRRTL源行和常数逐项配对，确认Pattern1覆盖/分组差异；三native owners在已有100k capture均零样本，尚无热路径收益证据 |
| Entry7同一寄存器成员的读取 | 不同reference的ENode指向同一个`NODE_REG_SRC`，C++直接引用同一current字段 | 数组每次引用新建ReadArrayPort，静态拆分后仍为不同ReadPort；该字段有9次比较读取和1次hold读取 | 首次差异在FIRRTL lowering，非C++拆函数才产生。CSE仅接受Pure，ReadState结果作为不同ValueId叶，因此也限制其后相同纯表达式的共享；跨采样域合并的安全性仍在核对 |

日志格式串对应源链：

```text
GSIM AST2Graph.cpp: OP_PRINTF.strVal
  → instsGenerator.cpp: gprintf字面量
  → SimTop17.cpp:18783（161605B同一字符串）

GrhSIM ingest/firrtl/lower.cpp: kConstant String + task operand
  → sn2813_chunk7发布nonSinkBoundaryStore字符串
  → sn21214 SystemTask通过TaskArg读取该slot
```

该NS owner有45个string比较点，单点相等比较124–179773B；45点各执行一次的
静态字节和4,345,847B不代表动态调用数或带宽。已匹配的35个被采样点合计
4,344,472B，余10个零样本ERROR字符串的GSIM去向尚未逐一定位。
证据为`ptmp/firrtl-ingest/F25/v6-memcmp-callchain/captures/c1/analysis-retry1/`
和`v6-memcmp-callchain-analysis-retry1/audit-report.md`。

writer的精确双侧对照为
`ptmp/firrtl-ingest/F25/v6-writer-gsim-align/findings.md`。Entry7的九路selector、
九路比较及OR reduction在双方均存在，GSIM也有NEXT写入、current复制和变化
激活；不能从GrhSIM额外shadow阶段或操作数目直接推导可删除的语义工作。
GSIM对公共enqueue/update分支生成一次`if`，GrhSIM按字段保留嵌套mux；需要
继续对guard公式和优先级配对，不能只根据分支文本相似合并。Delayer对应
GSIM把current-copy和下一拍NEXT写放在同owner，但它仍保留流水时间边界；
GrhSIM在index常量传播上反而优于该GSIM模型。两例完整batch成本包络分别
约1.505s、2.458s，不能把它们当作整个writer约93s的已解释主因。

有界NS核对还纠正了按owner名称猜工作类型的问题：20843/20761/20693/20762
虽带stride/decode/TAGE/issueQueue源域名，实际是每组128条fatal/assert任务，
不能把这些owner样本归给Pattern1算术。后续ROI先核实操作种类再选择。

v8已实现并安装`grhsim.literalFormat`，v9复用同producer完成完整100k性能：仅把FIRRTL printf/write的直接
String常量抽为任务元数据，base GRH及SV表示不变，动态/held String及其他
任务仍走原路径；GrhSIM dialect版本门控阻止旧reader静默误解新operand列表。
删除抽取后确实无其他用户、非port/声明锚点的常量，不添加全图DCE。空串、
首NUL截断、fire/enable和参数顺序保持现CPU行为。v8生成超时，v9关闭已有可选
readable dump后生成及新鲜编译均通过；quiet100k wall149.80s，较v6单次171.85s
下降12.83%，含v7数值局部存储及本字面量两项变化，不独立归因或宣称稳定提速。
安装37.509s、peak1,331,507,200B，资源保护有效，producer SHA为
`d23b78ae4d46bb65385f40354f63a2e4807096ad466aafce8216a0ba1091e83a`。
冻结源及安装证据在`F25/v8-workflow/`。45个旧格式发布点已全部按FIRRTL行及
字节SHA配对到v9 literal TaskArg，旧成员/getter和NS常量producer消失，覆盖
原35个采样点/486样本。独立99Hz/DWARF4096完整100k及raw/binary哈希核对已
完成，逐symbol/DSO闭合且lost0；同capture NS归属memcmp估算从v6的6.503s
降至v9的0.959s。静态对照在`v9-profile-analysis/static-format-comparison.json`，
新采样归因在`v9-profile-analysis-retry3/`。后置100k NEMU及231568条Verilator
精确提交比较随后通过，六阶段身份审计pass；116例runtime及相关变换/ingest
回归全部通过。

SSIT的64对记录和source身份复核在
`F25/v7-gsim-alignment/pattern1-roi/{findings.md,ssit-exact-alignment.json}`。
ReadState与公共when的前端溯源在`F25/v6-writer-gsim-align/readstate-provenance.md`。
FIRRTL静态成员读归一草案仅存ptmp，未应用：合并read后它可能由多个私有writer
共享而被推入NS，反而新增held边界和activation。下轮需把read、common-when
字段族及privateWriter分区规则一起检查，不能从读节点减少直接推导提速。
新草案已核对同一Entry7的29字段均为`H ? Update : (G ? Enqueue : 0)`，H/G
分别由独立NS发布；可在exact run内保留四种组合和H优先级恢复公共分支，
不能在恢复点假设二者互补。v9机器码已将current重复读从10次压至1次，G/H
直接读各29次也各为1次；该whole function仅1个新样本、约0.00969s预算。
所以草案仍未应用，源码58个select不足以证明进一步实际收益。
证据在`readstate-alignment-followup/{design.md,field-formulas.md}`。

v9完整writer batch排序已闭合到本次82.903s，最重824/1124两组分别估算
2.15993/1.79182s，合计仅writer的4.77%。Delayer14 index双级状态，以及
IQ0 Entry2 srcType[1]的同输入GSIM根已配对；后者在v9跨chunk135计算→242写入，
GSIM在同owner内算后写NEXT。下一候选是保留writer全序和原采样/barrier后，
让有界私有payload靠近消费者以缩短跨part存活。其后完整区间Next/dirty读写、
shared prerequisites全uses及old-current稳定性仍需证明；现有摘录不足以
授权重排，也尚无正收益下界。双侧根、整函数成本上限和必要证明见
`v9-writer-alignment/findings.md`，未将整batch成本视为局部可省时间。

## 对齐顺序

1. 先配对同一语义根的输入、输出、位宽、数组shape及有序writer；比较各pass
   之后的存活根和依赖，找首次出现差异的阶段。
2. 对存活普通NS比较owner分组、边界值、失效边及实际执行次数；同一逻辑在NS、
   sink私有锥中出现多份时明确记录复用和复制关系。
3. 对配对的C++比较表达式、临时变量、数组拷贝、比较、state transfer及activation。
   先证明双方代码在相同采样/提交边界内等价，再选取能消除差异的实现。
4. 以动态成本排序这些差异。新实现重新遵守840s生成、330s新鲜编译、128GiB/
   swap0，并先完整100k性能/采样，再做Verilator精确提交比较和必要回归。

GSIM的相应stage接口位于`reference/gsim/src/main.cpp`，支持小型统计、指定
dump stage及stop-after-stage。GrhSIM沿用生产22阶段；收集对齐诊断时将统计/
dump开销独立记录，避免把诊断流程当作无插桩性能成绩。全图产物串行，优先
紧凑统计与有界语义ROI，避免为每个pass保存一套巨大JSON。

同次采样把可归属共享helper计回NS后，v6 NS及activity调度为34.9013% CPU
period，按quiet user171.80s归一59.960s；v9为32.7743%，按自身quiet user149.76s
归一49.083s，是历史GSIM wall51.34s的0.956倍。v9 writer仍估算82.903s，整体
quiet149.80s仍约GSIM的2.918倍。两版quiet/profile有漂移，且GSIM提交终点
不同，这些均为估算，不构成严格同工作量parity。性能目标尚未完成。

v10 已实现保守的 Unique private payload→writer 就近布局：whole-run scalar
TwoState plain write gate、全operand occurrence归属、ReadState/Shared/control
前置、原ordered writer/dirty生命周期。真实新安装后22stage生成777.791s
controller wall、新鲜编译281.202s，均在840s/330s内。完整quiet100k161.32s
较v9单次149.80s慢7.69%；独立profile100k精确闭合16077samples/lost0，归属
NS+调度估算49.754s、writer92.540s。NS为历史GSIM总wall51.34s的0.969倍，整体
为3.142倍，GSIM端点不同，不构成parity。

Entry2最终payload从v9跨chunk135→242的frame中转变为v10chunk122寄存器中
直接比较/写相同shadow，实际对象定点汇编已证明；held current前置frame读
仍在。Delayer两级current frame读仍在。样本batch824/1124函数数增加与静态
frame引用减少同时出现，未证明前者导致时间回退。八根真实符号/target/
origin/operand/result核对及机器限制见`v10-writer-alignment/v10/`。
后置231568commit与Verilator逐项及字节完全一致，118例runtime、9CTest、
9effects集成及六阶段身份/资源审计通过。v10未获得性能改进验收；下一步只把
连续同enable writer units的有界合并作为待测布局候选，不降低采样/顺序约束。

该候选随后作为v11完整验证：生成controller751.159s、fresh编译267.550s，
quiet100k161.77s；独立profile15442samples/lost0、NS+调度估算51.160s、
writer91.985s。profile/quiet user漂移−3.481%，不将单次差值归因于scope。
Entry2同part保留，但824/1124两个batch的helper数量分别减少/增加，frame引用
数与v10相同；scope合并仍未获得整体收益。231568commit、118runtime、9CTest/
9effects及六阶段/独立身份审计通过；唯一审计重试仅修正固定原始compile日志
交织行，原失败保留，未重编译或放宽资源。

完整封存两候选后，三个文件已精确恢复历史baseline，其他12个累计修改保持；
真实重新安装producer与历史v9 SHA逐字节一致。当前源码/安装为v9，149.80s仍
是历史已审计成绩，没有冒充本次重测。v10/v11及恢复证据全部保留，继续按动态
成本覆盖排序新的GSIM语义对齐根，性能目标尚未完成。

v12 在既有 eligible exact run 内按完整 fanout key 聚合 shadow 通知，删除
dirty guard 已证明为 1 的自身位；实际 shadow/state dirty、原采样、enable、
writer 顺序、run 边界和 fallback/current/large 通知保持。静态 mask sites
580,098→309,413，定点机器码确认自身 OR 删除及重复通知单次 flush。
真实安装后原输入 22stage 生成 controller756.443s、fresh 编译258.607s，
满足840s/330s、128GiB/swap0/omit，无PGO。

完整quiet100k wall160.98s/user160.94s；独立profile161.45s/user161.27s。
15,953samples/831,629,539,467period/9,360symbolDSO/lost0经主分析和独立
对账闭合。按自身quiet user换算，NS+调度约50.449s（历史GSIM整体51.34s的
98.264%），writer约91.843s；采样秒数及不同GSIM终点不构成严格parity。
后置231,568条Verilator字段/顺序/周期/字节一致；8CTest通过，但生成器
旧统计断言实际失败，120runtime未运行。原完整审计exit2/缺summary；独立
补充报告明确not_accepted，不将已验证六阶段证据冒充完整回归通过。

另以原ELF完成同期串行quiet诊断：v9 155.19s→v12 160.50s→v9 157.06s，
共享输入/CPU2/seed0/NEMU/golden endpoint及冻结身份、资源均核对通过。
v12较前后v9 wall几何均值慢2.804%，v9前后漂移1.205%；未获性能收益，
不能把原先对历史149.80s的7.46%差值全部归因于实现。诊断不替换原成绩，
也不提供单次源码因果结论。v12已拒绝，三文件精确恢复和真实重装v9已通过，
producer与历史v9逐字节一致；恢复后生成器CTest3.73s通过，不冒称116例重测。
其余12个累计修改和全部证据保留，当前源码/安装为v9，F25目标继续进行。

后续v13调查已用全407 TU哈希及原8,558 writer samples核对公共selector族，
跨split宽松整函数包络约7.360s，不能解释整个82.903s writer。IQ0 Entry2的
九路比较已由一次current load服务，额外hold读取只再load一次，因而没有实施
全局ReadState归一。调查及成本范围见性能记录的v13前置调查节。

新的开发候选对应GSIM已匹配的`cmp/setne`→NEXT store→activation OR形态：
仅在现有eligible small scalar writer原位置计算零/全一change mask，并立即
按mask更新原state dirty及完整sink fanout；没有v12聚合或self-bit删除。
独立静态审查未发现该限定范围内的语义缺陷，生成器预检通过3.85s；新fixture
使用两时钟、16种width/sign状态和48个真实writer counters。源码已应用此
开发候选，其他12个累计diff sections保持。两个新用例及两个保留130-run/
多字fanout用例定向运行通过，尚非完整118例回归；安装仍为v9，尚无v13性能成绩。

随后已冻结完整v13控制并真实新安装（31.084s，peak1,026,981,888B，原控制器/
双端限额及source/control核对通过），producer SHA为`9177458b…043667`。
当前源码及安装为实验v13，原始FIRRTL完整生成进行中；尚无v13完整100k成绩，
性能目标未完成，v9仍为此前保留基线。

v13原始FIRRTL完整22stage生成随后通过：pipeline772.920s、resource service
776.087033644s、controller wall777.250087010s，peak114,188,435,456B。
原始控制器returncode0，840s/128GiB/swap0/omit双端资源检查通过，无PGO，
source/control及实际新producer身份前后不变，没有复用或恢复例外。证据为
`v13/{generate-result.json,generate-exit.json,generate-resources.json,generation-audit.json}`
及`v13/{generate-driver.log,logs/stages.jsonl}`。fresh完整编译已启动，330s截止仍生效，目前未完成；
尚无新的完整100k性能成绩或正确性验收，性能目标仍未完成。

v13 fresh完整编译随后通过：resource service269.114522148s、controller
wall277.945692344s，peak14,488,018,944B；无PGO，330s/128GiB/swap0/omit
原始控制器及资源门禁通过。完整quiet100k为wall155.55s/user155.51s，独立
99Hz/DWARF4096 profile为wall150.24s/user150.11s。主分析和独立复核逐项闭合
14,847 samples、770,283,214,903 period、8,919 symbol/DSO行、lost0；按自身
quiet user归一，NS+调度估算49.846841155s，writer估算86.153921842s。
NS+调度约为历史GSIM整体wall51.34s的97.092%，整体quiet约为其3.030倍，
性能目标仍未达标。GSIM与v13终点不同，仍不能声明严格parity；profile/quiet
user漂移−3.472%、wall漂移−3.414%，这些独立测量不证明稳定性能收益。

精确性能报告`v13-workflow/performance-report.md`已向用户报告并显式记录，
SHA256为`b6f3f940ef835fe807332835910f2029c6ba48d58a7cde2e1242a958fcbbafc2`，
确认在`v13-workflow/performance-reported.json`。原始测量、主分析及独立复核
分别见`v13/{run-time.txt,profile-time.txt}`、
`v13-profile-analysis/results/reconciliation.json`、
`v13-profile-independent-review/{capture-review.json,reconciliation-review.json}`。
本段尚不认证trace或118个runtime回归通过，后置正确性及最终审计仍待验收；
v9仍为此前完整验收并保留的基线。

后续trace100k/NEMU及231,568条Verilator精确提交比较通过。回归前8个CTest
通过，原suite在库存检查exit2停止：误要求全部生成规则只有118个，实际
202个；历史v9也为生成200、选中116，新增2个后本次选中118个。原失败及
冻结控件保持，runtime尚未执行；正在独立补充核对库存，尚无完整回归或
最终身份验收，不将本控制检查错误当作模型正确性失败或已修复通过。

v13实际O3核对已证明三个同IR标量根消除shadow changed JCC，保留旧Next采样、
原dirty及全部fanout，无新增mask spill；bool见证则证明走freshFire=false
fallback，仍保留原分支。两u64的其中一个sink word更新比v9更宽，故局部
branchless机制不能替代动态性能接受。详见
`v13-investigation/shadow-codegen/{findings.md,four-exact-proofs.json}`。

v13后置补充回归随后实际PASS：118个runtime、9个CTest、9个FIRRTL effects
integration及6个terminal检查全部完成，12个服务串行、原限额和冻结身份通过。
补充审计仅纠正整个generated==118的错误：实际202=历史200+新增2，选中118=
新增2+原116；原suite及库存失败仍保留，原冻结controls未改，不能称原suite
PASS。纠正来源和实际结果见
`v13-investigation/regression-inventory-correction/{README.md,preflight.json,summary.json}`；
独立原始证据复核
`v13-investigation/controls-independent-review/regression-correction-raw-review.{json,md}`
亦为PASS。

显式publish的`v13-regression/summary.json`与补充summary同字节，SHA256均为
`f7c14e93e9c0e56c0e077ee3b3ebc86490731d157657148a530c340e7e4838d4`，
明确记录`original_suite_status=fail`。随后未修改的原最终身份审计实际exit0，
`v13-profile-identity-audit.json`为PASS/failures为空，绑定该补充摘要；完整
231,568条提交精确比较与身份/资源/顺序验收通过。性能仍为quiet155.55s、
NS+调度估算49.847s、writer86.154s，暂无稳定收益结论，整体约GSIM的3.03倍
且终点不同，目标未达标。v9→v13→v9同期诊断控件已获静态独立审查，尚未
freeze或运行，无新计时；审查见
`v13-investigation/controls-independent-review/paired-quiet-inventory-gate-review.{json,md}`。

随后同期诊断实际freeze通过，`paired-quiet-diagnostic/{freeze.json,plan.json}`
已在`v13-investigation/`下创建，plan SHA256为
`a1cc0ea29158ac9fdd7107f7edc2085e0714efd3c74432192786a65c35967df9`。
A1(v9) quiet100k正在运行，尚无结果；完整诊断未完成，无新计时或稳定收益结论。

同期v9→v13→v9 quiet100k诊断随后完成，原审计及实际独立复核均PASS：
A1 wall157.48s/user157.44s，B1 wall149.95s/user149.91s，A2 wall157.58s/
user157.53s。wall B1/两段A几何均值为0.951882229119，本次B1低4.8118%；
A2/A1为1.000635001270（漂移+0.0635%）。三段同quiet、CPU2、seed0、NEMU、
单模型线程、独立runtime cwd及共同终点；原始资源双端、严格串行与全部冻结
身份通过。实际证据见
[audit.json](../../ptmp/firrtl-ingest/F25/v13-investigation/paired-quiet-diagnostic/audit.json)及
[独立实际复核](../../ptmp/firrtl-ingest/F25/v13-investigation/controls-independent-review/paired-quiet-actual-review.md)。

这仍是single-B诊断，无重复B或置信区间，不证明因果或稳定收益，不替换主
v13 quiet155.55s及历史v9 quiet149.80s。暂保留v13继续实验；原suite/库存FAIL
及补充118PASS保持，最终身份审计PASS。主whole-model约为历史GSIM的3.03倍，
GSIM endpoint不同，严格parity与F25性能目标均未完成。

2026-11-12 UTC，完整v9 writer sampled-IP census闭合8,558 samples /
445,398,547,864 period；branch43.1378%只是全量检查定位，393unknown完整保留。
原actual-ELF解码和同PID MMAP2/PT_LOAD精确IP关联已独立复核；首次未证明映射
的全unknown结果保留，加载关联不冒称完整虚存生命周期证明。另按完整fresh
event集合而非仅singleton的连续root前缀，原v9有44组/1,019 of1,134 roots，
全函数包络约6.7034s（writer8.0858%），含真/假路径，不能当作收益。

v14已在保留累计v13的基础上实现typed EventEdge/Assign/Or/false完整key的
连续batch调用端guard；原root、内部guards、active前缀、large reset和全部
writer顺序保留；latch/unclocked及String等非平凡局部对象fallback断组。
旧三文件/full diff/原控件/成功失败证据及完整测试产物先归档，再精确应用三文件，
其余12个累计diff section保持。独立静态审查、实际development generator
31.944s及CTest1/1（4.68s）通过，四个新增16/1024结构fixture均命中分组与
fallback；尚不构成runtime或性能验收。新控制包206生成/122选中/既有extra84
独立核对通过，避免旧全部生成==选中断言错误。

源及230controls实际freeze后，新producer真实安装32.210s、peak1,030,520,832B，
前后身份/330s/128GiB/swap0/omit核验PASS，新SHA为
`f243634e02664b2c941733710b220b1a4fd5d451df1297e93a2f442977b318e9`。
完整原始raw22stage生成随后实际通过，原Make/controller exit0；service
773.223699471s、controller774.438467691s，peak112,570,818,560B，原840s/
128GiB/swap0/omit双端核验通过，无resume/PGO。新模型实际为1,134 writer
batches、34 caller groups覆盖1,064 batches/max5events，累计scalar mask
sites265,397保持。新结构计数不同于旧v9 machine-prefix44组/1,019 roots，
不能套用其历史样本/成本包络。证据见
[generation audit](../../ptmp/firrtl-ingest/F25/v14/generation-audit.json)、
[result](../../ptmp/firrtl-ingest/F25/v14/generate-result.json)、
[exit](../../ptmp/firrtl-ingest/F25/v14/generate-exit.json)、
[resources](../../ptmp/firrtl-ingest/F25/v14/generate-resources.json)及
[sink stats](../../ptmp/firrtl-ingest/F25/v14/model/sink-activity-stats.json)。
fresh完整编译随后exit0，service263.774657780s/controller272.658062760s、
peak15,014,838,272B，原330s/128GiB/swap0/omit双端PASS；实际ELF SHA256为
`eeb8335c3449d7c5424c3aa222d347b057dfdbb6202ca777ce64ad15520e0ecb`，见
[compile result](../../ptmp/firrtl-ingest/F25/v14/compile-result.json)、
[exit](../../ptmp/firrtl-ingest/F25/v14/compile-exit.json)及
[resources](../../ptmp/firrtl-ingest/F25/v14/compile-resources.json)。quiet100k和随后
独立profile均terminal exit0，原始计时分别wall143.02s/user142.98s（host143002ms）
及wall149.85s/user149.73s（host149619ms）；两端点均记录
guest100001/core99996/instr238535/PC0x80000cde，见
[quiet time](../../ptmp/firrtl-ingest/F25/v14/run-time.txt)、
[result](../../ptmp/firrtl-ingest/F25/v14/run-result.json)、
[profile time](../../ptmp/firrtl-ingest/F25/v14/profile-time.txt)及
[result](../../ptmp/firrtl-ingest/F25/v14/profile-result.json)。主分析与独立capture/
reconcile随后均PASS，14,809 samples/770,023,179,677 period/lost0，8,942个
symbol+DSO逐项闭合。quiet-user归一NS39.945396s+其dispatch7.426375s合计
47.371771s，writer78.181119s；general_mixed_dispatch另计1.100926s，不含在
上述NS项中。这些均为采样估算，不能作为精确组件计时。见
[主对账](../../ptmp/firrtl-ingest/F25/v14-profile-analysis/results/reconciliation.json)、
[独立capture](../../ptmp/firrtl-ingest/F25/v14-profile-independent-review/capture-review.json)及
[reconcile](../../ptmp/firrtl-ingest/F25/v14-profile-independent-review/reconciliation-review.json)。
正式NS/GSIM报告已实际展示并单独report-record PASS，SHA256为
`d5e72380a10a75a34b797eb9277963e47295a35bc9f5d9bcf75c42f7c10cc8a0`，见
[报告](../../ptmp/firrtl-ingest/F25/v14-workflow/performance-report.md)与
[显式记录](../../ptmp/firrtl-ingest/F25/v14-workflow/performance-reported.json)。GSIM
整体wall/user51.34/51.33s采用不同端点（guest100001/core99998/instr238550/
PC80000b40），NS组件估算与其整体wall分母不等价，严格parity与F25目标均未完成。
本轮单次quiet/profile不证明稳定收益或因果，历史v13原主155.55s、单B同期
149.95s和旧FAIL/补充PASS历史均保留。

报告显式记录后，trace与精确比较随后全部PASS：231,568条commit的字段、
顺序、周期和三项导出字节均与冻结golden一致。正式suite原控制器exit0，122个
runtime/9个CTest/9个FIRRTL effects通过，selected122/generated206与extra84
库存闭合；13个串行服务的原330s/128GiB/swap0/omit双端约束均通过。原最终
身份审计控制器exit0，status=pass/failures=[]，
`identity_resource_correctness_profile_audit_passed=true`，绑定同一安装/源码/
控制/ELF/profile及完整trace与回归。证据见
[trace](../../ptmp/firrtl-ingest/F25/v14/trace-result.json)、
[compare](../../ptmp/firrtl-ingest/F25/v14/compare-result.json)、
[regression](../../ptmp/firrtl-ingest/F25/v14-regression/summary.json)、
[audit log](../../ptmp/firrtl-ingest/F25/v14-identity-audit/audit.log)及
[identity audit](../../ptmp/firrtl-ingest/F25/v14-profile-identity-audit.json)。
v14本轮完整验收链通过，143.02s是新的主性能观测。用户要求“做完v14就先停
一下”，因此验收完成后暂停；可选同期v13→v14→v13诊断仅部分准备，准备/
review已中断，未授权或执行实际paired freeze/run、未验收。不能将单次结果
写成稳定收益或严格GSIM parity，F25总体目标仍远未完成。
