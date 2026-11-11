# F24：XiangShan FIRRTL → GrhSIM 联调与验收

目标是让 XiangShan 全图经过固定22阶段生成原生C++，在同输入GSIM的生成、完整
编译预算内，通过NEMU difftest、提交行为和activation边数质量门。
**用户于2026-11-11明确调整验收口径：正确性通过即F24完成，停止继续性能优化；
原定单线程性能要求不再作为F24完成门。v14以显式FIRRTL ingest请求完成22阶段生成，
pipeline825.050s、受控service826.294s，840s生成门通过；activation、fresh编译
门通过；100k NEMU无差异且231,568条提交与Verilator逐字节一致。
正确性调试定位到SRAM的invalid控制策略。
提取原始SRAM模块与Verilator对照，已复现并通过zero策略消除67次读回差异。
byte-unpack跨helper生命周期修复已通过fresh ASan b16/b1024验证并安装。
F24按最新口径验收完成；当前收尾为脚本/Makefile/临时产物清理及提交。
性能运行触及152.190s硬截止的事实保留，不计为性能通过。**

## 现在处于哪个阶段，已经花了多久？

### 2026-11-11 continuation：显式 ingest 参数与 v14

**开始（06:48 UTC）**：用户恢复F24并要求继续记录。上一段正确性调试属于
**progress**：已有全核波形定位、原始SRAM隔离复现及67次读回对照，改变了下一步
行动；暂停期间未启动v14生成/编译/运行。工作树和goal状态已重新核验。

用户确认使用FIRRTL ingest的`firrtl_options={"invalid_policy":"zero"}`参数。
该参数映射到`IngestRequest.firrtl.invalidPolicy`，在`Lowerer::invalid`建图时
决定产生0或X，不是修改XiangShan RTL，也不是给优化pass增加特殊处理。
此前修改Make全局默认的方案已撤回；通用ingest/API以及既有Make默认仍为unknown。
本轮将显式导入请求作为输入清单记录并冻结，不依赖环境设置invalid策略。

**准备中**：为`xs-firrtl-grhsim`补齐显式prepared request入口与校验，保留
22阶段顺序。小规模回归完成后才冻结v14新输入/源码/库身份；正式生成仍为
840s、fresh完整编译330s、128GiB/swap0及24共享jobs，16MiB TU/32GiB artifact。
后续依次验证activation、100k/NEMU/精确trace，再进行未插桩性能测量。
隔离测试不替代上述任何全核门限。下述终态覆盖本段准备时状态。

**入口回归结束**：`make test_xs_firrtl_workflow SKIP_PY_INSTALL=1`共85项通过，
20.012s；新增用prepared request实际执行canonical22阶段、编译并运行生成模型，
确认`invalid_policy=zero`下`eq(invalid,0)==1`，即使旧Make参数要求unknown，
仍以请求参数为准。另验证top/输入/缺失source/非法policy提前拒绝且不启动生成，
harness与producer使用同一原FIRRTL哈希。独立review及Make语法检查完成。
实际v14请求已通过`prepare-request`创建，`ingest-request.json`与规范化
`sources.json`逐字节相同：invalid zero、init unknown、10 ingest threads。
本轮未改XiangShan源码，未改Wolvrix native库，无需重装已通过ASan的同一库。
日志：`ptmp/firrtl-ingest/F24/prepared-ingest-request-tests.log`。

**冻结/启动（07:00 UTC）**：v14新snapshot冻结643个源码文件、12,595,200 B
源码归档及显式ingest请求；实际已安装`libwolvrix-lib.so`仍为已验证的
`4648e9d77c5e25b24928fc58ffb3ad0c6dc62ad79da7a7a39eae7c599a826d63`。
首次sandbox启动在访问user-systemd时被拒，enforcement=false、exit125、
producer未启动；证据连同harness捕获保留在`v14/sandbox-launch-denied/`。
按权限流程重试同一Make目标后，正式service
`wolvrix-capped-a8e6f30a34d44d2bb9c31eadf30fdcc2.service`于
**07:00:12.25 UTC**启动，840s硬截止**07:14:12.25 UTC**。
独立start sidecar已核验128GiB/swap0/oom.group，当前在ingest-firrtl阶段。
拒绝启动的尝试不算一次全图生成成绩，正式源码/输入freeze未改写。

**进行中（07:04:37 UTC）**：已完成ingest39.945s、hier-flatten41.384s、
comb-loop-elim23.051s、split-static-array24.523s、split-nodes7.676s与
constant-analysis13.410s；当前运行后续DCE。阶段顺序以v14 JSONL日志为准，
仍未产生整轮生成成绩。期间不改冻结源码/控制，不启动并发全图任务。

**进行中（07:09 UTC）**：事件/输出拆分34.049s、nonsink/sink拆分23.504s、
partition-nonsink59.870s完成，当前partition-sink。最新cgroup memory.events
max/oom/oom_kill均0。本轮activation边数待新模型发布后独立核算，不沿用v13。

**生成结束（07:17 UTC复核）**：正式service于07:13:58.49 UTC结束，
22个stage的start/done与计划逐项一致。pipeline **825.050s**，service
**826.294s**，均低于840s（service余13.706s）；emit **281.569s**。
wrapper及source verification均exit0，freeze-model核验407个编译输入，
producer-final与build-root身份一致。完整发布409文件、403 TU、57,968函数，
正文6,713,031,849 B。cgroup peak **108,162,514,944 B（100.734 GiB）**，
swap0，max/oom/oom_kill全0，独立sidecar确认enforcement=true。
该结果仅证明本轮完整生成通过，尚不证明全核正确性或性能。

**activation开始（07:17 UTC）**：对v14新publication重新核算；复核原FIRRTL、
显式请求、实际加载库、完整model inventory及GSIM对照身份，重新census GSIM
C++。充分上限仍为2,193,888，不能把v13数值直接作为v14成绩。

**activation结束（07:18 UTC）**：target exit0，census **15.04s**；新模型
V=774531、Sc=0、Sw=189719、P=894，U=964250、U+P=965144，均≤2193888。
GSIM的240个C++文件inventory及stats与冻结对照相同，v14的输入、配置、实际
加载库、producer-final identity和publication哈希独立复核通过。结论是充分
不等式成立，不把上下界之比当作精确边数比；analyzer自身不认证身份或整体验收。

**fresh编译开始（07:18:56.94 UTC）**：通过v14 Makefile的compile target
执行，service为`wolvrix-capped-6057a7f7abaa4f2bb8aeb543cd86fbc0.service`；
330s硬截止 **07:24:26.94 UTC**，128GiB/swap0、24共享jobs，禁用cache/PGO。
payload涵盖fresh harness捕获、PCH、403个模型TU、harness、归档与最终链接。
执行前冻结源码/输入/模型核对通过，fresh-products证实无已有编译产物及emu树；
独立start sidecar确认限额生效，fatal monitor遇编译错误即停止独立组。
07:19 UTC采样已完成PCH并开始模型TU编译；尚未有v14完整编译成绩。

**编译进行中（07:20:38 UTC）**：service已运行约102s，330s预算余约228s；
已见297/403模型对象及40个harness对象，不能按对象数推算剩余时间。
当前cgroup内存约11.21GiB、peak12.52GiB，swap限制0，max/oom/kill事件全0，
fatal monitor无事件。本次continuation自06:48 UTC约32分38秒，正式生成
和当前编译的计时边界各自保留，不把准备/哈希检查混为payload成绩。

**fresh编译结束（07:24:08 UTC复核）**：service于07:24:02.72 UTC结束，
完整payload **305.71s**、service **305.837s**；330s硬预算余24.163s，
亦低于GSIM300.63×1.1=330.693s。403个模型TU、41个harness对象、archive和
最终链接完成；原始emu119,876,608 B。wrapper、fatal monitor、source/model
verification均exit0，freshness核验通过。cgroup peak14,615,396,352 B
（13.611GiB），swap0，max/oom/kill全0。**v14完整编译门通过。**

**100k trace准备/开始（07:25 UTC）**：通过v14 Makefile trace target，
使用上述原始exe、CPU2单线程、seed0、50 reset pulses和同一CoreMark/NEMU；
trace打开、wave/profile关闭，emu硬截止600s。运行前重新核对生成/编译终态、
完整publication、源码、加载库及harness身份。通过本轮100k endpoint和精确
提交比较前不执行perf。目标窗口参考为231,568 commits、guest100001/core99996
cycles；这不是完整两轮CoreMark结束。正式运行终态尚待取得。

**trace进行中（07:27 UTC）**：preflight完成后，实际runtime service
`wolvrix-capped-cb888bc162444e8d896ca2558171dc88.service`于
**07:26:33.88 UTC**启动；独立sidecar确认128GiB/swap0生效，emu600s硬截止
保留。日志已启用NEMU，PC0x80000040在cycle8257提交正确`00000893`，已越过
v13非法指令故障点；此前commit17/18的cycle8257也与参考一致。
采样已超过cycle10699，未见NEMU错误。该前缀观察不替代整段逐字节比较；
continuation累计约39分钟，正式trace最终耗时仍待终态time报告。

