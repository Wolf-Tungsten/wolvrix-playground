# F25：XiangShan FIRRTL 仿真性能对齐

状态：进行中。2026-11-11 开始；本阶段沿用 F24 的正确性成果，重新建立当前
源码身份的性能证据。目标是对齐 GSIM 仿真性能，不降低 GrhSIM 的事件、状态、
多轮调度及复杂语义支持能力。

## 固定范围与验收

- 输入为 XiangShan 全图 `build/xs/rtl/rtl/SimTop.fir`，CoreMark 100k-cycle
  窗口。生产入口 `make xs-firrtl-grhsim`。
- 固定流程：ingest-firrtl → xmr-resolve → hier-flatten → comb-loop-elim →
  split-static-array → dead-code-elim → expr-opt → used-bits → split-nodes →
  dead-code-elim → constant-analysis → dead-code-elim → alias-analysis →
  pattern-detect → comm-expr → dead-code-elim → grhsim-dialect-translate →
  split-event-and-output → split-nonsink-and-sink → partition-nonsink →
  partition-sink → emit-grhsim-cpp。
- 从 FIRRTL 到 C++ 的 `t_cpp`、从 C++ 到完整 emu 的 `t_bin` 分别不得超过
  同输入 GSIM 对应过程的 1.1 倍；达到截止立即杀死。既有保守硬截止为
  840s / 330s，不能以生成预算代替编译预算。
- 正确性以 `preserve-aggregate=none` 的 plain SV Verilator 为金标准；使用
  F24 显式 ingest 请求中的 `invalid_policy=zero`，不修改原始 RTL。新模型
  必须重新通过 100k NEMU 和提交行为对比；必要时使用 trace/FST 定位。
- 未插桩性能使用相同 CPU、单线程、seed、reset、NEMU 与 100k-cycle 窗口。
  记录完整 endpoint 和基准差异，不以超时外推、短窗成绩或 trace 耗时判定通过。
- 用户最新顺序：先完整100k性能及独立采样，再做正确性验证，并报告 GrhSIM
  nonsink 耗时与 GSIM 总耗时的关系。另跑同一二进制的完整100k外部采样，
  把采样归因估算和无插桩总时间分开；20k诊断不用于该比较。
- 用户补充要求：**禁止 PGO**。候选和参考均核验无 profile-generate/use，编译
  显式清空 `PGO_WORKLOAD`、`PGO_CFLAGS`、`PGO_LDFLAGS`，设置 `PGO_BOLT=0`；
  不训练 profile，不使用已有 PGO 二进制作为对齐成绩。
- 全图任务串行，独立 cgroup 128GiB、swap0，记录限额生效和内存峰值；日志、
  临时产物放在 `ptmp/firrtl-ingest/F25/`。保留参考证据，及时清理退役实验。

## 起点与证据边界

工作开始时根仓库及子模块无未提交修改，Wolvrix 为 `7ddc456`，GSIM 为
`9e9cbdf`。F24 完成情况见 [正确性 checkpoint](F24-correctness-checkpoint.md)。
清理后的源码未重跑全图，旧 v14 成绩不能充当本阶段新成绩。

| 已有证据 | 结果与限制 |
| --- | --- |
| v14 全图生成 | pipeline 825.050s，受控 service 826.294s，峰值 100.734GiB；403 TU，正文约 6.71GB |
| v14 fresh 完整编译 | 305.71s，受控 service 305.837s，峰值 13.611GiB |
| v14 正确性 | 100k NEMU 无差异；231,568 commits 与 Verilator 精确一致；guest100001/core99996/instr238535/PC0x80000cde |
| v14 未插桩性能 | 152.190s 被硬截止杀死，最后已报告 70k；没有完成成绩 |
| GSIM 同 FIRRTL 既有成绩 | 生成 779.02s、完整编译 300.63s、100k 运行 51.443s；需审计运行控制与 endpoint，尚不直接作为严格同 endpoint 性能通过凭证 |

证据目录：`ptmp/firrtl-ingest/F24/{full-native-v14,gsim-current-full,
gsim-current-compile,gsim-current-run100k}/`。旧的 `v14-perf-profile/` 已清理，
只有 tombstone，不能声称现有热点评测结果。

## 当前调查

并行检查：① GSIM 与 GrhSIM 的内存写入/activation，特别是
`largeBeforeStore` 和 `memoryTouchedStore`；② nonsink 图粒度、调度与 C++ 形态；
③复用现行 Make 入口建立独立时间/内存限制与正确性验证。变更和实验结果将在
取得直接证据后追加，不把分析计划计为性能提升。

2026-11-12 用户再次明确以同输入GSIM逐阶段图/语义/生成C++对齐为主线。
当前可核对差异和下一步见 [GSIM对齐矩阵](F25-gsim-alignment.md)；后文保留
各轮历史记录，不把局部热点优化或pass名称一致当作已完成结构对齐。

## 第一轮：内存 activation 与写入/发布开销

已对冻结 v14 原始无 PGO 二进制进行 20k-cycle 诊断采样，CPU2、NEMU、seed0，
128GiB/swap0、60s 内层/65s service 截止。运行完成，host 35.993s，guest20001、
core19996、instr14121、PC0x80000440。`perf cycles:u` 199Hz 共 7,163 个样本，
无丢样；按确切样本数汇总（不是累加四舍五入的百分比）：

| 函数族 | 样本 | 比例 |
| --- | ---: | ---: |
| writer | 3296 | 46.01% |
| Publish | 1951 | 27.24% |
| nonsink | 1149 | 16.04% |
| General dispatch | 411 | 5.74% |
| 其他，包括 Commit | 356 | 4.97% |

证据：`ptmp/firrtl-ingest/F25/baseline-profile/{perf.data,report-samples.txt,
resources-retry.json,driver-retry.log}`。首次 sandbox 访问 systemd 失败，未启动
payload；按权限流程启动的新 service 完成，两个结果分别保留。短窗采样用于
选择优化方向，不充当完整 100k 性能成绩。

代码对照结论：GSIM `cppEmitter.cpp` 对数组 writer 直接激活后继，没有 before
bool 或已触碰 leaf 位图。GrhSIM 的 on-write before bool 与已有 dirty bit
重复，已删除；读地址订阅/触碰位图及助手也已删除，恢复 full state fanout。
on-change 需要发布前的初值判断 A→B→A 是否净变化，保留该能力并明确改名
`largeBeforeImageStore`。历史 §7.11 记录位图方案比当时基线慢 4.225%，但这
不替代本轮全图测量。该项修改的 fixture 生成与 16 个 indexed/temporal
运行例已通过，覆盖 on-write/on-change、bitmap on/off、函数预算16/1024。

新的一项优化正在验证：small writer 将候选值与 **NBA shadow** 比较，只有
shadow 实际变化才设置 dirty bit；同一轮较早写入留下的 dirty bit 不清除，
因而保留 A→B→A 恢复、A→B→B 优先级、掩码及旧值采样语义。另检查 Publish
按字节快照 dirty bits、一次清除的实现，保持全部调度阶段及事件支持。

可复用实验入口为 `ptmp/firrtl-ingest/F25/Makefile`；正式新模型的全图生成、
fresh 完整编译、trace/逐项比较、未插桩100k均仍待执行，**F25尚未达标**。

**回归完成 / v1启动**：最终 emitter fixture 生成3.49s通过，40个独立选定
生成后C++程序通过。覆盖small shadow、A/B/A、A/B/B、部分/全数组、掩码、
NBA旧值采样、派生时钟、跨byte/batch发布以及indexed/temporal。原shared
payload测试创建了独立producer却期待共享次数；修正为显式共享DAG并加入
producer身份断言。先前失败日志原样保留，不计为通过；最终4种模式均通过。
安装通过现有`make py_install`，无PGO；实际库SHA256为
`b6e0f33da3c7bc0d65e1281811f4b056e474bca0dc587bbb7a0641bb5b189003`。
随后通过F25 Make入口启动`v1`原FIRRTL全图生成，硬截止840s，128GiB/swap0。
当前只有启动证据，不宣称生成、编译或性能通过。

GSIM同输入无PGO原exe补测得到51.656s，guest100001/core99998/instr238550/
PC0x80000b40。模拟器和service均exit0，128GiB/swap0、peak22,560,768B；
但并行工具修正与该次启动重叠，`experiment.py`前后哈希改变导致外层验收失败。
补充审计确认其余134项输入/二进制/harness身份稳定，明确保留原外层失败，
不把控制文件变化或GSIM端点差异隐去。见
`ptmp/firrtl-ingest/F25/gsim100k-control-audit.json`。

**v1生成通过**：新身份的22阶段start/done逐项核验通过；入口822.81s，service
824.9996s，均低于840s。emit282.075s，发布402个C++源文件、58,637个函数；
峰值118,244,655,104B（约110.12GiB），swap/max/OOM/kill均0。
源码、实际加载库、输入、harness、工具链前后哈希和发布文件哈希均通过。
`generate-result.json`/`generation-audit.json`/资源sidecar为独立证据。
已启动v1 fresh完整编译：LLVM22、24共享jobs、330s、128GiB/swap0、无PGO，
尚无编译终态。

**v1完整编译通过**：fresh对象/PCH/archive/emu检查通过；包含harness捕获、
402个模型TU、harness对象、归档和最终链接，计时233.71s、service233.894s，
低于330s及GSIM300.63×1.1的约束；峰值13,890,625,536B（约12.94GiB），
swap/max/OOM/kill均0，源码/库/模型身份前后不变。编译后的emu SHA256为
`d9590166a3b59fb06725b5b195727e6fd3957c8dc134bb3e025509a3d697dd74`。
新发布的hpp独立确认无`largeBeforeStore`/`memoryReadIndexStore`/
`memoryTouchedStore`。已启动100k/NEMU trace；该次采集不是未插桩性能成绩。

**v1正确性通过**：100k trace完整结束，NEMU无差异，host167.465s；
guest100001/core99996/instr238535/PC0x80000cde与plain-SV Verilator一致。
原exporter生成的`commit.trace`、`commit.tsv`及`summary.json`哈希逐项精确
一致；独立exporter/comparer再次确认231,568条提交及全文字节相同。
证据为`v1/{trace-result.json,compare-result.json,trace-comparison/comparison.json}`。
随后启动无插桩100k，诊断保护截止300s，所有v1源码/库/控制文件继续冻结。

**v1首轮性能与完整采样**：无插桩100k完整完成，host172.400s，user172.36s、
system0.02s；golden endpoint、冻结身份及128GiB/swap0资源检查均通过。
该次运行期间分析代理误用`sed -n '1,80p'`读取约10GB、单行的`code-map.json`，
具体起止时间/RSS未记录，可能带来短暂带宽干扰，不能据此定量解释差异。
保留原结果，另行安静复测。用户指出其比trace167.465s慢4.935s（2.95%）；
旧测试没有CPU频率记录，原因未证实，不能声称关闭trace本身导致变慢。

同一二进制另跑完整100k `perf record -F199 -e cycles:u`完成，host166.350s，
user166.33s、system0.06s；33,100样本、丢样0，golden endpoint及冻结身份通过。
该采样时间仅为诊断；后续按实际period加权给出exclusive nonsink及其明确归属
调度的占比，再用安静复测的无插桩时间估算秒数。共享helper无调用栈时单列，
不强行归给nonsink，也不把混合调度`pGeneral()`全部归给nonsink。
证据：`v1/{run-result.json,run-time.txt,run-resources.json,profile-result.json,
profile-time.txt,profile.data,profile-report.txt}`。

## 完整100k归因与第二轮方向

安静复测完整100k：host **165.710s**，user165.68s、system0.02s，所有分析/
构建代理暂停。NEMU无差异且golden endpoint一致，Make/service成功，32项
输入/二进制/控制身份前后及补审计时哈希一致，128GiB/swap0生效、memory
events均0。新增runner错误地在仅含模拟器输出的日志里查找`[RUN]`配置header，
原外层exit2保留；独立补审计从driver日志确认全部开关及time实际argv，
结果为`supplemental_audit_pass`，未重新模拟，也未将原失败改写成通过。
证据：`v1-rerun-tools/repeat1/`及
`v1-rerun-audit/repeat1/supplemental-result.json`。

同CPU、NEMU、seed0的GSIM完整100k新对照 **51.343s**，user51.33s；这次
外层冻结及资源检查也成功。其guest100001/core99998/instr238550/PC80000b40
仍与Verilator端点不同，因此是固定100k窗口的成本对照，不是严格相同行为的
性能验收。证据：`gsim100k-clean/{gsim-result.json,gsim-time.txt,gsim-resources.json}`。

完整100k采样period合计853,309,580,351，与perf报告总事件数逐位一致；
33,100样本、丢样0，采样跨度166.361s。按当前IP exclusive归类，不重复计费：

| 部分 | period占比 | 以无插桩user165.68s换算 | 相对GSIM总时间51.343s |
| --- | ---: | ---: | ---: |
| nonsink `sn_*`自身 | 23.431% | 约38.82s | 约75.6% |
| nonsink `pGeneral_active_batch*`调度 | 4.644% | 约7.69s | 约15.0% |
| nonsink计算与明确归属调度合计 | 28.075% | 约46.51s | 约90.6% |
| sink writer | 58.128% | 约96.31s | 约187.6% |
| Publish | 7.614% | 约12.62s | 约24.6% |
| large Commit | 1.813% | 约3.00s | 约5.9% |

顶层`pGeneral()`混合调度约1.209%，未全部归到nonsink。共享helper没有
callchain，留在other；内联代码归包含它的符号。秒数是周期归因换算估算，
不是逐阶段直接计时；频率变化、采样skid及相关性仍有限制。完整报告和原始
period/sample双口径见`perf100k-analysis/`。

用户指出的机制性问题已通过源码核对：GSIM的`Node::updateConnect()`不把
寄存器clock字段接入普通数据依赖；`genStep()`隐含推进周期，门控clock可在
`clockOptimize()`中转成WHEN条件，且复杂时钟支持有限。GrhSIM保留显式边沿、
NBA与多轮语义，nonsink已有activity门控，但writer的private pure cone仍随
有效fire重复执行。clock不会沿数据DAG反向激活祖先；重复来自合并执行单元
或writer内未独立门控的计算。因此writer成本也包含组合计算，不能把它全部
当作状态提交成本，nonsink成本也不是完整组合逻辑成本。

