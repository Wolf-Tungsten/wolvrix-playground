# F10 代表模块比较

脚本 `scripts/xs_firrtl_compare.py` 使用同一份原始香山 FIRRTL 和冻结生成
SV，分别执行 native FIRRTL/mixed ingest 与 SV ingest，再进入相同 GRH
和 GrhSIM flow。SV 文件只收集被选 top 的可达模块和真实 assertion DPI
声明，不沿用历史 ROB benchmark 的端口豁免或 assertion stub。

FIRRTL 的 `off`、`prefer` 两个模型从同一份完成普通优化、node CSE 和
event/output/nonsink/sink split 的 checkpoint 分叉；两者的
`optimized_checkpoint` 身份写入生成模型 identity。node CSE 都使用
`gsim-soft-v2`，supernode 容量为 128 个 node。`prefer` 的有效提示统计
保存在每个模型的 `generation-identity.json`，可核对 flatten 后仍有提示。

端口配对按 SV 的真实 packed struct/array 位布局与 FIRRTL 的保留 shape
展开到逻辑叶子，拒绝宽度、方向、不完整输出和歧义绑定。端口以 JSON 的
真实 port list 为准；多个常量输出可共用同一 value，仍保留每个输出名和
观察位。冻结 SV 的 `attribute_0` 与 FIRRTL 的 `attribute` 做明确 ABI
字段改名配对，保持真实成员访问并检查宽度和方向。firtool 已经通过
层次引用移除的 passive Probe 输出，保留在 native off/prefer 之间比较；
它们不冒充 SV 输出比较。被 SV 优化删除的 FIRRTL 输入显式记录在
`bindings.json` 的 `retained_extra_inputs`，driver 对其保留初始化值；有
用户的未配对输入必须通过原始整机 FIRRTL context constant 审计，否则
生成 driver 失败，不能将未知输入默认为零。

初始化使用 source unknown，经共享 `grh-to-grhsim logic_domain=2state`
显式转换。Verification.Assert/Assume/Cover 层启用，SV `xs_assert` 和
`xs_assert_v2` 真正终止 driver。每个时钟电平连续调用 eval 三次，并要求
观察输出稳定。没有通过关闭验证层或忽略 assertion 达成比较通过。

## 激励与观察范围

| 模块 | 激励 | 比较范围 |
| --- | --- | --- |
| RenameTable | 4 cycles reset，随机 read/specWrite/archWrite/diffWrite 端口，snapshot enqueue、rollback 和普通 redirect | cycle 8 起所有输出，低/高电平各观察一次，额外 native Probe 只比较 native 两模式 |
| 128×138 SRAM | 先完整写入 128 个地址，再随机读写、双 69-bit lane mask 0/1/2/3 和 enable=0 | 仅定义的同步读结果；全部三模型同时对照独立 Python 内存记分板 |
| Rob | 冻结 CoreMark trace 逐周期输入，保留真实 reset、enqueue、writeback | cycle 8 起观察所有输出；有定义位严格比较，源码证明的动态越界 info 位逐项检查取值策略和 valid=0；额外 native Probe 只比较 native 两模式；要求实际 commit |

每个模块生成 `stimulus-identity.json`，保存输入、观察 mask、trace、记分板
身份及活动计数。`comparison.json` 保存第一个差异的周期/电平/端口/word，
并逐输出统计差异次数。原始逐位比较遇到任何差异、无观察位或无 ROB
commit 均失败。ROB 另外生成独立 `defined-comparison.json`，区分源码
有定义位的严格比较和 indeterminate 越界位的策略检查，保留原逐位报告。

## 已有执行证据（F10 尚未整体验收）

证据目录：`ptmp/firrtl-ingest/F10/components/`。

2026-11-01 对已有生成模型重新生成 driver、激励和 SRAM 记分板后：

| 模块 | cycles | 有定义 SV/FIRRTL 普通比较位数 | 结果 |
| --- | --- | --- | --- |
| RenameTable | 512 | 717,696 | SV/native off/native prefer 一致；另有 1,008 个 Probe 观察位在 native 两模式之间一致；无额外未绑定输入 |
| 128×138 SRAM | 512 | 64,170 | 三模型与独立记分板一致；233 read cycles、35 disabled cycles，write mask 0/1/2/3 分别 23/32/36/153 cycles |
| Rob（components14） | 10,000 | 367,224,104 | 全部有定义输出一致，indeterminate 策略差异已验证；另有 19,984 个恢复表达式位和 325,719,216 个 native Probe 位；原始逐位失败报告保留 |