**trace进行中（07:28:43 UTC）**：采样到cycle67384、135,115条提交附近，
未见NEMU mismatch；service已运行约130s，emu600s预算尚有约470s。
cgroup peak68,587,520 B（65.41MiB），max/oom/kill全0；continuation累计
约40分43秒。尚未导出正式全量trace或执行精确比较，未启动perf。

**trace结束 / postflight误报（07:29:48.96 UTC）**：emu正常完成100k，
payload **194.96s**、service **195.140s**，emu/Make/service均exit0；
guest100001、core99996、instrCnt238535、terminalPC0x80000cde与参考一致。
cgroup peak100,110,336 B（95.47MiB），swap0、max/oom/kill全0。
原script exit2，因为`[Mm]ismatch`扫描误命中45条合法硬件PERF统计
（如`ras_top_mismatch`）；golden也有相同45条，非PERF错误命中为0。
**原status、控制文件及完整运行证据均保持不变，不能把原script声称为成功。**

**补充校验/比较结束（07:33 UTC）**：新增独立`v14-validation/` Make流程，
只对完整数值PERF记录豁免上述词扫描，保留所有endpoint/身份/资源/时间要求，
8个正反例通过；controls哈希冻结，audit-trace与compare均exit0。
重新核对完整publication、源码/库/原exe与运行前后哈希；同一raw无需重跑。
原始exporter的commit.trace、commit.tsv、summary.json三项`cmp`全部通过；
独立comparer也确认 **231,568 commits**、cycle568..99996、PC/指令/写回/
ROB/queue/tag与周期全等，inactive writeback差异0，normalized字节一致。
故**本轮100k功能与精确提交门通过**，不声称完整两轮CoreMark执行结束。
证据：`v14-validation/`、`full-native-v14/{commit-trace,trace-comparison}/`。

**perf准备（07:33 UTC）**：同一原始exe、CPU2单线程、NEMU开启，关闭trace/
wave/profile/log窗口观测，152.190s emu硬截止不放宽。补充控制仅修正上述
postflight误报，使用原runtime-main及同一完整identity/精确trace前置门；
性能只有完整达到同一100k endpoint且限额内结束才通过。

**perf开始（07:34:54.83 UTC）**：补充控制经独立review无实质阻塞，仍调用原
`f24_runtime_main perf`，只更正PERF字段误报及trace成功凭证来源。
service为`wolvrix-capped-fc0bb6f9a3b548c4b2d72509e680be12.service`，
独立start sidecar确认128GiB/swap0。CPU2、NEMU开启，trace/wave/profile关闭，
emu152.190s硬截止继续生效。07:35:25 UTC日志显示已启用difftest并进入
CoreMark，尚无完整endpoint或性能通过证据。continuation累计约47分25秒。

**perf结束 / 停止性能工作（07:37 UTC）**：152.190s硬截止实际触发SIGKILL，
原emu137、Make/service2，service **152.324s**。最后日志报告cycle70000，
未达100k endpoint；这只是最后报告点，不是精确被杀周期。cgroup peak
39,698,432 B，swap0、max/oom/kill全0；无继续等待或延长预算。

**验收口径调整 / 清理提交（用户最新决定）**：用户先暂停性能并要求整理提交，
随后明确“F24先不继续抠性能了，F24判定为完成，把正确性搞对了”。据此F24
以已通过的正确性、生成/编译及activation证据完成验收；性能未达标仍如实记录，
不再作为本阶段阻塞，不启动profiling或后续全图性能运行。当前仅清理旧迁移/
phase probe/M0 baseline脚本及Make入口、删除可重建历史临时大产物并提交。
清理改变了脚本/Make源码身份，小回归验证后提交；v14原始snapshot和正确性
证据原样保存，不能把它们误写为清理后版本全图重跑的结果。

**收尾结束（08:04 UTC核验）**：21个退役脚本/辅助Makefile/专属测试及旧
migration/phase probe/M0入口已删除，两个重复/无调用包装清理完成。
14,174个可重建历史产物已删除（638.261GiB apparent，含hardlink重复路径），
`ptmp`约680GiB→43GiB，删除清单和各目录记录保留。v14/参考/隔离证据均未选入
删除范围，清理后publication/runtime/参考哈希与三个精确cmp重新核验通过。
最终136项脚本回归、相关native suites及F21分析回归通过，不重跑全图；
具体版本、身份边界、测试命令及证据见[正确性提交记录](F24-correctness-checkpoint.md)。

### 2026-11-11 continuation：fresh ASan 与 v13

本轮开始先核验工作树与现存产物。上一轮分类为**progress**：已完成
byte-unpack生命周期修复、fixture重新生成（16.10s、exit0）、b16/b1024
普通执行（exit0）及修复后py_install（20.22s、exit0）。下面旧状态保留作
历史，不能再据其断言修复尚未安装。修复的loop RHS直接引用scalar，避免
跨helper保存指向stack local的bytes pointer。

**开始**：执行`validation/v13/asan.mk check-after`，使用fresh拷贝、LLVM22、
ASan UAR always及`-fno-inline`，b16/b1024顺序运行；每case60s硬截止。
仅关闭已证实受环境限制的LSan，保留ASan/UAR。验证通过后冻结v13身份，
正式全图保持840s生成/330s完整编译及128GiB/swap0，不复用旧编译对象。
宿主user-systemd运行态检查因sandbox拒绝bus访问，已按权限流程申请只读检查；
隔离namespace的ps不能证明宿主无任务。

**结束（04:27 UTC核验）**：fresh ASan b16/b1024均Make/runtime exit0，
分别3.45s/2.59s，driver总6.08s。b16生成代码已确认loop读取
`chunkFrame.*packed_bits`，scalar本体跨helper存活；原before b16的
stack-use-after-return复现保留。宿主user-systemd列出0个capped unit，
可以顺序启动新全图。下一步冻结输入/源码/已安装库，并启动v13。

**进行中（04:29:26.99 UTC启动）**：v13正式生成已运行，service为
`wolvrix-capped-f23a5e97fa0c4c5eab4524d289a2ae27.service`，840s硬截止为
**04:43:26.99 UTC**。独立start sidecar已验证128GiB/swap0/oom.group。
642个源码文件及12,574,720 B源码归档已冻结；安装库SHA为
`4648e9d77c5e25b24928fc58ffb3ad0c6dc62ad79da7a7a39eae7c599a826d63`。
本轮使用FIRRTL生产默认16MiB TU/32GiB artifact，未提高任何硬预算。

**生成结束**：22/22完成，pipeline806.912s、Make run807.66s、受控service
807.838s；外层Make含独立harness捕获809.82s，所有口径分开保留。service
及source-verification均exit0。nonsink/sink/emit分别59.579/51.211/280.919s，
完整发布409文件，403 TU、57,970函数、正文6,713,633,825 B；nonsink报告
与v12逐字节一致。cgroup peak113,804,083,200 B（105.988 GiB），swap0，
max/oom/oom_kill全0，840s预算余32.34s（Make run）。

**activation结束**：新GSIM C++ census14.55s，240个文件inventory及stats哈希
与冻结对照一致；新v13输入/配置/原始producer-final identity及完整生成
inventory/源码/库核验通过。V=774666、Sc=0、Sw=189720、P=894，
U=964386、U+P=965280均≤2193888（1.5×GSIM已确认下界1462592）。
这是充分不等式证明，未把上下界比称为精确边数比；analyzer自身不认证身份，
该判断还依据本轮独立的identity/runtime scope核对。

**编译开始（04:52:44.24 UTC）**：fresh完整编译已启动，service
`wolvrix-capped-0aa18ebd2b3b46aaa713c6c41305b8af.service`，330s截止
**04:58:14.24 UTC**。fresh-products检查通过，harness/PCH/全部model对象/
归档/最终链接均在同一payload，24共享jobs、128GiB/swap0；fatal monitor
独立存活。编译前再次核对冻结控制/输入/模型，未复用v12或其它旧产物。

**编译结束（05:04:16 UTC核验）**：payload **314.96s**、service
**315.085s**，wrapper/monitor/source verification 均 exit0；完整403 model
TU、41 harness对象、archive和最终链接均完成，freshness为无旧编译产物。
emu 为 v13 `grhsim-compile/emu` 的原始链接，119,868,552 B。cgroup peak
和事件记录已保存，编译门以GSIM **300.63×1.1=330.693s**比较，**通过**。
下一步运行 trace；performance 必须在 trace/精确提交比较通过后进行。

