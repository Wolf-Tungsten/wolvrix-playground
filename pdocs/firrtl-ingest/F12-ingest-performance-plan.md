# F12：FIRRTL ingest 性能专项计划

建立日期：2026-11-02。

状态：按 2026-11-02 用户决定，收尾为初步版本。保留当前语义与性能优化，
移除临时插桩；完整 FIRRTL→C++ 的 20 分钟目标转为后续整机工作，
不再作为本次 ingest 初步版本提交的门槛。下文实验记录保留历史上下文，
包括已经撤回的计时与当时尚待完成的门禁；当前状态以本节收尾记录为准。

## 初步版本收尾

最后的实现检查收掉两处全设计规模的重复工作：`Semantics` 不再为每个模块
重建全部接口的 hash 索引，而是按实际访问的接口建立端口索引；接口推断的
child-changed 检查直接使用当前模块的子模块，不再逐模块扫描全体反向依赖。
接口解析中的 leaf 列表复用已有分析内缓存。width/Reset 的传播顺序、first-match
端口行为、错误检查和缓存生命周期保持原有契约。

已删除 `lib/ingest/firrtl/profile.hpp` 以及所有 F12 原生 timer/counter、逐模块
耗时日志和 `WOLVRIX_FIRRTL_PARSE_CACHE` 实验开关。parse cache 固定启用，
仍在 lowering 后释放。benchmark 只在 Python 外层测完整 ingest wall/RSS、
实际加载库、输入清单、diagnostics 和完整图 hash；不再提供原生 profile 或
cache-disable 参数。对照工具保留读取历史 profile 产物的能力。

收尾版全量样本 `closeout-full-cpu0/`：固定 CPU 0，原生插桩已删除，
ingest **293.761 s**、峰值 **71,372,320 KiB（68.07 GiB）**。实际映射核心库
SHA-256 为 `5ac72df26fc3be8bdc04d6620f13636b8411ce9f2a4c0eb2bbd9e34a7502f840`。
相对先前 290.600/291.345 s 样本仍在约 290 s 的范围，本轮不宣称额外的
可归因性能收益。

完整 JSON **40,947,736,294 bytes**，SHA-256
`cec09ca95fdf06eeefca6ffcb8d3165c503af655ae97d4c9098577d3a7aaf553`，与收尾前
候选逐字节身份一致；manifest、全部 **6,007 条诊断**、dependencies、metadata
keys 和 CPU affinity 也全部通过严格对照。证据为
`closeout/final-comparison.json`。本轮执行完整保存/hash；完整整机 JSON 往返
只引用前述历史轮次，不把本轮保存/hash 误写为新的全量 roundtrip。

收尾验证全部经 Make：`test_wolvrix` **81/81**；
`test_xs_firrtl_workflow` **65/65**；`test_ingest_python` **9/9**；
`test_firrtl_parser_inputs verify_firrtl_inputs test_firrtl_comb test_firrtl_state
 test_firrtl_memory test_firrtl_effects test_ingest_mixed test_firrtl_target
 test_grhsim_flow` 全部退出 0，包含对应模型的编译执行与逐周期对照。
日志位于 `ptmp/firrtl-ingest/F12/closeout/`。检查后未发现需继续展开的明显
全设计重复遍历/索引问题；当前初版保留全部语义检查与 annotation。

初步版本不宣称整机 FIRRTL→C++ 在 20 分钟内完成，也不将 SV 的 ingest 时间
视为等量输入成本。SV 输入经过 firtool 的前置 lowering/优化，两条路线的
工作边界和保留的 GRH 规模不同。

## 收尾后：40 分钟 FIRRTL→C++ 实跑

2026-11-02 按用户要求扩大完整试跑预算为 40 分钟；外层覆盖 harness/manifest
准备与整个 Make 生成目标，内层超时通过 `XS_FIRRTL_GENERATION_TIMEOUT=40m`
显式覆盖，默认仍为 20m。回归验证默认值、40m 参数转发和 SIGKILL 行为，
`make SKIP_PY_INSTALL=1 test_xs_firrtl_workflow` 65/65 通过。

`full40m/` 在 **2400.009 s** 被外层 SIGKILL，退出 **137**，未发布 flat
checkpoint 或 C++ model。保持 full pipeline、annotations on、全部默认优化、
checkpoint/roundtrip on，未从 checkpoint 恢复。ingest **293.093 s**，
hier-flatten **467.958 s**，环路处理 **44.981 s**，后续全图校验 **22.856 s**。
超时时仍在普通 GRH `simplify`；已完成五轮均 `changed=1`，分别为
**999.972、84.451、83.542、80.144、81.833 s**。首轮 const-fold
**593.627 s**、redundant-elim **303.085 s**、DCE **103.259 s**。
这证明当前默认配置下 40 分钟仍不足以从原始 FIRRTL 生成 C++，也尚未到后端
分区/发射阶段。下一性能瓶颈是普通 GRH 化简，不能将本轮结果归因于 ingest。

证据：`ptmp/firrtl-ingest/F12/full40m/{result.json,summary.md,driver.log}`；
包含实际加载库身份、完整配置和冻结输入/harness 关联。外层 GNU time 不能在
SIGKILL 后归集被杀后代的 CPU/RSS，其 timeout 进程 RSS 不代表生成峰值内存。

## 测量证据更正：安装库身份

### source-info 正确性更正

对 `profile-identity/` 和 `whole-roundtrip/` 的完整 JSON 对照发现 source-info
内容不同。首个差异在 JSON 第 6497 行，指向 FIRRTL 第 821355 行：原始长路径
的开头被损坏。根因为 `Lowerer::location()` 将临时 `SourcePosition` 所拥有的
`sourceInfo` 保存为 `string_view`，对象销毁后缓存悬空；即使首次 miss 的
`SrcLoc.note` 复制也发生在该对象销毁之后。缓存已改为拥有字符串并 move 接收。
新增组合回归逐项检查两行嵌套表达式的 operation/result source info，释放
source owners 后及 JSON roundtrip 后均须保持原文。

此前 297.350/298.779/297.960 s 仅为含此缺陷版本的历史性能记录，不能作为
完整语义验收。旧整机 JSON 自身 roundtrip hash 一致只证明自洽，不能证明保留
正确的原始 source info。所有 source-info/全图 identity 正确性结论撤回，修复后
必须重新安装、计时并执行 profile/no-profile、roundtrip 和端到端门禁。

