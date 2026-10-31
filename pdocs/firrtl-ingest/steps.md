# FIRRTL ingest 分阶段实施

阶段总览见 [index.md](index.md)，接口、属性及语义合约见
[architecture.md](architecture.md)。以下 Make target 以“现有”或“待新增”标明；
待新增入口必须先写入项目 Makefile，之后才能运行对应构建、测试或脚本。
所有临时工作目录使用 `ptmp/firrtl-ingest/Fxx/`。

## 推进顺序与共同退出条件

主线顺序为 F00 → F01 → F02 → F03 → F04 → F05 → F06 → F07 → F08 →
F09 → F10 → F11。属性与 node 作用域检查从 F02 开始伴随实现，F08 实现
完整 node CSE 并验收全流程。混合模块注册表从 F01 设计，F07 完成端到端
绑定；F09 可在 F02 后使用人工标注 fixture 做独立准备，不能据此宣称真实
FIRRTL 路线完成。

每阶段共同交付为原子实现、必要回归、相应正式文档、实际命令及证据。发现
前阶段缺失语义时回到对应阶段修正；不通过移除输入构造来让目标模型通过。
机械迁移、语言支持、属性/作用域传递、完整 node CSE 与分图策略分别提交。

## F00：固定目标输入和测量口径

交付：

- 固定一份 XiangShan FIRRTL、它对应的 SV 基线、必要的 SV 实现/include/宏、
  Chisel/生成配置、workload、NEMU 和工具链身份。大文件只记录 manifest/hash。
- 以自有轻量扫描建立特性清单：版本、module/extmodule、defname/参数、原语、
  node、Bundle/Vector、reg/regreset、memory/mport、layer/intrinsic、Probe、
  annotation 和未初始化行为；检查伴随 annotation JSON 中的 SV 路径、资源
  及内嵌实现。特性统计不代替正式 parser。
- 分离“原始 FIRRTL 中保留的结构”和“已在 Chisel 中展开的结构”。保留
  RenameTable 动态写、ROB 字段与一个 memory 模块作为小范围验证候选。
- 冻结 SV 路线的 correctness、各构建阶段 wall/RSS、分图统计及运行对照。
  既有 NO00012/13 记录只用于调查，不把历史耗时当作本轮正式样本。
- 固定 FIRRTL 规范和 ABI 修订版本，建立支持/待支持/明确拒绝矩阵，并列出
  达到整机目标所需的构造。记录预计资源预算及 1.6 GiB 输入的解析策略。
- 固定本地 GSIM `a3ecb26` 的 commonExpr、treeOpt 和 pass 顺序作为参照，
  记录整体判等、实际共享门槛、后继计数及数组/状态排除规则。

验证入口：现有 `make xs_grhsim_emu`、`make run_xs_grhsim_emu`；需要扫描或
manifest 检查时新增 `make inspect_firrtl_inputs`，避免直接调用 Python 工作流。

退出条件：输入能互相追溯到同一设计配置，SV 基线正确运行，必要 SV 外部
实现无遗漏，每个目标 FIRRTL 构造有明确的实现阶段或阻塞原因。

实施记录（2026-10-30）：F03 所需的语法输入身份和目标构造矩阵已提前交付，
见 [inputs.json](inputs.json) 和 [F03-acceptance.md](F03-acceptance.md)。
生成日志固定 TLConfig、issue E.b、单核、`--dump-fir` 及 aggregate SV 配置；
FIRRTL、SV、生成日志、fixture 和规范均有内容校验。F00 仍为进行中，尚需
完整外部 SV/annotation 依赖核对、workload/NEMU/工具链身份、SV 正确性与
本轮性能基线等其余交付。F03 的 parser 验收没有代替这些整机验收。

## F01：迁移 ingest 目录并建立公共读取层

交付：

- 将 `wolvrix/lib/core/ingest.cpp` 原样迁移为 `lib/ingest/sv.cpp`；公共 SV
  声明移至 `include/ingest/sv.hpp`，删除旧 `include/core/ingest.hpp`，更新
  CMake 及全部调用方、测试、Python 绑定和文档示例的 include 路径。
- 新建 `lib/ingest/firrtl.cpp`、`driver.cpp` 和对应入口头，形成明确的模块
  扫描、语言前端、specialization 和统一链接边界，空入口返回未支持诊断。
- 共享 `IngestRequest`、模块/叶子端口签名、带类型参数和诊断结构；与 SV AST
  类型隔离。保留旧命名空间/API，不能为了迁移就改动 SV lowering。
- 设计持有全部 source owner 的读取结果，保证 session 替换及失败原子性。

验证入口：现有 `make build`、`make test_wolvrix`、`make py_install`、
`make test_grhsim_flow`；小样例执行现有 HDLBits Make target。

退出条件：旧 `read_sv` 调用兼容，既有 SV 回归通过，构建只编译新的 sv.cpp
路径，原 core/ingest.cpp 不再注册；旧 `include/core/ingest.hpp` 已删除，
无调用方引用旧头路径；不宣称此时已支持 FIRRTL 行为。

实施记录（2026-10-30）：已完成。