**运行失败与诊断开始**：原trace和仅修改log end的独立retry均约0.02s退出，
在RAM/NEMU初始化之前触发`LogUtils.scala:132`。该位置是通用硬件ERROR断言，
与log参数校验无关；此前log-end猜测已撤回。原v13模型、编译产物及freeze不改动。
GDB定位到`sn_20206`内`o9219515`，FIRRTL第1726815行，
`cpu$l_soc$core_with_l2$core$backend$inner$ctrlBlock$rob$rab`。
条件为`(1 << deqPtrVec[0].value) != deqPtrOH`且局部reset为0；顶层clock/reset均为1。
复位来自`ResetGen.pipe_reset`异步复位状态。冻结Verilator的initial代码会先将
clock历史采样为当前输入，首eval不产生clock posedge；native历史初始为0，
首eval直接输入clock=1会触发posedge。下一步用独立GDB诊断仅将首eval的clock
置低，观察复位传播和NEMU启动；这不是正式功能或性能成绩。
证据：`full-native-v13/debug-startup-detail.{gdb,log}`。

**复位定位结束 / 新正确性诊断开始**：首eval clock-low的独立GDB实验运行1000
cycles正常结束并启动NEMU。GrhSIM既有fixture明确要求首个high eval触发边沿，
因此不改变事件历史语义；在XiangShan `Emulator::reset_ncycles` 的GRHSIM分支
加入reset=1/clock=0的settle eval，再保留原50个reset脉冲。新增
`make test_xs_grhsim_reset` 提取实际reset函数，验证未settle会失败、1/50个脉冲
计数、零周期及trace replay分支，exit0。独立`startup-reset-diagnostic`只重编
harness并链接v13 archive，**不是fresh完整编译或新全图成绩**。

**新失败证据**：10k诊断运行13.87s，在guest8268/core8264 cycles发生NEMU
CSR mismatch；前19条提交PC/指令/写回一致，首次时序差异为提交17（PC38）
native8258/ref8257，提交19变成PC40/inst0/illegal-instruction异常。RAM DPI
GDB记录包含index8→`0000091300000893`，外部读回正确。
用户提示使用已有Verilator波形/trace后，已用既存FST逐段对照：以timer校准，
本窗口native eval ordinal=reference raw time+2。PC40的missUnit respDataReg
native16584/16586低/高beat均正确；mainPipe s1_datas_r在native16596读到PC0
正确数据，但native16600应读取PC40时全0，对应ref16598的正确
`0000091300000893`。问题已夹在ICache refill写SRAM→读回/选择→mainPipe，
尚无证据修改RAM DPI或宽值拼接。read-only静态审计未发现DPI/respDataReg漏激活。
下一步采样SRAM前四行、读地址及IFU状态，先定位具体首次差异再准备v14。
证据：`startup-reset-diagnostic/{debug-ram.log,native-state2.events.tsv}`、
`reference-roi/{calibration,icache,icache-array,ifu,ifu-internal}.{signals,events}.tsv`、
`dpi-schedule-audit.md`。早先native-state.events.tsv是60s截止的过宽GDB采样，
未到故障窗口，不能作为该比较依据。

**SRAM根因 / 隔离验证**：后续`native-state4.events.tsv`与
`native-sram.events.tsv`显示bank0 way0行0..3始终为0，PC40编码写数据
`0x244c0000224c`已到达，但`RW0.wmode`恒0。源FIRRTL的
`eq(io.broadcast.ram_hold, 0)`在生成代码中成为0，因此写mask从未有效。
逐层追踪发现最顶层`XSTop`将`core_with_l2.io.dft.ram_hold`标为invalidate；
v13用`invalid_policy=unknown`先按四态折叠`eq(X,0)=X`，再两态投影得到0。
Verilator参考先将源invalid取0，得到`eq(0,0)=1`。这是策略/投影时机差异，
并非DPI、66bit拼接、masked write提交或逐行activation缺陷。

按用户建议，原样提取`SRAMTemplate_4`和其256×66单端口SRAM，使用相同激励
对照既有firtool生成SV的Verilator模型：unknown策略下bare/显式hold0均
67次读回全匹配，只有invalid hold的67次全失败；同一driver与gold保持不变，
新目录改用zero策略后3组均67次全匹配、exit0。测试包含PC40写行1、写行0后
重读行1、66bit高位及重复high eval。最初提出改变Make流程默认invalid策略，
已按用户要求撤回；改用本次FIRRTL ingest请求中的显式zero参数，通用unknown
默认保留。额外literal `1'bx` gold对照也得到同样结果，原始gold的ram_hold取0
另由冻结`verilator-default/rtl/rtl/XSTop.sv:1883`证实。
证据：`icache-sram-isolated/{README.md,result.log,result-zero.log,observations*.tsv}`、
`icache-sram-root-cause.md`。下一步使用fresh v14进行全核100k正确性验证，
隔离结果不充当全核验收成绩。

以下当前状态截至 **2026-11-11 清理提交阶段**：v14生成、activation、fresh完整
编译、100k NEMU功能及精确提交比较均已通过。原trace脚本postflight因合法PERF
指标名误报而exit2，该原状态保持不变；新增独立补充校验audit-trace与compare
均exit0，不重跑模拟器、不改冻结控制。未插桩性能触及152.190s硬截止，未达100k；
用户决定以正确性通过完成F24，将性能移出本阶段验收门，不再继续性能实验。
fixture生成/执行、安装、请求准备及snapshot不计入正式生成或fresh完整编译。

| 当前任务 | 阶段 / 结果 | 累计墙钟 | 本阶段耗时 | 硬预算 / 结余 |
| --- | --- | ---: | ---: | ---: |
| v14 FIRRTL → C++ | **22/22完成并完整发布，exit0**；显式请求选择invalid-zero，init保持unknown | pipeline **825.050s**；Make run **826.12s**；service **826.294s** | emit **281.569s** | **840s / service余13.706s** |
| v14 activation边数 | **充分不等式通过，target exit0**；新identity、完整publication和GSIM inventory/stats独立核验 | census **15.04s** | V=774531、Sc=0、Sw=189719、P=894；U=964250，U+P=965144 | 均≤ **2193888** |
| v14 fresh完整C++编译 | **完整成功**；wrapper/monitor/source verification均exit0，freshness及身份核验通过 | payload **305.71s**；service **305.837s**；结束07:24:02.72 UTC | **403 model / 41 harness**、PCH、archive、link及target全部完成；emu **119,876,608 B** | **330s / service余24.163s** |
| 显式请求 / workflow | **85项通过**；prepared request经canonical22阶段并实际编译/执行小模型 | **20.012s** | 验证参数优先级、top/输入拒绝、harness与generation identity | 通用unknown默认及16MiB/32GiB默认保留 |
| native 100k功能 / trace | **v14通过**；emu/Make/service均exit0，补充audit-trace/compare均exit0；原trace脚本exit2误报记录保留 | emu **194.96s**；service **195.140s**；运行结束07:29:48.96 UTC | NEMU无差异、冻结endpoint一致；**231,568 commits**及commit.trace/commit.tsv/summary.json三项精确cmp全0 | emu timeout **600s**；此采集耗时不作未插桩性能成绩 |
| native未插桩性能 | **152.190s超时，性能未通过；按用户决定移出F24完成门** | service **152.324s** | 最后报告70k cycles，emu137、Make/service2；未继续等待或重跑 | cap保持 **152.190s** |

v14使用原始冻结FIRRTL和现有native ingest选项，不修改XiangShan RTL或新增
harness绕过。`ingest-request.json`与规范化`sources.json`逐字节一致，原始请求、
实际producer输入及其哈希均已冻结；实际加载库、源码和producer-final identity
核验通过。22阶段start/done与计划逐项匹配，完整发布409文件、403 TU、57,968函数，
正文 **6,713,031,849 B**。生成cgroup peak **108,162,514,944 B（100.734 GiB）**，
swap0，memory.events的max/oom/oom_kill均0，独立sidecar确认资源约束生效。
外层`generation-time.txt`记录 **828.32s**，包含harness准备和service包装；它不与
pipeline、Make run或受控service计时混用。生成、activation通过均不替代全核正确性。

fresh编译service为`wolvrix-capped-6057a7f7abaa4f2bb8aeb543cd86fbc0.service`，
于07:18:56.935 UTC启动、07:24:02.72 UTC结束，保持24共享jobs、128GiB/swap0
及330s硬截止。payload **305.71s**、service **305.837305s**；403个模型对象、
41个harness对象、PCH、archive、最终link及target均完成，emu为原始v14目录的
**119,876,608 B**链接产物。cgroup peak **14,615,396,352 B（13.611 GiB）**，
swap0，max/oom/oom_kill均0；wrapper、fatal monitor、source verification三项
均exit0，freshness、资源enforcement及postflight身份核验通过。

trace使用本轮原始emu、CPU2单线程和NEMU，在100k窗口采集完整提交，模拟器
timeout为600s。emu、Make和受控service均exit0，emu **194.96s**、service
**195.140s**，于07:29:48.96 UTC完成；guest/core cycles **100001/99996**、
instrCnt **238535**、terminal PC **0x80000cde**与冻结参考完全一致。
cgroup peak **100,110,336 B（95.47 MiB）**，swap0、max/oom/oom_kill均0。