第二轮验证精确schedule run的sink activity：只有纯、无观察副作用且具有
可靠输入/发布失效路径的small Logic run可跳过；其数据边界以及pending target
都必须保持上次执行后的值。任意竞争writer实际修改shadow即失效，包含
A→B→A最终净值不变的情况；边沿资格、原执行位置、写优先级和所有phase不变。
该方案仍需编译、定向执行回归及全图时限内验证，不将源码审阅视作性能提升。

**v2定向验证**：已应用审阅过的emitter实现；生产源码SHA256为
`1a7c51d9320a9baaa5f0256fcd9b9b579a081a294d2be44d63f4da355d4dd620`。
完整fixture生成3.50s通过，新增exact-runs与competition各16/1024预算共4个
运行例通过，实际writer-sample/private Add计数证明稳定重复执行被跳过；
竞争写与A/B/A恢复、无edge/false enable、非零init、双实例及单实例reinit
均通过，且eligible统计非零，避免回退导致空验证。另42个既有运行例通过。
形态oracle原将空ordinary fanout视为可省比较；现对有sink订阅的值要求比较
并失效，同时新增真正无订阅值仍验证省略，原失败日志保留。
`make py_install`成功，安装库SHA256为
`4cd4ee8171cf29e4fcd20cbd82a7cfc4fdaaaf3e0db2085b2069fffd8591df7d`。
剩余定向检查为fire-as-data回退与异常重试期间eligible run失效保留；完成后
才启动新身份全图，仍严格840s/330s、128GiB/swap0，性能无PGO且完整100k。

**v2回退与异常检查完成 / 全图启动**：新增interrupted-fallback双预算与arrays、
immutable-interrupted-source双预算共6个运行例通过，本轮共52个唯一选定运行例。
新case实际eligible1/fire-as-data拒绝1/publication sources2；先warm到clean，
再由nonsink发布新payload后抛异常。无输入变化重试不重放已消费posedge，
随后仅clock low/high即按新payload执行一次，再稳定edge跳过，均由真实writer/
Add计数确认。完整fixture生成3.63s通过；首次新case的primary字段形态断言错误
已按实际small payload boundary修正，失败日志保留，未修改emitter。
证据为`v2-regression/{existing-42.log,interrupted-fallback-generate.log,
interrupted-fallback-generate-retry.log,interrupted-fallback-runtime.log}`及
`v2-fixtures-new-activity-runtime.log`。已冻结源码、安装库与控制文件，启动
`make -f ptmp/firrtl-ingest/F25/Makefile generate ATTEMPT=v2`；当前仅有启动与
部分stage完成证据，未宣称全图生成或性能通过。

**v2全图生成与fresh完整编译通过**：22阶段start/done逐项核对成功；入口
805.27s、service807.448s，emit283.364s，均在840s截止内。峰值
114,776,850,432B（约106.89GiB），swap/max/OOM/kill均0，实际加载producer及
所有输入/发布身份检查通过。发布404个源、59,793个函数。

实际sink activity覆盖50,512个run、138,238个writer（总351,368），bitmap
6,320B；订阅101,591个值/73,579个target，value/run pairs318,649、target/run
pairs138,238。实际input/publication/shadow mask sites分别607/118,419/247,768；
最大target fanout152、4个mask word，最大value fanout19,077、603个mask word。
主要回退为non-direct-edge113,246 writers、non-small50,989及effectful-local
46,251；这些仅是静态覆盖，不代表动态跳过量。

随后fresh PCH/404模型TU/harness/archive/link完整编译228.98s、service229.152s，
低于330s及GSIM编译约束，峰值14,037,028,864B（约13.07GiB），资源事件均0。
源码/producer/模型身份稳定，LLVM22 O3/native/no-strict-aliasing，无PGO/cache/
运行时计数与计时探针；emu SHA256为
`812c3273e362bd8f051fb2acce8d1c9b66e8294356466d10ea29b34cea81235b`。
已启动同二进制100k NEMU trace；正确性与运行性能仍待结果，F25未达标。

## v2完整100k结果与架构归因

上述trace已完成：host183.653s，NEMU无差异，guest100001/core99996/
instr238535/PC80000cde；231,568条commit与plain-SV Verilator golden的
独立解析及原始文本比较均一致。trace运行时间仅用于正确性诊断。

随后安静运行同一个无计数/计时插桩二进制完整100k：host181.896s，
user181.87s、external wall181.91s，端点和冻结身份检查通过。相对v1安静
复测165.710s回退9.77%，不能把sink activity作为性能成功发布。
完整100k外部perf采样host182.049s，36,224样本、lost0；period总和
937,225,274,828与perf报告一致，采样跨度182.060798s。

| 独占部分（采样换算user秒） | v1 | v2 | 增量 |
| --- | ---: | ---: | ---: |
| nonsink正文 `sn_*` | 38.821 | 48.887 | +10.067 |
| nonsink activity调度 | 7.694 | 8.009 | +0.315 |
| nonsink及其调度合计 | 46.515 | 56.896 | +10.382 |
| writer | 96.306 | 101.508 | +5.202 |
| Publish | 12.614 | 13.005 | +0.390 |
| large Commit | 3.004 | 2.847 | −0.157 |

相对GSIM完整100k总时间51.343s，nonsink及其调度由90.6%升至110.8%。
该预算已无法给其余阶段留下足够时间。平均采样cycles/profile user秒
仅上升0.361%，整体频率下降不能解释这次回退。flat profile没有callchain，
`sn_*`包含数据发布处新增的sink失效维护，writer包含private组合计算、
guard、chunk调用、采样/搬运及写入，不能直接将整类计为单一原因。
证据：`v2/{trace-result.json,compare-result.json,run-result.json,profile-result.json}`、
`perf100k-analysis/{v2-profile100k,v1-v2-comparison}/`。

**机制结论及下一步边界**：GSIM普通数据依赖不包含寄存器clock，每step
隐含推进周期；next-data可与普通组合逻辑共用activity supernode。
GrhSIM的fire不会逆向激活任意RHS祖先，但fire/enable允许writer进入后，
私有数据锥仍与写入执行耦合。v2只为一部分run添加整体dirty门控；同目标
竞争writer改变next-shadow时，`markState()`会重新置订阅run的dirty，
即使payload数据没变也会再次进入整个runBody。稳定独立writer可跳过，
A/B/A竞争恢复仍必须重施写入，已有真实writer/Add计数测试覆盖两者。

用户提出的首要结构假设是将data-dirty与edge/fire以及目标竞争重新写入
解耦：数据变化时重算，合法事件发生时按原序采样/写入。当前数据支持
优先调查，但尚不能量化private payload重算占writer成本的比例。
应先区分计算、guard/chunk、搬运和失效维护，再选择实现。此前拟议的
v3发布聚合/batchguard实施已停止，没有v3生产源码或emitter文档改动落盘。
不改六阶段、多轮、NBA、多时钟语义，不使用PGO，F25目标仍未达到。

**既有writer样本的局部源码核查**：v1/v2各选period最高的20个函数，逐个
与反汇编IP核对counts和period，全部吻合。这两组分别只覆盖writer period
的1.539%/1.380%，不能外推为全局成本比例。选中的部分函数完全是chunk
调用分发；其他函数包含enable/fire分支、frame搬运、pending比较和更新。
v2所选33个dirty保护块中，14块没有非恒定local赋值；另两个局部块分别有
448/408个非恒定赋值，其中409/364个mux。说明eligible既有廉价复制，也有
大私有选择锥，静态writer覆盖数不能代替可节省工作量。完整证据位于
`writer-hotspot-audit/findings.md`及其v1/v2 source/annotations/summary。

下一项诊断使用独立派生生成源和独立二进制，保留原v2语句并验证去掉计数
注入后逐源SHA恢复。给现有dirty位另加data/target来源侧位图及exact-run
原因计数，保持原始计算、guard、顺序及清位语句。计划完整100k统计dataOnly/
targetOnly/both，并与局部大锥对应；不使用逐操作计时，诊断运行时间不进入
性能验收。此处仅记录诊断设计，尚无该诊断编译或运行通过的证据。

## 独立writer诊断完整100k：收窄缓存假设

`writer-diagnostic/d1`已完成。7项synthetic检查通过，含真实C++ A/B/A、
self-mark、reinit、同bit双来源顺序，以及跨TU/chunk和第二bitmap word。
准备阶段逐源剥离注入后恢复原SHA，50,512个exact run各一处guard/clear，
三类静态OR sites与v2 metadata逐项一致，保留409个构建输入文件；没有
重新raw生成，也不把派生诊断当作生产生成/性能验收。

Fresh PCH/404模型TU/harness/archive/link全部完成，wall227.57s、编译stage
226.38s，330s整组截止有效，峰值14,469,283,840B（约13.48GiB）。完整100k
诊断host234.156s，仅用于计数；NEMU无差异，端点guest100001/core99996/
instr238535/PC80000cde。128GiB/swap0及整组终止设置已核验，资源事件全0。
source、工具、编译器、FIRRTL、common/generated harness及运行输入前后
冻结检查通过，compile/run记录的二进制SHA均为
`7673aaf6ad8b89759898139979beca089a0cebc203620bb0aa0812920fe2d1a8`，
harness build identity一致，无PGO。原生产emitter仍为冻结v2 SHA。

| eligible run诊断事件 | 次数 |
| --- | ---: |
| 已通过原外层fire/enable/guard后的dirty探测 | 2,485,056,834 |
| 实际进入并成功完成run正文 | 703,634,942 |
| dataOnly（包括初次执行） | 685,327,755 |
| targetOnly | 13,112,289 |
| both | 5,194,898 |
| clean探测跳过正文 | 1,781,421,892（71.685%） |

targetOnly占实际入场**1.864%**。原始每run三类计数求和与全局完全一致，
neither=0，进入/成功清位次数相等；prepare eligible census、运行报告和
33个局部源码块的ordinal/guard绑定均独立复核。两个较大局部mux锥run2107/
2128分别执行51,751/61,294次，全部dataOnly，targetOnly和both均0，不能
误读成这些锥没有执行。因此暂缓为当前eligible集合实现两级payload cache；
目标竞争导致的重算确实存在，但现有证据不足以把它列为该集合的主要收益。
1.864%是入场次数比例，不是耗时比例或可节省时间上界。

本轮动态publication/target mask OR分别351,379,832/473,613,585次；
原始coarse computeBatchExec=529,563,211、commitBatchExec=6,028,842,231、
touchedStateShadow=474,500,897、touchedWrite=6,192,132,075。不同计数单位
包含优先级覆盖、多leaf与large on-write事件，不能据此声称92%的写可省。
探测跳过71.685%也不能证明扫描或分发便宜。诊断仅覆盖现eligible集合，
未覆盖约60.66%的静态writer不等于其耗时比例。

证据：`writer-diagnostic/d1/{prepare-manifest,compile-result,run-result,
writer-counts,compile-resources,run-resources}.json`；独立补审及33块关联为
`perf100k-analysis/writer-diagnostic-d1/analysis.{json,md}`。诊断工具与
主Makefile转发前的原件留在`writer-diagnostic/`，所有构建/运行均经Make。

**下一轮实施**：优先消除v2发布处逐点sink mask维护的重复，按完整
nonsink+sink目的集合共用比较/dirty汇总，并为全部eligible的原有writer
batch增加精确mask外层探测，减少全clean时的chunk进入。保持exact run、
原顺序、异常即时发布及current/next活动规则。另单独审计strict OR/Assign
fire候选和private small-current ReadState资格，后者需要新的Publish失效
路线，暂不与当前修复混合；first-rejection覆盖上界不作为收益预测。
本轮仅诊断完成，仿真性能对齐仍未达到。

**v3实现与定向验证**：完整目的集合发布聚合及全eligible batch coarse
guard已落地，生产emitter SHA256为
`4ef394e80d6d8eaa6c8af37869100e16ef6f141cb0e146c57b975fa24434a1ff`。
完整fixture生成3.67s通过；58个唯一选定生成程序全部运行通过，包含此前
52例及新增batch-competition、batch-masks-fallback、complete-publication-keys
各16/1024预算。新增测试以真实writer/private-op计数及严格形态同时验证
同NS不同sink不混组、empty NS的sink-only聚合、raw7→actual4 mask sites、
跨chunk比较/flush、精确word masks、混合fallback及跨batch竞争恢复。
Make py_install成功；安装core库SHA为
`baf802b237b638526aafe8f35ea8321a288916c257ad867a1b618433ca5b4b3c`。
日志为`v3-fixtures-{generate,runtime}.log`及`install-v3-launch.log`。
已启动`make -f ptmp/firrtl-ingest/F25/Makefile generate ATTEMPT=v3`，
严格840s/128GiB/swap0，从原始FIRRTL走固定22阶段；尚未获得全图生成、
fresh完整编译或100k性能结果，不将定向验证视作F25达标。

**v3全图生成通过**：固定22阶段完整执行，入口827.176s、service829.975s，
低于840s；emit283.069s。峰值104,217,034,752B（约97.06GiB），128GiB/swap0
生效，max/OOM/kill事件均0，producer/输入/控制/发布身份前后校验通过。
eligible集合仍为50,512个run/138,238个writer；publication sink mask静态sites
由118,419降到63,188，完整key聚合8,839组；1,134个writer batch中297个全eligible。
这些静态数字不代表动态收益：完整key可能拆开原NS共享组，nested fire/dirty
guard经函数拆分也可能增加helper层。已启动fresh完整编译，330s整组硬截止，
无PGO；正确性与完整100k性能均仍待结果。