日志为 `component-drivers-audit.log`、`component-compare-audit.log`。
RenameTable native prefer 的 `firrtl-nodes=167`、`shared-nodes=124`，
证明不是所有提示都在 flatten/优化后丢失。两种模式均有 4 个 supernode。

保留上述 512-cycle 证据后，又将同一批模型复制到
`ptmp/firrtl-ingest/F10/components-10k/` 重放 10,000 cycles。RenameTable
在 14,228,608 个 SV/FIRRTL 观察位上一致，另有 19,984 个 native Probe
观察位一致；SRAM 在 1,651,308 个观察位上与记分板一致。
日志为 `component-drivers-10k.log`、`component-compare-10k-final.log`。这是
同一批已生成模型的激励增强，不表示重新生成了当前 native binding 的模型。

ROB 第 11 次生成中，native 读取在 194.243 秒内完成；其中 Rob lowering
产生 10,694,053 operations，用时 96.995 秒。链接阶段的两个组合假环均已
成功消除，没有 unresolved loop。后续 mux-tree-fold 的 dead-op 清理暴露
`node::recordDead` 按 root 反复复制/排序累计 metadata 的二次复杂度路径。
确认具体实现修复和回归后，显式中止该旧进程（退出 130）；未将读取成功
误报为模型生成或模块仿真成功，也没有跳过正常优化 pipeline。

第 12 次生成使用独立 `components12/Rob/`，mux-tree-fold 在 29.832 秒内
完成；flatten 后组合环数为 0，`grh.verify` 通过。但第一轮 simplify
抛出 `OperationId refers to erased operation` 并退出 2。最小独立回归
确认是 `redundant-elim` 将常量复制到输出端口时，删除 assign 后再通过
`inheritOrigin` 读取其属性，同时也在删除后检查单用户关系。修复在删除前
保存用户关系、origin 和 node 属性；clone 与最后用户的 reparent 都只使用
已保存的数据。新增双输出小图先 clone、后 reparent，检查两条路径的
origin union 与 node 关联有效。原回归先失败，修复后
`make test_transform_shape_mapping test_transform_simplify` 的 4 项测试
全部通过；证据为 `redundant-output-repro.log`、`redundant-output-fixed.log`。
这项修复尚不等于 ROB 模型已经生成或执行通过。

第 14 次使用 install13 完成 native 读取、普通优化、GrhSIM 转换及三模型
生成，FIRRTL off/prefer 与原始 SV 模型库均已编译退出 0。native off 和
prefer 的共同优化 checkpoint 为 813,574,753 bytes，SHA256 为
`7e87831f3fc74de81c9f49175fac8be6b813fd0a9578694d49b3954e169948cc`。
native off 为 44,634 nodes / 381 supernodes，prefer 为 132,332 / 1,196。
主要日志为 `rob-generate14.log`、`rob-firrtl-off-build14.log`、
`rob-firrtl-prefer-build14.log` 和 `rob-sv-build14.log`。

端口完整审计发现，`io.flushOut.bits.attribute.rasAction` 仍在 frozen SV
中，只是字段名为 `attribute_0`，不属于不可观察输出；其 source
`invalidate` 在共享 2state 转换下仍与 SV 的 `2'h0` 比较。唯一真正被
全芯片 firtool 优化移除的普通输出为 `io.isVsetFlushPipe: UInt<1>`：
原 FIRRTL 的父层没有任何消费者，冻结 `CtrlBlock.sv` 的 `Rob rob`
实例也没有该端口。它不是 Probe，不加入 Probe 分类，也不忽略该位。

FIRRTL 的输出与 `isVsetFlushPipeReg` nextValue 都直接连接同一表达式
`rawInfo[0].commit_w & deqHasFlushed & exceptionGen.io.state.bits.isVset`。
冻结 `Rob.sv:879177` 将等价表达式写入 `isVsetFlushPipeReg`。新的
`xs_firrtl_compare_observe` 从保存的 SV base checkpoint 唯一匹配该
`kRegisterWritePort`，操作数定义为 `[updateCond, nextValue, events...]`，
只给 operand 1 的原有 1-bit value 增加只读输出 port。所有 operation、
状态、表达式和原始 port 都不变；原 `sv-off/model` 保留，观察模型写入
独立 `sv-observed/model`。该位参与三路比较，并独立计为
`sv_internal_bits`；普通 SV 输出仍全部计入 `sv_firrtl_bits`。