原`run-trace-returncode.txt`仍为 **2**：postflight的`[Mm]ismatch`扫描误命中
45条合法`[PERF ]`数值指标（如`ras_top_mismatch`），参考也有相同45条，非PERF
失败marker为0。原控制、状态及运行证据保持不变，不能声称原trace脚本exit0。
新增`v14-validation/`独立Make流程，只豁免完整数值PERF记录的精确语法，8个
正反例通过；controls独立冻结，保留全部endpoint、时间、资源及身份要求。
`audit-trace`与`compare`均exit0，复核同一raw、原始exe、完整publication、源码/
实际加载库及运行前后哈希；没有重跑参考或native模拟器，也未改写原freeze。

补充流程用原exporter导出的`commit.trace`、`commit.tsv`、`summary.json`与
冻结参考逐项`cmp`，全部exit0。独立comparer确认 **231,568 commits**、cycles
**568..99996**，architecture、timing、inactive writeback及nonarchitectural detail
差异均0，`text_bytes_equal=true`，全序列长度相等。由此判定本轮100k功能及精确
提交门通过，不声称两轮CoreMark完整执行结束。性能运行使用同一exe，关闭
trace/wave/profile及log窗口观测，在 **152.190s** 模拟器硬截止处被终止，
未完成100k；此结果保留，按用户决定不再阻塞F24完成。

以下v12/v11细节及后文各轮记录保留为历史。v12生成和失败编译两项payload累计
1116.24秒；失败前耗时不作为完整编译成绩。v12独立retry目录仍为未执行准备，
不刷新其旧freeze，也不复用为v14成绩。

v12于 **02:51:47.55 UTC** 正式开始，840s截止为 **03:05:47.55 UTC**，service为
`wolvrix-capped-7b8454c842564e5fb0d974f9c217b2f2.service`。本轮仅将已有
`XS_GRHSIM_MAX_TU_BYTES` 从 **1 MiB** 调为 **16 MiB（16777216 B）**，
不修改源码或重装库；FIRRTL及native-before哈希与v11一致。32GiB单文件磁盘门限、
128GiB/swap0、840s生成、330s完整编译和24共享jobs均不变，生成与编译顺序执行。
依据是下文的小样本前端成本测量；本轮完整编译仍未通过。

### v12生成与编译的最终结果

生成pipeline total **794.982 s**、Make run **795.46 s**、service含启停/取证
**795.617 s**，三个口径分开保留。emitter **278.869 s**；正文仍为
**6,713,541,941 B / 57,964个函数**，TU从v11的 **7187** 降至 **403**，没有
减少模型计算正文。完整22阶段顺序检查为true，nonsink报告与v11逐字节一致，结束时
native库SHA与冻结值一致。生成聚合内存峰值 **116,206,231,552 B（108.225 GiB）**，
swap0，memory.events的max/oom/kill全0。最终activation统计、输入及generation
identity已独立核验；publication上界 **964386**，含pulse **965280**，与v11不变。

fresh完整编译于 **03:07:56.419 UTC** 正式开始，service截止为
**03:13:26.419 UTC**，unit为
`wolvrix-capped-e94d1ec30c8148d997c9d3133959e2bb.service`。范围仍是全部model、
PCH、harness、archive、最终链接和target完成，24共享jobs、128GiB/swap0；
累计时间从本轮payload Make启动计，不混入已完成的生成或v11试跑时间。

payload在 **320.78 s** 后正常非零退出，service含启停/取证 **320.935 s**，
stop sidecar时点为 **03:13:17.284 UTC**，终态 `Result=exit-code`、exit2；
这是**编译错误，不是330s超时**。全部 **403** 个模型对象和
`model/libgrhsim_SimTop.a` 已产出，harness在 `grhsim.h` 访问
`difftest_uart_out_valid` 等成员时报错：FIRRTL转义点号端口的C++成员名与SV
flat difftest端口名不一致。未执行最终链接，未产出可运行emu，不能据此判定
完整编译达标或开始native 100k/trace/性能测量。模型、harness并行编译，
没有各自独立的墙钟记录，不能把320.78s称作单独模型编译耗时。

编译聚合内存峰值 **14,968,942,592 B（13.941 GiB）**，swap0，memory.events
的max/oom/kill全0。当时harness接口适配通过局部回归，byte-unpack生命周期UB尚待
修复；随后修复已通过fresh ASan并安装，v13已重新生成且完成fresh完整编译。
这些后续结果不改写v12编译失败的历史，v13运行也未通过正确性门。
v12独立attempt2未执行，其旧控制freeze随root Make变更失效，不刷新掩盖。

### v11基线的最终结果与计时证据

v11于 **02:16:44 UTC** 开始，生成截止为 **02:30:44 UTC**；最后一个pipeline
阶段于 **02:29:57.36 UTC** 结束，Make run于 **02:29:58 UTC** 退出。
pipeline计时 **793.727 s**，Make run **794.22 s**，service含启停/取证
**794.391 s**，这三个口径分开保留。nonsink / sink分图分别为
**58.638 s / 50.336 s**，emitter内readable dump为 **72.757 s**。

完整编译于 **02:33:21.99 UTC** 启动，service于 **02:38:51.99 UTC** 达到
330s截止并整组SIGKILL，stop sidecar于 **02:38:52.298 UTC** 保存；wrapper
总墙钟 **330.3918 s**。unit为
`wolvrix-capped-dbef184a953843958dc30f19dca66032.service`，终态
`Result=timeout`、`RuntimeMaxUSec=5min 30s`、`RuntimeRandomizedExtraUSec=0`、
`KillSignal=9`。聚合内存峰值 **9,776,091,136 B（9.104 GiB）**，swap0，
memory.events的max/oom/kill全0；这是**时间超限，不是OOM**。截止覆盖全部模型、
harness及最终链接，但本轮只到对象编译；完成数量不包含仅发出命令但尚未产出的对象。

`compile-build-time.txt`为空，因为服务内time进程也被硬杀；不能据此虚构完整
编译耗时，更不能把wrapper的330.3918s当作编译完成成绩。超时与资源证据由独立
recorder的 `compile-resources.json`、start/stop sidecars及编译日志保留。

v11**生成**聚合内存峰值 **106,919,407,616 B（99.576 GiB）**；独立cgroup上限
**128 GiB**，swap0，memory.events的max/oom/kill全0。结束时已安装库SHA与冻结
值一致。生成与编译顺序执行，期间仅有一份全图负载。正式model包含 **10,025,742,118 B** code-map、
**8,298,927,192 B** readable graph、**65,171,394 B** manifest。

code-map把C++函数、变量和存储位置对应回IR实体及RTL来源；readable graph展示
完整IR、分区和调度，manifest是文件/函数清单。它们用于调试，不参与仿真执行；
当前生成计时包含全部这些默认产物，文件流式写盘。

v11相对v10的唯一配置变化是显式允许单个磁盘artifact最大 **32 GiB**，解决v10的
code-map超过默认4GiB检查；映射仍流式输出，不整份驻留内存。不修改通用默认值、
生成代码、分图或调度；128GiB、840s、330s和完整负载不变。

v11证据在 `ptmp/firrtl-ingest/F24/full-native-v11/`：`command.txt`、
`driver.log`、`logs/xs_firrtl_stage_full-native-v11.jsonl`、
`generation-resources.json`及其start/stop sidecars。

## 各项验收离通过还差什么？

| 验收项 | 有效对照 / 门槛 | 当前证据 | 判定 |
| --- | --- | --- | --- |
| canonical全图生成 | 同输入GSIM **779.02 s**；1.1×为856.922s，native采用更紧 **840 s** 截止 | v14完整22阶段，pipeline **825.050s**、Make run **826.12s**、service **826.294s**；原始请求、源码、实际加载库及producer-final identity核验 | **v14通过** |
| fresh完整C++编译 | 同输入GSIM **300.63 s**；1.1×为330.693s，native采用 **330 s** 截止 | v14 payload **305.71s**、service **305.837s**，403 model/41 harness、PCH/archive/link/emu完整；freshness、身份与资源终态通过，三项exit0 | **v14通过** |
| activation边数 | 同口径native ≤ GSIM ×1.5 | GSIM确认下界 **1,462,592**；v14保守上界U=**964,250**，含pulse **965,144**，均≤**2,193,888**；新身份/publication/GSIM inventory与stats独立核验 | **v14充分不等式通过** |
| 100k功能 | NEMU无mismatch，完整100k-cycle window | v14 emu/Make/service均exit0；guest100001/core99996/instr238535/PC0x80000cde完全匹配；原脚本exit2误报保留，补充audit-trace exit0 | **v14通过** |
| 提交行为 | 与冻结参考有序commit trace匹配 | v14 **231,568** 条提交；commit.trace/commit.tsv/summary.json逐项cmp全0；独立comparer架构/周期/inactive/detail差异全0、text字节相等；补充compare exit0 | **v14通过** |
| 单线程性能 | 原要求CPU2、相同负载、观测关闭，≤ **152.190 s** | v14触及152.190s硬截止，最后报告70k，未达100k；用户明确停止性能工作并以正确性完成F24 | **未达标，移出F24完成门** |
| 资源隔离 | 单个全图任务，128GiB、swap0，记录器独立存活 | v14生成peak **100.734GiB**、编译peak **13.611GiB**、trace peak **95.47MiB**、perf peak39,698,432 B；均swap0、max/oom/oom_kill为0；perf截止立即杀死 | **资源约束通过** |