**v3 fresh完整编译通过**：PCH、404模型TU、harness、归档及最终链接共
265.60s，service265.762s，均低于330s及GSIM300.63s×1.1；峰值
13,951,422,464B（约12.99GiB），资源事件均0，生成/编译身份检查通过。
无PGO、运行时计数或逐段计时，emu SHA256为
`c2710dcead83c5bd7394e59dcfe4d50d31e01b8a7683b11e57b2d4b30cc15c07`。
已启动同二进制完整100k NEMU trace，随后逐项比较Verilator golden；
此时没有v3正确性或性能终态。

## v3完整100k结果：维护优化不足以消除writer瓶颈

完整100k trace host178.855s，NEMU无差异，golden endpoint为guest100001/
core99996/instr238535/PC80000cde；231,568条提交经原exporter和独立比较器
字段、时序及全文字节比较均一致。之后所有分析代理暂停，同二进制安静
无插桩100k完成：host177.723s、user177.70s、external wall177.74s；
端点、前后冻结身份、128GiB/swap0及资源事件检查均通过。无PGO。
相对v2 host181.896s改善2.29%，仍比v1安静复测165.710s慢7.25%。

同二进制独立完整100k外部采样host177.530s，35,324样本、lost0；
period合计913,356,898,246，与perf报告精确一致，采样跨度177.539s。
沿用exclusive IP分类及无插桩user时间换算，保留共享helper和混合调度单列：

| 部分（估算user秒） | v1 | v2 | v3 |
| --- | ---: | ---: | ---: |
| nonsink正文 | 38.821 | 48.887 | 43.644 |
| nonsink活动调度 | 7.694 | 8.009 | 7.726 |
| nonsink及其调度 | 46.515 | 56.896 | 51.370 |
| writer | 96.306 | 101.508 | 102.718 |
| Publish | 12.614 | 13.005 | 13.317 |
| large Commit | 3.004 | 2.847 | 3.069 |

v3 nonsink正文占24.560%，加调度28.908%；其51.370s已约等于GSIM总
wall51.340s（约100.1%），没有给writer/发布等留出追平预算。GSIM端点差异
继续保留，这不是严格同工作量验收；分项也是采样估计，不是阶段直接计时。
writer占57.804%，仍是最大绝对成本。v2→v3的改善主要来自nonsink正文
约−5.244s，writer估计反增1.210s；不能把本轮称作writer优化成功。
采样period/profile user秒的整体代理仅变化−0.065%，不支持将回退/改善
简单归因于整体频率，但这也不是经校准的频率因果测量。

证据为`v3/{trace,compare,run,profile}-result.json`及
`perf100k-analysis/{v3-profile100k,v1-v3-comparison,v2-v3-comparison}/`。
比较工具已参数化版本名、按实际数值描述增减，12项分析自测通过；不再
沿用固定v1/v2的结论文案。局部`v3-helper-audit/`确认一个all-clean/fire真
batch仍进root和chunk1，但使用条件尾跳，不能误称额外call/ret对。

下一步优先减少writer私有计算和中间frame搬运，暂不无差别扩大dirty层。
既有两个局部大mux锥的409/364个mux结果均为单用，其中356/309个仅供下游
mux消费，最长链9；这仅是局部结构证据。正准备同enable-demand纯区域内的
有界scalar mux表达式融合，保持既有numeric_select求值语义、采样位置、
可观察边界及有序写入，不新建运行时缓存。尚无该候选实现或验证通过证据，
F25仿真性能对齐目标仍未达到。

## v4候选：有界私有scalar mux表达式融合

已实现同exact payload demand、连续纯scalar mux区域内的单用data-arm融合。
保留现有legacy按值eager mask-select / `numeric_select`路径及width/sign清理，
不新增helper ABI或运行时缓存。多用值、selector、可观察/存储值、非mux、
不同demand及非eligible run均保持原路径。每树最多16节点/8深度；携带表达式
超过32KiB时物化，最终root语句不承诺该字节上限。原counter位置、helper
操作来源及全部采样/状态应用顺序保留；新增`private-mux-stats.json`仅计静态
覆盖和实际树边界。生产emitter/source hashes见`v4-regression/source.sha256`。

最终完整fixture生成3.84s通过；64个唯一选定生成后C++程序通过，即v3原58例、
四种预算/计数开关的符号与宽度融合例、两种预算的20级cutoff例。新例证明
多用mux不被复制、counter逐步相等、折叠来源属于实际helper、local/frame真实
消除；20级链保留7/15/19三个root，消除17赋值，最大树节点/深度8/8，
独立overwrite oracle覆盖44种selector×8数据×两次init、enable与无新edge更新。
整体运行回归service192.467s、peak约1.45GiB；cutoff运行service3.008s。
首次直接根Make入口因未设置已有环境标志而在payload前失败，原日志保留；
后续明确使用既有虚拟环境，未重复安装环境依赖或改变测试预期。

通过既有`make py_install`安装成功，service30.360s、peak约0.95GiB；
实际安装core库SHA256为
`17fd98af5b04aff76c5ce89dfba1c74b31e02ff0a8ede4055aaa65f36de23ece`。
已冻结源码/producer/控制，运行`make -f ptmp/firrtl-ingest/F25/Makefile generate ATTEMPT=v4`，
840s硬截止、128GiB/swap0、无PGO，走原始FIRRTL固定22阶段。该次在`comm-expr`
阶段被OOM kill终止，尚未进入emitter；service364.083s、外层365.409s，峰值
94,574,600,192 bytes（约88.1GiB），本service的memory.events及local OOM计数
前后均0。因此未触及840s截止，也没有证据将失败归因于mux融合。随后系统日志
确认systemd-oomd在epoch1794400773.424684因`user@1000.service`内存压力
64.51%持续超过50%/20s，选择并终止本service；这是上层压力策略主动终止，
不是本service触及MemoryMax。失败证据保留于
`v4/{generate-resources,generate-exit}.json`和阶段日志，OOM来源证据在
`oom-audit/`。通用resource wrapper已增加可选`--managed-oom-preference`，默认
none；F25显式使用omit，仅排除本service作为该用户会话oomd策略的候选，
128GiB硬限额、swap0及硬截止保留，未修改系统全局策略。16项Make入口测试及
64MiB/swap0/10s实际service预检通过；start/stop均验证unit属性、实际cgroup
xattr和与监控祖先同UID，证明本机设置生效，而非只记录请求参数。证据为
`oom-audit/{README.md,unit-tests.log,service-smoke/resources.json}`。
没有v4全图模型、编译或性能结果。fixture/install日志为`v4-fixtures-*`和
`install-v4-launch.log`。架构讨论后继续目标，已用新目录`v4-retry1`重试相同v4
生产候选；原失败不覆盖，生产/控制在新实验前重新冻结。下一轮结构改动只在
`post-v4-activity-expanded/`离线副本准备，不进入当前重试的生产输入。

**v4-retry1生成与编译**：完整原始FIRRTL固定22阶段通过，流水线826.487s、
emitter283.841s、service829.328s（小于840s），peak112,381,349,888 bytes
（约104.7GiB），memory事件均0，前后身份及oomd配置生效检查通过。实际
69,297个非空mux区域折叠23,123个mux/局部赋值，最大树16节点/8深度；这些
只是静态覆盖。随后全新完整编译service258.514s（小于330s），peak
13,908,037,632 bytes，资源及无PGO审计通过。二进制SHA256为
`eb17fc1907a28b8a8383e1785a0708aba6029fa5febe4f2a5cf14da147b29752`。
完整100k trace host176.282s、NEMU无差异，231,568条提交的字段、时序及全文
字节与plain-SV Verilator精确一致；端点guest100001/core99996/instr238535/
PC80000cde。所有分析代理停止后，同二进制安静无插桩100k host175.068s、
user175.04s、external wall175.08s完成；同二进制独立完整100k采样
host175.221s、user175.19s。二者端点正确、资源及前后冻结检查均通过，
全过程无PGO。

采样34,864、lost0，period900,970,689,924，与perf report及全部exclusive
类别求和精确对账。各自无插桩user时间乘各自cycle share得到：

| 部分（估算user秒） | v1 | v3 | v4-retry1 |
| --- | ---: | ---: | ---: |
| nonsink正文 | 38.821 | 43.644 | 42.673 |
| nonsink活动调度 | 7.694 | 7.726 | 7.708 |
| nonsink及其调度 | 46.515 | 51.370 | 50.380 |
| writer | 96.306 | 102.718 | 100.839 |
| Publish | 12.614 | 13.317 | 13.231 |
| large Commit | 3.004 | 3.069 | 3.233 |

本轮user较v3改善2.660s/1.50%，但较v1仍慢9.360s/5.65%。nonsink+调度
约占历史GSIM wall51.340s的98.1%，仅留下约0.96s预算；writer仍约100.84s，
显然无法仅凭本轮局部融合达到对齐。writer估算较v3减少1.880s、NS及其调度
减少0.990s；flat profile不能证明这些变化全部由mux融合直接造成。平均
period/profile user秒代理较v3仅变化约-0.050%，也不是校准后的频率因果测量。
GSIM端点差异、v1原outer失败记录及采样秒数估算限制继续保留。
证据为`v4-retry1/{trace,compare,run,profile}-result.json`及
`perf100k-analysis/{v4-retry1-profile100k,v3-v4-retry1-comparison,
v1-v4-retry1-comparison}/`。当前候选性能目标未达成。

另对历史GSIM端点差异进行了只读复核：从git历史重建的harness SHA与冻结
编译输入精确匹配；GSIM reset循环每次含asserted及deasserted两个step，
而Grh/Verilator保持reset跑脉冲后才释放。还存在NEXT提交/DPI取样相位因素，
尚不能证明只是固定两周期平移，未擅自修改参考模型、缩短100k或改写成绩。

## 时钟激活与纯数据重算的结构性问题

用户指出：若nonsink及其调度已用掉GSIM完整仿真的时间预算，sink就没有追平
余量。v3的51.370s对GSIM user51.33s确实呈现这一现象；两者仍受端点差异及
采样估算限制。这支持优先调查激活和计算边界，尚未证明该机制解释了主要差距。

当前nonsink/sink按消费者划分，并非所有组合计算都留在nonsink：
`split-nonsink-and-sink.cpp:45–74`将单一writer私有的可移动纯锥纳入sink；
共享数据和External/effect操作留在nonsink。因此writer约102.718s也包含私有
组合计算，nonsink约43.644s则包含部分DPI/断言及其数据准备。不能将两个
函数类别直接解释为“纯组合逻辑”和“纯状态提交”。

GSIM的`Node::updateConnect()`不将register clock接入普通数据依赖，
`genStep()`将一次step抽象成周期推进；GrhSIM保留显式边沿及settle/NBA协议。
合并带有不同激活原因的执行组，确实可能让clock/fire携带原本不需重算的纯数据。
但显式边沿不要求每次都重算全部next-data，clock也不反向激活数据祖先。

v3只读生成代码审计得到两类具体证据：

- 输入clock变化直接激活1个146-op nonsink组；其中只有1个LogicNot使用clock，
  同组还有独立state/array读取和mux计算。主posedge直接激活812个nonsink组，
  含158,771个静态op；总nonsink为21,110组。该范围不是全图时间占比，且不含
  间接publication激活。每个edge的必要effect检查不能全算作冗余。
- `sn_20979`的598个op精确分为401个私有非constant DPI payload操作、18个
  enable操作、9个DPI、168个constant和2个独立publication。401个payload操作
  在最终`fire && enable`检查之前计算；有界源引用闭包未发现其他consumer或
  persistent publication。这是可按guard需求延迟计算的具体候选，尚无enable
  false频率或节时测量。

后续验证应区分三种资格：真实数据依赖变化使纯payload需要重算；合法fire/enable
决定采样和有序写入；目标next-shadow被竞争writer覆盖可能要求重施写入。
在payload未依赖该目标的前提下，第三种原因不必同时使payload缓存失效。
纯payload缓存/按需计算需要证明依赖完整、值有效及采样位置正确；每次合法事件
的effect顺序、disabled hold、NBA、多轮和多时钟语义全部保留。不能直接跳过
整个混合nonsink组，也不能复用陈旧enable。

结构审计证据为`ns-clock-audit/v3/{findings.md,activation-summary.json,
guarded-demand-evidence.json}`。

随后将这些静态owner与已有完整100k的exclusive样本相交，root及chunk只累计
一次，四个不重叠集合逐位对账到全部NS body period224,324,198,644：

| owner集合 | 样本数 | period | NS正文占比 | 总占比 | 估算user秒 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 主event的812组 | 3310 | 85,594,996,562 | 38.157% | 9.371% | 16.653108 |
| 额外event组sn20667 | 0 | 0 | 0% | 0% | 0（零样本） |
| 独立input clock组sn2919 | 10 | 258,688,951 | 0.115% | 0.028% | 0.050330 |
| 其余20,296组 | 5355 | 138,470,513,131 | 61.728% | 15.161% | 26.940411 |

814个event/input-clock owner整个body合计约16.703438s，占总9.400%。这是该
集合直接body成本的乐观天花板，必要effect/enable/publication仍需执行，样本
也不能证明其激活原因；共享helper、NS调度及下游writer/Publish不在这个上界内。
特别是598-op案例sn20979仅6个样本/约0.030187s，稀疏估算误差较大，但已足以
说明不能凭静态401-op私有payload就将它列为全局首要性能改动。证据为
`ns-clock-audit/v3/profile-attribution.{json,md}`；新增Make分析入口只复用既有
profile，没有新编译、模拟或采样。

因此NS事件组的guarded demand保留为具体优化候选，当前实现优先级回到writer
的fallback覆盖及计算/应用资格。只读既有诊断显示，已eligible集合中target-only
entry只占1.864%，不能仅靠给这部分新增payload cache期待追平。正在离线审查
纯EventEdge OR/Assign fire，以及当前state读取的真实Publish失效路径，目标是
覆盖此前被排除的稳定私有计算，同时保持fresh edge、按序施写及全部仿真语义。
候选尚未进入生产或通过验证，F25仍未达到性能目标。

**后续状态（writer activity与NS隔离分别验收）**：扩展writer的EventEdge
OR/Assign与current-state读取资格已进入生产，并通过新12和原64共76个生成
C++运行用例。fixture生成29.603s，新12运行11.842s，原64运行194.420s；均经
Make入口、128GiB/swap0和330s资源服务验证，内存事件为0。
`v5-regression/summary.json`为pass。此轮没有安装包、全图生成或完整模拟，
也没有修复clock带动无关NS计算的问题。