- wolvrix 实现提交为 `db11f0d`（`grh/firrtl-ingest`）；实施基点为主仓
  `20989f59615121b78205340c507d2704e57e50c2`、wolvrix
  `1101c77c2606a8160e24879be4ceefe5e7077120`。F00 仍待实施；本阶段只验证
  独立的目录/接口迁移，不引用未冻结的香山输入作验收。
- `lib/ingest/sv.cpp`、`include/ingest/sv.hpp` 已接替旧路径；SV lowering
  本体与基点逐字节一致。构建源列表及全部调用方 include 已迁移，旧头已删除。
- `include/ingest/ingest.hpp` 提供请求、类型化参数、模块/叶子签名、绑定请求、
  独立源位置诊断及 source owner 集合；driver 保持 SV 读取可用，其余扫描、
  FIRRTL lowering、显式 specialization、混合链接入口返回未支持错误。
- Python `read_sv` 使用公共 driver，读取结果和 session clone/copy 持有全部
  source owner。SV owner 同时保留 compilation 与拥有 SourceManager 的
  slang driver。失败读取不覆盖旧 design 或其他种类的 session 值。
- 新增 `ingest-driver` CTest 和 `make test_ingest_session`（3 项 Python 测试）；
  覆盖指定输入根/顶层、slang 参数文件、源生命周期、独立错误位置、未支持
  入口、失败替换、重复 key、clone/copy 及同 key 克隆。
- 正式接口文档见 [reading.md](../../wolvrix/docs/ingest/reading.md)。node attrs、
  FIRRTL parser 和真实混合绑定仍属 F02 及后续阶段。

实际验证均经项目 Makefile，日志在 `ptmp/firrtl-ingest/F01/`：

| Make 命令 | 结果 | 日志 |
| --- | --- | --- |
| `make test_wolvrix`（依赖 `build`） | 完整构建成功；66/66 CTest 通过 | `test_wolvrix.log` |
| `make py_install PYTHON="$PWD/.venv/bin/python"` | Python 扩展构建与安装成功 | `py_install.log` |
| `make test_ingest_session SKIP_PY_INSTALL=1 PYTHON="$PWD/.venv/bin/python"` | 3/3 通过 | `test_ingest_session.log` |
| `make test_grhsim_flow SKIP_PY_INSTALL=1 PYTHON="$PWD/.venv/bin/python" GRHSIM_FLOW_TEST_WORK="$PWD/ptmp/firrtl-ingest/F01/grhsim-flow"` | 2/2 Python 测试及全部 checkpoint 模型编译/运行通过 | `test_grhsim_flow.log` |
| `make run_hdlbits_test DUT=001 SKIP_PY_INSTALL=1 PYTHON="$PWD/.venv/bin/python"` | 经新前端读取、SV 输出及仿真通过 | `hdlbits_001.log` |

上述命令带 `WOLF_ENV_SOURCED=1`，TMPDIR 和 CCACHE_DIR 分别为
`$PWD/ptmp/firrtl-ingest/F01/tmp` 与 `.../ccache`；完整构建和 Python 安装
使用 `CMAKE_BUILD_PARALLEL_LEVEL=8`。测试 fixture 沿用
`wolvrix/tests/ingest/data/`，CMake 测试产物位于 `wolvrix/build/artifacts/`，
session/flow 临时产物位于 F01 证据目录，HDLBits 产物位于 `build/hdlbits/001/`。

## F02：定义 node 属性和 CSE 作用域

交付：

- 实现 architecture §7 的 schema v1，以及 node key 构造、属性读取/规范化、
  union、root result remap、实例路径限定和 verifier。
- 区分 members、roots 与诊断 origins；多个成员身份须有整体 node 合并或
  显式变换依据。aliases/constants/dead node 按合约处理，不新增可执行 node op。
- 检查 JSON 已有属性类型能无损往返，clone/rename/ID 重排不依赖裸实体 ID。
  单独检查两个同模块实例的 key 不碰撞。
- 普通 simplify/CSE 和 GrhSIM `cseKey` 分开处理功能判等与合法作用域：
  node 内可简化/CSE；跨 node 不提取公共内部 op。常量/纯别名可以消除，
  无注解 SV 保持原规则，但不能与受保护 node 内部 op 跨边界合并。
- 提供整体 node 合并时的成员与根重定向工具；实际判等和门槛在 F08 实现。
- 新增属性验证和观察报告，报告真正根映射而非只搜索属性字符串。

验证入口：新增 `make test_firrtl_node_attributes`、`make test_firrtl_cse_scope`，
复用现有 `make test_transform_simplify`、`make test_grhsim_transforms`，并为 store/load
必要定向检查先添加 Make target。

退出条件：node 内局部简化正常，两个不同 node 的相同内部 and/add 保持独立，
纯常量/别名不被过度保护；属性损坏被拒绝，作用域及根映射 JSON 往返通过。

实施记录（2026-10-30）：已完成，wolvrix 实现提交为 `d60f522`
（`grh/firrtl-ingest`）。