局部测试、阶段到达、部分C++文件写出不能替代整体验收。超时立即终止并优化，
不提高时间/内存预算，不缩短workload，不用增量编译代替fresh编译。

## 时间和资源按什么口径比较？

| 测量 | 起止范围 | 接受的证据 / 注意事项 |
| --- | --- | --- |
| FIRRTL → C++ | 正式producer开始至全部22阶段及完整发布结束 | Make run累计墙钟和22对pipeline start/done；包含生成identity，自动JSON checkpoint/roundtrip关闭 |
| 完整编译 | service payload Make开始，经过harness预检、PCH、全部model/harness对象、archive、最终链接和target完成 | 成功须有build-time与service终态；被硬杀时time可为空，以独立资源报告证明失败。无旧对象/PCH/archive/emu，Clang22.1.2，**24个共享jobs** |
| 仿真性能 | 服务内time包围模拟器；100k cycles、CPU2、seed0、reset50、NEMU开启 | trace/wave/progress/profile关闭；采集trace/FST的耗时不作性能基准 |
| 聚合内存 | 独立workload cgroup全部进程的记账内存 | resources JSON的peak/events；外层GNU time的child RSS不能代表systemd workload |

生成watchdog为 `timeout --signal=KILL 840s`。完整编译同时使用service
`RuntimeMaxSec=330s`、`RuntimeRandomizedExtraSec=0`、`KillSignal=SIGKILL`、
`KillMode=control-group`，覆盖嵌套进程组，外层recorder独立存活。wrapper的
service启停/取证时间与编译payload墙钟分别记录，不混作编译成绩。

JSONL的 `scope=pipeline` 只记录正式22阶段；验证重建用 `scope=verification`。
父Make另记 `scope=run` start/exit、command/tee状态及累计墙钟。失败记failed，
不记done；子进程被杀后以父run/service取证，缺少exit不能算成功。840s截止后的
记录/清理开销不意味着允许producer继续工作。

## 编译瓶颈、TU尺寸和代码体积的依据是什么？

### 与GSIM相比，TU及生成代码到底多大？

| 尺寸口径 | GSIM同输入基线 | Native v12 |
| --- | ---: | ---: |
| 配置分文件阈值 | **8 MiB**（cpp_max_size_kb=8192） | **16 MiB** |
| 模型C++ TU数 | **240** | **403** |
| 实际TU平均 / 中位数 / 最大 | **9.482 / 8.606 / 39.940 MiB** | 平均 **15.894 MiB**；其余待尺寸审计 |
| 全部模型.cpp字节 | **2,386,301,976 B** | **6,716,414,457 B**，约 **2.815×** |
| 共享模型头文件 | **64,540,437 B** | **569,865,099 B**，约 **8.830×** |

阈值与总代码量是两个问题。GSIM在允许的边界换文件，8MiB是近似阈值而非文件
硬上限（`reference/gsim/src/cppEmitter.cpp`的`__emitSrc`）；native阈值更大，
仍因源码总量更多而产生更多TU。上表源码字节包含注释、可读标识符、禁用宏块等，
不能直接等同于编译器实际处理的有效代码量，也不包含code-map/readable graph。
下述历史实验测量了16/32/64MiB的相同函数样本，并审计TU119/186尾部及源码体积
构成；未据此手工更改正式模型，也未将局部成本实验算作fresh完整编译。

流式审计已确认，native共享头的 **421,470,545 B（74.0%）** 是注释，
GSIM为 **14,870,660 B（23.0%）**；剔注释后头文件比降至 **2.99×**。
native重复的绝对来源路径前缀占 **123,338,538 B（21.6%）**。分层TU样本中，
native注释占41.1%，GSIM完整禁用ENABLE_LOG块占24.5%；这些是样本比例，
不能推广为全体.cpp的精确比例。样本中GSIM标识符字节反而更多，不能把差距
归因于native名字整体更长。剩余声明/存储结构差距见下，不能只用raw字节推导
运行时计算量。证据：`ptmp/firrtl-ingest/F24/cpp-volume-v12/`。

结构统计补齐：native为 **990,235个store字段声明 + 716,042个helper/frame字段
声明**，GSIM根类为 **491,997个数据成员声明**。native大项含nonsink boundary
375,621、small/large captured payload 201,340/179,806；frame中writer batch
584,264、nonsink 130,030。frame用于拆分函数的传值/局部存储，不等于新增持久
state副本。已有emit日志中nonsink和General writers分别占raw正文46.4%/41.6%，
包含声明与注释；只能作为代码组织归因，不能等同于有效执行工作量。

### v12更大TU与尾部探针

| 同一组v12 TU100–103函数 | 单job总墙钟 | 前端 / LLVM优化 | 峰值RSS |
| --- | ---: | ---: | ---: |
| 4个约16MiB TU | **12.03 s** | **6.318 / 3.181 s** | **1.403 GiB** |
| 2个约32MiB TU | **9.25 s** | **3.742 / 3.343 s** | **1.525 GiB** |
| 1个约64MiB TU | **8.00 s** | **2.485 / 3.505 s** | **1.783 GiB** |

三个成本实验加两个syntax-only探针共 **32.54 s**；每case60s、尾部语法30s
硬截止，单job/8GiB地址空间限额，无全图并发。首TU100对象与原v12对象逐字节
一致，原9个输入的哈希/大小/mtime未变。32/64MiB局部收益分别1.30×/1.50×，
额外收益递减且优化时间略升；不据此预测全图24jobs或慢函数的收益。

TU119/186的syntax-only仅 **1.60 / 1.66 s**。TU119的`sn_13436`约500行，
旧对象中该函数机器码 **893,998 B**；其中有4096次循环，每次对4096位scalar
动态移位再取1bit。其未优化bitcode生成 **1.64 s**，LLVM default<O3> **0.19 s**；
单函数llc在 **30s** 硬截止时仍处于 **X86 DAG->DAG Instruction Selection**，
已定位到后端指令选择阶段，不能把这段长尾称为前端或LLVM中端优化问题。
30s整组SIGKILL使内层time未完整写出，未声称llc的峰值RSS。

在现有byte-layout约束下的unsigned bool unpack按字节取位变体已取得局部成本
和O1执行结果，但独立review确认其bytes pointer跨helper形成stack lifetime UB，
不能称为修复完成。后续已改为循环RHS直接引用scalar，使liveness提升scalar本体，
并通过fresh ASan + `-fno-inline`两预算验证及安装；v13全图生成和fresh完整编译
已通过，v14也已完成本轮fresh完整编译、100k NEMU功能及精确提交匹配。
局部成本结果不替代这些验证；v14性能超时结果已独立记录，用户将其移出F24完成门。
唯一一行差分变体正常O3编译 **1.59 s**，机器码从 **893,998 B降至1,475 B**，
RSS **1.278 GiB**，前端/IRgen/LLVM优化/机器码生成分别
1.3838/0.1330/0.0162/0.0054s，支持该宽动态移位是后端热点。
production分支只覆盖TwoState unsigned bool、target>64、sourceWidth>=target.width；
不改变pack和其它叶宽，遵循原地读取/调用方输出数组策略。完整生成与整机验收
必须重新进行，旧模型不被手工改写。证据：`compile-probes-v12/`和
`compile-probes-v12/tail119-pass/`。

FIRRTL专用Make默认已设为16MiB TU/32GiB单文件产物限额；SV/API/reemit默认仍
为1MiB/4GiB。共享CLI > 专用CLI > 专用环境 > 共享环境 > FIRRTL默认；原81项
workflow测试（含20组真实argv mock矩阵）于17.85s通过。加入显式prepared request
入口后的最新suite为 **85项、20.012s通过**，请求选项优先于旧Make ingest默认，
通用invalid/init unknown策略及128GiB cap不变。
证据：`production-default-proposal/workflow-tests{.log,-time.txt}`、
`prepared-ingest-request-tests.log`。

### v11从1MiB到16MiB的依据

**已测热点是每个TU重复的编译前端工作。** v11有 **7187** 个TU，共享header
**569,865,099 B**、PCH **348,379,416 B**。单个TU1000实测总墙钟 **1.63 s**；
Clang report总计1.5819s，其中前端 **1.3736 s（86.8%）**，LLVM优化仅
**0.0517 s**。time trace的ReadAST约 **6 ms**，不能将热点描述为PCH文件读取I/O。