修复后的 `source-info-owned/` 已通过 `make test_wolvrix`（81/81）、指定
Make 功能门禁，以及含对照工具回归的 Python workflow（63/63）。负向实验
只恢复借用字符串缓存，`make generate_firrtl_comb` 按预期失败，错误为
`nested expression source info borrowed temporary storage`；恢复修复后同一目标
通过。日志分别为 `regression-negative.log` 和 `regression-positive.log`。
修复后的安装核心库 SHA-256 为
`5ba833d1edd5ab23a9be4b7ecabba9adc8f819ed9abfa3f251b0965a7a71d30c`。

新增 `make compare_xs_firrtl_ingest`，通过
`FIRRTL_INGEST_COMPARE_BASELINE/CANDIDATE/OUTPUT` 指定证据目录和报告。工具
严格比较全图字节数/hash、manifest、diagnostics、dependencies 和 metadata keys；
诊断只归一化 `transactions/<digits>-<digits>/`。profile 报告使用
`Transaction::run()` 中互不重叠的 sibling scopes 解释总耗时，单独列出剩余
成本和按 lowering/resolve self time 排序的 top-20；不把嵌套 scope 累加。

修复版首轮 `source-info-owned-profile/`：ingest **328.917 s**，峰值
**72,031,012 KiB**，完整 JSON **40,947,741,643 bytes**，SHA-256
`c63dd00d5944234071e48d282dc1f8b3ac57e9d9ba78c47271b0a0797f68392a`。
此前损坏的 JSON 第 6497 行现与 FIRRTL 第 821355 行的原始 `@[home/…]`
文本一致。该轮与功能门禁并行运行，不能作为正式无 profile 性能结论。
独立 sibling scopes 覆盖 profile 总时间的 **97.846%**：scan interfaces
13.344 s、resolve 52.267 s、ensure 207.789 s、hierarchy 0.978 s、linked
verify 47.369 s；未归属 7.083 s，包括 registry/metadata、事务发布及框架开销。
lowering self top-3 为 Rob 31.917 s、LogPerfEndpoint 15.725 s、RenameBuffer
3.377 s。完整 top-20/self/child 及计数见
`source-info-owned/profile-accounting.json`；该文件是单轮 profile 汇总，
其中与自身比较的 equality 不构成跨配置 identity 验收。

修复版无 profile `source-info-owned-roundtrip/` 的 ingest 为 **316.453 s**，
峰值 **71,756,068 KiB**，尚未达到 300 s。与 profile 轮的 manifest、6,007 条
diagnostics、dependencies 和 metadata keys 一致，但原始全图 hash 不同。
首个差异在 byte 786,818,266、JSON 第 1,133,290 行，是内联 ClockGate 的
`ingest.sourceFile` 中不同的事务临时目录；不能因此宣称 raw identity 通过。

该轮随后完成完整 JSON roundtrip（退出码 0）：两份文件均为
**40,947,741,643 bytes**、SHA-256
`303488bd974e153ae3ef00ea78d69a518342fb3e53a3b6a4084076e1969aa6ea`，验证耗时
**981.555 s**。这证明拥有 source-info 的版本能够保留完整图往返；它尚未包含
生成 SV 路径规范化和直接提取 source-info 候选，不能替代最终候选的验证。

为满足重复 ingest 的确定性，新增发布前的生成 SV source identity 规范化：
绑定和 source-unit 检查仍使用实际路径，发布图中的生成文件 metadata 和
op/value location 使用 `generated-sv:fnv1a64:<content-hash>/<relative-name>`。
原始输入路径、行列、pass 和 note 不变；只访问已导入的 SV graph，避免扫描
整份 FIRRTL 图。inline/path/resource 的重复读取全图序列化回归和全部 81/81
CTest 已通过，证据为 `generated-source-identity/tests.log`。新版本的整机
profile/no-profile 原始字节 identity 仍待重跑，旧轮次不计为该项成功。

下一单因素候选为 `source-info-direct/`：将原有逐行 source-info 扫描抽为内部
`sourceInfoAt()`，lowering 不再为取 note 构造完整 `SourcePosition`（包括 file、
sourceLine 等拥有字符串）。扫描仍执行同一引号、注释和转义规则；缓存继续
拥有字符串，复用容量而非保留临时对象的 view；最终 op/value `SrcLoc` 仍各自
拥有相同原文。81/81 CTest、补充的 scanner 回归和候选 Python workflow
63/63 已通过，尚无整机性能或 identity 收益结论。

对照库保存在 `generated-source-identity/native-baseline/libwolvrix-lib.so`，
SHA-256 为 `f2909a4af87b96fc4997dde70fc21234a115c97e0e03d30efa9ddc0630bb5d7c`；
它包含 source-info 所有权和生成 SV 路径修复，但不含直接提取候选。对照通过
请求级 `LD_LIBRARY_PATH` 选择，实际映射仍由 benchmark 的 native identity
验证；该库的 Python workflow 同样 63/63。候选核心库 SHA-256 为
`0c19177f135a3acd708d2433f738c56dcfca390dd81b318480c49143ad352ae8`。
benchmark 新增 `--cpu` 并记录实际 `cpu_affinity`，后续 A/B 固定同一 CPU，
对照工具将 affinity 差异视为门禁失败。历史未绑定 CPU 的数字只作为历史样本，
不能用它们隔离新候选收益。

固定 CPU 0 后，`source-info-direct-baseline-cpu0/` 的无 profile ingest 为
**305.431 s**、峰值 **71,737,768 KiB**；单因素候选
`source-info-direct-candidate-cpu0/` 为 **290.600 s**、峰值
**71,810,076 KiB**，减少 **14.831 s（4.86%）**。两轮完整 JSON 均为
**40,947,736,294 bytes**，SHA-256 均为
`cec09ca95fdf06eeefca6ffcb8d3165c503af655ae97d4c9098577d3a7aaf553`。
manifest、6,007 条 diagnostics、dependencies、metadata keys 和 CPU affinity
全部一致，实际映射的两版核心库身份符合预期；证据为
`source-info-direct/baseline-candidate-comparison.json`。这也验证了生成 SV
临时目录不再改变完整图 identity。候选指定 Make 门禁均退出 0，新增 SV 路线
Make 入口的 fixture 覆盖完整层次 roundtrip 和 CPU 绑定，workflow 为 64/64。
当前仅有一轮正式候选计时；重复测量、最终候选 profile/no-profile roundtrip
和完整端到端门槛仍未通过，不能据此宣布 F12 完成。