`sv-observation.json` 保存两个 checkpoint 的 SHA256、唯一 write op、
原始 value 几何、四条 FIRRTL 语句和 SV assignment 的实际源码行；生成前
逐项检查语句/表达式仍完全匹配。源 checkpoint 为
`768810a9da4f8ac310cca3c7bb5c7db4342be7b9f29e0474823d581146228404`，
适配后为 `7ddd6355542d7e81f00570bb3d6ff244ee26ec57a2377f9bc96c8893a7444123`。
该恢复从 install14 继续后续 SV GrhSIM 流程；native 两模型仍是 install13
生成，不能称作 install14 全量重新生成。

独立复核已确认适配 checkpoint 的实际差异只有上述两处。初版观察模型
的自定义 `generation_identity` 遗漏了生成时的 loaded library / 源码
捕获；后续入口已修正为合并 `capture_generation()`，当前产物保留原始
记录，没有补写成“生成时捕获”。单独的
`sv-observed/provenance-audit.json` 于 `2026-10-31T18:19:42Z` 完成事后
metadata 审计，复核原/适配/最终 checkpoint、生成 C++/header/manifest、
静态库、原生成记录及 install14/生成日志身份。审计时的 native 库
`libwolvrix-lib.so` SHA256 为
`a96819d3d427777310890d30ebbf75188f4c4df6b5225dd47bef5d7a4cf2eca4`，
`_wolvrix.so` 为
`60ee7369eccd19dd2f05cf4530fa33dabfc8da69ea2fa4e611ded9278aac6465`。
这些是审计时身份；安装/生成日志及会话顺序支持 install14 归属，不能
追溯证明原生成进程当时的 mappings。审计日志为
`rob-sv-observe14-audit.log`。

ROB 实际有 333 个未出现在 frozen SV ABI 的 native 输入。
`retained-input-audit.json` 核对其中 328 个在普通优化后 `users=[]`；
另 5 个 `exuWriteback` lane 1/3/5/14/15 的 64-bit `bits.data` 仍用于
`debug_exuData` 状态写入，不能称作未使用。它们在 `WbDataPath` 原 FIRRTL
中分别显式连接 `UInt<64>(0h0)`，经 `Region.intWBDataPath`、
`BackendInlined.intRegion`、`CtrlBlock.fromWB` 和 clocked delay 传入 ROB。
源 unknown 经共享 2state 转换为零，clocked delay 后仍为零；frozen
`Rob.sv:773537` 起对应写优先级分支也使用 `64'h0`。审计逐项检查完整
模块/instance/连接语句并记录真实行号、源文件和 checkpoint SHA256；
若 live input 无此证明即拒绝生成，未导入历史 ROB 豁免表。

SV 10k driver 已完整退出 0，native 两模式从 `2026-10-31T18:20:02Z`
开始执行，输出分别最后写于 `19:00:02Z`、`19:00:14Z`，并在 `19:00:18Z`
确认两个原始进程均返回退出码 0。三路各有 977,760,000 bytes / 20,000 条完整记录，最终
比较未重跑或重新生成模型。起始文件时间和进度保存在
`rob-run-start-progress14.log`，终止状态保存到
`components14/Rob/driver-terminal-status.json`。
`comparison-prefix6144.json` 明确记录 `complete=false`、`passed=false`，
仅比较 12,288 / 20,000 个 records：226,307,952 个普通 SV/FIRRTL 位、
12,272 个恢复表达式观察位三路一致，200,021,328 个 Probe 位在 native 两
模式一致；三路均产生 6 个 commit valid lane 和 1 个 walk valid lane。
前缀只消费各路已完成的共同 records，记录未消费的尾部 bytes；不会生成
最终 `comparison.json`，也不代表 10k 已通过。最终比较要求激励 mask 和
全部输出都具有 `stimulus-identity.json` 声明的完整 records，拒绝多路
共同截断的伪通过；缺少激励身份时直接拒绝，不能从 mask 长度推断总周期。