NS隔离另在`ns-clock-isolation/`准备：以EventEdge的clock输入和fire输出为根，
仅沿真实数据依赖向前标记，将clock相关与无关数据操作在family、MFFC、
coarsen、segment及clone五处隔开，不沿state writer关系或effectOrder反推。
配套emitter给NS DPI/task的fire-control OR/Assign树订阅真实EventEdge叶，
避免拆组后held join一直为1造成漏触发；held数据值和原effect顺序保留。
源码独立审阅完成后已统一应用到生产，开始串行transform及生成C++回归；
在这些检查和完整100k结束前，不能声称已修复或获得性能收益。
不同clock之间及level/pulse之间仍可能共组，不保证任意等价clock锥识别。

NS生产回归的首两项已通过：`test_grhsim_firrtl_nodes` 1/1（含新增12组合），
服务16.187s；`test_grhsim_virtual_partitions`所含virtual/sink schedule/
transforms 3/3，服务15.710s。128GiB/swap0/330s/omit验证与所有内存事件均正常，
证据为`ns-clock-isolation/regression/`。后续生成C++回归分新8、敏感24和原76，
共108个去重用例，结果仍待完成。

首次emitter generation已通过（CTest1/1，20.360s），随后新8的driver编译在
两处`const auto`多变量声明处失败：把计数器的unsigned long long和回调计数的
unsigned放在同一声明。失败尚未进入运行断言，与生成模型实现无关；已拆开
声明，预期不变，保留`v5-ns-regression/`首次日志，在独立retry1目录重跑。

retry1生成通过（19.931s），新8全部通过（6.331s）：clock-only活动不会增加
独立Add的真实operation计数，真实data变化仍会增加；两个独立effect owner
共享OR/Assign fire时连续/多时钟/同时边均各调用一次，无边eval及异常重试不
重放，init后重新驱动输入也正确。敏感24全部通过（31.984s），其中旧
`dpi-trigger`计数曾编码coarse owner拖带，现明确要求无关d/clk变化时inc保持2，
真实a变化才变3；clocked dbl仍恰好两次，所有return/held output断言保留。
random每eval的主动激活及sample guard未改，effects/monitor/strobe/派生sample
clock回归也通过。原76回归及完整100k仍在后续阶段，尚无新性能数字。

随后原76回归全部通过（206.101s）；retry1共108个去重C++ runtime用例全部
通过，summary/audit为pass，源码前后哈希一致。所有服务128GiB/swap0/330s/
omit实际验证生效，memory/swap事件为0。证据为
`v5-ns-regression-retry1/summary.json`。开始安装与完整原始FIRRTL新尝试`v5`；
只有完整100k NEMU/Verilator提交对比和安静运行/采样结束后才给新性能结论。

**v5全图生成通过**：原始FIRRTL固定22阶段成功，限时服务815.514s<840s，
emitter289.543s，峰值111,057,965,056B（约103.4GiB），资源/omit验证成功且
内存事件为0。NS分区60.145s；clock根843、clock依赖操作7998、clock相关
supernode65；NS总supernode21201（v4为21110），activity node仍2190479。
event pulse直接激活边从894降至143；普通value-change边增加，需以实测核算
收益。额外effect fire订阅在本全图新增边为0（既有直接订阅已覆盖），通用
跨owner共享join场景仍由新runtime用例检验。

合并的writer资格扩展使eligible从50512 run/138238 writer增至95885 run/
293060 writer；含joined fire 43392 run及current-state 8688 run。当前state
订阅32636项（small32498、large138），新增Publish/实际large-store失效路径
保留语义。私有mux折叠75036项（v4为23123），界限仍16节点/深8。
这些均是静态生成统计，未宣称动态提速；已启动新鲜完整编译，330s硬限制。

**v5编译未通过门槛**：service330.373s触发systemd RuntimeMax并SIGKILL，
资源报告timeout；peak14,292,172,800B，memory/swap事件为0，非OOM。
源代码、producer与414个生成文件的冻结身份核对均通过；没有最终LD、二进制
或完整100k结果。日志保存在`v5/`，独立资源/清理审计为
`v5-compile-audit/resource-audit.json`，不延长原编译或使用未完成结果。

只读源码审计锁定唯一未完成对象TU189（其余406个TU对象及PCH完成）。其中
`sn_21198`有128个logEndpoint task、68841个TaskArg，源码13,760,268B但只有
400行；35个单条调用长118KB～404KB，参数最多2001项。相同128个task在v4
分散于39个NS owner，最大owner642,716B；task op ID和参数个数逐项相同。
clock分类使task集中，既有128-node容量和1024-line拆分均看不到单条巨大
initializer_list的编译成本。这是源级最强解释，尚无LLVM pass采样，不能
简单归因于writer资格扩展。证据为`v5-compile-audit/{source-audit.md,
task-comparison.json,task-summary.json}`。

下一候选保留NS clock隔离与新writer机制，按SystemTask实际参数规模计入
分组容量（每16个TaskArg约占一个node容量单位），保持每个调用、参数和
effect顺序。普通节点仍占1，实际node数量统计保持原含义；待回归与完整
840s/330s再验收，不声称v5已完成100k或性能目标达成。

task容量补丁已独立复核并精确应用，生产partition SHA256为
`95b5c976fd669bf7e3cc5e675f1f6700c50d376aeafe151e12531a998c126efa`。
`ns-clock-task-budget/task-budget.patch`保留完整变更，配置升级v6；新增测试
覆盖0/16/17/33/257个TaskArg、单node夹紧、legacy/bytes、三种coarsen接受路径、
节点/操作/操作数守恒、oracle效果序列、checkpoint replay及旧v5拒绝。
开始`v6-regression/`串行transform与108个C++用例；通过才安装和新全图`v6`。

v6回归全部通过：FIRRTL nodes 1/1、virtual/sink/transforms 3/3、generator1/1，
以及108个runtime（新8为6.287s、敏感24为32.246s、原76为206.481s）。
`v6-regression/summary.json`为pass/failures为空，7个生产/测试/文档哈希前后
一致；全部资源服务128GiB/swap0/330s/omit生效、memory/swap事件为0。开始
安装v6，完整全图结果仍待验证。

用户最新要求从此刻改为**先性能、后正确性**：完整编译通过后先无插桩100k，
再独立100k采样；随后才trace100k及Verilator精确提交对比。性能阶段保持既有
benchmark/NEMU配置，以免改变计时口径；先报告的数据明确标记独立正确性
对比尚未完成。此前已完成的fixture与失败记录保留，不改变证据顺序。

**v6完整生成/编译均通过**：生成限时服务811.666s、emitter285.819s，peak
105,944,363,008B；NS分区59.841s。clock依赖仍7998 ops，clock supernode99，
仅35个重参数task提高容量权重，最大task仍2001参数，实际node仍2190479、
supernode21235，最大capacity128。新鲜完整编译232.578s<330s并成功LD，peak
14,324,731,904B，binary SHA256为
`8b2a8a68572e111e0d045703715b14cf83dcb24b50e319bae895f77a376a7c91`。
两阶段资源验证和冻结核对通过，未使用PGO。按用户最新顺序已启动安静100k，
尚未运行本版trace/精确提交对比。

**v6性能先行：安静完整100k已完成**。host171.835s、external wall171.85s、
user171.80s，guest100001/core99996/instr238535/PC80000cde；相比v4安静
host175.068s下降1.847%（联合NS隔离/参数容量/writer资格机制，不能单独归因）。
未使用PGO或内部计数器/trace，按既有benchmark口径NEMU启用。当前只确认
性能运行终点及NEMU未报错，独立Verilator完整提交对比尚未进行；已启动同
二进制独立100k perf，结束并先报告NS成本关系后再进入trace/compare。

独立100k采样随后完成：host166.908s、user166.89s、wall167.02s，33,211样本、
lost0、period858,205,552,157，所有category与report事件总数精确对账。该次
profile比安静wall快约2.8%，与单次v4差1.85%的幅度相当，故不能把单次差值
称为稳定提速。基础报告在`perf100k-analysis/v6-profile100k/`与
`v4-retry1-v6-comparison/`。按安静user171.80s乘各自exclusive周期占比估算：

| 部分（估算user秒） | v4 | v6 |
| --- | ---: | ---: |
| NS正文 | 42.673 | 43.920 |
| NS activity调度 | 7.708 | 7.770 |
| NS及其调度 | 50.380 | 51.690 |
| 混合General dispatch | 1.597 | 1.960 |
| writer | 100.839 | 93.125 |
| LargeSink commit | 3.233 | 2.867 |
| Publish | 13.231 | 13.270 |
| other（含共享helper/libc/NEMU） | 5.323 | 8.490 |

NS及其调度仍为GSIM total wall51.34s的1.007倍，不能说clock隔离已经解除
整体性能矛盾。秒数是样本换算，尤其本轮安静/profile时间不一致，不宜解释
NS估算+1.31s为确定回退；其直接sample period基本未变。NS正文还包含该位置
发出的sink失效维护，并非纯组合计算。静态sink publication mask site从
63188增至171670、shadow site从247768增至580098，另有current-state失效路径；
需后续IP/owner分析才能定量归因。历史GSIM终点不同，仅作成本分母，不作严格
同工作量parity。性能结果已先报告用户，随后才启动本版trace100k。

**后置正确性完成**：trace跑满100k且NEMU无错；随后231568个commit的完整
字段、时间、顺序和字节与plain-SV Verilator黄金trace完全一致。
`v6/compare-result.json`明确`exact_fields_and_bytes_equal=true`。

动态manifest/生成代码审计进一步证明了隔离范围：raw clock直接组从
sn2919（146 ops/126 nodes）变为sn2958（1 op/1 node，即LogicNot）；原145个
操作仍全部存在于新图，但退出该直接clock组。全部event加clock直接组从
814 owners/159129 ops变为99 owners/7998 ops，151131个旧操作退出直接组而
未删除。main posedge从812 owners/158771 ops变为98 owners/7997 ops。
逐组样本预算中，direct union约16.870→5.856s，remaining NS约25.803→
38.063s；这包含owner重分类/迁移，不能把direct预算减少11s直接当作收益。
证据为`v6-ns-clock-audit/comparison.{json,md}`，未整读code-map。

other符号变化也精确闭合：`__memcmp_evex_movbe`估+6.463s，`bcmp@plt`
+0.010s，带ABI tag的生成string getter -3.309s，其余合计+0.003s。getter沿用
原分类记other；无callchain时不能把memcmp强行归到NS或writer。
证据为`v6-ns-clock-audit/other-symbols.{md,json,tsv}`。当前性能目标仍未达到，
clock拖带结构问题已隔离，NS整体和writer成本仍需继续分析。

**v6最终身份审计通过（retry1）**：
`v6-profile-identity-audit-retry1.json`为pass/failures为空，六阶段顺序为
generate→compile→run→profile→trace→compare。367生产源码、414生成文件、
全程binary SHA及跨阶段共享哈希一致；5个资源服务均128GiB/swap0/omit两端
验证、memory/swap事件全0，无PGO。原审计唯一失败为按行首解析命令漏掉两条
被并行Clang诊断拼接的TU282/283命令；新解析经独立复核恢复408条完整命令，
并额外精确核对407个TU对象与1个PCH均非空、mtime位于原fresh服务区间。
原失败script/report/log保留且哈希未变，没有重复编译或放宽验收标准。
ELF/perf无GNU build-id，按实际DSO路径及binary完整SHA链确认归属；原流程
未冻结profile.data输出哈希，此限制保留。性能仍未对齐，F25目标未完成。

**v7调查与实现方向（尚未测量）**：继续遵循先完整100k性能、再正确性的
顺序，禁用PGO。v6 writer的全函数exclusive预算按源码角色闭合为：含dirty
guard及私有计算48.103s、large capture及私有计算14.445s、其余私有计算
12.152s、纯chunk dispatch4.082s、其余guard/transfer/dispatch14.343s。
这是整函数包络，不能解释为各类指令的独立成本。证据在
`ptmp/firrtl-ingest/F25/v6-writer-audit/function-role-census.json`。

热点源/指令联合审计发现，`function-writer`为满足声明行数预算而强制spill的
一些数值临时变量仅在一个part使用，仍落入跨函数共享frame；在13个热点
batch的1370函数检查中，命中67个这样的frame访问样本，其中18个为常量写。
拟让具备明确无地址逃逸保证的生成函数，把这类单part数值临时量放入part内部
聚合对象，交给编译器消除中间存储；跨part、循环重复、参数、return控制、
非平凡类型和显式初始化仍保留原生命周期。当前尚未完成编译/测量/正确性
验证，不预报收益。

两个较小候选暂不作为主线：small array逐叶写循环的全部127个writer函数仅
143样本，完整函数预算约0.740s，合并markState只能覆盖其中一部分；
RenameTable动态connect在GSIM为顺序索引写，GrhSIM保留了全宽移位/掩码/
pack-unpack，三个owner共1560条链的完整NS预算约1.148s。sn5608完整预算
约0.657s，包含2600个SliceArray及publication，不能归因成一次私有state数组
复制。旧memcmp采样无CALLCHAIN/BRANCH_STACK，无法事后恢复调用者；已在
冻结v6二进制上安排独立完整100k的99Hz/DWARF4096诊断采样，不作为新的
安静性能基线，捕获后另存原始profile.data哈希及caller恢复率。

**v6独立调用链100k已完成**：冻结同一binary，99Hz/cycles:u/DWARF4096，
host165.484s、资源服务166.948s，128GiB/swap0/omit有效、资源事件0，141项
捕获身份前后一致。raw70,949,880B，SHA256为
`cf28960508ab6c8fa6a039ab82c4f7d9e243e981935bad29d0d9fa1f6247c5bd`。
16,379 samples、period850,920,052,902、lost0；9,309个symbol/DSO逐项与
perf report对账。原分析器假设flat header包含leaf，未适配callgraph首frame
格式而失败；保留原control和输出，在`analysis-retry1`解析现有文本，再以
同raw的flat导出按time/period对齐真实leaf，不重录。6个unknown leaf保持
unknown，没有把首个可展开user frame误当成原采样位置。