| 相同输入函数集合 | 分开编译的总墙钟 | 合并为单TU的墙钟 | 观测加速 | Frontend trace事件汇总 |
| --- | ---: | ---: | ---: | --- |
| 4个原TU | **6.25 s** | **1.80 s** | **3.47×** | **5.698 s → 1.506 s** |
| 16个原TU | **25.19 s** | **3.02 s** | **8.34×** | **22.693 s → 1.844 s** |

表内trace事件汇总与Clang report口径不同，不相加。report的Front end墙钟分别为
4TU **5.2839s → 1.3883s**、16TU **19.9831s → 1.6647s**；两种口径均指向
前端重复成本随TU合并而下降。

这些实验都通过 `compile-probes/Makefile` 执行，保留正式 **-O3 / native /
fno-strict-aliasing**、同一PCH和单job；每次有60s timeout及 **8 GiB虚拟地址
空间限制**，这不是cgroup内存上限。merged16峰值RSS **1,463,144 KiB
（约1.395 GiB）**。TU1000 probe对象与v11对应原对象逐字节相同。

同一函数集合的合并结果证明可减少重复前端成本，支持用既有16MiB TU设置做下一轮
正式测量；它不证明全图330s必然达标。merged对象仅用于成本实验，不能替代整机
功能验收；v12生成已通过，完整编译因接口错误失败，修复后仍须fresh完整编译
及100k功能/性能验收。
证据在 `ptmp/firrtl-ingest/F24/compile-probes/` 的 `Makefile`、`summary.json`及
`single-1000/`、`serial4/`、`merged4/`、`serial16/`、`merged16/`。

## 输入、工具和参考机是否可比？

| 项目 | 冻结身份 / 约束 |
| --- | --- |
| native / GSIM FIRRTL | `build/xs/rtl/rtl/SimTop.fir`，**1,671,325,062 B**；SHA256 `b313a3ecd154cbd9279b14403709806b95fb136cf44b475e9def46a926ecb26b` |
| v14显式ingest请求 | `full-native-v14/{ingest-request.json,sources.json}`，两文件逐字节一致；invalid_policy=zero、init_policy=unknown、lower_threads=10；原请求和实际归一化输入哈希分别冻结 |
| harness | `ptmp/firrtl-ingest/F24/full-native-capped/harness-inputs/generated-src`；每轮捕获snapshot/build identity |
| native工具链 | Clang/Clang++ **22.1.2**；C++20、`-O3 -march=native -fno-strict-aliasing`；PERF/SN_TIMING/WAVEFORM=0，无PGO/对象缓存 |
| v11 / v12已装库 | 与v10相同，无源码重装；各轮 `native-before.sha256`及早期generation identity记录路径/哈希，v11/v12生成结束核验一致 |
| v14实际生产者 | `full-native-v14/{snapshot.json,native-before.sha256,xiangshan_grhsim.generation-identity.json,model/generation-identity.json}`；记录实际加载库/源码，保留既有生命周期修复；本轮无新增XiangShan RTL/harness修改 |
| 默认Verilator | XiangShan clean HEAD `faa4aeacb9776c369c902409ae5130d1fa36c0f6`，DiffTest clean `ee3eee0788384fd819bd3792425f4817b1992eb8`；firtool1.135.0，Verilator5.051 devel |
| workload / 状态 | `coremark-2-iteration.bin`、冻结NEMU；CPU2、单线程、seed0/reset50、max-cycle100000 |

Verilator输入明确**不使用 `preserve-aggregate=all`，沿用上游默认配置**；不加
兼容/优化绕过参数，不改工具或输入来建立偏慢基准。入口为
`make xs_ref_rtl xs_ref_emu`，reference与aggregate SV目录分开，拒绝复用带
preserve-aggregate的生成记录。旧aggregate配置下的断言失败不作为默认Verilator
故障结论，早期170.xs记录也不再作为当前门槛。

native/GSIM使用相同冻结FIRRTL；新默认reference的FIRRTL **字节不同**。CPU相关
输入身份关系已有单独审计，不能把哈希不同的文件称为同输入；最终行为及性能
判定仍须结合NEMU、端点和提交序列。详见
`ptmp/firrtl-ingest/F24/resume-audit/reference-input-audit.md`。

默认reference已通过：Host **152.190 s**，guest/core cycles **100001/99996**，
instr **238535**，PC **`0x80000cde`**，exit0；停止于100k窗口，不宣称两轮
CoreMark完整结束。trace序号 **0..231567**、cycles **568..99996**，独立trace
与波形采集的提交记录逐字节相同。FST约 **1.18 GiB**、1ps、范围 **0..200101**，
包含复位及两半周期。完整身份与采集说明在
`verilator-default/{report.md,commit-trace/,waveform/README.md}`。

## 固定流水线及实现决策是什么？

生产入口 `make xs-firrtl-grhsim`；下列阶段不得省略，按编号顺序执行。

```text
 1 ingest-firrtl                12 dead-code-elim
 2 xmr-resolve                  13 alias-analysis
 3 hier-flatten                 14 pattern-detect
 4 comb-loop-elim               15 comm-expr
 5 split-static-array          16 dead-code-elim
 6 dead-code-elim               17 grhsim-dialect-translate
 7 expr-opt                     18 split-event-and-output
 8 used-bits                    19 split-nonsink-and-sink
 9 split-nodes                  20 partition-nonsink
10 dead-code-elim               21 partition-sink
11 constant-analysis           22 emit-grhsim-cpp
```

| 问题 | 已采用的实现 / 必须保留的语义 | 测量或验证依据 |
| --- | --- | --- |
| DCE高fanin重复工作 | 全位需求内联allBits；concat范围线性映射；区域需求与共享constant-index规则 | DCE首轮stage **491.835s** → v2 **68.624s**；不能只归因于单项 |
| shape / indexed demand / 借用span导致非法类型 | 标量bit view清除shape；索引保活；递归/arena扩容前保存IDs/attrs；选择缓存不存depth0 no-op | 原图Oracle、完整校验、signed/unsigned/unknown与递归选择回归 |
| 四态算术错误窄化 | Add/Sub/Mul prefix优化限TwoState，FourState保留完整输入及未知传播 | preserveUnknowns Oracle、TwoState穷举 |
| CommonExpr / ConstantAnalysis非线性工作 | 浅结构签名+ordered child IDs+显式后序；就绪计数按operand use | SemanticIds/origin并集、顺序、fanout与循环拒绝均保留 |
| 转换helper / 语义池爆炸 | 完整event key共享detector、有序OR前缀共享join；唯一helper外部累计provenance，最后一次发布 | v6语义池失败；v7转换 **14.140s**、rewrite **1.232s**、detector422 / join46 |
| GSIM node语义对齐 | SemanticTree Declaration/Expression family，Field/Element归原family，实例隔离；clone保留op/value SemanticIds | `semantic-tree-mffc-v1`；最新 **2,190,614** activity nodes / **21,110** supernodes |
| nonsink重复quotient构造 | 容器机械优化；clusters未变时跨mode/round复用，成功contraction后失效；保留候选/成员/拓扑顺序 | nonsink v9 **136.180s** → v10 **58.908s**；v8/v9报告相同，v10/v11报告相同 |
| sink schedule展开闭包占内存 | 唯一字典+CSR DAG+每run直接roots，完整闭包按需恢复；verifier仍重建完整契约 | **144,602** runs / **919,570** roots；v10 DAG **2,190,614** nodes / **3,456,954** edges；压力例持久条目<展开的1/16 |
| 静态局部写引入整数组旧值依赖 | 相交DriverPieces高到低组成旧目标片段；保留最终整体物化、动态路径和guard/覆盖/mask规则 | v10正文 **6.714GB**；此规模不等于编译/运行通过 |
| emitter宽值及重复扫描 | 私有宽常量leaf literal/RLE、显式写零；反向use worklist；单元素copy/emitLeaves特化 | analyze v9 **54.409s** → v10 **20.447s**；控制/跨owner/永久阻塞、helper ABI及4096配额保留 |
| workflow清理和恢复身份 | 删除退役benchmark脚本；中央表/Make guard拒绝10项旧设置（含空/0）；prefix身份区分pre/post-opt | 80项workflow；旧v3及更早nonsink缓存须从split重建，不能仅重建schedule |

canonical新名保留旧API/checkpoint别名，emitter不是普通rewrite pass。分图缓存
配置为 `v4/.../semantic-tree-mffc-v1`。prefix的inode/mtime/size只作freshness，
输入/库/工具/生成文件的密码学哈希另记，不混用。

## 各轮试跑说明了什么？

本表记录**到成功或失败终点的累计时间**；失败时间不是完成生成的成绩。v8起为
独立128GiB/swap0 cgroup，更早轮次的资源口径不同，峰值不直接比较。