候选固定 CPU 0 重复计时 `source-info-direct-repeat-cpu0/` 为 **291.345 s**，
峰值 **71,612,636 KiB**。两轮候选均低于 300 秒，manifest、diagnostics、
dependencies、metadata keys、库身份和 affinity 一致。重复轮只复测 ingest，
未保存另一份约 41 GB 图；`source-info-direct/repeat-timing-comparison.json`
显式记录 `graph_checked=false`，不能当作新增的图 identity/roundtrip 证据。
完整图对照仍以此前 A/B 及后续最终候选 profile/roundtrip 为准。

benchmark 新增 `make benchmark_xs_sv_ingest`：通过
`SV_INGEST_BENCH_FILELIST` 和 `SV_INGEST_BENCH_READ_ARGS` 指定冻结的纯 SV
参考输入，沿用计时、实际库/CPU 身份、全图保存和 roundtrip 工具。SV 路线实际
调用 `read_sv`，FIRRTL/mixed 调用 `read_sources`，两者在报告中明确标记。
SV filelist 要求每行一个绝对源文件路径；全部源文件字节数和 frontend 返回
的依赖均保留。新 fixture 验证两模块完整 roundtrip、CPU 绑定、复用输出目录
时清除旧 identity 报告，以及失败 ingest 仍保留 timing/diagnostics；workflow
64/64。`compare_xs_firrtl_ingest` 默认仍要求完整图报告，只有显式
`FIRRTL_INGEST_COMPARE_ARGS=--timing-only` 才允许仅比较重复计时。

纯 SV 固定 CPU 0 参照：`sv-reference-cpu0/` 为 **143.807 s**、峰值
**34,483,616 KiB**，profile 轮 `sv-reference-profile-cpu0/` 为 **144.698 s**、
峰值 **34,463,056 KiB**。两轮均使用 2,149 个显式源（367,908,462 bytes），
逐源 SHA-256 一致；与历史未绑定 CPU 的 45 s 样本不能直接计算优化收益。
两份 JSON 各为 6,910,165,323 bytes，但原始 hash 和 348,470 条诊断的顺序
不同。`--inspect-order` 流式对照确认：2,147 个 graph 各自的完整内容逐字节
相同，诊断内容及重复次数相同，根因是并行 SV 转换按完成顺序发布图、声明
和诊断。该解释不覆盖原始 identity 门禁失败，报告仍返回非零；证据为
`source-info-direct/sv-order-analysis.json`。

已在纯 SV 的 `readSources()` 成功发布边界固定图遍历、设计声明、模块、依赖
和诊断的顺序；保留图内对象、图 ID、顶层选择和全部诊断。FIRRTL/mixed 仍
走原有入口。新增回归三次读取 18 模块并行层次，逐项比较完整 JSON 和拥有的
诊断快照；另检查排序后图 ID、alias 和 top 不变。81/81 CTest 通过，见
`sv-publication-order/tests.log`。修复后的纯 SV 全量 identity 对照尚待重跑。

完整 SimTop 的显式 FIRRTL-only 清单已实际检查：不提供 SimJTAG.v 时，以
`unknown module 'SimJTAG'` 失败，未发布设计。报告保留于
`firrtl-only-cpu0/timing.json`，`success=false`；230.073 s 只是失败请求耗时，
且与构建并行，不能作为有效 ingest 性能。该冻结输入需要真实的辅助 SV
绑定，不能删除 JTAG 或裁剪顶层来制造纯 FIRRTL-only 正向样本。

后续核查发现，多轮候选只执行 `make test_wolvrix` 后就以
`SKIP_PY_INSTALL=1` 执行 benchmark；C++ build 与 Python 安装目录并非同一个
库。核查时安装库时间为 2026-11-02 09:25:13 +0800，build 库已更新至
11:27:11 +0800。因此 `access-inline-*`、`solve-buffer-*`、`leaf-cache-hash-*`、
`driver-index-*`、`result-reserve-*`、`node-key-move-*`、`primitive-inline-*`、
`primitive-leaf-reuse-*`、`primitive-type-reuse-*` 和 `primitive-kind-hash-*`
这些目录只能证明当时加载的安装库耗时约 312–315 秒，不能证明对应候选的
收益或退化。此前依据这些数字作出的单因素性能结论撤销。

后续修改必须先经 `make py_install` 刷新扩展；benchmark 的 `timing.json`
新增 `native_libraries`，记录进程实际映射的 wolvrix 共享库路径、SHA-256 和
mtime，身份采集在 ingest 计时外执行。`SKIP_PY_INSTALL=1` 只用于明确已安装
当前候选的重复测量。当前仍未证明 300 秒门槛或完整 F12.5 验收通过。

刷新安装库后的首个有效基线位于 `native-fresh-symbol-noprofile/`：
310.022 s，峰值 72,101,028 KiB，核心库 SHA-256
`6d6caab8b7e5c744031bebaf93a9996f0c9ac1964e71b6e0c89cf847fe1146b9`。
该配置包含内部符号生成在确认名称不存在后直接插入的候选；其独立性能收益
尚未隔离。内部符号冲突/预留顺序已由新增 GRH 回归覆盖。

随后只将 `AttributeValidation::canonical()` 的 `parseKey()` 改为已有的
`validateKey()`：有效 canonical key 使用无分配校验；无效输入仍走原解析器
保留诊断。重新执行 `make test_wolvrix`（81/81）和 `make py_install` 后，
`native-validator-noprofile/` 为 **297.350 s**，峰值 **71,272,620 KiB**，核心库
SHA-256 为 `fe5bd62760b144dc74da8f3e5694abe060873f825be2ad56916115c78b8371b8`。
该单因素样本比基线减少 12.672 s（4.09%），首次低于 300 秒；仍须重复测量。
两次 manifest SHA-256 均为
`0a857b495fa77318ba05f6cc8ec97ff5dc1121f80747e19338dfd4aa6ca0a071`。
6,007 条 diagnostics 在只归一化事务临时目录后逐项相同，metadata keys 和
dependencies 相同；对照在 `native-identity/validator-comparison.json`。
这不替代 GRH identity、JSON roundtrip 或完整 20 分钟端到端验收。
本轮 Python workflow（含加载库身份检查）为 60/60。