- `ingest/node_attributes.hpp` 和 `lib/ingest/node_attributes.cpp` 提供 schema
  v1、canonical key、规范化、实例限定、结果映射、合法共享 union、根重定向、
  verifier 和 inspection report。未知 schema/属性类型、无根活跃成员、重复根、
  非法 result 序号和损坏 key 均诊断；缺失 members 的片段保留独立作用域并报告。
- 普通 `simplify` 的 primitive CSE 将功能签名与 node 作用域分开；完整 key
  只在本轮作用域表内保存，primitive 签名持有瞬时整数作用域。无 schema 的
  SV 图跳过 node scope 计算。常量、纯别名和 DCE 继续工作。
- GrhSIM `cseKey` 排除来源 attrs，同时匹配 node 作用域；新 op 复制 members，
  原地重写保留属性。slice/concat/arrayCreate、NOT/XOR、mux chain 和 masked-OR
  融合不进入另一个 node 的计算。完整执行 leaf 内可共享，跨 leaf 仍隔离。
- 根折叠到同作用域结果或常量时迁移 result 映射；转成输入或其他 node 的
  结果时保留透明 `kAssign`，不把归属写到不相关 producer。真实多结果端口
  置换核对到实际输出 value；同 op 不同 result 的根重定向及自合并均有
  定向验证。
- 持久化回归先制造稀疏 ID，再断言 clone 确实改变 op/value 索引；重命名
  op/value 后，源 key 与根映射保持一致，inspection 使用新符号定位真实
  结果。freeze/JSON 重载后报告一致；同模块两份实例限定后的 key 不碰撞。
- 新增 `firrtl-node-attributes`、`firrtl-cse-scope` CTest 及相应 Make 入口；
  scope suite 用独立组合求值器检查 normal/GrhSIM 优化和 JSON 重载前后的
  512 组输入。覆盖局部共享、跨 node/SV 隔离、常量/别名/死节点、根到输入、
  数组 shape、部分属性丢失、融合边界及同/不同执行 leaf。
- 真实 parser、混合链接、hier-flatten/phase clone 的全流程属性传递、GSIM
  完整 node 判等门槛及 nonsink 利用仍属 F03–F09，未将人工标注回归视为
  FIRRTL 读取完成。正式合约见
  [node-attributes.md](../../wolvrix/docs/ingest/node-attributes.md)。

实际验证通过项目 Makefile，日志在 `ptmp/firrtl-ingest/F02/`：

| Make 命令 | 结果 | 日志 |
| --- | --- | --- |
| `make test_firrtl_node_attributes` | 通过；身份、属性错误、实例限定、实际 ID 重排/重命名、多结果输出映射与 JSON 往返 | `node_attributes.log` |
| `make test_firrtl_cse_scope` | 通过；primitive 共享范围及独立组合结果检查 | `cse_scope.log` |
| `make test_wolvrix` | 完整构建和 68/68 CTest 通过（含上述新增回归） | `test_wolvrix.log` |

命令带 `WOLF_ENV_SOURCED=1`；全量构建使用 `CMAKE_BUILD_PARALLEL_LEVEL=8`，
构建 TMPDIR、CCACHE_DIR 指向本阶段 `tmp/`、`ccache/`。定向 Make 入口内
设置同样目录，全量 CTest 沿用 Makefile 的 `ptmp/ctest_tmp/`、
`ptmp/ctest_ccache/`；测试工作产物遵循 `wolvrix/build/artifacts/`。F00 输入冻结仍待完成，
本阶段未声称整机 FIRRTL 正确性或性能提升。

## F03：自有 parser 和接口索引

交付：

- 在 `firrtl.cpp` 后按需拆分私有 lexer/parser。使用缩进 token 和递归下降
  表达式解析，支持目标版本的文件头、模块、类型、声明、语句及 source info。
- 做模块级扫描/解析接口，支持先建立模块符号再解析主体，模块及声明的
  引用规则服从 FIRRTL，不沿用 SV 文本顺序假设。
- 版本门控与错误恢复：能识别但尚未 lowering 的构造保留类型化表示并报错，
  不用静默跳过未知行接受文件。
- 控制大文件资源：文件文本不多次复制；名称/类型 intern，模块按需解析与
  lowering，避免同时持有全文件文本副本、完整 AST 和全设计中间图。
- 报告行列、原始 FIRRTL source info 及当前模块；扫描结果供混合 driver 使用。

验证入口：新增 `make test_firrtl_parser`、`make inspect_firrtl_inputs`。
fixture 包括缩进/注释/引号、嵌套语句、版本差异、截断文件和错误语法。

退出条件：F00 冻结输入可完成语法和接口扫描，目标构造没有被跳过；资源与
诊断记录可审查。该阶段通过只说明 parse 成功，不代表行为 lowering 完成。

实施记录（2026-10-30）：已完成。parser 和接口索引实现提交为 `501360f`
（`grh/firrtl-ingest`）；资源与源位置边界回归提交为 `c798118`，并补齐冻结
输入复验。F03 所需的
输入身份已冻结，全模块语法与接口验收通过；F00 其余整机交付仍为进行中。
逐项验收和目标构造矩阵见 [F03-acceptance.md](F03-acceptance.md)。