完整原始 `components14/Rob/comparison.json` 保留 `complete=true`、
`passed=false`，`rob-compare14-final.log` 的 Make 退出码为 2。首差异为
cycle 9282 高电平 `io_diffCommits_info_519_ldest`：SV 为 5，两路 native
为 0。全部 258 个不同叶子仅为 `info[434..519]` 的 `ldest/pdest/rfWen`，
共 195,126 条叶子记录；三路均产生 650 个 commit valid lane 和 314 个
walk valid lane。普通输出比较 368,524,944 位，恢复表达式 19,984 位，
native Probe 325,719,216 位；native off/prefer 完整输出 SHA256 均为
`0f3e7785ca4ac3ccd2ef49235142f89c6df268cc708d075b95a6cf5e7bfa1266`。

`xs_firrtl_compare_rob_oob_audit` 从原激励的 reset 和每拍低电平
`diffCommits.commitValid` 前缀计数重构实际 `diffPtr`。首差异边沿前为
184，commitSize 为 1，边沿后为 185，因此 info519 的读索引为
`185 + 519 - 352 = 352`。原 FIRRTL `renameBufferEntries` 仅有 352 行，
native bounds guard 选择 unknown，随后共享 2state 转为零；冻结
`RenameBuffer.sv` 的 `_GEN_691` 则把 352–511 显式补成第 0 行的副本。
同拍有定义的 info167 实际读第 0 行，ldest 正好为 5。该重构逐条解释全部
195,126 条差异，没有改变原始输出或 mask。

完整 OOB 审计还检查 65,042 个 lane-records / 1,300,840 个 info 位，
包括值恰好一致的零字段：native 八个字段均为零，SV 均等于同拍有定义的
第 0 行，OOB lane 的 commitValid 均为零。证据为
`components14/Rob/oob-audit.json`、`rob-oob-audit14-all.log`。FIRRTL v6
规范定义动态越界结果为 indeterminate；不同具体取值不能称作所有输出
原样逐位相等。

独立 `xs_firrtl_compare_defined` 已完整退出 0，保存
`components14/Rob/defined-comparison.json` 的 `complete=true`、`passed=true`
及 `bitwise_all_output_equality=false`。全部 367,224,104 个普通有定义位和
19,984 个恢复表达式位三路一致；1,300,840 个 indeterminate info 位按
每拍实际指针逐项检查 native off/prefer 都为零、SV 等于同拍有定义的第
0 行、三路该 lane 的 commitValid 都为零。全部 valid、全部 in-range
info 和其他输出继续严格比较；native off/prefer 在 694,264,144 个完整
观察位上严格一致，其中包括 325,719,216 个 Probe 位。三路实际 commit
均为 650。该报告不按字段名或固定索引区间整体豁免，原 mask 未改。

运行前严格源码审计核对 RenameBuffer 的 352 项别名、全部 520 路指针
表达式和 commitValid 谓词、reset/更新优先级及 frozen SV 的 row0 补齐：
共 14,939 条 FIRRTL 语句和 1,050 个 SV 定义，任意公式、部分覆盖写或
guard 变化都会拒绝该证明。报告保存源文件完整身份、原严格报告、OOB
诊断、输入/mask/输出身份；原 `comparison.json` 仍为 `passed=false`，
SHA256 为 `ae8dac58c5fa630a77d25eff10bff58d4557d8174a55dfdcf70790498ba80d50`。
源码检查日志和完整投影比较为 `rob-defined-compare14.log`；独立代理的
全记录复验也得到相同 OOB 位数和零 in-range 差异，见
`rob-independent-definedness-report.md`。

后续短 literal 回归还验证了输出与输入 signedness 不同时，常量复制不能
重新解释 literal 的符号扩展。最小图先失败，增加 `sameValueType` 保守
条件后 4 项 transform 回归通过；证据为 `redundant-literal-repro.log`、
`redundant-literal-fixed.log`。该条件已纳入 install14。

冻结 ROB trace 的有效输入并非从 cycle 0 开始：`rob-trace-activity10k.log`
确认 enqueue 首次为 cycle 612，writeback 为 710，commit 为 617。前
10,000 cycles 有 716 个 enqueue valid lane、364 个 writeback valid
lane、650 个 commit valid lane。原先 512-cycle 前缀无法证明 ROB 活跃
行为。脚本生成前会先核查这三类活动，并在模型执行后核查真实 commit
输出；ROB 正式比较应显式使用 `XS_FIRRTL_COMPARE_CYCLES=10000`。