memcmp/bcmp共621样本、period32,262,299,045，直接caller全部恢复且与静态
bcmp返回地址匹配；NS620、other1，writer/Publish均0。最重caller
`sn_2813_chunk7`486样本、period25,248,467,774，占该helper约78.26%，实际
为长日志格式字符串常量的boundary比较，不是whole-array比较。

同次c1采样的flat NS正文25.5278%加调度4.9041%=30.4319%；按实际调用链
归入可恢复的共享helper后，NS正文29.9972%加调度4.9041%=**34.9013%**，
共5,716样本、period296,982,290,181。仅按旧quiet user171.80s归一，正文
51.535s、调度8.425s，合计约**59.960s**，为历史GSIM wall51.34s的约
**1.168倍**。这是同次诊断采样比例的归一估计，不能当作旧51.690s的精确
回填或本次capture的新quiet基线；GSIM终点不同的限制继续保留。用户指出
NS本身必须为sink留出成本空间的问题，依然成立。证据在
`ptmp/firrtl-ingest/F25/v6-memcmp-callchain/captures/c1/analysis-retry1/`。

独立复核通过（`v6-memcmp-callchain-analysis-retry1/independent-review.md`）。
sn2813_chunk7的45个bcmp调用点全部对应std::string常量，35点被采样。
单点相等比较长度124–179,773B，45点各执行一次相等比较合计4,345,847B；
这只是静态字节量，不能当作运行调用数或带宽。最热采样点对应161,605B
格式字符串。后续候选仅针对直接String Constant的唯一publication slot：
若证明其初始empty且以后只被同一常量赋值，可把原相等比较改为
`destination.empty() && !constant_accessor().empty()`。该形式保留首次lazy
初始化、实际getter的嵌入NUL行为及原copy/sync/activate顺序；不应用于
Assign或动态/held string，不提前初始化常量。本轮v7不包含此候选。

v7已安装并开始完整生成，先性能后正确性。112个后置runtime用例已准备，
含原108、局部数值聚合2例及显式初始化2例；新fixture在静态复核时把每组
16个scalar改为18个，以确实跨过24行声明预算，尚未运行。此修改仅涉及
test源码，保留安装前后旧哈希并另记fixture-only修订；生成器生产源码及
已安装library继续冻结，不改变v7性能模型身份。

**v7生成门禁失败，未进入编译/性能/正确性**：日志记录pipeline total
837.104s、emitter289.308s，但受限服务840.229s触发840s硬截止并被杀死，
资源结果`timeout`、Make exit2；peak113,511,645,184B。保留全部输出和失败
sidecar，不能把部分/已落地产物当作生成通过，也不运行准备好的后续验收。
v7只有静态实现与审查证据，无性能收益或正确性结论。
逐阶段journal按重复pass的出现次序对应，pipeline各stage合计v6为807.286s、
v7为835.509s；最大差项为源码未改的comm-expr32.825→51.529s（+18.704s），
emitter285.819→289.308s（+3.490s）。因此本次总超时也不能单独归因于
局部frame修改；此处保留失败门禁，不用这一推断替代一次成功的生成测量。

**用户再次明确的分析主线**：以同输入GSIM的阶段、普通Node语义、生成C++
为参照，定位同一逻辑从哪一步开始多出计算、跨组边界、搬运或调度；热点
仅用于给这些差异排序。现有F21资料按输入/源码身份分开复用，不能把旧图
计数当作当前生产图已对齐。`current-lowering`使用同一raw FIRRTL b313a3ec，
`continuous-state-split-v13`为旧cc46输入分支；两者producer仍为历史版本。
下一轮先形成可查的同逻辑双侧对照，保留复杂事件语义，继续先性能后正确性。

**同逻辑对齐继续落实**：Entry7的源寄存器、九路selector/比较/OR reduction、
NEXT/current复制及activation已逐段对上。GSIM也保留两版状态，故不能将
GrhSIM writer约93s简单解释为“不必要的shadow”；已确认的表示差异是公共
分支逐字段mux化、单part中间值落共享frame，以及同一regCacheIdx[0]产生
10个独立ReadState。最后一项可追至FIRRTL数组引用每次新建ReadArrayPort，
split-static-array原地改成标量ReadPort而不归一；GSIM多个reference共用
同一NODE_REG_SRC。当前CSE既不合并ReadState，也将这些读取的不同ValueId
带入下游表达式身份。仍需证明安全采样域后再决定在哪个pass对齐。
详见`F25-gsim-alignment.md`及`v6-writer-gsim-align/findings.md`。

v8已准备资源/安装入口，主改动是从早期GrhSIM dialect中将已证明同字节的
FIRRTL printf字面量抽为任务元数据，移除其runtime数据边及边界存储。通用
String、非printf任务及完整事件语义保留；旧版本reader明确拒新格式。已完成
安装（37.509s、peak1,331,507,200B，资源门禁通过）。随后完整生成在受限服务
840.2785s触发840s硬截止，结果为`timeout`、Make exit2，peak110,140,493,824B；
memory/swap事件均为0。`emit-grhsim-cpp`没有done记录，未生成成功结果。
已写完407个TU、code-map、manifest和Makefile仍属被中断staging，不能当作
生成通过。截止时正在输出约8GB的可选`grhsim.txt` readable StoreText；不由
部分产物推断编译、性能或正确性。保留失败sidecar及全部证据，停止后续编译、
quiet/profile、trace/compare和已准备的116例回归/审计，均未运行。
v7失败证据保留；本轮继续840s/330s硬门禁、完整安静
100k及独立profile100k在先，然后才做trace/Verilator及回归，无PGO。

**v9仅调整已有输出配置，复用同一producer**：使用现有
`XS_GRHSIM_READABLE_DUMP=0`，关闭可选的全图`grhsim.txt`文本导出，保留
完整C++、code-map和compact statistics。映射为根Makefile已有的
`--no-readable-dump`参数，最终仅跳过emitter的StoreText分支；原始FIRRTL、
固定22阶段、仿真语义和840s/330s门禁不变，不改生产源码、不重新安装。
所复用已安装library SHA256为
`d23b78ae4d46bb65385f40354f63a2e4807096ad466aafce8216a0ba1091e83a`。
`v9-workflow`的before/after源码与producer快照原样复制自v8安装证据，
`producer-reuse.json`明确记录复用关系；它们不是一次新v9安装的观测。
v9身份审计与116例回归已从已审v8模板准备，尚未执行，仍先完整性能后正确性。

这一配置变更的证据是emitter先完成C++/map/stats发布准备，再单独调用
StoreText导出可读图。历史F24 v14内部phase log记录
`readable-dump-start total_ms=200131`到`readable-dump-done elapsed_ms=73712`，
即该历史运行的73.712s；它不是v8实测时长，也不能直接扣减为v9预计收益。
v8的comm-expr为46.652s，v6/v7为32.825/51.529s，三者源码SHA、operation数
14,395,034及shared数3,482,129相同；现有wall数据不能证明此差异的CPU/
分配/调度成因。当前优先消除无对应默认GSIM全图dump的可选输出，再按原门禁
重新取得完整生成测量；没有放宽用户的`t_cpp`限制，也尚无v9收益结论。

**临时产物清理**：通过`cleanup-20261112/Makefile clean`删除v1/v2/v3/
v4-retry1/v5及失败v7的过时code-map，另清除前五版编译中间产物，共2034文件、
63,308,158,742B。精确路径、size/mtime及已有generation哈希记录在plan.json；
没有为清理重新扫描约56GiB code-map。所有源码CPP、二进制、日志和已完成审计
报告保留，v6与当前GSIM未动。被清理的大文件不能再作在盘重验材料，原成功
报告与原始身份记录继续保留，未将清理描述为重新验证。

**v9完整生成通过，控制器记录已限定恢复**：pipeline780.861s、emitter220.121s，
原始run journal完整22阶段并记录Make/command/tee均exit0；ExecStopPost为
success/exited/0。原launch至stop的epoch区间784.480s<840s，peak113,743,224,832B，
双端128GiB/swap0/omit验证、资源事件均0。外层控制器未写完汇总，原unit已被
systemd回收；没有重跑生成。`v9-control-recovery/`独占保存原始starting报告、
sidecar、journal、日志和identity，重新核对414个发布文件SHA及源码/producer
前后相等后，补齐兼容汇总。恢复明确保留原controller返回码、monotonic wall和
systemd-run返回码不可恢复的限制；784.480s是原epoch边界区间，非补造的外层wall。
独立`v9-control-recovery-independent-review.json`为pass/failures为空；已启动
330s新鲜完整编译，尚无本版运行或正确性结果。

**v9编译及安静100k通过，仍待采样与后置正确性**：新鲜完整编译服务272.457s，
GNU time272.27s，peak14,440,497,152B，成功最终LD并通过全部冻结核验；无PGO，
binary SHA256为`3fea8cbef6097e199c9672070d1a58cb49da27e40d0e2192c9f104f8cbc3f894`。
安静完整100k的host149.780s、external wall149.80s、user149.76s，NEMU无错且终点
guest100001/core99996/instr238535/PC80000cde。相对v6单次quiet wall171.85s下降
约12.83%，包含数值局部存储及printf字面量两项改动，不能只归因于其中之一，
也未作为重复测量的稳定提升结论。对历史GSIM wall51.34s仍约2.918倍；GSIM
终点不同，仍非严格同工作量parity。已启动同binary的99Hz/DWARF4096独立100k，
后续才trace、Verilator精确提交比较和116例回归。

**v9独立100k采样与归因通过**：同binary99Hz/cycles:u/DWARF4096，host156.250s、
user156.34s、wall156.53s，终点与quiet相同；raw66,997,616B，SHA256为
`ad50ee59e780bce0ef8575ad3fa4cb43561eb5dbf06f5672300cbd9cf9865cf4`。
15,467samples、period804,584,952,634、lost0，9,213项symbol/DSO的计数与period
逐项闭合。初次离线解析误拆含括号的C++符号，retry1又未接受perf的inlined
伪帧；retry2剩一项vDSO未知IP的绝对/映射偏移差异。原失败均保留，retry3用
同raw额外导出的MMAP按PID/time/IP/period证明offset，原unknown仍为other，未
重录或重导出原采样文本。`v9-profile-analysis-retry3/results/`及独立
`v9-profile-independent-review/reconciliation-review.json`均pass/failures为空。

| 同capture归属，按各版quiet user归一（估算秒） | v6 c1 | v9 |
| --- | ---: | ---: |
| NS正文，含可恢复共享helper | 51.535 | 40.850 |
| NS activity调度 | 8.425 | 8.233 |
| NS正文及其调度 | 59.960 | 49.083 |
| writer | 92.305 | 82.903 |
| LargeSink commit | 2.666 | 3.168 |
| Publish | 14.068 | 12.261 |
| NS内memcmp/bcmp子集，已含在NS中 | 6.503 | 0.959 |

v9 NS及调度32.7743% CPU period，归一49.0828s，为历史GSIM total wall51.34s的
0.9560倍；NS仍几乎耗尽GSIM总预算，writer占55.3576%，整体目标未达成。
45个旧长String发布点全部以同FIRRTL行+格式字节SHA匹配到新literal TaskArg，
对应成员/getter及NS常量producer均消失；35个旧采样点覆盖原486样本。该结构
差异确已消除，但剩余memcmp及NS不能被当作同一旧owner继续解释。
v6 profile/quiet user漂移−3.708%、v9为+4.394%，两次归一差值是估算而非精确
指令节省或稳定提速。完整双侧表在`v9-profile-analysis-retry3/v6-v9-comparison/`。
性能及NS关系已先报告，随后才启动本版100k trace；完整正确性仍待比较。

**v9后置完整正确性及六阶段身份审计通过**：trace100k NEMU无错；随后231,568
条commit完整字段、时间、顺序、文本/TSV/summary字节均与plain-SV Verilator
黄金trace一致，独立解析比较亦match；`v9/compare-result.json`明确
`exact_fields_and_bytes_equal=true`。生成→编译→quiet→profile→trace→compare顺序
符合要求，`v9-profile-identity-audit.json`为pass/failures为空，核对367份生产源、
414个生成文件跨阶段身份、407个fresh TU对象与1个PCH、完整binary SHA链及
无PGO；全部5个服务的双端128GiB/swap0/omit及零内存事件通过。生成外层控制器
观测缺口继续显式保留，没有将恢复sidecar的epoch区间冒充controller wall。
116例runtime及相关变换/ingest回归正在串行执行，本段不预先声明通过。

**v9后置回归通过**：`v9-regression/summary.json`为pass/failures为空，116个去重
CPU runtime用例全部完成：format4、numeric2、initializer2、clock8、sensitive24、
prior76；另9个CTest及9个FIRRTL effect integration用例通过。各阶段串行，
128GiB/swap0/omit、330s门禁实际双端生效，资源事件0；最长prior-runtime
208.864s，源码/安装producer冻结核对一致。六阶段独立复核进一步以实际服务
时间验证先quiet/profile再trace/compare，并将同raw/binary SHA联接到独立
采样分类复核（`v9-profile-independent-review/six-phase-audit-review.json`）。
本轮生成、编译、性能、正确性及相关回归验证完成；F25性能对齐目标仍未达成。

**后续候选排序纠正**：Entry7同29字段在v9机器码中，原10次相同current读已为
1次，G/H各29次直接读也均为1次；实际951条静态指令（原v6为1483）。新采样
该whole function仅1样本，估算约0.00969s，不能用源码58个select或旧30样本
继续宣称大收益。公共分支/读归一保留为未应用结构草案；后续先按v9完整writer
batch及同GSIM语义根核对，避免改写已被编译器消除的工作。