- 新增自有 source owner、lexer 和递归下降 parser，不链接或调用 CIRCT。
  接受版本头 `FIRRTL version 6.0.0`，支持精确 `expectedVersion` 检查；
  旧版本、未知语句/表达式及截断文件明确诊断。
- 接口索引保留模块范围、类型、别名、layer、formal 和 annotation 原文；
  模块主体按需解析为 arena。Unix 文件使用单个只读映射，名称/类型 intern，
  全量验证逐模块释放 AST。模块实例可引用后定义模块，普通声明遵循词法作用域。
- Bundle 递归拆字段，Vector 保留外到内 shape，flip 决定叶子方向。
  位宽推导、Reset、Probe、Analog 和属性类型的待解析状态显式保留，
  原始字符串参数与带引号字符串区分，大整数参数不截断。
- CHIRRTL mport 数据继承 memory 的作用域，访问语句保留原条件嵌套，供 F06
  推导使能。共享 `scanInterfaces` 完整验证主体后返回接口；`readFirrtl`
  在验证后明确拒绝尚未实现的 lowering，不生成部分可执行设计。
- 回归覆盖嵌套 node 表达式、属性类型、enum、class/formal、参数、source info、
  缩进/字符串/注释、版本差异、错误恢复、引用/别名错误、接口 shape、
  名称碰撞和 source owner 生命周期。语法与 API 合约见
  [firrtl-parser.md](../../wolvrix/docs/ingest/firrtl-parser.md)。

实际验证通过项目 Makefile，日志在 `ptmp/firrtl-ingest/F03/`：

| Make 命令 | 结果 | 日志 |
| --- | --- | --- |
| `make test_firrtl_parser` | 定向 parser 回归通过；后续补充用例由最终全量回归覆盖 | `parser_and_xs_after_mport.log` |
| `make test_wolvrix` | 最终完整构建和 69/69 CTest 通过，含 parser 与公共 driver 回归 | `final_checks.log` |
| `make inspect_firrtl_inputs` | 本地 SimTop 所有 10,008 个模块及共享接口签名验证通过，退出码 0 | `final_checks.log` |
| `make freeze_firrtl_inputs` | 首次冻结输入及全模块统计；2,146 份生成 SV/头文件纳入内容清单 | `freeze_inputs.log` |
| `make test_firrtl_parser_inputs verify_firrtl_inputs test_wolvrix` | 4/4 输入校验回归、冻结清单复验和最终 69/69 CTest 通过，含新增宽值/换行/错误数量与嵌套边界回归 | `acceptance.log` |

本地输入为 `ptmp/xs/rtl/rtl/SimTop.fir`，FIRRTL 6.0.0、circuit `SimTop`，
大小 1,671,325,062 字节，SHA-256 为
`cc46aae1a379d9e62132b76b0702685ba67761c87815067f770b0743d7dc754a`。
共 10,008 个模块（含 521 个 extmodule）、164,537 个源端口、649,436 个
共享叶子端口，其中 121,756 个标记为仍需类型解析。全模块验证统计
8,297,452 条语句、45,897,965 个表达式、5,476,900 个 node；最大模块有
1,225,389 条语句。最终检查耗时 12.24 秒，峰值 RSS 4,694,468 KiB；
最大模块 AST 仍决定主要额外内存，未声称固定内存上限或仿真性能提升。
冻结后复验保留全部语法/接口计数，并在解析前后检查内容身份；验收证据位于
`ptmp/firrtl-ingest/F03/input-verify/`，逐文件 SV hash 清单为
`sv-inventory.json`。检查明确要求 `validation=all-module-bodies`，不能以
`--index-only` 结果通过验收；原冻结清单不会被 capture 自动覆盖。

命令带 `WOLF_ENV_SOURCED=1`，构建临时目录和 ccache 使用本阶段 `tmp/`、
`ccache/`；全量 CTest 沿用 Makefile 的 `ptmp/ctest_tmp/`、
`ptmp/ctest_ccache/`。生成的 FIRRTL、参考材料与日志留在 `ptmp/`。
类型/行为 lowering、混合链接、完整 node CSE 和 nonsink 利用仍属 F04–F09。

## F04：类型、组合语义和聚合 lowering

交付：

- 类型/位宽/Reset/flow 解析，以及目标原语、connect、when 和最后连接语义。
  将 FIRRTL 的定宽和符号规则明确映射到 GRH，不复用 SV 表达式定宽规则。
- Bundle 递归拆字段、Vector 保留 shape；实现字段/动态索引、整体连接、mux、
  相等、构造及位布局转换，处理 flip、零宽、extent=1 和名称碰撞。
- 每个源 node 及拆分叶子产生 schema v1 标注，引用 node 不复制定义；内部
  primitive op、结果边界、别名与常量可在导出报告中定位，第一次 simplify
  即执行 F02 的 node 作用域约束。
- 纯 FIRRTL 组合设计到普通 GRH，再通过既有 GrhSIM emitter 运行；形成早期
  端到端样例，避免直到整机阶段才发现前后端类型不兼容。