该激励所属的 ROB 设计身份也已核对：当前 `SimTop.fir` 的 Rob 模块
字节范围 `[233037522, 461456473)` 的 SHA256 为
`24f547a0ae0377f7c0f877a6bfcb07619c85db2625ab2b72b19d19dbdda09130`，
与 `testcase/xs-components/rob/manifest.json` 一致；其记录的 12 个 SV
层次模块也全部与当前冻结 SV 的 SHA256 一致。证据为
`rob-frozen-module.sha256`、`rob-sv-hierarchy-identity.log`。这证明激励与
当前比较模块对应，不把历史整机 trace 的存在当成当前整机通过证据。

trace 的 `io_hartId` 是 `kind=static, offset=null, width=6` 行；它不占
record word。当前 `fst_mapping.json` 对应 captured handle 4534，bit 0，
source width 6；`pack_rob_fst.cpp` 在任何 static slice 非零时直接失败。
重放按这个声明的格式约定置零，拒绝未声明 static 的空 offset，并记录
`trace_static_inputs`、capture manifest/summary 和 packer 身份；没有导入
历史 benchmark 的按名称置零列表。capture summary 的 cycles、record
几何、bytes 和首拍 reset 必须与当前 trace 对应。

工作流和比较器单测通过 46 项，日志为 `compare-workflow-tests15.log`。
独立测试检查 SRAM 数据差一位必失败，ROB 空激励和无 commit 必失败。
观察适配器测试检查 source bytes、全部 operations 和既有 ports 不变，
拒绝重复 register writes 或改变后的 source expression，且恢复观察位
在 SV 单路损坏时必须三路比较失败；另检查输出别名与字段改名绑定。
trace static 测试核对声明为零的配置输入逐条重放为零，并保留捕获几何。
source-definedness 回归还检查 native 两路任一路的 OOB 值损坏、SV padding
损坏、三路任一路 OOB valid=1、in-range 字段差一位或 Probe 差一位均失败。
这些测试仅验证比较器自身，不能替代上表的真实模块或整机执行。

复验入口：

```sh
make generate_xs_firrtl_compare SKIP_PY_INSTALL=1 \
  PYTHON=.venv/bin/python XS_FIRRTL_INPUT=ptmp/xs/rtl/rtl/SimTop.fir
make run_xs_firrtl_components PYTHON=.venv/bin/python -j 8
make test_xs_firrtl_workflow SKIP_PY_INSTALL=1 PYTHON=.venv/bin/python
make xs_firrtl_compare_trace PYTHON=.venv/bin/python \
  XS_FIRRTL_INPUT=ptmp/xs/rtl/rtl/SimTop.fir \
  XS_FIRRTL_COMPARE_CYCLES=10000 XS_FIRRTL_COMPARE_TOPS=Rob
# 对已保存的 Rob14 完整输出做只读诊断与 source-definedness 比较
make xs_firrtl_compare_rob_oob_audit PYTHON=.venv/bin/python \
  XS_FIRRTL_INPUT=ptmp/xs/rtl/rtl/SimTop.fir \
  XS_FIRRTL_COMPARE_SV_DIR=ptmp/xs/rtl/rtl \
  XS_FIRRTL_COMPARE_WORK=ptmp/firrtl-ingest/F10/components14
make xs_firrtl_compare_defined PYTHON=.venv/bin/python \
  XS_FIRRTL_INPUT=ptmp/xs/rtl/rtl/SimTop.fir \
  XS_FIRRTL_COMPARE_SV_DIR=ptmp/xs/rtl/rtl \
  XS_FIRRTL_COMPARE_WORK=ptmp/firrtl-ingest/F10/components14
```

模块结果不能替代整机初始化、短前缀或 CoreMark100k/NEMU。F10 完成状态以
`steps.md` 的整机退出条件与最终验收记录为准。

## AheadBtbReplacer：独立记分板与默认 reference 断言

新增实际 frozen `AheadBtbReplacer` 验证，原始 FIRRTL 来自
`ptmp/xs/rtl/rtl/SimTop.fir`，SHA256 为
`cc46aae1a379d9e62132b76b0702685ba67761c87815067f770b0743d7dc754a`；
SV 使用同目录的原始 top 及 `PlruStateGen`、`PlruStateGen_1`、
`ReplacerState`。模块源身份、ABI、原始宏和生成配置保存到
`ptmp/firrtl-ingest/F10/replacer/identity.json`。