新capture全部writer owner聚合闭合到82.903s，最重batch824为2.15993s，
batch1124为1.79182s，两者合3.95175s，仅占writer约4.77%，不是可省时间。
有界双侧ROI已定位Delayer14的`REG.index/REG_1.index`（FIRRTL8810184/
8810258），以及IQ0 Entry2的`srcType[1]`（FIRRTL3812640）。后一payload在
v9 chunk135计算后跨part存到chunk242再写，接下来需证明是否可在保留原writer
顺序、current/NEXT采样及所有barrier的条件下缩短活跃期。GSIM也保留NEXT与
current提交边界，不能直接删shadow。排名证据在`v9-writer-alignment/`；ROI
仅选取根，不将其局部差异扩展解释全部writer。

## v10：私有 payload 就近 writer，局部中转消失但本次总时间回退

v10 在 exact small-run activity 资格之外，要求整个 run 都是非 history 的
scalar TwoState、1–64bit、三 operand `grhsim.write(fire, enable, data)`。
只有 Pure scalar 运算的全部 operand occurrence 都流向同一个 writer 的 data
才能后移；Shared/Prefix consumer 不进入 owner 表，其所有前置依赖自然留在
prefix。ReadState、控制/unconditional 运算及其依赖保留原 demand/采样位置。
每个 writer 仍按原序执行 next-shadow compare、write、dirty OR，run probe/clear
也保留。每个移动 payload 与原 writer 放入一个 structured scope，不复制计算。
超预算 scope 仍由原 splitter 正常拆分；FunctionWriter 本轮未改。

本轮相对 v8/v9 冻结源码的实际增量仅 emitter planner/stats、文档及两个新增
fixture；不是把累积 dirty diff 都算作本轮。独立语义/增量复核分别在
`ptmp/F25/v10-stream-plan/semantic-review.md` 和
`ptmp/firrtl-ingest/F25/v10-code-review/`。新增 b16/b1024 小模型预检通过，
包含实际同 part/无 chunkFrame 断言、shared、多 enable、old-current、双时钟、
A/B/A、mask/large 回退、重复 eval 和 reinit；原116例未修改。

**真实安装及完整性能**：本轮重新执行 capped `py_install`，31.341s，源码及
控制前后冻结一致，安装 producer SHA 为
`46841a9eb9e2e3cb11be82808e62675c587861e3c7d7cf2fb7e63847a8bdbeea`。
原始 FIRRTL SHA 和22阶段不变，仅沿用已有 `readable_dump=0`。本轮不使用
v9 producer 复用或控制器恢复例外。

| v10 实际完整窗口 | 结果 |
| --- | --- |
| 生成 pipeline / emitter | 773.312s / 226.617s |
| 生成 service / controller wall | 776.630975s / 777.791015s；840s 内 |
| 生成峰值 | 116,905,025,536B；128GiB/swap0/omit 双端核验 |
| fresh 完整编译 service / controller wall | 270.644496s / 281.201972s；330s 内 |
| fresh 编译产品 | 408 TU + 1 PCH + archive/link；无 PGO |
| quiet100k | host161.299s，wall161.32s，user161.28s |
| 独立 profile100k | host162.414s，wall162.70s，user162.52s；99Hz cycles:u/DWARF4096 |

同一新 binary SHA
`f12427a554ea9d8a82e379c008b2fc068d4e4b08fc17a6439f552c36eae8f3ae`，
quiet/profile/trace 端点 guest100001/core99996/instr238535/PC0x80000cde。
quiet 比 v9 wall149.80s **本次慢7.690%**，不是性能改进；单次差值不证明稳定
回退或具体原因。完整资源和身份链在 `v10/`、`v10-workflow/`。

独立 raw profile SHA
`6d98ff27a30da7fabcf255eed65db9b48f05c5c360f990347c0d1ce8ad36c48c`，
16,077 samples、period837,155,985,669、lost0，9,607个symbol/DSO行逐项精确
闭合。仅在需要时按本 capture 的 PID/time/MMAP 解释未知 vDSO 地址；unknown
分类不变。`v10-profile-analysis/results/` 与独立
`v10-profile-independent-review/{capture-review,reconciliation-review}.json`
均 pass。按各版完整 quiet user 归一的 caller-phase 估算如下：

| 成本估算秒 | v9 | v10 |
| --- | ---: | ---: |
| NS 本体，含可归属 helper | 40.850 | 42.139 |
| NS 调度 | 8.233 | 7.615 |
| NS + 调度 | 49.083 | 49.754 |
| writer | 82.903 | 92.540 |
| LargeSink commit | 3.168 | 2.841 |
| Publish | 12.261 | 13.135 |

v10 NS+调度为30.8497% period、历史GSIM total wall51.34s的0.9691倍；整体
quiet为其3.1422倍。GSIM端点仍不同，不能当严格parity。profile/quiet user
漂移v10为+0.769%、v9为+4.394%，阶段估算不是精确quiet计时。

**有界结构及机器证据**：完整图实际规划47,432 runs、173,929 writers、
1,050,304 ops 后移，这些是静态 site 数。八个选定 op 的真实符号、target、
operand/result、FIRRTL/source/resolved origin 与 v9 核对后，确认 Entry2
o34423784→o34423785 在 v10 TU352 `writer_run_batch1124_chunk122` 同函数，
最终payload由寄存器直接比较/写入相同shadow，v9 chunk135→242 的 frame
store/reload 消失。held current 前置值仍读frame，函数其他位置仍有栈spill。
Delayer14 两级current采样仍跨frame，不能算本轮消除。

同时，batch824/1124函数数分别430→515、282→303；静态frame引用减少但更多
helper并存，不能仅凭源码引用判断动态收益，也不能将不同siblings的整函数
字节/指令数相减归给一个根。源码/实际对象/编译身份及定点反汇编证据在
`v10-writer-alignment/v10/{source-findings,machine-findings}.md`。采样显示主要
回退成本位于writer区域，但尚未证明是helper增加导致。

完整性能及NS关系报告后，trace100k NEMU通过；随后231,568条提交的字段、顺序、
周期、文本/TSV/summary字节与plain-SV Verilator完全一致。
`v10/compare-result.json` 为pass、`exact_fields_and_bytes_equal=true`。
后置118例运行回归、9个CTest与9个FIRRTL effects集成用例全部通过，
`v10-regression/summary.json` 为pass/failures为空；原116例清单逐字保留，
新增private-payload组2例。各阶段串行330s/128GiB/swap0/omit双端生效，零内存
事件，最长prior-runtime209.038s。`v10-profile-identity-audit.json` 六阶段身份、
完整资源、真实安装、无PGO、415生成文件/408fresh TU/1PCH与binary链、性能先于
正确性的时序及离线采样闭合均pass/failures为空。本轮没有控制器观测缺口。
独立最终结审已在源码仍冻结时完成，
`v10-profile-independent-review/six-phase-audit-review.json` 为pass/failures为空；
另一路独立回归复核确认实际118个driver、9CTest/9effects及12阶段日志/资源链。

v10验证完整，但本次性能慢于v9，**F25仍未达标**。下一候选是按实际行数与
局部声明成本合并连续同enable的writer units，保留完整采样和writer顺序；
目前只有布局草案，未将其视为收益或性能验收。

## v11：连续同 enable 的有界 scope 分组，仍无已证性能改进

在 v10 的完整归属/采样检查之外，只将连续同 enable ValueId、同 exact run /
bitmap segment 的 writer units 合为一个 structured scope。保守成本为
`7 + body Code::lines() + distinct referenced locals <= max-function-lines`；
遇 enable/segment/run/预算边界关闭，不把 A/B/A 合并，超大单元保留 v10 正常
拆分回退。每次 packing reset、原 writer body/guard、next 比较及 dirty 生命周期
不变；FunctionWriter 和 fixture 源本轮未改。具体未应用草案与审查记录保留在
`ptmp/v11-stream-plan/`，随后应用为本轮冻结源。原118例生成/结构断言及两个
新增模型预检通过；生产预算的选中payload仍同part、无chunkFrame。

真实 capped 安装20.461s，producer SHA
`515a99043b2e7de58751aad3b4a2c7335fde870567af84b0707e663137f5a724`。
原始 FIRRTL 和22stage不变，完整生成日志 total747.255s、emitter223.015s；
service749.990281s、controller751.158508s，峰值107,605,504,000B，840s内。
fresh完整编译service258.769359s、controller267.550376s，407 TU + 1 PCH及
archive/link，330s内。414个生成文件/实际安装/原控制器/128GiB/swap0/omit
证据均保留在`v11/`、`v11-workflow/`，无PGO或恢复例外。

| 完整100k测量 | quiet | 独立profile |
| --- | ---: | ---: |
| host seconds | 161.755 | 156.001 |
| wall seconds | 161.77 | 156.23 |
| user seconds | 161.73 | 156.10 |

binary SHA
`ea56a3989e7426c74bf532d5ab9316962a4d365f55d376abae38ed520fbcd39b`，
quiet/profile/trace均guest100001/core99996/instr238535/PC0x80000cde。
quiet比v9单次149.80s慢7.991%，比v10慢0.279%，没有获得性能改进证据。
profile/quiet user漂移−3.4811%、wall漂移−3.4246%；profile绝对运行与v9的
profile接近，不把单次差值解释为稳定回退或scope分组的因果结论。

raw profile SHA
`4b15866a9317736fcc0284cf4d4fdb4520ea4a124a962c60297d64c13dc64507`。
15,442 samples、period802,924,233,780、lost0，9,165个symbol/DSO行逐项闭合；
4个未知vDSO样本只用本capture PID/time/MMAP解释，全部unknown raw仍归other。
离线对账及独立capture/reconciliation复核pass。按本轮quiet user161.73s归一：

| caller-phase估算 | seconds |
| --- | ---: |
| NS本体+可归属helper | 43.031 |
| NS调度 | 8.129 |
| NS+调度 | 51.160 |
| writer | 91.985 |
| LargeSink commit | 2.724 |
| Publish | 12.760 |

NS+调度31.6330% period，为历史GSIM总wall51.34s的0.9965倍；整体quiet为其
3.1510倍。GSIM端点不同，以上均为跨运行采样估算，不是严格parity。

有界三向source检查再次核对8根真实身份，实际覆盖仍为47,432 runs /
173,929 writers / 1,050,304 ops，与v10相同。Entry2在TU351 chunk83仍同part，
普通局部payload无frame/localFrame引用；batch824函数数430(v9)→515(v10)→
353(v11)，batch1124为282→303→324；writer sites恒13739/4386，两batch的
shared/localFrame引用数与v10相同。因此不能从局部helper数推全局收益。
Delayer两write合到chunk167，但current-read仍跨part。证据在
`ptmp/v11-writer-alignment/v11/source-findings.md`；本轮未新增机器码收益主张。

完整性能及NS关系报告后，trace100k通过；231,568条提交与Verilator精确字段/
顺序/周期/text/TSV/summary字节一致。后置118例runtime、9CTest、9effects集成
全部通过，最长prior-runtime208.550s，零内存事件，原始资源/控制器记录完整。

首次最终审计因compile log5502的diagnostic/compiler命令字节交织而失败，原
`v11-profile-identity-audit.json`及log保留。离线retry1限定raw log SHA、行号、
prefix/context SHA、完整TU371 argv及实际source SHA识别这个唯一边界；其他
未知prefix仍拒绝，407TU+1PCH、fresh对象/mtime/flags及无PGO全规则保留。
未重编译、未重录或改变原数据。`v11-profile-identity-audit-retry1.json`
已pass/failures为空；新独立最终复核
`v11-profile-independent-final-retry1/six-phase-audit-review.json` 也pass/failures
为空，且完成时源码仍冻结。该记录是离线日志解析修正，没有控制器恢复或时限
例外。首次失败及两个成功报告的source/log/report SHA均由后续恢复流程保存。

本轮两种布局均未获得性能改进验收。完整封存v11后，已应用独立审查的三文件
精确恢复补丁；cpu/test目标绑定历史v9复用SHA，docs目标明确来自保留v8文本，
不冒称v9有单独docs观测。完整累计diff SHA恢复为
`8f5a785f70d155dbd93b8a8e5669d64eea5d9f3ac3627ffc9310f0de008d7b53`，
其余12个累计修改保持原样，没有reset到git HEAD。恢复后生成/结构CTest3.90s
通过，原116例相关回归目标全部存在；没有把这次生成当作116例重新运行。
实际恢复安装31.444s、peak1,017,688,064B通过，原始controller/双端限额及
source/control freeze完整；实际producer SHA逐字节等于历史v9
`d23b78ae4d46bb65385f40354f63a2e4807096ad466aafce8216a0ba1091e83a`。
`install-after`/`check-evidence`均pass，没有用旧安装结果冒充本次安装。
计划、逐字节逆向路径及检查在
`ptmp/F25/restore-v9/`，本次真实安装在
`ptmp/firrtl-ingest/F25/restore-v9-workflow/`。v10/v11全部历史证据保留。
独立恢复结审 `ptmp/F25/restore-v9-completion/completion.json` 为pass/failures为空，
核对三文件/12个非目标sections、实际安装与资源、v11原失败及两份PASS历史链。

**v10/v11恢复时状态**：源码及安装恢复到v9；本次没有重新生成/编译v9全图或重测其
149.80s性能，沿用已审计历史证据并明确时间边界。两个候选正确性/资源验证
完整，但未证得性能收益，不能以局部frame消除宣布对齐。后续须以更大动态
覆盖的同GSIM语义根排序writer差异，避免继续把少数ROI或scope数量当总收益。
F25目标继续进行，尚未完成。

## v12：shadow 通知聚合未取得性能收益

v12 从恢复后的 v9 出发，在既有 eligible exact run 内按完整、不可变的
`sinkTargetFanout` mask key 聚合重复 shadow 通知，并删除 dirty guard 内
已经为 1 的自身位。实际 shadow 写入及 `dirtyStateFlags` 仍立即发生；重复
非空 key 的 bool 在原 run 入口初始化，在完整有序 body 之后、原 clear 之前
flush。采样、enable、writer 全序、run 边界及 fallback/current/large 路径
保留；未合入归档的 inner-guard 草稿。

真实安装及原始 FIRRTL 完整 22 阶段生成、fresh 完整编译均通过，无 PGO，
保持 `readable_dump=0`，保留 C++、code-map 和紧凑统计：