| 轮次 | 累计producer / run时间 | 终点 / 结论 | 关键测量 | 证据目录（F24/下） |
| --- | ---: | --- | --- | --- |
| v1 | **673.40s** | split-nodes shape校验失败 | DCE491.835s，未到emit | `full-native-capped/` |
| v2 | **394.96s** | 转换前完整校验发现30个非法Assign | DCE68.624s；轻量校验不等于完整校验 | `full-native-v2/` |
| v3 | **151.79s** | split-static-array选择缓存失败，exit134 | 尚未进入UsedBits/SplitNodes | `full-native-v3/` |
| v4 | **841.41s** | 840s截止，转换rewrite未完成 | 转换约430s | `full-native-v4/` |
| v5 | **841.34s** | 840s截止，转换rewrite未完成 | 准备累计5.041s；rewrite约444s | `full-native-v5/` |
| v6 | **520.82s** | SemanticId pool capacity，正常非零退出 | detector452803 / join146013 | `full-native-v6/` |
| v7 | **无完整终态** | systemd-oomd杀原scope及记录器，不判为timeout/成功 | scope160.2GiB；nonsink140.659s | `full-native-v7/`、`memory-audit/v7-oomd.log` |
| v8 | **841.91s** | 840s截止，emitter未完成 | nonsink141.098s / sink55.037s；peak111.37GiB，无OOM | `full-native-v8/` |
| v9 | **841.86s** | 840s截止，emitter writer阶段 | nonsink136.180s / sink55.722s；peak114.78GiB，无OOM | `full-native-v9/` |
| v10 | **719.57s** | 完整code-map超默认4GiB，未发布model | nonsink58.908s / sink50.278s；peak106.59GiB，无OOM | `full-native-v10/` |
| v11生成 | **794.22s** | **完整22阶段生成成功；activation充分不等式通过** | emit277.799s；peak99.576GiB，无OOM | `full-native-v11/` |
| v11编译 | **330s硬截止**；wrapper330.3918s | **超时SIGKILL，未归档/链接**；不能作为完整编译成绩 | 模型对象2253/7187（31.35%）；peak9.104GiB，无OOM | `full-native-v11/compile-*` |
| v12生成 | **795.46s** | **完整22阶段生成成功；activation充分不等式通过** | TU403，正文/函数数不变；peak108.225GiB，无OOM | `full-native-v12/` |
| v12编译 | **320.78s**；service320.935s | **harness接口错误exit2，非timeout**；未链接/无emu，完整编译失败 | 模型对象403/403及archive完成；peak13.941GiB，无OOM | `full-native-v12/compile-*` |
| v13生成 | **807.66s**；service807.838s | **完整22阶段生成成功；activation充分不等式通过** | emit280.919s；peak105.988GiB，无OOM | `full-native-v13/` |
| v13 fresh编译 | **314.96s**；service315.085s | **完整archive/link/emu成功，exit0** | 403模型TU、41 harness对象；freshness/身份核验通过 | `full-native-v13/compile-*` |
| v13正确性诊断 | **13.87s**（复位修复后的诊断） | **PC40非法指令，未通过100k**；SRAM invalid控制根因已由golden FST和原模块隔离确认 | 原始SRAM invalid-unknown 67次读回全失败，显式zero 3组各67次全匹配 | `startup-reset-diagnostic/`、`reference-roi/`、`icache-sram-isolated/` |
| v14生成 | pipeline **825.050s**；Make run826.12s；service826.294s | **完整22阶段发布成功，exit0；新请求/原始身份核验通过** | emit281.569s；403 TU、57,968函数；peak100.734GiB，无OOM | `full-native-v14/` |
| v14 activation | census **15.04s** | **target exit0，独立身份与GSIM inventory/stats核验通过** | U=964250，U+P=965144≤2193888 | `full-native-v14/activation-*` |
| v14 fresh编译 | payload **305.71s**；service305.837s | **完整archive/link/emu成功，三项exit0**；freshness/身份/资源终态核验通过 | 403 model/41 harness；peak13.611GiB、swap0，无OOM；emu119876608B | `full-native-v14/compile-*` |
| v14 trace / 运行 | emu **194.96s**；service195.140s | **emu/Make/service exit0，100k/NEMU及精确trace通过**；原脚本exit2为45条合法PERF指标误报，原证据不改写 | 231568 commits，3项cmp全0、独立comparer全等；补充audit-trace/compare均0；peak95.47MiB，无OOM | `full-native-v14/{run-trace-*,commit-trace/,trace-comparison/}`、`v14-validation/` |
| v14未插桩性能 | **152.190s超时；service152.324s** | 未达100k，emu137、Make/service2，最后报告70k；非精确被杀周期 | 按用户决定不再作为F24完成门，不继续性能工作 | `full-native-v14/run-perf-*`及`v14-validation/` |

## 小图验证覆盖了哪些风险？

| 领域 | 最近有效结果 | 证据（F24/下） |
| --- | --- | --- |
| v13旧variant emitter生成测试 | **旧变体exit0，27.61s**；其中CTest **3.43s**，不能排除已确认的跨helper生命周期UB | `validation/v13/emitter-generate{.log,-time.txt}` |
| v13旧variant生成模型执行 | **旧变体12/12 exit0，仅保留为旧结果、不足以认证修复**；O1、4并行jobs，总 **731.74s**，GNU time最大child RSS **2,095,928 KiB** | `validation/v13/generated-execution{.log,-time.txt}`；time文件保留完整case命令 |
| byte-unpack生命周期修复验证 | **fresh ASan 2/2通过，6.08s**；b16/b1024两预算，ASan UAR always + `-fno-inline`，scalar本体跨helper保活 | `validation/v13/asan-after/`及`asan-results.md`；before失败复现另存 |
| FIRRTL专用默认 / workflow | **81项通过，17.85s**；16MiB/32GiB默认、共享override与真实argv矩阵 | `production-default-proposal/workflow-tests{.log,-time.txt}` |
| 显式prepared request / workflow | **85项通过，20.012s**；真实canonical22阶段+生成模型执行，eq(invalid,0)==1；提前拒绝top/输入/缺失source/非法policy并验证harness来源 | `prepared-ingest-request-tests.log` |
| 原始SRAM隔离对照 | unknown下仅invalid-hold 67次全失败，bare/显式hold0均67次通过；zero下3组各67次全通过，driver/gold不变 | `icache-sram-isolated/{README.md,result.log,result-zero.log,observations*.tsv}` |
| trace失败marker精确分类 | **8个正反例通过**；仅完整数值PERF记录获豁免，CSR mismatch/disabled/bad trap/assertion/伪PERF仍拒绝；原trace脚本状态2保留 | `v14-validation/{Makefile,markers.awk,marker-check.log,controls.sha256}` |
| v13旧variant库安装 | `make py_install` **exit0**，仅属修复前历史；不认证后续修复 | `validation/v13/py-install{.log,-time.txt}` |
| 生命周期修复后安装 | `make py_install` **exit0，20.22s**；修复后生成测试16.10s、普通fixture执行通过；实际库身份由v13/v14独立冻结 | `validation/v13/{py-install-lifetime-fixed,emitter-lifetime-fixed,lifetime-fixed-execution}{.log,-time.txt}`、v13/v14的`native-before.sha256`与generation identity |
| node / partition / transform / sink | suite通过；容量、等权/重排、CSR/roots伪造拒绝、完整闭包顺序 | `validation/v10-partition-emitter.log`、`validation/compact-sink-schedule.log` |
| emitter实际C++执行 | **14**模型通过，**46.46s**；80/4096-bit、signed叶、24级链、重复use、复用frame、双实例/epoch、storage/boundary/wave/counter/source-map | `validation/v10-emitter-retest.log`、`validation/v10-leaf-models.log` |
| FIRRTL state / memory | 生成与实际模型运行通过，**76.12s** | `validation/v10-firrtl-state-memory.log` |
| aggregate / partial write | 多piece/重叠guard/动态切换/OOB/roundtrip通过；假环先规范化再Oracle，原图/真实环/unknown断言保留 | `validation/v10-aggregate-final.log` |
| 安装后入口 / workflow | 安装 **49.07s**，flow行为与 **80项**workflow通过；22阶段、失败/超时/tee终态、checkpoint恢复 | `validation/v10-installed-workflow.log`、`journal-tests/` |
| 默认reference入口 | **8 + 80项**通过；不传preserve-aggregate/额外Verilator参数 | `validation/reference-defaults.log` |
| 资源机制 | **11项**mock；真实64MiB触顶只杀独立组；2s deadline杀另session子进程且recorder存活，peak17.43MiB、总2.255s | `memory-audit/`、`memory-audit/deadline/report.md` |

v13修复前的12个fixtures为`packed-bool-unpack`、`contiguous-arrays`、`packed-array-constants`、
`arrays`、`static-array-windows`、`dynamic-array-bits`各自的`b16/b1024`版本。
旧O1执行通过不能排除chunk6局部scalar退出后被chunk7解引用的UB，也不能代替
修复后的fresh ASan证据。它们的生成/执行时间不计入正式全图生成或fresh完整编译，也不替代100k门禁；
上述GNU time child RSS不能当作4并行jobs的聚合内存。fixture修正没有放宽
production verifier；详细原因与原失败保留在历史存档。