native FIRRTL off/prefer、SV ingest 和原始 SV 的 Verilator `-O0` 对照
在独立 7-bit tree-PLRU scoreboard 上完整通过 241,988 cycles / 483,976
条双电平记录，每路检查 1,451,928 位，覆盖全部 128 个 PLRU 状态、8 个
victim、32 个 set、256 种 read mask、8 个 write way，以及同 set 写优先、
不同 set 并发和无效读。所有输出位都比较，没有观察 mask。
四路完整输出与 scoreboard 的 SHA256 均为
`1472d35f540f509e229d4e355766c5019e6b7afbfc4162ea6f932ce99677ddf8`。

默认优化 Verilator 仍触发原始 `AheadBtbReplacer.sv:124` 断言，已缩减为
6 周期：reset 两拍，write(set9,way6)，write(set9,way4)，
read(set9,mask4)+write(set10,way0)，然后 write(set11,way1) 且 replaceSet9。
cycle 4 后 primary state 为正确的 `0x7a`，duplicate checker 错为 `0x42`；
cycle 5 上升沿断言失败。生成 C++ 的跨 word packed slice 更新漏掉
应保留的 subtree bits；仅关闭 Verilator 优化的 `-O0` 对照完整通过。
原始 RTL、断言、DPI 和验证层都保留，未重写或豁免该失败。

实际命令为 `make test_xs_firrtl_replacer`、
`make test_xs_firrtl_replacer_minimal`（两者保留默认优化断言失败），
`make test_xs_firrtl_replacer_noopt`（完整对照通过），以及
`make test_xs_firrtl_replacer_oracle`（4 个 oracle/harness 单测通过）；
均使用 `WOLF_ENV_SOURCED=1 PYTHON=.venv/bin/python`，首个生成命令额外指定
`XS_FIRRTL_INPUT=ptmp/xs/rtl/rtl/SimTop.fir`
和 `XS_FIRRTL_COMPARE_SV_DIR=ptmp/xs/rtl/rtl`。

完整输入、命令、保留的断言形式、首个状态分歧、生成代码片段和局限见
[F10-replacer.md](F10-replacer.md)。主要证据为上述目录中的
`comparison-noopt.json`、`diagnosis.json`、`minimal/diagnosis.json`、
`replacer-run.log`、`replacer-minimal.log`、`replacer-monitor.log`、
`replacer-noopt-compare.log` 和 `oracle-final.log`。
该结果不表示整机默认优化 reference 已通过；独立 `-O0` 整机 reference
按相同 frozen SV 构建，并以固定 100000 cycles + NEMU 单独验收。

整机对照使用现成 `xs_ref_emu` / `run_xs_ref_emu` 入口，独立构建目录为
`ptmp/firrtl-ingest/F10/reference-noopt`。`EMU_OPTIMIZE=-O0` 控制 Verilator
RTL 优化，C++ 的 `OPT_FAST` 保持原默认 `-O3`；其余为单 core、threads 2、
VM_BUILD_JOBS 起初 4、后增量恢复为 12、EMU_RANDOMIZE 0、XS_ZERO_INIT 0、waveform 0，
原始 `DIFFTEST`、`--assert` 和 NEMU 配置保留。
构建前 `capture_xs_firrtl_reference_identity` 记录了 2,247 个 frozen RTL、
实际 common/generated SV、宏、harness 源/头文件、Makefile、CoreMark/NEMU
和工具身份，见 `reference-input-identity.json`。

第一次整机 codegen 在当前 Verilator 5.051 的默认语言模式下拒绝原始
`VecExcpDataMergeModule.sv` 的 struct member `until`。源码未改；后续用
`XS_SIM_VFLAGS='+define+DIFFTEST --language 1800-2005'` 进入持续 codegen。
首轮日志为 `build-driver.log`，兼容模式日志为 `build-language2005.log`；
第二轮无语法/语义 error，但工具因 2,198 个编译告警终止：NEWERSTD 1、
SYMRSVDWORD 603、UNOPTFLAT 1594。第三轮请求的 flags 追加
`-Wno-fatal`，只改变告警是否致命；运行断言和 NEMU 检查保持开启。
最终 flags 和输入身份在 `reference-input-identity.json`，第三轮日志为
`build-compatible.log`。第二轮在告警终止前已写完生成源和 `VSimTop.mk`；
恢复命令复用同一 `-O0` / language2005 生成源进入 C++ 编译，实际 codegen
命令以 `build-language2005.log` 为准，未将恢复误报为重新执行 codegen。
确认整机 native 进程停止且可用内存 180 GiB 后，经调度方明确授权，
旧 jobs4 会话退出 130 并确认 terminal，再以同 target/目录/输入/flags
增量恢复 jobs12，复用已完成的 348 个 objects。并发变化保存到
`build-parallelism.json`，恢复日志为 `build-compatible-j12.log`；这是 F10
验证构建，不能作为 F11 性能数据。整机构建已退出 0，生成
424,130,880-byte ELF，固定 100000-cycle/NEMU 仿真也已退出 0。
ELF SHA256 为
`8fe47962b22c0424765e59e62d62959cc53ba4d1d5f10d5fd6b2bf278fd3ccf6`。