同一安装库的第二次无 profile 测量 `native-validator-repeat/` 为 **298.779 s**，
峰值 **72,117,948 KiB**。两次样本均低于 300 秒；库身份、manifest 和 dependencies
一致，6,007 条 diagnostics 在归一化事务目录后逐项一致。证据为
`native-identity/validator-repeat-comparison.json`。阶段性能已得到两次样本支持，
仍不能替代 F12.5 的功能、identity/roundtrip 和完整端到端验收。

当前候选另已完成 F12.5 的 Make 门禁：`test_firrtl_parser_inputs`、
`verify_firrtl_inputs`、`test_firrtl_comb`、`test_firrtl_state`、
`test_firrtl_memory`、`test_firrtl_effects`、`test_ingest_mixed`、
`test_firrtl_target`、`test_grhsim_flow`，组合调用退出码为 0；完整日志为
`native-identity/acceptance.log`。其中 target 使用原始
`ptmp/xs/rtl/rtl/SimTop.fir`，模型编译/执行均经既有 Make 目标。
全量图的 identity/JSON roundtrip、profile/no-profile 一致性和完整 20 分钟
FIRRTL→C++ 试跑仍待验收；F12 保持进行中。

benchmark 现提供 `FIRRTL_INGEST_BENCH_ARGS='--no-profile --verify-roundtrip'`。
该选项在 ingest 计时后保存完整 design 为 `ingest.json`，删除 Session 中的
原图，再加载并保存为 `roundtrip.json`；`roundtrip-identity.json` 记录两份文件
的字节数、SHA-256、逐字节 identity 是否相同及独立验证耗时。失败会返回非零，
且保留先行写出的 `timing.json`。SHA-256 使用流式读取，不在 Python 中加载
完整整机 JSON。新增层次/node-annotation fixture 已通过，workflow 为 61/61；
不能以该 fixture 代替整机验收。

整机 `whole-roundtrip/` 已执行成功（退出码 0）：ingest 为 **297.960 s**，
ingest 阶段峰值 RSS **72,120,676 KiB**；其后完整 JSON 验证耗时
**997.924 s**。`ingest.json` 与 `roundtrip.json` 均为 **41,790,354,702 bytes**，
SHA-256 均为 `1cf4c109626930fd3df6868448f3fc7bcb89fbd8ff1b220751c10120b97a8af0`。
证据为 `whole-roundtrip/roundtrip-identity.json`，Make 输出在
`roundtrip-gate/whole-driver.log`。该项是完整 design 的 roundtrip identity 验证，
不是从冻结输入开始的 20 分钟 FIRRTL→C++ 端到端成功；profile/no-profile
及优化前后全图 identity 对照也尚未由本次单配置测试证明。

## 目标和边界

当前完整 FIRRTL/mixed ingest 已成为 20 分钟整机预算的第一大固定成本：

| 路线 | 实测耗时 | 证据 |
| --- | ---: | --- |
| FIRRTL/mixed | 516.645 s（full36） | `ptmp/firrtl-ingest/F10/full36/logs/driver.log` |
| FIRRTL/mixed | 514.461 s（full37） | `ptmp/firrtl-ingest/F10/full37/logs/driver.log` |
| 纯 SV | 45.741 s | `ptmp/xs/logs/xs_grhsim_20261030_082621.log` |

当前可复现的阶段基线已经低于早期整机记录，但还没有达到 F12 的第一门槛：同一
manifest `e38eb3daa632249e295756e6d8f698129029c1161ec7a05cef77727efaa12e0b`
在现有 worklist、leaf cache、SrcLoc 单扫描和 canonical node 路径下，无 profile
基线为 **325.652 s**。加入 operation operand vector 的条件式容量预留后，三次
无 profile 样本为 **319.421 s**、**324.111 s** 和 **322.146 s**，profile 样本为
**324.235 s**；
profile 的 `lower_module` 从 202.585 s 降至 199.633 s。样本仍有机器噪声，正式
三次样本中位数为 **322.146 s**，相对基线约快 3.51 s（1.08%）；仍需后续
轮换基线/候选顺序以排除机器频率影响，当前距离 300 s 门槛约 **22 s**。当前
FIRRTL/mixed 阶段约为纯 SV ingest 的 7 倍。纯 SV
的 45.741 s 仍只是同输入规模的路线参照，不是删减 FIRRTL 语义检查的目标。

这里的 `ingest FIRRTL/mixed RTL` 计时从 `read_sources` 开始，包含 FIRRTL
读取、解析、类型和语义 lowering、混合源链接以及事务发布。45 秒的 SV 数字
只作为路线对照，不能把 FIRRTL 的工作错误归因给 SV parser，也不要求两条路线
生成相同的中间图。

固定输入约为 1.6 GiB、9,487 个 module、10,263 个 instance、3,962,622
个 `node`、1,637,265 个 `connect` 和 249,022 个 `wire`。所有测量使用同一
冻结 FIRRTL、辅助 SV 清单、harness 快照、源码和加载库身份；产物写入
`ptmp/firrtl-ingest/F12/`。

F12 只优化实现成本，不删减功能。以下内容必须保持：FIRRTL 6 语义、类型和
宽度检查、source info、effects/invalid/init、memory 和 reset 规则、全部
node annotations、混合语言绑定、诊断和确定性顺序。完整优化轮次、packing、
masked-OR、phase/clone、checkpoint、roundtrip、验证和 C++ emit 均不能关闭或
减少来换取 ingest 时间；不能从 checkpoint 续跑来重置 20 分钟计时。

## 硬预算与测量规则

每次完整 FIRRTL→C++ 试跑使用单个 20 分钟 wall-clock 预算，超时立即
`SIGKILL`，返回码记录为 137。预算从原始冻结输入和 manifest 准备开始，不能
将 ingest 单独跑完后再把后续阶段另算成成功。F12 的阶段 benchmark 可以只到
ingest，但必须明确标记为阶段测量，不能冒充整机通过。

每个实验固定 CPU、线程数、构建类型和环境变量，并记录：

- 输入、辅助 SV、harness、源码和库 SHA-256；
- 每个阶段的 wall time、峰值 RSS、输入/输出字节数和对象计数；
- module、instance、statement、value、operation、annotation 数量；
- diagnostics 数量、GRH identity、JSON roundtrip hash 和退出码。