验证入口：新增 `make test_firrtl_comb`、`make test_firrtl_aggregate`、
`make test_firrtl_widths`；复用 `make test_array_create`、
`make test_transform_shape_mapping`、`make test_grhsim_cpu_st_cpp`。

退出条件：独立预期结果/参考解释器覆盖组合运算和聚合几何；node attrs 可
从输入追到优化前 GRH；数组访问没有变成逐槽译码；错误类型有准确诊断。

实施记录（2026-10-31）：已完成，wolvrix 实现提交为 `5be5cb9`，
分支为 `grh/firrtl-ingest`。逐项证据和阶段边界见
[F04-acceptance.md](F04-acceptance.md)，正式合约见
[firrtl-combinational.md](../../wolvrix/docs/ingest/firrtl-combinational.md)。

- 新增独立类型/位宽/Reset 推导和组合 lowering，连接先汇总再按条件与文本
  顺序生成最终驱动。Bundle 递归展平、Vector 保留 shape，动态访问直接使用
  多索引 kSliceArray；组合部分写用 O(rank) 偏移/mask 合并，未逐槽译码。
- 真实 node 的内部计算和每个物化叶子结果根生成 schema v1 attrs；node
  引用复用定义，首次 simplify 通过 F02 作用域隔离。FourState 初始图与
  invalid 策略均显式保留，零宽/空 Vector 不物化非法 GRH value。
- 三项 FIRRTL 回归、三份 GrhSIM 模型实际编译/运行及完整 72/72 CTest
  通过；复用 array/create verify 2/2、shape 3/3 和 CPU 生成回归通过。
  旧 CPU 批量编译中两个用例因验证目录被并行重建而失败，单独重跑通过；
  失败及重跑日志均保留，没有将首次批量命令记为成功。
- 冻结输入身份和香山 10,008 个 module body 再验证通过，输入门禁 4/4
  通过。新 fixture 放在 comb 子目录，原 F03 fixture/manifest 未修改。
- 证据目录为 `ptmp/firrtl-ingest/F04/`。寄存器、memory/effects、混合
  FIRRTL/SV 链接及 node 级 CSE/nonsink 消费继续按 F05–F09 推进。

## F05：时序状态与有序数组写

交付：

- reg/regreset、同步与异步复位、clock/reset 类型解析，生成既有状态/读写族。
- 条件、部分/整体和动态索引写先建立有序连接意图，再归一化为 writer，
  保留同目标优先级、复位屏障及采样旧值规则。
- 为目标初始化/invalid 语义提供显式配置；混合时不能悄悄改变 SV 逻辑域。
- RenameTable 小用例保留动态索引写，覆盖两端口同地址、不同地址、无写、
  复位和写数据读旧状态。不是把数组整体复制后逐元素提交作为最终实现。

验证入口：新增 `make test_firrtl_state`；复用现有
`make test_grh_register_write`、`make test_grh_to_grhsim`、
`make test_grhsim_cpu_st_cpp`。

退出条件：多周期独立记分板和等价 SV 对照通过；动态写顺序及 old-value
行为正确；保留 node 的计算不越过状态/事件边界。

实施记录（2026-10-31）：已完成。wolvrix 状态实现提交为 `f38084a`；
执行复制的 node 根保真修复单独提交为 `a77e6c6`，分支均为
`grh/firrtl-ingest`。逐项验收见 [F05-acceptance.md](F05-acceptance.md)，
正式合约见 [firrtl-state.md](../../wolvrix/docs/ingest/firrtl-state.md)。

- reg/regreset 映射到既有 kRegister 和 whole/indexed 读写端口；Bundle
  拆字段、Vector 保留 shape。每条 connect 生成有序 writer，保留整体/部分
  覆盖优先级；数据、索引、使能和同步 reset data 均观察旧状态。
- 同步/异步复位使用最终 whole-state writer 屏障，普通写带 !reset；
  异步状态的全部 writer 共用 clock/reset posedge 事件域。初始化与 invalid
  配置独立，初始 FourState 保留至既有显式投影；条件声明按 interleaving
  条件处理，不把硬件声明本身当作条件执行。
- 真实时序 node 覆盖 General/Output 双需求；合法执行 owner 间的复制
  使用 grhsim.nodeClone 保留 source key/roots，同 owner 或无标记重复仍拒绝。
  该补齐不代表 F08 完整审计或 F09 node-aware nonsink 已完成。
- RenameTable 和 priority 的多周期独立记分板对照普通 GRH、JSON 重载、
  simplify 及等价 SV；四份 state 模型实际编译运行，各重复 3 个初始化周期。
  RenameTable 保留 1 个数组状态和 2 个动态索引写端口，没有逐槽译码。
- SV 参考输出显式拼接数组槽作观察，规避既有 aggregate state forwarding
  无驱动问题；参考状态/动态写仍为数组，该限制和检查见正式合约。

实际验证全部通过项目 Makefile，日志在 `ptmp/firrtl-ingest/F05/`：