| 阶段 | controller wall s | resource elapsed s | peak bytes |
| --- | ---: | ---: | ---: |
| 实际安装 | — | 31.644828 | 1,023,614,976 |
| 完整生成 | 756.443175 | 755.273804 | 110,157,709,312 |
| fresh 完整编译 | 258.606958 | 249.887616 | 14,301,503,488 |

生成 emitter 为 219.966s，406 TU、60,771 functions；生成/编译均满足
840s/330s，独立服务 128GiB、swap0、live omit 有效，内存事件为零。
eligible runs/writers 保持 95,885/293,060；静态 shadow mask sites 从
580,098 降为 309,413，含 15,022 个聚合组和 71,350 个 self-only sites。
定点机器码证实自身 OR 删除和重复通知单次 flush；这些不是动态次数或收益。

| 完整 100k 测量 | wall s | user s |
| --- | ---: | ---: |
| quiet | 160.98 | 160.94 |
| 独立 99Hz / DWARF4096 profile | 161.45 | 161.27 |

主分析和独立复核均逐项闭合 15,953 samples、831,629,539,467 period、
9,360 symbol/DSO 行，lost0。按本轮 quiet user 换算，NS 正文和可归属 helper
约 42.649s、NS 调度 7.800s，合计 **50.449s**；writer 约 **91.843s**。
NS 合计为历史 GSIM 整体 wall51.34s 的 98.264%，整体 quiet 约为其 3.136 倍。
采样和 quiet 来自独立运行，GSIM 提交终点不同，不构成严格 parity。

性能及 NS 关系报告之后，trace100k/NEMU 和 231,568 条 Verilator 精确提交比较
通过，字段、顺序、周期及 text/TSV/summary 字节均相同。后置回归实际为
8 个 CTest 通过，生成器 CTest 在 2.08s 因漏查的旧结构断言失败：
`bindSinkActivitySites` 仍要求 `shadow_change_mask_sites >= runs`，而三个
self-only run 实际 before=3、after=0、self-only=3、removed=3。该断言失败
本身不证明运行时语义错误，但阻止了完整 fixture 生成，120 个 runtime 例
未执行。冻结测试、源码及审计要求均未放宽。

原完整审计实际 exit2，因缺 `v12-regression/summary.json` 留下原 traceback，
没有最终审计 JSON。独立补充报告固定为 `not_accepted/accepted=false`，
十节中只有 regressions 失败，其余九节已验证；不替代完整审计 PASS。
证据在 `F25/{v12,v12-workflow,v12-regression,v12-profile-analysis,
v12-profile-independent-review,v12-incomplete-regression-review}/`。

为检查非同期成绩漂移，另以原审计 ELF 进行了完整 100k 串行 quiet 诊断：

| 顺序 | 模型 | wall s | user s |
| --- | --- | ---: | ---: |
| A1 | v9 | 155.19 | 155.15 |
| B1 | v12 | 160.50 | 160.46 |
| A2 | v9 | 157.06 | 157.01 |

三次 CPU2、seed0、单模型线程、CoreMark/NEMU 和 golden endpoint 相同，
source/control/ELF 身份及独立资源检查通过。B1 相对前后 v9 wall 几何均值
慢 **2.804%**，A2/A1 漂移 **1.205%**；未显示收益。它只用于漂移诊断，
不替换原 quiet160.98s 或历史 v9 149.80s，不提供源码因果证明或严格 parity。
两版均使用相同 launcher 和独立 runtime cwd，GNU time 包含 launcher 启动。
原始计划和三段结果在 `v12-investigation/paired-quiet-diagnostic/`。

**当前处置**：v12 已拒绝，三个文件已精确恢复到保留 v9 基线，其余十二个
累计修改保持；完整累计 diff SHA 回到 `8f5a785f…7b53`，没有 reset 到 HEAD。
真实重新安装 resource31.174455s、peak1,022,644,224B，双端资源及 source/control
检查通过；实际 producer SHA 与历史 v9 完全一致：
`d23b78ae4d46bb65385f40354f63a2e4807096ad466aafce8216a0ba1091e83a`。
恢复后的生成器 CTest3.73s 通过，不冒称116个 runtime 例重新运行。
`v12-restore-v9-workflow/check-evidence.json` 为 pass，仅覆盖精确恢复和真实安装；
v12 原实现、完整差异、失败和全部测量证据保留。当前源码/安装为 v9，
F25 性能目标未完成。

## v13 前置调查：按机器残余与完整覆盖选择候选

本次调查未修改生产 emitter、生成新模型或重新计时；源码及安装仍为 v9。
原始 v9 profile 的 8,558 writer samples 和 82.903s 估计继续作为成本分母。

- IQ0 Entry2 `regCacheIdx_1` 的 9 次比较读与 1 次 hold 读，在实际 v9
  `batch1124_chunk56` 只剩两次同字段 byte load；九路比较共用第一次读取，
  其中八路已向量化。第二次是 hold 路径读取。整函数只有 3 samples/约0.029s，
  因而没有把源码十次读取当作十次可省访存。精确 state/源行/ABI/ELF 证据为
  `ptmp/F25/v9-current-reuse-review/{entry2-machine.json,findings.md}`。
- 共享 mux 调查两次独立验证全部407 TU/6,774,949,472B及20,733 writer函数
  SHA。相同函数/brace scope 内共有13,251个重复 selector-tree 字段族，但其
  **整函数**只覆盖686 samples/约6.644s。补充跨split分析后，按batch sibling
  合并的宽松整函数包络为760 samples/约7.360s；具有相同已知exact-run
  dirty owner的为482 samples/约4.668s。前者混合不同run，后者仍未证明
  EnableSet及采样支配关系；均不是选择操作成本或提速估计。实际sample落在
  cmov的总计58个，其中同函数含4+根字段族的为38个。不能从巨大静态字段数
  推断它解释整个writer预算。证据为
  `ptmp/firrtl-ingest/F25/v13-investigation/mux-census/`。
- fire/call 调查闭合batch824完整430函数/429条唯一父调用边，无event修改或
  未知callee。单一fresh-fire root支配的32个helper入口仍保留同event机器
  分支，计35 samples/约0.339s IP包络；不是保证可省时间。全capture的808个
  event入口branch samples中565个属于root门，不能直接删；其余243个chunk
  samples尚未全部证明冗余。已建立writer条件与单fire batch上下文是两个
  不同候选，不把全部branch或调用参数搬运归为它们的收益。证据为
  `v12-investigation/writer-guard-call/findings.md`。

下一项正在核对的较广差异是每字段shadow变化分支：既有同语义GSIM Delayer14
对象以`cmp/setne`计算change，写NEXT后把change位OR到activation；v9以
`if(candidate != next)`包住store和通知。新草案只在既有eligible small scalar
writer原位置计算零/全一change mask、写同一next并立即按mask更新全部原dirty
位；没有v12的通知聚合或self-bit删除。它可能减少分支，也会增加unchanged
时的store及零mask RMW流量，尚无收益结论。草案、约束和独立审查材料放在
`v13-investigation/shadow-change-{design.md,draft/}`；尚未作为完整性能候选冻结。

随后完成独立静态语义审查并应用三个开发文件，原v9三文件和完整累计diff已
保存在`shadow-change-draft/baseline/`；其他12个累计diff sections逐项保持。
当前**源码为scalar change-mask开发候选，已安装producer仍为v9**。应用后的
完整累计diff SHA为`584faf3e6826dffa03d69e5daacfb8ff0a5c0fff2a4715def068a971a0237ac6`。
生成器预检CTest通过3.85s，独立资源服务30.614s/peak493,813,760B；两个新fixture
各实际覆盖48个eligible scalar writer sites，保留130-run/多字fanout fixture也
明确验证新route统计。此处仅为生成/结构检查，不能当作118个runtime回归通过。
随后四个定向runtime通过：两个新scalar-mask用例和两个保留130-run/多字
fanout用例，预算16/1024。独立资源服务19.886s/peak581,066,752B，完整
双端资源记录、无PGO及source/installed身份核对通过；本次为O1+counter
开发预检，不是full model O3 codegen证据或完整118例回归。
`v13-investigation/targeted-precheck/summary.json`为pass。尚无v13完整100k性能成绩。

补充机器绑定完成：原v9的`batch824_chunk300`两个uint64 counter（两个完整
fanout words）、`batch1125_chunk191`两位依赖字段及`batch431_chunk33` bool
blocked（无sink fanout）均实际保留shadow compare→branch→store→state dirty→
完整fanout顺序。三函数/四个采样站点是机制见证，均仅约两个whole-function
samples，不冒充热ROI。直接RDI/Next范围/短CMP窗口定位到的125个branch
samples只是严格定位子集，既不是全部shadow成本或上界，也不是可省时间。
证据为`ptmp/F25/v9-shadow-branch-review/findings.md`，初次parser失败全部保留。

完整v13实验已另行冻结：`v13-workflow/`的真实新安装31.084253s、
peak1,026,981,888B，source/control前后相等，原控制器及双端330s/128GiB/
swap0/omit证据通过，无producer复用或恢复例外。实际安装producer为
`9177458b234f27b94a29e540fed456a5bf6e53e3a7451b9ed27ece60d6043667`。
当前源码/安装均为实验v13，完整生成已从原始FIRRTL启动，尚无完整模型性能
或正确性验收；v9仍是此前保留基线。完整控制独立审查、主/独立对账和report
关卡预演的证据在`v13-investigation/{controls-independent-review,workflow-schema-review}/`。

**v13完整生成通过，fresh编译进行中**：原始FIRRTL完整22stage均完成，
pipeline772.920s、resource service776.087033644s、controller wall777.250087010s，
peak114,188,435,456B；原始控制器returncode0，840s/128GiB/swap0/omit双端
资源检查通过，无PGO，生成前后source/control及实际新producer身份保持不变。
本轮没有复用历史producer或运行证据，也未使用控制器恢复例外。证据为
`v13/{generate-result.json,generate-exit.json,generate-resources.json,generation-audit.json}`
及`v13/{generate-driver.log,logs/stages.jsonl}`。随后已启动同冻结模型的fresh完整编译，仍执行330s
截止；目前尚未完成，不能声明编译通过。尚无v13完整100k性能或正确性验收，
v9仍为此前保留基线，F25性能目标未完成。

**v13 fresh编译及完整100k性能已完成，尚待后置验收**：完整编译resource
service269.114522148s、controller wall277.945692344s，peak14,488,018,944B，
原始控制器成功，330s/128GiB/swap0/omit门禁通过，无PGO。证据为
`v13/{compile-result.json,compile-exit.json,compile-resources.json}`。

| 完整100k测量 | wall s | user s |
| --- | ---: | ---: |
| quiet | 155.55 | 155.51 |
| 独立99Hz / DWARF4096 profile | 150.24 | 150.11 |

主分析及独立capture/reconciliation复核均通过，14,847 samples、
770,283,214,903 period、8,919 symbol/DSO行、lost0逐项闭合。按本轮quiet
user归一，NS正文及调度估算**49.846841155s**，writer估算**86.153921842s**。
NS及调度为历史GSIM整体wall51.34s的97.092%；整体quiet约为其**3.030倍**，
F25性能目标仍未达标。GSIM终点为guest100001/core99998/instr238550/
PC80000b40，v13为guest100001/core99996/instr238535/PC80000cde；终点和
组件范围不同，不能声明严格parity。profile比quiet的user低3.472%，wall低
3.414%；独立运行的漂移及采样估算不能作为稳定性能收益或精确阶段耗时。

性能报告已向用户报告，随后显式`report-record`成功。精确报告为
`v13-workflow/performance-report.md`，SHA256
`b6f3f940ef835fe807332835910f2029c6ba48d58a7cde2e1242a958fcbbafc2`；
正文/输入元数据和报告确认分别在`performance-report.json`、
`performance-reported.json`。原始测量见`v13/{run-time.txt,profile-time.txt}`，
主对账为`v13-profile-analysis/results/reconciliation.json`，独立复核为
`v13-profile-independent-review/{capture-review.json,reconciliation-review.json}`。
本段不认证trace或118个runtime回归通过，后置精确提交比较、完整回归及最终
身份审计仍待验收；v9仍为此前完整验收并保留的基线。

随后trace100k/NEMU通过，231,568条提交与Verilator的字段、顺序、周期及
导出text/TSV/summary字节精确一致，见`v13/compare-result.json`和
`v13/trace-comparison/comparison.json`。完整回归的前四个独立服务、8个CTest
通过；原`suite`随后在`check-inventory`以exit2停止，runtime尚未执行。
原失败为把全部生成用例数错误要求为118：实际为202，而历史v9原PASS记录
本就为200个生成用例、选中116个；本次新增2个后应选中118个。原
`v13-regression/{inventory.json,inventory.log}`和冻结控件完整保留，不能
宣称原suite通过。正在独立核对202个生成规则及118个选中用例，补充审计和
剩余runtime仍待完成；未修改生产源码、原控制文件或已完成六阶段证据。

实际O3同根检查也已完成：`o33918715/o33918727`在TU320的
`writer_run_batch824_chunk284`，`o34553847`在TU367的
`writer_run_batch1125_chunk186`。三处均先比较旧Next、再无条件store，以
setne/cmove保留原dirty位及完整fanout words；没有changed-derived JCC或
新增mask frame/stack spill。`o16250721`在TU248的原bool路径仍有changed
JCC；由accepted run必给每个target加入自身ordinal、实际完整key为空的
不变量反证其freshFire=false，具体rejection原因未知。完整生成统计有
265,397个scalar-mask writer站点，但四个见证不代表全局机器形态或动态收益。
证据在`v13-investigation/shadow-codegen/{findings.md,four-exact-proofs.json}`；
初次source识别失败和自动`review-needed`记录保留，后续精确有界指令证明
另存，未覆写为自动PASS。两个u64的word1477由旧byte窄化更新变为完整64-bit
写回，说明消除条件分支同时可能增加访存，不能仅凭branchless判定优化有效。