profile 默认关闭。开启 profile 时只增加分阶段和按 module 的计时，不能在
每个 operation 上打印或分配临时对象。计时输出必须是确定顺序的 JSON/JSONL，
并保存 profile 开关和命令行，方便与无 profile 的正式测量区分。

## 阶段 F12.0：冻结基线和计时契约

交付一个经 Makefile 调用的 ingest benchmark 入口（已有入口不足时先扩展
`benchmark_xs_firrtl_ingest`，不手工调用构建器），生成：

1. `manifest.json`：输入身份、配置、工具和库身份；
2. `stage-timing.json`：读取、解析、索引、lowering、链接和发布的总时间；
3. `module-timing.jsonl`：每个 module 的字节、语句、操作和阶段时间；
4. `rss.txt`、`counts.json` 和 `baseline-summary.md`。

先测纯 SV、FIRRTL-only 和 FIRRTL+SimJTAG mixed 三条路线。若三条路线的
计时标签不同，必须在报告中明确，不把 setup、harness 快照或后续 GRH pass
计入 ingest。

退出条件：同一输入重复两次，阶段总和与现有 `read_sources` 计时误差可解释；
无 profile 和 profile 模式的 GRH identity、diagnostics、roundtrip 和输出
逐字节一致。

当前入口 `make benchmark_xs_firrtl_ingest` 在 profile 开启时还会写出
`profile.jsonl`（确定性 JSON）、`stage-timing.json`、`module-timing.jsonl`、
`counts.json`、`rss.txt` 和 `baseline-summary.md`。无 profile 时仍生成相同的
计时文件集合，阶段和 module 明细为空，从而明确区分没有计时与计时为零；所有
文件都位于该次 benchmark 的 `ptmp/firrtl-ingest/F12/<change>/` 目录。

## 阶段 F12.1：建立热点分解

在 `wolvrix/lib/ingest/firrtl.cpp`、共享 driver 和必要的链接代码加入低开销
scope timer，至少区分：

- 文件 I/O 和缓冲区建立；
- lexer/token 扫描、缩进和 source span；
- circuit/module/interface 索引；
- 类型、宽度、引用和时钟域解析；
- statement lowering（node、connect、wire、reg、memory、when、效果）；
- annotation/node attribute 规范化和 provenance；
- instance specialization、FIRRTL↔SV 接口配对和 mixed link；
- GRH builder 写入、事务发布和临时对象释放。

同时按 module 记录 self time、child time、输入字节和产生的 GRH 对象。先找出
覆盖 90% ingest 时间的两个或三个阶段，再改代码；在热点未知时不做大范围
容器或并行化改写。

退出条件：报告能解释至少 95% 的 ingest wall time，并列出 top-20 module
及其占比；没有因为计时器本身改变排序、identity 或内存峰值。

当前实现已接入 `WOLVRIX_FIRRTL_INGEST_PROFILE=1`。它只在 profile 开启时
累计 `index_file`、`validate`、`parse_module`、接口推导、lowering、事务和
验证计时，并输出 top-20 module 的 parse/resolve/lower 时间与 parse 次数；默认
路径不执行这些计时和输出。`benchmark_xs_firrtl_ingest` 通过 Makefile 调用
固定 manifest，保存 `manifest.json`、`timing.json` 和 `benchmark.log`。

首轮香山整机 profile（同一 manifest、同一 1.67 GB FIRRTL 输入，缓存开启）已经
完成，结果如下。`ensure_phase` 包含 `lower_module`，所以阶段不能直接相加：

| 阶段 | wall time |
| --- | ---: |
| ingest 总计 | 486.120 s（benchmark wall 486.191 s） |
| interface resolve / `Semantics::analyze(true)` | 86.043 s |
| ensure FIRRTL | 328.912 s |
| module lowering（ensure 的子集） | 321.327 s |
| linked-design verify | 51.801 s |
| parse module | 17.347 s |
| index file | 2.484 s |

缓存关闭的严格对照为 514.608 s；缓存开启约减少 28.4 s（5.5%），峰值 RSS
从 72,412,564 KiB 降到 71,171,188 KiB。缓存命中/未命中分别为 28,461/9,487，
每个 module 的 parse 次数从 5 次降为 2 次。证据在
`ptmp/firrtl-ingest/F12/whole-chip-stage/run/benchmark.log`、
`whole-chip-cache-off/run/benchmark.log` 和对应 `timing.json`。

当前 top-20 module 的 resolve 数字是从依赖遍历入口开始的 inclusive time，父模块
会包含其 FIRRTL 子模块的分析时间；不能把 top-20 数字相加作为总成本。profile
已新增 `resolve_self_us`，只包住本模块的 `Semantics::analyze(true)`；下一轮整机
profile 将用 self/child 对照选择具体缓存或语义分析优化。

重新安装 Python 扩展后复跑的 self-time profile 为 484.011 s（benchmark wall
484.0 s），阶段仍为 resolve 85.239 s、lowering 320.343 s、linked-design
verify 51.218 s。代表模块的 self/inclusive 对照为：`Rob` 10.604/15.086 s、
`LogPerfEndpoint` 3.340/3.941 s、`SimTop` 0.868/84.974 s；这证明顶层的
大数主要来自递归子模块，不能把顶层 inclusive 时间当成本模块分析时间。证据在
`ptmp/firrtl-ingest/F12/whole-chip-self2/benchmark.log`。

随后实施的 SrcLoc 候选把 `lower.cpp::Lowerer::op()` 对同一 `Range` 的两次
`Source::position()` 扫描合并为一次，仍分别保存 operation/value 的 source info。
同一 manifest 的 profile A/B 如下：

| 配置 | ingest | lower_module | ensure | verify |
| --- | ---: | ---: | ---: | ---: |
| cache-on、SrcLoc 双扫描 | 484.011 s | 320.343 s | 328.089 s | 51.218 s |
| cache-on、SrcLoc 单扫描 | **452.812 s** | **290.053 s** | **297.627 s** | **50.142 s** |

该候选减少约 31.2 s（6.5%）；lowering 减少约 30.3 s（9.5%），峰值 RSS 为
72,176,164 KiB。`Rob` lowering 为 36.731 s，`LogPerfEndpoint` 为 17.991 s。
图、属性和诊断回归由 `make test_wolvrix` 81/81 通过；正式无 profile 重复测量和
代表模块 JSON/hash 对照仍是 F12.5 的必要门槛。证据在
`ptmp/firrtl-ingest/F12/whole-chip-lower-src-loc/benchmark.log`。