| Make 命令 | 结果 | 日志 |
| --- | --- | --- |
| `make test_firrtl_state test_firrtl_node_attributes test_firrtl_cse_scope` | 定向语义、属性、CSE 作用域通过；四份 state FIRRTL/SV 模型编译运行通过 | `state-final.log` |
| `make test_wolvrix test_firrtl_state test_firrtl_comb test_grh_register_write test_grh_to_grhsim` | 最终 73/73 CTest、四份 state 及三份组合模型、register-write 1/1、GRH→GrhSIM 3/3 全部通过 | `final-checks.log` |
| `make test_grhsim_cpu_st_cpp` | 生成 CTest 1/1 和 154 项模型用例编译运行通过 | `cpu_st_cpp.log` |
| `make run_grhsim_cpu_st_cpp GRHSIM_CPU_ST_CPP_JOBS=8` | 完整 CTest 重生成后，最终 154 项模型用例再次通过，退出码 0 | `cpu-final.log` |

命令带 `WOLF_ENV_SOURCED=1`；完整构建使用
`CMAKE_BUILD_PARALLEL_LEVEL=8`，TMPDIR/CCACHE_DIR 指向本阶段 tmp/ccache，
定向入口沿用各模块 Makefile 约定。生成与消费同一模型目录顺序执行，
产物沿用 `wolvrix/build/artifacts/`。F03 冻结输入及 manifest 未修改；
memory/effects、混合链接、完整 node CSE/nonsink 利用继续按 F06–F09 推进。

## F06：memory、效果及目标版本构造

交付：

- 实现标准 mem 和目标使用的 cmem/smem/mport，明确 clock/enable 推导、
  latency、mask、read-under-write、冲突及越界语义，复用数组状态和流水寄存器。
- printf/stop/assert 及所需 intrinsic 映射到现有效果机制，保留触发条件、
  参数采样、顺序与终止行为。初始化和随机化纳入输入身份。
- 按清单处理 layer、Probe/引用与 annotations。未知且影响功能/观察的构造
  明确失败；验证层启用配置可追溯，不做无条件删层或展开。
- 完成不含外部模块的目标 FIRRTL 模块运行；外部引用保留明确绑定请求，
  不通过 blackbox-guard 伪装成完整可执行设计。

验证入口：新增 `make test_firrtl_memory`、`make test_firrtl_effects`；
复用 `make test_transform_memory_read_retime`、`make test_grhsim_cpu_st_cpp`。

退出条件：memory 时序与 mask 记分板通过，effects 的次数/顺序可核验；F00
目标矩阵里除跨语言链接外的必要构造完成，并且没有静默语义降级。

实施记录（2026-10-31）：已完成。memory、效果与冻结目标模块运行及最终
全量复验通过。
逐项证据与执行支持边界见 [F06-acceptance.md](F06-acceptance.md)。
实现提交为 wolvrix `60ee737`，node provenance 修复为 `8f4a4a4`，均位于
`grh/firrtl-ingest`。

- 标准 mem 与 CHIRRTL cmem/smem/mport 使用统一的 Memory/MemoryPort
  描述；Bundle 拆字段，Vector 保留 shape，depth 是最外层。复用普通
  kRegister、数组读写端口及流水状态，不引入后端专用 memory opcode。
- 延迟/read-under-write、独立时钟重叠、同钟别名、并发写冲突、mask、
  越界、depth-one 零宽地址与 Bundle rdwr 统一模式均有独立记分板。
  FourState 回归直接观察 X，TwoState 投影仍由既有转换显式选择。
- printf/stop/assert/assume/cover 和目标 ifelsefatal 使用既有 SystemTask；
  compiled driver 对照旧值采样、效果顺序/次数、精确输出及终止状态。
- layer 显式选择并记录 metadata；Probe 使用无条件且唯一完整的 define，
  忽略 invalidate 并拒绝聚合 connect 绕过。接口保留待解析的 Probe ABI。
- 五类冻结 annotation 使用严格 schema，DontTouch 保留符号，inline SV
  payload 保留到 F07；未知可观察语义失败，实例具名请求外部实现/模块绑定。
- 原始 SimTop 文件中的 Queue2、138-bit SRAM 和 JTAG 三个无外部依赖
  模块通过完整后端运行；JTAG 启用 Verification.Assert 并校验 fatal。
- node verifier 允许死 node 留在共享字面量上的 provenance；非字面量
  无 root 的活计算仍拒绝，直接回归及 JSON 往返覆盖这一区别。

新增工作流入口为 `make test_firrtl_memory`、`make test_firrtl_effects` 和
`make test_firrtl_target`；证据日志位于 `ptmp/firrtl-ingest/F06/`。
定向最终命令 `make test_firrtl_memory test_firrtl_effects
test_firrtl_node_attributes test_firrtl_target` 退出 0，日志为
`final-boundaries-target.log`；全量最终命令 `make test_wolvrix
test_transform_memory_read_retime run_grhsim_cpu_st_cpp test_firrtl_memory
test_firrtl_effects test_firrtl_parser_inputs verify_firrtl_inputs` 退出 0，
日志为 `final-acceptance.log`。结果为 75/75 CTest、154 个 CPU 模型、
37 个 memory 模型、8 个 effects 模型、输入校验 4/4 和冻结身份复验通过。
F07 混合链接、F08 完整 node CSE 和 F09 node-aware nonsink 仍待实施。