## 当前阻塞是什么，下一步如何判定？

| 优先级 | 当前问题 | 下一步 / 明确判定 |
| --- | --- | --- |
| 1 | F24已按用户最新口径完成：生成、activation、fresh编译、100k/NEMU及精确trace通过；性能超时但移出完成门 | 完成当前脚本/Makefile/临时产物清理和提交，不再启动性能实验 |
| 2 | 原trace脚本postflight状态仍为2，须保持失败原因与补充验收证据可复查 | 保留45条合法PERF指标误报、原controls/status和新补充controls/audit-trace/compare exit0证据；不改写freeze、不重跑来掩盖原状态，也不把trace采集耗时当作性能成绩 |

边数使用最终emitter的实际publication统计，不能用结构分图边或unique supernode
pairs替代。`U=V+Sc+Sw`及更严格 `U+P` 的充分上限均为 **2,193,888**。
`Sw`混有small-state比较，必须完整纳入；indexed/on-write所有可能state→nonsink
route均计入。充分不等式未成立只表示证明未解决，不直接证明实际比例>1.5；
脚本不会自动认证输入身份或质量门。定义见 [activation边数审计](F24-activation-edge-audit.md)。

当前v14已独立复核原始FIRRTL、显式请求、最终generation identity、实际加载库、
完整publication和GSIM的240个C++文件inventory/stats哈希；GSIM确认下界仍为
1,462,592。本轮V=774531、Sc=0、Sw=189719、P=894，U=964250、U+P=965144。
v11/v12/v13结果分别保留在各轮历史目录，不作为v14成绩。分析脚本保留
`quality_gate_certified_by_script=false`，表示其自身
不替代这份口径审查；本文件的通过判断由身份复核与上述充分不等式共同支持，
不是把保守上界/已知下界之比当作精确实际边数比例。

## 如何复查和继续记录？

以下路径相对 `ptmp/firrtl-ingest/F24/`。执行均通过Make targets，日志/临时文件/
缓存留在ptmp。**后续覆盖更新状态表、验收矩阵及本轮结果行，不再文末追加过程段落。**
每次更新必须有“截至时点、当前阶段、任务累计墙钟、阶段耗时、预算/剩余、已知
结果与缺失证据”；结束时补最终时间、退出原因、资源峰值和门槛判定。

| 要复查的问题 | 证据入口 |
| --- | --- |
| 当前v14显式请求 / snapshot | `full-native-v14/{prepare-request.py,ingest-request.json,sources.json,snapshot.json,helper-source.tar,inputs-before.sha256,native-before.sha256,sources-before.sha256}`；请求与归一化输入逐字节一致，记录原始FIRRTL、源码及实际加载库 |
| 当前v14生成终态 / 原始身份 | `full-native-v14/{command.txt,driver.log,generation-stage-order.json,generation-exit-status.json,generation-time.txt,generation-resources.json,xiangshan_grhsim.generation-identity.json,model/generation-identity.json,freeze-model.log}`及资源start/stop sidecars、stage JSONL；22/22、pipeline825.050s/service826.294s、exit0 |
| 当前v14 activation边数证明 | `full-native-v14/{activation-result.json,activation-comparison.json,activation-analysis-time.txt,activation-identity-checks.log,activation-same-input-evidence.json,activation-evidence.sha256,activation-returncode.txt}`；新publication与GSIM inventory/stats独立复核，census15.04s、exit0 |
| 当前v14 fresh编译终态 | `full-native-v14/{compile-command.txt,compile-freshness.json,compile-fresh-products.txt,compile-driver.log,compile-build-time.txt,compile-resources.json,compile-exit-status.json}`及资源start/stop sidecars、`emu/grhsim-compile/emu`；payload305.71s/service305.837s，三项exit0，完整链接及身份核验通过 |
| 当前v14原始100k运行终态 | `full-native-v14/{run-trace-command.txt,runtime-common.sh,run-trace-time.txt,run-trace-resources.json,run-trace-returncode.txt,run-trace-make-returncode.txt,run-trace-before.sha256,run-trace-after.sha256,logs/xs_grhsim_full-native-v14-trace-100k.log}`及资源sidecars；emu/Make/service exit0，194.96s/195.140s；原脚本postflight状态 **2** 保持不变 |
| 当前v14补充trace验收 / 误报分类 | `v14-validation/{Makefile,markers.awk,common.sh,audit-trace.sh,controls.sha256,marker-check.log,trace-verification.log,trace-audit.sha256,audit-trace-returncode.txt}`；8例通过，45条合法PERF指标/失败marker0，完整endpoint/身份/资源复核且audit-trace exit0，无模拟器重跑 |
| 当前v14精确提交比较 | `v14-validation/{compare.sh,compare.log,compare-preflight.log,compare-returncode.txt,compare-make-returncode.txt}`、`full-native-v14/commit-trace/`及`full-native-v14/trace-comparison/comparison.json`；231568条，3项cmp全0，独立comparer架构/时序/inactive/detail差异0、text相等，补充compare exit0 |
| v14性能超时终态 | `full-native-v14/run-perf-{time.txt,resources.json,returncode.txt}`及原log；152.190s立即杀死，未达100k，用户决定移出F24完成门 |
| SRAM首次差异及原模块隔离 | `icache-sram-root-cause.md`、`reference-roi/{README.md,icache*.tsv,sram-path*.tsv}`、`startup-reset-diagnostic/native-{state4,sram}.events.tsv`、`icache-sram-isolated/`；golden FST沿用原波形，无参考仿真重跑 |
| 显式请求入口最新回归 | `prepared-ingest-request-tests.log`；85项、20.012s通过，不替代全核验收 |
| 旧variant回归 / 安装结果 | `validation/v13/{emitter-generate,generated-execution,py-install}{.log,-time.txt}`；均属生命周期修复前，不认证当前修复，fixtures不计入全图计时 |
| 历史v13正式生成 / 编译 | `full-native-v13/`；生成于04:29:26.99 UTC启动；driver/JSONL/resources及sidecars保留成功成绩，不能代替v14本轮编译或运行 |
| 历史v12生成命令及身份 | `full-native-v12/{command.txt,inputs-before.sha256,native-before.sha256,source-snapshot.tar,xiangshan_grhsim.generation-identity.json}` |
| 历史v12阶段/累计时间与资源 | `full-native-v12/{driver.log,generation-time.txt,generation-resources.json,logs/}`及资源sidecars |
| 历史v12 activation边数证明 | `full-native-v12/{activation-result.json,activation-comparison.json,activation-identity-checks.log,activation-same-input-evidence.json}`；与v11统计逐字节一致 |
| v12编译失败原因 / 最终耗时 / 资源 | `full-native-v12/{compile-command.txt,compile-parameter-audit.md,compile-fresh-products.txt,compile-driver.log,compile-build-time.txt,compile-wrapper-time.txt,compile-resources.json}`及资源sidecars；archive已产出，无最终exe |
| 阶段/累计时间及资源终态 | `full-native-v11/{driver.log,generation-time.txt,generation-resources.json,logs/}` |
| 编译fresh/计时/并行保证 | `full-native-v11/{compile-command.txt,compile-parameter-audit.md,compile-fresh-products.txt}` |
| 编译超时、进度与资源终态 | `full-native-v11/{compile-driver.log,compile-wrapper-time.txt,compile-resources.json}`及资源start/stop sidecars；`compile-build-time.txt`为空，原因见上文 |
| 编译规模与热点输入 | `full-native-v11/model/{grhsim_SimTop.hpp,grhsim_SimTop.hpp.pch,manifest.json}` |
| 单TU / 合并TU成本实验 | `compile-probes/{Makefile,summary.json,single-1000/,serial4/,merged4/,serial16/,merged16/}`；每个attempt保留time/report与对象 |
| 历史v11 trace/perf准备 | `full-native-v11/{run-trace-command.txt,run-perf-command.txt,trace-compare-command.txt,runtime-audit.md}`；准备控制不构成执行成绩 |
| GSIM生成/编译及边数 | `gsim-current-full/`、`gsim-current-compile/`、`activation-audit/gsim-scalar-edges.json` |
| 默认Verilator及trace/FST | `verilator-default/report.md`、`verilator-default/{commit-trace/,waveform/README.md}` |
| 旧判断、已放弃配置、详细修复/测试原因 | [冻结历史原文](F24-history-through-v11.md)，不作为当前结论 |

本文件是当前验收入口；实现契约分别见
[FIRRTL组合语义](../../wolvrix/docs/ingest/firrtl-combinational.md)、
[GrhSIM transforms](../../wolvrix/docs/transform/grhsim-transforms.md)和
[CPU C++ emitter](../../wolvrix/docs/emit/grhsim-cpu-st-cpp.md)。