随后实施的依赖驱动 interface worklist 保留首轮全量分析；后续只重跑接口发生
宽度变化的 module、其自身和反向父模块，仍按原 DFS 顺序递归检查依赖和循环。与
上述同一 manifest 的结果为：

| 配置 | ingest | resolve | lower_module | ensure | verify |
| --- | ---: | ---: | ---: | ---: | ---: |
| cache-on、SrcLoc 单扫描 | 452.812 s | 85.710 s | 290.053 s | 297.627 s | 50.142 s |
| 加 worklist | **409.236 s** | **45.922 s** | **280.182 s** | **288.554 s** | **54.156 s** |
| 加 Lowerer/semantic leaf cache、canonical node write | **378.781 s** | **46.672 s** | **254.450 s** | **262.372 s** | **49.646 s** |

`resolve_module_calls` 从 28,461 降到 9,818（仍保留 3 个收敛轮的确定性边界），
峰值 RSS 为 72,164,708 KiB。width/Reset 层次 fixture、mixed linking 和全部
`make test_wolvrix` 81/81、`make test_xs_firrtl_workflow` 59/59 通过。该 profile
仍启用计时，最新候选峰值 RSS 为 72,182,260 KiB；正式无 profile 和全链路
20 分钟门槛尚待 F12.5 验收。证据分别在
`ptmp/firrtl-ingest/F12/whole-chip-worklist/benchmark.log` 和
`ptmp/firrtl-ingest/F12/whole-chip-worklist-resolution-profile/benchmark.log`。

这也确认了路线差异：纯 SV ingest 的既有基线为 45.741 s（通常重复测量约
45–49 s），约比当前 FIRRTL/mixed ingest 快 7.2 倍。该数字不包含 FIRRTL 的
类型/语义解析和 lowering，不能用来推断 FIRRTL parser 单独应达到同样耗时；下一
项优先分析剩余的 lowering/GRH 构建和 linked-design verify 成本；worklist 已消除
主要的 `resolve_interfaces` 全量重跑。

## 阶段 F12.2：解析和索引优化候选

按 profile 结果逐项实施，每项单独提交并保留 A/B：

- 复用 lexer 的缓冲区和 token 字符串，避免对 module、field、instance 名称
  重复分配和复制；必要时使用稳定的字符串池，但不得改变 source text 或
  diagnostics 的生命周期。
- 让 module/interface 索引一次建立并供类型解析、instance linking 和
  diagnostics 复用；预留已测规模的 vector/hash capacity，避免反复 rehash。
- 缓存不可变的 port 顺序、aggregate shape、宽度和符号查找结果；缓存键必须
  包含输入身份、module specialization 参数和语言来源，禁止跨设计复用。
- 保留 source line/column、原始 attribute 文本和错误顺序；只有在证明不影响
  诊断时，才延迟构造昂贵的 source/quoted 对象。

不在这一阶段删除未使用 module、关闭宽度/类型检查或把 parser 改成只读可达
子图。若未来要做可达性裁剪，必须单独定义诊断合约和全输入负例回归。

首个实现候选是请求级 ModuleBody cache：接口推导和 lowering 复用同一份 AST，
每个 module 完成 lowering 后立即释放。`WOLVRIX_FIRRTL_PARSE_CACHE=0` 保留
无缓存对照路径；缓存命中/未命中和 parse 调用数由 profile 记录。该缓存不跨
请求、输入或 specialization 复用，也不改变 validate 对所有 module 的诊断顺序。

### 当前执行顺序（2026-11-02）

先完成 ingest 本身，再进入 flatten、simplify 和 C++ emit。每个候选按以下顺序
推进，并在同一 manifest 上留下可复现的 A/B 证据：

1. 固定 parse-cache、source-location、接口 resolve 和 lowering 的阶段基线；
2. 用依赖驱动的 worklist 减少固定点中的重复 `Semantics::analyze(true)`，但首轮
   仍分析全部模块，宽度和 Reset 变化仍沿反向 instance 边传播；
3. 在 lowering 内复用不可变 type leaf 展开结果，并为已经 canonical 的 node
   attribute 写入提供等价快路径；
4. 逐项复核图、source info、annotation、diagnostics、JSON roundtrip 和模块
   identity，再合并候选；
5. 重新安装扩展后测无 profile 的整机 ingest，最后才把完整 FIRRTL→C++ 放入
   20 分钟硬截止。

任何候选若只靠跳过检查、减少 annotation/effect、裁剪不可达模块、减少
   simplify/flatten 轮次或改变诊断顺序取得收益，立即撤回。性能报告同时记录
   纯 SV 参照（约 45.7 秒）和 FIRRTL/mixed 实际值（当前约 322 秒无 profile 候选值），
   不能把两条路线的计时混为同一 ingest 工作量。

首轮 profile 已确认 `resolve_module_calls=28,461`，即 9,487 个 module 在固定点
推导中完整重跑 3 轮；依赖 worklist 已按接口宽度/Reset 变化完成首轮实现。它只
重跑受影响 module 及其父模块，并保留 `resolve_self_us`、原有拓扑诊断顺序和
“已访问”循环检查，不能仅按访问标记跳过后续宽度约束。