## F07：混合 SV/FIRRTL 读取与链接

交付：

- 完成 `read_sources` 和 `read_firrtl` 及 Python native 注册，旧 `read_sv`
  继续有效；请求一次性覆盖两种语言并事务式发布。
- 实现 FIRRTL extmodule → SV 的 defname/类型化参数 specialization，和
  SV → FIRRTL 的接口签名声明，支持交替实例化依赖的去重与递归检测。
- 两类源端口通过显式 ABI adapter 对接；测试扁平端口、聚合端口、flip、
  嵌套数组、signedness、位布局、宏/include 和参数派生端口宽度。
- 收集目标使用的 blackbox 路径/资源/内嵌 SV annotation，将内容作为真实
  SV 源交给 slang，并保留依赖身份；签名声明不进入普通空模块 lowering。
- 提供非标准外部绑定清单及具名诊断；DPI/host 实现走真实效果调用机制。
  原型签名声明最后必须全部被绑定或作为错误报告。
- 完成多 source owner 生命周期、依赖清单、session 失败不变性和重复读取。

验证入口：新增 `make test_ingest_mixed`、`make test_ingest_python`；
复用 `make py_install`、`make test_grhsim_flow`、`make test_wolvrix`。

退出条件：FIRRTL top → SV → FIRRTL 和 SV top → FIRRTL → SV 均可仿真；
两组参数生成不同正确实现，未解析/重复模块和端口错误不发布半成品 design。
这里不能仅以“两个 parser 都执行过”作为混合支持证据。

## F08：GSIM 模式完整 node CSE 和属性保真

交付：

- 审计 XMR、mux-tree-fold、write normalize、memory retime、hier-flatten、
  普通 simplify/CSE/DCE、grh-to-grhsim、全局仿真优化、phase/sink split 的
  重写入口，传播根映射和 node 作用域；禁用分图前的跨 node 内部 op 共享。
- 新增 `grhsim-node-cse`，从有效根和成员构造完整表达式结构视图，先 hash
  再精确比较功能、完整类型及依赖。等价类分析与实际物理合并分开，上游
  等价但未合并时，下游仍可利用其等价事实。
- 首版合并门槛固定为等价组规模 ≥5、结果位宽 >256 或某成员后继数 >1；
  统计命中和保留原因。数组/状态/效果及无法证明完整的区域不进入整体合并。
- 将 pass 放在 converted 阶段的局部优化之后、phase/sink split 之前；
  新增 `firrtl-node-cse=off|gsim`，off 仍保持 F02 作用域，只关闭整体合并。
- 明确整体合并后的多源身份、根指向输入、多结果、packing、alias 和 DCE
  规则；origins 不授予跨 node 融合权限。优化策略和执行配置随 checkpoint
  保存，旧的全局 primitive CSE 图不能补标签后冒充新策略输入。
- 建立每 checkpoint 的 source node 可用性报告，区分合法简化与信息丢失。
  store/load、clone、rename/ID 重排后可以重建同样的候选区域。
- 对大模型检查 attrs 的存储/分配成本：intern 可复用身份，持久化仍是标准
  attrs；禁止每个 pass 复制完整上游来源闭包。统计 key 重复量及报告大小。

验证入口：新增 `make test_firrtl_node_pipeline`、`make test_grhsim_node_cse`、
`make inspect_firrtl_node_retention`；复用现有 `make test_grhsim_transforms`、
`make test_grhsim_flow`、`make test_grhsim_readable_store`。

退出条件：真实 FIRRTL 的完整 node 和作用域可追溯；4/5 个等价 node、
256/257 bit、1/2 个不同后继的门槛边界通过，等价未合并的下游判等正确。
公共内部子树不会提前被抽取，hash 碰撞和功能差异不误合并；同模块两实例
的不同输入不误判。JSON 往返、幂等与配置检查通过，SV 原有语义回归通过。

## F09：利用 node 的 nonsink 分图

交付：

- 新增独立的 `firrtl-nodes=off|prefer|auto` 配置，原型默认 off；配置进入
  Make/Python/FlowOptions、checkpoint 配置版本和 generation identity。
  它只控制分图，与 F08 的 node CSE 开关独立。
- 读取整体 CSE 后的 node DAG，以完整计算单元形成初始工作节点；未达到
  合并门槛的等价 node 保持独立。显式字段/位拆分保留可验证片段边界；
  无注解 SV 区域走既有逆向吸收。
- 在候选 node DAG 上做 coarsen/segment，并让发布、激活与额外重算共同参与
  决策。真实 op 工作量仍参与预算，超预算完整 node 单独成组并报告，
  不靠任意切开表达式填充预算；后续拆分必须是有根映射的显式语义变换。
- 与 bounded clone、叶内 simplify、writer prerequisite 和 emitter 局部值
  相协调；归属确定后 op 级 CSE 限于同一执行 leaf，不跨 owner 抽取内部
  子表达式，不形成独立 node 执行器。