**v13后置补充回归及原最终身份审计实际通过**：在保持原库存失败和冻结控件
不变的前提下，独立补充控件确认202个唯一合法生成规则=历史200+新增2，
选中118=新增2+原顺序116，额外84为既有fixture。补充preflight只纠正
“整个generated必须等于118”的错误断言，绑定原失败inventory/log、源差分、
全部选中driver/run.mk及source/install/229个冻结control身份；详见
`v13-investigation/regression-inventory-correction/{README.md,preflight.json}`。

随后实际完成118个runtime、9个CTest、9个FIRRTL effects integration及6个
terminal检查，补充审计为PASS/failures为空。12个独立服务串行，330s/
128GiB/swap0/omit双端资源与零内存事件均通过，source/install/control保持；
独立原始证据复核亦PASS，见
`v13-investigation/controls-independent-review/regression-correction-raw-review.{json,md}`。
原`suite`仍为FAIL，原`inventory.json`/`inventory.log`未改，不将补充通过
重写成原suite通过。

经独立复核后显式`publish`将同一明确标注补充来源的摘要独占写入此前不存在的
`v13-regression/summary.json`，与
`v13-investigation/regression-inventory-correction/summary.json`同字节，SHA256
均为`f7c14e93e9c0e56c0e077ee3b3ebc86490731d157657148a530c340e7e4838d4`；
其中明确保留`original_suite_status=fail`及`original_inventory_status=fail`。
随后未修改的原最终审计实际exit0，`v13-profile-identity-audit.json`为PASS/
failures为空，绑定该摘要SHA，完整source/ELF/raw/资源/报告先于trace顺序及
231,568条Verilator提交字段/周期/顺序/字节比较通过；原审计日志保存在
`v13-identity-audit/audit.log`。

当前v13完整性能仍为quiet wall155.55s/user155.51s，NS+调度估算49.847s、
writer86.154s；尚无稳定收益结论，整体约历史GSIM的3.03倍且终点不同，
F25性能目标未达标。v9→v13→v9同期quiet诊断已通过控件静态独立审查，
准备开始；目前尚未freeze或运行，没有新的诊断计时。控件审查见
`v13-investigation/controls-independent-review/paired-quiet-inventory-gate-review.{json,md}`。

随后同期诊断实际freeze通过，
`v13-investigation/paired-quiet-diagnostic/{freeze.json,plan.json}`已创建，plan SHA256为
`a1cc0ea29158ac9fdd7107f7edc2085e0714efd3c74432192786a65c35967df9`。
首段A1(v9) quiet100k已启动，正在运行，尚无A1结果；完整A1/B1/A2诊断未完成，
没有新的诊断计时或稳定收益结论。

**同期v9→v13→v9诊断随后完成，实际独立审计PASS**。三段均以原ELF、CPU2、
seed0、NEMU、单模型线程、quiet/无PGO和独立runtime cwd严格串行运行；
305s/128GiB/swap0/omit原始服务及完整start/stop资源证据通过。实际ELF、
263个source、229个冻结control、安装及请求身份、共享135项和六个边界快照
逐项闭合；v13最终身份审计与补充118回归来源也保持。原suite及库存FAIL、
补充118PASS和显式发布的同字节摘要均保留。

| 同期quiet100k | wall s | user s |
| --- | ---: | ---: |
| A1：v9 | 157.48 | 157.44 |
| B1：v13 | 149.95 | 149.91 |
| A2：v9 | 157.58 | 157.53 |

独立解析raw/GNU time所得wall B1/两段A几何均值为**0.951882229119**，
即本次B1低**4.8118%**；A2/A1为**1.000635001270**，漂移约+0.0635%。
三段终点均为guest100001/core99996/instr238535/PC80000cde。原审计见
[paired quiet audit](../../ptmp/firrtl-ingest/F25/v13-investigation/paired-quiet-diagnostic/audit.json)，
实际独立复核见
[review.md](../../ptmp/firrtl-ingest/F25/v13-investigation/controls-independent-review/paired-quiet-actual-review.md)及
[review.json](../../ptmp/firrtl-ingest/F25/v13-investigation/controls-independent-review/paired-quiet-actual-review.json)。

这是仅含一次B的历史二进制同期诊断，没有重复B或置信区间，不证明因果或
稳定收益；不替换主v13 quiet155.55s或历史v9 quiet149.80s。**暂保留v13继续
实验**。主测量整体仍约为历史GSIM的3.03倍，GSIM终点不同，不能声明严格
parity，F25性能目标仍未完成。

### v14：完整 writer 指令调查与调用端 fresh-fire 分组

2026-11-12 UTC。完整v9 writer指令复核已闭合8,558 samples /
445,398,547,864 period、8,088个IP、5,798个函数及944个采样batch；branch
占43.1378%、register compute32.8622%，393个unknown保留完整权重。使用已验收
原ELF解码和先行同PID MMAP2→file offset→PF_X PT_LOAD→精确instruction start
建立加载关联，保留无法证明完整虚存生命周期的限制。首次全unknown结果未覆盖，
未新解码或跑模型。详见
[全量census](../../ptmp/firrtl-ingest/F25/v13-investigation/writer-ip-census/findings.md)。

同一完整canonical fresh-event集合的连续root可在调用端增加外guard；原v9
实际前缀证据覆盖44组/1,019个root（共1,134个）。完整函数包络692 samples /
36,014,035,221 period，约writer的8.0858%、归一6.7034s，含true/false及
scaffolding，不是可省时间，也不能用上述43.1378%替代该候选覆盖。

v14在完整累计v13上实现这一候选：验证EventEdge/Assign/Or/false的typed
完整叶集合，按实际ValueId去重，仅相邻相等非空集合、至少两个batch加guard；
原root及内部fire/activity/writer顺序全部保留。NS前缀及large-enable reset
保持原位置；unclocked/latch及含非平凡局部对象的batch保留原调用并打断分组。
原v13三文件、完整diff、其余12个累计section和完整旧测试产物已精确归档，
包括原suite/库存FAIL与补充118PASS证据；没有修改旧冻结控件来接受新实现。

独立producer和fixture静态审查通过后，精确应用三个文件。development
generator实际service31.943985621s、peak497,651,712B，330s/128GiB/swap0/
omit双端核验通过；CTest1/1通过（4.68s）。四个新增fixture在16/1024两种预算
下分别实际生成7batch/2groups5roots/max2events及5batch/2groups4roots/
max2events，验证完整分组、合法latch fallback、held与fresh区别、原调用顺序
及真实String局部的fallback。这是当时的结构预检，彼时尚未执行这些driver或接受
运行正确性；后续正式suite结果见下文。
两处早期fixture错误及修复前版本已保留；未放宽IR验证。

五个全新v14控制包已独立复核：selected122=新增4+完整原v13的118执行顺序，
generated206=selected122+明确既有84，所有规则/recipe/phony唯一检查；原两例
scalar case保持。实际freeze后真实安装32.209554361s、peak1,030,520,832B，
source及230个controls前后相同，安装审计PASS。新producer为
`f243634e02664b2c941733710b220b1a4fd5d451df1297e93a2f442977b318e9`。
原840s完整raw22stage生成随后通过，原Make/controller exit0，service
773.223699471s、controller774.438467691s，peak112,570,818,560B；双端
128GiB/swap0/omit及原始raw22stage核验通过，无resume/PGO。fresh完整编译随后
exit0，service263.774657780s、controller272.658062760s，peak15,014,838,272B；
原330s/128GiB/swap0/omit双端核验通过，新ELF SHA256为
`eeb8335c3449d7c5424c3aa222d347b057dfdbb6202ca777ce64ad15520e0ecb`。

quiet100k与随后独立99Hz/DWARF4096 profile现均terminal exit0：quiet
wall143.02s/user142.98s、host143002ms；profile wall149.85s/user149.73s、
host149619ms。两次结果均记录guest100001/core99996/instr238535/PC0x80000cde。
主离线分析和独立capture/reconcile随后均PASS：14,809 samples /
770,023,179,677 period、lost0，8,942个symbol+DSO逐项闭合，flat/caller分类
分区均闭合。按本轮quiet user142.98s归一，exclusive NS估算39.945396s、其
dispatch7.426375s，二者合计**47.371771s**；writer估算**78.181119s**。
`general_mixed_dispatch`另计**1.100926s**，未包含在上述NS+其dispatch中。
这些是采样归一估算，不能当作精确组件计时或将混合caller全部归入NS。

正式性能报告已实际向用户展示各项指标、端点差异及估算边界，并单独执行
report-record PASS，报告SHA256为
`d5e72380a10a75a34b797eb9277963e47295a35bc9f5d9bcf75c42f7c10cc8a0`。
历史GSIM whole-simulator wall/user为51.34/51.33s，其端点为
guest100001/core99998/instr238550/PC0x80000b40，与v14不同；NS估算相对GSIM
整体wall不是等价组件分母，不能宣称严格parity或F25完成。本轮仅一次quiet和
一次独立profile，不证明稳定收益或因果；历史v13原主155.55s与单B同期149.95s
均保留。

显式报告记录之后，trace和精确比较现已全部PASS：完整100k窗口的231,568条
commit字段、顺序、周期以及commit.trace/commit.tsv/summary.json导出字节
均与冻结golden一致。正式suite原控制器exit0，122个runtime、9个CTest、9个
FIRRTL effects通过；selected122/generated206及既有extra84独立库存核验正确，
13个串行服务均在原330s/128GiB/swap0/omit双端约束内成功。原最终身份审计
控制器exit0，audit.log为status=pass/failures=[]，
`identity_resource_correctness_profile_audit_passed=true`，链接同一实际安装、
源码/控制冻结、ELF、profile全量对账及上述trace/回归结果。

**v14本轮完整身份/资源/正确性/profile验收链通过，quiet143.02s为新的主性能
观测。**原v13主155.55s、单B同期149.95s及原suite/库存FAIL与补充PASS历史均不
覆盖。用户明确要求“做完v14就先停一下”，因此本轮v14验收完成后暂停后续工作。
可选同期v13→v14→v13诊断仅部分准备，控件准备/review已中断；未授权或执行
实际paired freeze/run，也未验收。现有单次v14观测不能证明稳定收益，严格GSIM
parity仍不成立，F25总体目标仍远未完成。

本次完整生成的实际sink统计为1,134 writer batches、34个caller groups覆盖
1,064 batches、最大5个fresh事件；累计scalar shadow change mask sites仍为
265,397。这是新生成结构计数，与原v9 machine-prefix的44组/1,019 roots属于
不同证据，不能套用其692样本或6.7034s历史包络，也不证明新caller的机器绕过、
性能改善或运行正确性。

实际证据：
[开发计划](../../ptmp/firrtl-ingest/F25/v14-investigation/caller-fire-draft/plan.json)、
[生成器资源](../../ptmp/firrtl-ingest/F25/v14-investigation/caller-fire-draft/generator-resources.json)、
[安装审计](../../ptmp/firrtl-ingest/F25/v14-workflow/install-audit.json)、
[控制包独立审查](../../ptmp/firrtl-ingest/F25/v14-tool-preparation/independent-controls-review-1.md)、
[完整生成审计](../../ptmp/firrtl-ingest/F25/v14/generation-audit.json)、
[生成结果](../../ptmp/firrtl-ingest/F25/v14/generate-result.json)、
[原始退出记录](../../ptmp/firrtl-ingest/F25/v14/generate-exit.json)、
[生成资源终态](../../ptmp/firrtl-ingest/F25/v14/generate-resources.json)、
[实际sink统计](../../ptmp/firrtl-ingest/F25/v14/model/sink-activity-stats.json)、
[完整编译结果](../../ptmp/firrtl-ingest/F25/v14/compile-result.json)、
[编译退出](../../ptmp/firrtl-ingest/F25/v14/compile-exit.json)、
[编译资源终态](../../ptmp/firrtl-ingest/F25/v14/compile-resources.json)、
[quiet计时](../../ptmp/firrtl-ingest/F25/v14/run-time.txt)与
[结果](../../ptmp/firrtl-ingest/F25/v14/run-result.json)、
[独立profile计时](../../ptmp/firrtl-ingest/F25/v14/profile-time.txt)与
[结果](../../ptmp/firrtl-ingest/F25/v14/profile-result.json)、
[主全量对账](../../ptmp/firrtl-ingest/F25/v14-profile-analysis/results/reconciliation.json)、
[独立capture](../../ptmp/firrtl-ingest/F25/v14-profile-independent-review/capture-review.json)与
[reconcile](../../ptmp/firrtl-ingest/F25/v14-profile-independent-review/reconciliation-review.json)、
[已展示的正式报告](../../ptmp/firrtl-ingest/F25/v14-workflow/performance-report.md)与
[显式记录](../../ptmp/firrtl-ingest/F25/v14-workflow/performance-reported.json)、
[完整trace结果](../../ptmp/firrtl-ingest/F25/v14/trace-result.json)、
[精确比较](../../ptmp/firrtl-ingest/F25/v14/compare-result.json)、
[122例回归摘要](../../ptmp/firrtl-ingest/F25/v14-regression/summary.json)、
[原最终审计输出](../../ptmp/firrtl-ingest/F25/v14-identity-audit/audit.log)及
[完整身份审计报告](../../ptmp/firrtl-ingest/F25/v14-profile-identity-audit.json)。

随后实际生成器独立复核PASS：完整旧tar及237个已绑定成员、三文件及其余12
section、实际206规则/244个selected driver与run.mk、四fixture的完整调用顺序、
函数预算和counter site均闭合，见
[actual review](../../ptmp/firrtl-ingest/F25/v14-investigation/generator-review/review-3.md)。
fresh-fire两fixture在emit后注入唯一held-false测试hook，因此当前测试header的
FNV不再等于原emitter tag；仅移除该hook的内存重构精确匹配原tag，最终测试源
由独立SHA/site检查绑定。不能称这两个instrumented fixture的严格native
metadata loader校验通过；该次结构审查当时尚未运行直接driver，后续正式suite
已执行全部122个runtime并通过。原审查脚本的两处解析错误、
失败结果及源码也已保留，未改生产或冻结包来通过复核。