依赖 worklist 的首轮整机候选已经完成（同一 manifest、同一 cache 和 SrcLoc 单扫
配置）。首轮仍全量分析；之后只传播接口宽度变化涉及的模块及其 reverse instance
parents，`drivenWidths` 保持单调最大值，因此不会丢失后续轮次的宽度约束。
在 Lowerer leaf cache 和 canonical node-write 快路径加入后，profile 显示
`resolve_module_calls` 从 28,461 降到 9,818，接口 resolve 为 46.7 秒；随后撤回了
source line map 和 schema-ready 这两个无收益候选；它们增加了预处理或
只减少 metadata 查找，分别没有带来 wall-time 下降。当前保留的 operation
operand reserve 将 profile ingest 降至 324.235 秒，lowering 为 199.633 秒，
resolve 为 47.490 秒，verify 为 49.403 秒，峰值 RSS 为 72,105,260 KiB；同一
候选三次无 profile 为 319.421、324.111 和 322.146 秒。此前 378.8/381.4 秒仍保留为
历史 A/B 对照。证据在 `ptmp/firrtl-ingest/F12/operand-reserve-profile/`
和对应的 `operand-reserve-noprofile*` 目录；此前同配置 profile 的 409.2 秒记录
在 `ptmp/firrtl-ingest/F12/whole-chip-worklist/`，用于说明机器负载和缓存波动。
同一 manifest 的无 profile 复测为 381.391 秒，峰值 RSS 为 72,129,188 KiB，
退出时的 comb-loop-elim 统计也完整输出；证据在
`ptmp/firrtl-ingest/F12/whole-chip-worklist-resolution-noprofile/timing.json`，
manifest SHA-256 为 `e38eb3daa632249e295756e6d8f698129029c1161ec7a05cef77727efaa12e0b`。
此前 semantic leaf cache 加入前的 394.783 秒记录保留在
`ptmp/firrtl-ingest/F12/whole-chip-worklist-noprofile/`，用于 A/B 对照。该数值
仍是候选结果；默认合入前还要完成 identity、diagnostics、JSON roundtrip
和完整 FIRRTL/SV 回归。端口签名比较覆盖会影响层次解析的字段，并对 stale
`portIndices` 做边界保护；`requiresTypeResolution` 作为宽度/shape 派生状态被
排除，避免触发无关固定点重跑。曾测得包含该字段的失败 A/B 为 406.8 秒、18,995
次 resolve 调用，已撤回。

随后继续对 lowering 的 source-location 路径和容器容量做了保持语义的细粒度
A/B。请求级 source line map 的候选需要额外扫描整份 FIRRTL 文本，profile 结果为
329.499 s，相对基线变慢，已撤回。canonical schema-ready 候选也只跳过重复
metadata 查找，profile 为 327.163 s、no-profile 为 329.988 s，未保留。当前保留
的低风险改动是：为新建且确实带 node annotation 的 operation 预留属性槽，并为
多 operand operation 预留 operand vector；它们仍保留 source info、全部
operation/value、annotation、类型/宽度检查和诊断顺序，没有跳过 module、statement
或 verification。固定 manifest 的结果为：

| 配置 | ingest | resolve | lower_module | verify | 峰值 RSS |
| --- | ---: | ---: | ---: | ---: | ---: |
| no profile，既有候选基线 | 325.652 s | — | — | — | 72,187,972 KiB |
| no profile，operand reserve 样本 1 | **319.421 s** | — | — | — | 71,269,820 KiB |
| no profile，operand reserve 样本 2 | **324.111 s** | — | — | — | 72,098,572 KiB |
| no profile，operand reserve 样本 3（最终二进制） | **322.146 s** | — | — | — | 72,117,672 KiB |
| profile，operand reserve | **324.235 s** | 47.490 s | 199.633 s | 49.403 s | 72,105,260 KiB |

证据在 `ptmp/firrtl-ingest/F12/operand-reserve-profile/`、
`operand-reserve-noprofile/` 和 `operand-reserve-noprofile-repeat/` 的
`benchmark.log`、`timing.json`；最终清理后二进制的证据在
`ptmp/firrtl-ingest/F12/final-noprofile/`；schema-ready 和 source-line-map 的撤回证据分别在
`schema-ready-*`、`source-line-index-profile/`。F12 的 300 s 第一门槛尚未达成；
后续实验优先拆分剩余 expression/access 临时对象、GRH operation/value/attribute
建立和代表热点模块，不把 profile 数字作为正式无 profile 验收值。

### 下一轮细粒度 profiling 计划

目标是解释最新无 profile 324.111 s 中至少 95% 的时间，并把可优化成本与
完整语义检查分开记录。每一轮只改变一个实现因素，使用同一 manifest；profile
只增加聚合计时，不在 operation 热点打印或分配对象。

| 顺序 | 观察面 | 记录的计数 | A/B 约束 |
| --- | --- | --- | --- |
| 1 | `expression`/`access` 临时对象 | 构造/复制/释放次数、字节数、self/child time | 保留所有 ValueId、source info 和错误顺序 |
| 2 | GRH operation/value 建立 | builder 调用、扩容次数、属性/operand 字节数 | 保持 OperationId/ValueId 分配顺序和图 identity |
| 3 | annotation/provenance 规范化 | schema parse、origin/member/root 合并次数 | JSON roundtrip、annotation 数量和内容必须一致 |
| 4 | `Rob`、`LogPerfEndpoint` 等 top modules | module self time、statement/expr/value/op 数量 | 与通用 lowering 对照，不能只对单模块设特例 |
| 5 | verify 和事务发布 | 检查项数量、发布批次、峰值 RSS | 不减少检查；只评估批量提交和临时对象生命周期 |

每个候选完成后先跑局部语义/属性回归，再跑 `make test_wolvrix` 和
`make test_xs_firrtl_workflow`；只有 identity、diagnostics、JSON roundtrip、
mixed binding 全部一致，才进行一次无 profile 整机 A/B。尚未达到 300 s 前，不
开始 flatten、simplify 或 C++ emit 的性能取舍。

在实施下一项结构性改动前，先增加只在 profile 模式启用的 aggregate counters，
不输出 per-operation 日志，也不改变任何 ValueId、OperationId、source info、
annotation 或诊断顺序。计数契约如下：

| 计时面 | 必须记录 | 用途 |
| --- | --- | --- |
| source location | `Source::position` 调用次数、line-cache hit/miss、扫描字节和 `SrcLoc` 构造时间 | 判断单行缓存是否因交错/跨行输入失效；只有测得 miss 成本后才考虑请求级 line map |
| `Lowerer::op` | op-kind、`createOperation`/`createValue`、operand/result 写入、source-info 写入和 node-attribute 写入次数与累计时间 | 区分图建立、符号生成、source info 和 node provenance 的固定开销 |
| expression/access | Reference、Field、Index、Mux、primitive、array/memory access 的计数，以及 AccessPath vector 构造/复制字节 | 识别递归临时对象成本，避免凭经验改写 aggregate 语义 |
| GRH builder | operation/value/attribute 容器 reserve 命中、扩容、`setAttr` 插入和属性字节 | 只在扩容或排序占比明确时调整容量或批量写入 |
| canonical node | schema/member/origin/root 规范化调用和 metadata 查找/写回次数 | 已评估 schema-ready 快路径并撤回；仍保留完整 schema、members、origins、roots |
| leaf/type cache | `(TypePtr, flow)` hit/miss、叶子数和递归时间 | 确认 cache 覆盖率及其对不同 aggregate 的影响 |