- 报告实际利用的 node 范围、边界持久值、计算复制、超节点规模和拒绝原因；
  使用 diagnostics 计数观察活动和发布，正式计时关闭计数。

验证入口：扩展现有 `make test_grhsim_virtual_partitions`、
`make test_grhsim_transforms`；新增 `make test_grhsim_firrtl_nodes`、
`make inspect_firrtl_partitions`。

退出条件：优化后的完整 node 实际作为初始分组单位；分图 off/prefer 在
相同 node CSE 配置下结果一致，owner 唯一、quotient 无环、激活完整。
验证相同内部 op 在不同 owner 保持独立、在同一 leaf 可以共享，并覆盖
超预算 node、合法语义拆分、少发布及额外重算，不能只测节点变少。

## F10：香山集成和差分正确性

交付：

- 将混合读取接入 `scripts/wolvrix_xs_grhsim.py` 和共享 flow，输入清单只包含
  FIRRTL 及真正需要的 SV 辅助实现，避免重新读取重复的 FIRRTL 生成 SV。
- 新增独立香山 Make 入口及输出目录，复用现有 harness/NEMU/workload，
  纯 SV 入口继续可用。构建 FIRRTL 仿真器本身不依赖生成 SV。
- 新增 FIRRTL-only 输入生成/检查入口，只需 Chisel 输出和必要 SV 资源；
  审计 Make 传递依赖，不沿用强制检查 `XS_SIM_TOP_V` 或
  `check_xs_aggregate_rtl` 的 SV 路线，避免间接调用 firtool。
- 先做 RenameTable、ROB 和 memory 代表模块的两路线比较，再做整机初始化、
  短前缀和 CoreMark100k，逐步启用 node prefer 模式。
- 核对 DPI、assert、初始化和观察配置，记录效果调用差异；新前端不自动
  继承旧迁移过程中针对特定版本批准的例外。
- 验证实际 FIRRTL/SV 跨语言调用都完成绑定，node 信息在 flatten 后仍可用。

验证入口：新增 `make xs_firrtl_inputs`、`make xs_firrtl_grhsim_emu`、
`make run_xs_firrtl_grhsim_emu`；复用现有 `make run_xs_ref_emu`、
`make run_xs_grhsim_emu` 和必要的 XS 组件 Make target。

退出条件：相同设计配置下混合路线可完成无 CIRCT 的读取至 emu 构建，固定
100k/NEMU 及必要模块差分通过；所有未解释行为差异解决后再进入性能结论。

## F11：性能消融、默认策略和正式交付

交付：

- 按 architecture §10 固定 A（SV）、B（FIRRTL/mixed + GSIM node CSE +
  原分图）、C（同 B + node prefer）、D（同 C + 整体 node CSE off）。
  B/C 从同一分图前 checkpoint 分叉；C/D 从完整 node CSE 前分叉，均保留
  node 作用域，区分物理共享策略与分图策略的收益。
- 记录完整构建和各阶段 wall/RSS、属性成本、图规模、超节点/边界、生成代码
  与 text 大小，区分输入路线、完整 node CSE 和 node 分图带来的变化。
  A/B 含输入及分图前优化差异，不能全算成 FIRRTL 解析收益。
- 在正确性通过后，固定 CPU、单线程、无 PGO、seed、CoreMark100k 和 NEMU，
  A/B/C/D 各测三次，轮换顺序。按耗时总和报告分图收益 B/C、整体 node
  CSE 收益 D/C 和总收益 A/C，保存完整身份。
- 诊断结果用于解释边界与重算变化，正式计时不启用波形、profile 或额外计数。
  对重复测量噪声、资源回退和不同模块/活动的适用范围据实记录。
- 根据可重复的吞吐与构建结果决定 auto 默认，不能以 node 数下降替代运行
  提升；必要时保留 opt-in，并具体说明仍需改进的成本。
- 同步 `wolvrix/docs/ingest/`、`wolvrix/docs/transform/`、Python API、Make
  用法和本目录；保留源码、回归及可重放 manifest，不提交生成模型。

验证入口：新增 `make benchmark_xs_firrtl_ingest`、
`make test_firrtl_ingest` 汇总前述必要检查；最终复用 `make test_wolvrix`、
`make test_grhsim_flow`、`make test_grhsim_cpu_st_cpp` 和相关 HDLBits/XS 检查。

退出条件：原始需求的目录组织、无 CIRCT 读取、混合语言、聚合类型、属性
全流程传递、nonsink 实际利用及正确性全部有证据。性能结果可重放，并能
明确区分输入路线、完整 node CSE 和 node 分图收益；未测或未改善的项不能
写成已实现加速。

## 完成阶段时的记录模板

```text
阶段：Fxx
状态：进行中 / 已完成 / 阻塞（具体原因）
源码提交：主仓库 / wolvrix
输入与基线 manifest：
实际 Make 命令：
结果与退出条件：
日志及产物：ptmp/firrtl-ingest/Fxx/...
node 信息变化与正确性：
资源或性能变化（如已测）：
尚未完成的事项及下一阶段：
```