第一次运行使用默认 `taskset -c 2`，Verilator 5.051 根据进程可用 CPU 数
将 `VerilatedContext` 的默认线程数设为 1，而模型以 `--threads 2` 构建，
在仿真开始前报线程数不匹配。保留失败日志 `run-driver.log` 和
`xs_ref_coremark100k_noopt.log`，随后仅用现有 `XS_EMU_CPU=2,3` 参数
运行同一二进制，无需重编译或更改 shared harness。

原始 harness 在 reset 期间使用 `common_init_without_assertion`，因而日志
包含 reset 阶段原始 `$fwrite` assertion 文本；`main.cpp` 在初始化后调用
`common_enable_assert`，活动仿真断言保持开启。这是未修改的 shared harness
行为，不能以日志中完全没有 `Assertion` 字符串作为验收条件。
`common.cpp:75` 的原始 `setbuf(stderr, mybuf)` 还会把部分 reset 文本延迟
到退出时输出：日志启动阶段的 `Assertion failed: prio` 在最终统计后续上
`rityVecReg must be different`。原始 `xs_assert_v2` 在启用后会另外输出
`.sv:line` 诊断并递增 `assert_count`；本次没有该诊断、assertion-stop、
ABORT 或 BADTRAP，按原始 harness 正常到达周期上限。
有效运行日志为 `xs_ref_coremark100k_noopt_cpu23.log`，wrapper 日志为
`run-cpu23.log`。

本次固定周期运行命令：

```sh
TMPDIR="$PWD/ptmp/firrtl-ingest/F10/reference-noopt/tmp" \
make --no-print-directory run_xs_ref_emu WOLF_ENV_SOURCED=1 \
  XS_RTL_BUILD="$PWD/ptmp/xs/rtl" \
  XS_REF_BUILD="$PWD/ptmp/firrtl-ingest/F10/reference-noopt" \
  XS_LOG_DIR="$PWD/ptmp/firrtl-ingest/F10/reference-noopt" \
  XS_SIM_MAX_CYCLE=100000 XS_PROGRESS_EVERY_CYCLES=10000 \
  XS_WAVEFORM=0 XS_ZERO_INIT=0 XS_EMU_THREADS=2 XS_EMU_CPU=2,3 \
  RUN_ID=coremark100k_noopt_cpu23
```

最终 progress 为 host/model cycles 100000、instr 238535，commit PC
`0x80000bc6`，trap PC `0x80000cde`，随后报告预期的
`EXCEEDING CYCLE/INSTR LIMIT`。Difftest trap cycleCnt 为 99996；原始
析构统计额外执行一次 `single_cycle`，因而 `Guest cycle spent` 为
100001。这是固定 100000-cycle CoreMark 前缀与 NEMU 对照通过，
没有声明完整两轮 CoreMark 已结束。

运行后 `make capture_xs_firrtl_reference_result WOLF_ENV_SOURCED=1
PYTHON=.venv/bin/python` 通过，`reference-output-identity.json` 绑定上述
ELF、生成 C++ manifest、实际 codegen/构建文件和全部日志。
`changed_hardware_harness_inputs=[]`：frozen RTL、实际宏、harness、
CoreMark 和 NEMU 内容均未变化。根 Makefile 的 pipefail/native workflow
规则调整与 difftest Makefile 作为构建控制独立记录 before/after hash；
未将这些工作流变化冒充硬件输入变化或据此重建相同硬件。
真实 Make 会话退出 0、最终计数和日志 SHA256 另存于
`reference-runtime-result.json`；仿真日志 SHA256 为
`34210b42cdab03c11c8faa1ff902134f6b54e653260cfb0ca168e3e1855da5e5`。