module 计时继续报告 self/child 两列。当前 top lowering self time 为 `Rob`
31.744 s、`LogPerfEndpoint` 15.035 s、`RenameBuffer` 3.480 s；top-20
合计只覆盖约 68.7 s，剩余时间来自大量小 module 的每 statement/op 固定成本，
不能只为两个大模块写特例。第一轮 counters 完成后，已先验证 GRH operation
容量候选：多 operand operation 的 operand vector 预留在两次 no-profile 样本中
保持或改善 wall time，profile 的 `lower_module` 下降约 2.95 s；属性槽预留本身
在 no-profile 中近似中性，只作为配套容量优化保留。下一项按下列顺序做单因素
A/B：expression/access 临时对象 → memory/effects/state 专用路径 → attribute
key/批量写入。每项都须有同 manifest 的 profile/no-profile、identity、diagnostics、
JSON roundtrip 和 mixed binding 证据；不通过就回退。

## 阶段 F12.3：lowering 和 GRH 构建优化候选

- 复用每 module 的声明符号表、端口索引、类型 shape 和事件域信息，避免每条
  statement 重新解析相同声明。
- 预留 operation/value/attribute 容器并采用 move 或稳定 arena，减少大规模
  `node`、`connect`、Bundle/Vector shape 和 provenance 的临时复制。
- 对常见 FIRRTL 语句批量建立 GRH 对象，但保持现有 ValueId/OperationId
  分配顺序、source info、annotation 顺序和错误优先级。
- 将 effect、memory、reset、invalid、clock crossing 等少数高成本路径单独
  计时；任何专用快路径都必须与通用 lowering 逐项对照。

优化目标是降低 CPU、分配次数和峰值 RSS，同时保持完整图。不能以减少 node、
annotation、检查次数或 lowering 轮次作为“优化收益”。lowering 的细粒度计时
随后拆为 source-location 构造、expression/access 临时路径、`leaves()` 递归、
GRH operation/value 建立和 node annotation 规范化；最新 profile 中 `Rob`
lowering self 为 31.744 s、`LogPerfEndpoint` 为 15.035 s。任何快路径都须与通用 lowering 的图、
属性、诊断和 roundtrip 逐项对照。

已完成的低风险候选包括：`Lowerer::op()` 对同一 range 只构造一次 source
location；Lowerer 高频 leaf 展开按 `(TypePtr, flow)` 请求级缓存；canonical node
attribute 写入使用保留 schema、成员、origin 和 root 索引的单 key 快路径。组合、
state、memory、effects、aggregate、widths 及 node-attribute Make 回归均通过。
这些候选没有删除 source info、annotation 或 operation/value，最新 profile 与无
profile 数值见上表和上文。

F12.2/F12.3 细粒度 A/B 另外验证了三条实现路径：source line map 会额外扫描整份
输入且使 profile 到 329.499 s，已撤回；schema-ready 只减少 metadata 查找，
profile/no-profile 为 327.163/329.988 s，也已撤回；新 operation 的属性槽预留
在 no-profile 中基本中性，因此作为 operand reserve 的配套保留；多 operand
operation 的 `reserveOpOperandCapacity` 是当前唯一有稳定方向的 GRH 容量改动。

## 阶段 F12.4：mixed link 优化候选

- 对同一个请求内的 FIRRTL module/interface 和 SV module 只解析一次；按源文件
  fingerprint、module 名称和 specialization 参数缓存接口签名。
- 使用显式 manifest 传递实际辅助 SV，避免扫描生成 SV 目录或重复导入已由
  FIRRTL blackbox annotation 提供的实现。
- 将跨语言绑定、参数化 defname、packed aggregate shape 和 ABI adapter 的
  查找结果缓存到请求级 registry；缓存失效时回退到现有完整路径。
- 保持交替 FIRRTL→SV→FIRRTL 和 SV→FIRRTL→SV 的递归检测、重复定义诊断、
  端口缺失错误及确定性绑定顺序。

退出条件：mixed、FIRRTL-only 和 SV-only 的模块身份及绑定报告可重放；所有
 F07 mixed、FIRRTL target、effects/memory/state 和输入 manifest 回归通过。

## 阶段 F12.5：验证和整机门槛

每个候选优化都必须通过以下顺序：

1. `make test_wolvrix` 与对应 parser/ingest CTest；
2. `make test_firrtl_parser_inputs verify_firrtl_inputs`；
3. `make test_firrtl_comb test_firrtl_state test_firrtl_memory test_firrtl_effects`；
4. `make test_ingest_mixed test_firrtl_target test_grhsim_flow`；
5. 代表模块和原始香山输入的编译执行、JSON roundtrip、diagnostics 对照；
6. 从原始冻结输入开始的一次完整 20 分钟 FIRRTL→C++ 试跑。

正式性能报告必须同时给出无 profile 的阶段 wall/RSS 和正确性 hash。任何
一项语义、identity、diagnostics、绑定或 roundtrip 变化都阻止进入下一项优化。

F12 的阶段目标分两档记录，不把目标当作已经达成：

- 第一门槛：在保持完整 ingest 语义的情况下，将 FIRRTL/mixed ingest 从
  514–517 秒降到 300 秒以内，并能解释剩余成本；
- 伸展目标：在同一输入规模上逼近 180 秒，最终是否足以让完整 FIRRTL→C++
  在 20 分钟内完成，以实际整机试跑为准。

纯 SV 的 45–49 秒是诊断参照，不是 FIRRTL 必须达到的验收数字。若阶段目标
未达成，报告必须说明剩余热点和下一项实验，不能通过关闭 annotations、减少
pass、减少 simplify 轮次或恢复 checkpoint 宣称完成。

## 记录和回滚规则

每个优化变更使用独立目录 `ptmp/firrtl-ingest/F12/<change>/`，至少保存
baseline/candidate manifest、profile、A/B hash、Make 输出和失败原因。正式
整机试跑仍使用单次 20 分钟硬截止；超时立即 SIGKILL，完整记录停止阶段和已
消耗预算。发现语义或诊断差异时回滚该项，不把多项混合提交后再猜测来源。

F12 完成后才进入 F11 的 A/B/C/D 输入路线、node CSE、分图和仿真吞吐消融；
F12 的 ingest wall time、RSS 和热点报告作为 F11 的共同输入成本单独列出。
