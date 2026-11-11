# FIRRTL ingest 分阶段实施

阶段总览见 [index.md](index.md)，接口、属性及语义合约见
[architecture.md](architecture.md)。以下 Make target 以“现有”或“待新增”标明；
待新增入口必须先写入项目 Makefile，之后才能运行对应构建、测试或脚本。
所有临时工作目录使用 `ptmp/firrtl-ingest/Fxx/`。
2026-10-31 最新决定将 node 定位为不阻碍 simplify 的 op 级软提示。
F01–F08 的实施/验收记录保留历史含义；其中 source-node 优化屏障及
严格根保留合约已由 F09 修正；实际实现见本页 F09 记录与验收文档。

## 推进顺序与共同退出条件

主线顺序为 F00 → F01 → F02 → F03 → F04 → F05 → F06 → F07 → F08 →
F09 → F10 → F12 → F13 → F14 → F15 → F16 → F11。属性与 node 作用域检查从 F02 开始伴随实现，F08 实现
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

历史阶段合约：下述 source-node CSE/inline 隔离已实现；按最新决定在
F09.0 撤除，属性改为不阻碍普通 simplify 的软关联。实施记录保留原义。

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

### 实施记录（2026-10-31）

实现和完整证据见 [F07-acceptance.md](F07-acceptance.md)；公开合约见
[mixed.md](../../wolvrix/docs/ingest/mixed.md)。本阶段已落实：

- 请求级模块注册表与依赖遍历，FIRRTL实例直接落GRH，SV保持slang elaboration；
  接口声明不作为空行为实现，参数wrapper在导入真实实现后删除。
- 两向交替层次、跨FIRRTL源的显式绑定、类型化参数及等价specialization去重；
  端口名/方向/位宽/逻辑域/shape检查，等宽布局和符号差异采用显式view。
- 路径/资源/内嵌SV annotation按可达extmodule收集；所有schema仍验证，
  依赖保留内容身份，未使用payload保留pending，读入失败不发布design。
- 多owner诊断使用自有坐标，clone保留owner；层次展开为node身份逐级追加
  instance path。F08完整node CSE与F09 nonsink消费没有提前纳入支持声明。
- 11个编译混合模型及负例通过；最新Python包8/8、全量CTest76/76、
  checkpoint流程2/2和生成模型通过。原始香山ClockGate混合路径、Queue、
  SRAM和JTAG四个目标以及冻结输入身份通过；CPU154模型最终顺序回归通过。

工作流和日志位于 `ptmp/firrtl-ingest/F07/`，验证均通过Makefile入口。
Wolvrix 实现提交：`ad4d9a2`（feat(ingest): link mixed FIRRTL and SystemVerilog sources）。

## F08：GSIM 模式完整 node CSE 和属性保真

历史阶段合约：下述强隔离、根保留及 GSIM 门槛已实现并验收；F09.0
修订其默认行为和配置，不能据此继续限制普通 primitive CSE/重写。

交付：

- 审计 XMR、mux-tree-fold、write normalize、memory retime、hier-flatten、
  普通 simplify/CSE/DCE、grh-to-grhsim、全局仿真优化、phase/sink split 的
  重写入口，传播根映射和 node 作用域；禁用分图前的跨 node 内部 op 共享。
  再精确比较功能、完整类型及依赖。等价类分析与实际物理合并分开，上游
  等价但未合并时，下游仍可利用其等价事实。
- 首版合并门槛固定为等价组规模 ≥5、结果位宽 >256 或某成员后继数 >1；
  统计命中和保留原因。数组/状态/效果及无法证明完整的区域不进入整体合并。
- 将 pass 放在 converted 阶段的局部优化之后、phase/sink split 之前；
- 明确整体合并后的多源身份、根指向输入、多结果、packing、alias 和 DCE
  规则；origins 不授予跨 node 融合权限。优化策略和执行配置随 checkpoint
  保存，旧的全局 primitive CSE 图不能补标签后冒充新策略输入。
- 建立每 checkpoint 的 source node 可用性报告，区分合法简化与信息丢失。
  store/load、clone、rename/ID 重排后可以重建同样的候选区域。
- 对大模型检查 attrs 的存储/分配成本：intern 可复用身份，持久化仍是标准
  attrs；禁止每个 pass 复制完整上游来源闭包。统计 key 重复量及报告大小。

`make inspect_firrtl_node_retention`；复用现有 `make test_grhsim_transforms`、
`make test_grhsim_flow`、`make test_grhsim_readable_store`。

退出条件：真实 FIRRTL 的完整 node 和作用域可追溯；4/5 个等价 node、
256/257 bit、1/2 个不同后继的门槛边界通过，等价未合并的下游判等正确。
公共内部子树不会提前被抽取，hash 碰撞和功能差异不误合并；同模块两实例
的不同输入不误判。JSON 往返、幂等与配置检查通过，SV 原有语义回归通过。

### F08 实施记录（2026-10-31）

Wolvrix 实现提交：`5f31043`。

已完成完整node signature/hash精确判等、独立等价分析/门槛合并、多源根/成员
传播和 source-node policy/inventory/retention。普通生产重写及全局仿真优化
按源作用域保守保留；XMR和ROM/RAM retime补齐结果根/output重绑专项。
converted局部优化后执行，off/gsim配置、revision和generation identity随
checkpoint保存；所有stage恢复、旧policy/改配置拒绝及幂等通过。

inspect_firrtl_node_retention` 通过，完整 CTest 78/78；组合/时序/memory/
effects/11个混合编译模型、8个选定CPU模型、Python 3+8+3、HDLBits001
普通SV/GrhSIM均通过。RenameTable自包含层次2230源nodes，gsim合并8个，
所有checkpoint missing=0；JSON节点信息增加约1.46MB，报告2504bytes。
该测量不代表整机或仿真提速。详细审计、命令、成本和边界见
[F08-acceptance.md](F08-acceptance.md)，日志位于 `ptmp/firrtl-ingest/F08/`。
该历史节点尚未实施 F09；当前软提示实现见下一阶段。

## F09：统一 node 构建与 nonsink 分图

状态：2026-10-31 已完成 F09.0–F09.5。详细规则及例子见
[F09-plan.md](F09-plan.md)，实际验收见 [F09-acceptance.md](F09-acceptance.md)。
已撤除 F02/F08 的 node 优化屏障，以 op 软关联参考统一 nonsink 分图。
当前 F09.6 设计：有 FIRRTL 提示按提示、无提示按 MFFC 形成统一 node；
supernode 在 Node DAG 上按 node 数分组，不感知内部 op 数/work。它取代
前次“单 node 超 work 预算豁免”的方案。已实现并验收，见
[F09.6-acceptance.md](F09.6-acceptance.md)。以下 F09.0–F09.5 表及记录是旧 v2 的历史行为，
不用于验收新的两层分图。

node 表示 op 上可选、多对多的来源关联。普通 simplify 不因该关联限制
CSE、inline、重关联、折叠、mux/bit packing/写归一化和 DCE；维护不了的
提示可以降级/清除，不能靠 kAssign 载体或保活根阻止优化。新流程以优化后
真实 op 图为准，按提示/MFFC 形成统一 node，再按 node 数组合完整 node
为 supernode。共享和结构冲突在 node 构建层解决，不交给上层按 op 切片。

F09.0–F09.5 的历史交付：

| 子步骤 | 交付 | 退出条件 |
| --- | --- | --- |
| F09.0 撤除提示屏障 | 修订 schema/policy、根/retention、多成员合并；审计普通和 GrhSIM 的 CSE/inline/annotated 短路，明确旧 node CSE 配置迁移 | 关闭独立提示消费者时，有/无标注的普通优化图一致；无额外 kAssign，无 node 保活/源作用域限制 |
| F09.1 关联索引 | 从当前 ops 建立允许相交、不完整和无根的有界提示集合 | 共享 op/phase copies/不同实例/Vector 正确，不按相交关联传递 union；正常提示消失不报语义错误 |
| F09.2 软提示分图 | 同一 op 引擎以提示生成候选及确定性 tie-break，固定旧 cost | 同 node 拆分、跨 node/语言合并和忽略提示均通过；真实预算相同，off 复现基线 |
| F09.3 独立成本改进 | 两条路线共用 bytes/重算代理，必要时试验独立有界亲和度 | 提示/成本/亲和度分别消融，不凭来源猜活动率，发布与额外求值可计数 |
| F09.4 owner 与 clone | 最终 leaf、合法融合、bounded clone、叶内 simplify 和调度依赖重建 | source key 不新增屏障、不授权跨实际 owner 共享；effects、旧值、writer prerequisite 和预算一致 |
| F09.5 配置与验收 | Make/Python、版本/恢复迁移、报告与真实代表模块 | 0%/部分/完整提示覆盖和 SV/mixed 回归通过；采用/忽略/降级与元数据成本可审计 |

已实现的 firrtl-nodes=off|prefer|auto 只控制分图是否参考提示，原型默认 off。
它不改变普通 simplify，也不删除来源或关闭既有语义检查。现有
不完整候选跳过。GSIM 门槛不再控制 primitive CSE；旧 schema/policy 拒绝恢复。

验证入口：复用现有 make test_grhsim_virtual_partitions、
make test_grhsim_transforms、make test_grhsim_flow、node pipeline 和
CPU/mixed 检查；已新增 make test_grhsim_firrtl_nodes、
make inspect_firrtl_partitions。全部入口通过项目 Makefile 运行。

历史退出条件（F09.0–F09.5）：首先在测试中移除一份图的 node 非功能信息，
关闭独立提示消费者，验证普通优化结构一致且行为正确；然后固定同一份
已 simplify checkpoint 的 attrs、cost、clone、leaf 和 trace，只切
分图 off/prefer。覆盖跨 node 公共子表达式共享、重关联、根消失且无载体、
DCE、重叠/非凸提示、超预算 node 切分、交错语言、Vector、phase/sink 和
效果。每 op 唯一 owner、quotient 无环、真实激活/发布正确；不以源 node
完整率或节点变少作为退出标准。SV/FIRRTL 前端性能另行比较。

### F09 实施记录（2026-10-31）

F09.0–F09.5 已完成；详细矩阵、命令、报告口径及限制见
[F09-acceptance.md](F09-acceptance.md)，日志位于 `ptmp/firrtl-ingest/F09/`。
Wolvrix 实现提交：`7e51d14`。

- node schema 2 / soft-node-v2，普通 CSE 不带源作用域；根可丢失、不加
  carrier、不保活。普通及完整生产流水的有/无标注规范化结构对照通过。
- 现存 op 的多对多 members 进入有界索引；off/prefer/auto 共用 op DAG，
  prefer 只排等权 coarsening/同成本 segment，非凸/重叠/无根/超预算可拆。
- legacy/bytes、leaf fusion、单轮 bounded clone 独立开关；clone 包含所有
  支持常量的 work，要求 varying input 已到达目的执行 owner。实际 owner、
  phase/effects、writer prerequisite 和 SinkSchedule 约束保持。
- Python/Make/XS/reemit 接入选项、v2 恢复检查和 snapshot 报告。旧 source-node
  checkpoint 要求 re-ingest，旧 nonsink 八字段配置要求从 split 重启。
- 全量 79/79、Python flow 4 项及 10 份 SV restart 编译模型、FIRRTL 组合/
  状态/memory/effects/mixed 编译执行、冻结目标 Queue2/SRAM/JTAG/ClockGate
  和 HDLBits001 通过。新增非凸提示、幂等报告重放、正向 clone 回归通过。
- RenameTable 六组均使用完全相同 split checkpoint，nonsink 639 ops，
  提示覆盖 270 ops。prefer/legacy 与 off/legacy 都为 13 SN，提示被切分
  数 420→416，但 consumer bytes 5044→5071。bytes 为 109 SN；Queue2
  compute 调用 356→551。未宣称加速，默认维持 off/legacy/unfused。

### F09.6 当前实施记录（已完成）

2026-10-31 已完成；wolvrix 提交 007c097。完整 CTest 79/79、Python
4+16+1、10 个阶段恢复编译模型、FIRRTL/mixed 编译执行与 HDLBits001
均通过。RenameTable 在相同 split checkpoint 下为 off 359 nodes /
prefer 382 nodes，两者均 4 SN；Queue2 默认容量 compute 均为 356。
完整命令、日志与限制见 [F09.6-acceptance.md](F09.6-acceptance.md)。

| 步骤 | 交付 | 退出条件 |
| --- | --- | --- |
| F09.6a | 提示区域构建 node，剩余区域按 MFFC；解决共享与真实语义冲突 | 实际 op 归属唯一、node 边界不受 op 数/work 限制，两前端同一合约 |
| F09.6b | 统一 Node DAG 上按 node 数分组，max-supernode-nodes | 每 node 权重为 1；大小 node 等价计数，K/K+1 容量正确 |
| F09.6c | 新配置/恢复身份，移除旧 work-cap/fusion 耦合；依赖与 SinkSchedule | 旧阈值不静默换单位，新恢复/调度及行为正确 |
| F09.6d | Make/Python/mixed、透明性、RenameTable/Queue2 及可选 clone 验证 | 两层统计清楚、普通 simplify 不回退，实际性能如实记录 |

F09 是分图机制和代表模块验证，不替代 F00/F10 的整机依赖/差分、F12 的
ingest 性能专项或 F11
的正式吞吐、compile wall/RSS 消融。当前默认 auto/legacy/128 nodes，
直接落实有提示按提示、无提示按 MFFC；不据此宣称性能收益。

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

实施中（2026-11-01）：独立 mixed/Chisel-only、harness 快照及 build-only
入口已接入；全量 native 79/79 和相关生成模型回归通过。full16 在
1332.641 秒完成冻结整机输入的 mixed ingest，后在 flatten 长时间未返回，
验证批量 inventory 修复后主动中止并启动 full17。full17 读取/配置及此前
共享 pass 通过，flatten 时因持续内存增长、swap 近耗尽主动中止，退出 130；
未观察到 OOM kill。源图存储修复通过定向、79/79 及 mixed 编译执行回归，
已安装并在 full18 重试；该次已完成 mixed ingest、flatten 及 flatten 后
52 个假环的全部修复，GRH 验证通过，随后因 checkpoint 保存时的内存增长
主动中止，退出 130；正在修复 JSON 文件存读的内存峰值，尚未构建/执行整机 emu。
JSON 文件存读修复后，全量 80/80、Session/工作流及各阶段 checkpoint 重载的
生成模型编译执行通过；已安装并在独立 full19 重试，整机退出条件仍待完成。
full19 mixed ingest 在 1289.608 秒完成，423 个候选环全部为假环且修复；
严格配置 44/44、输入/harness/flow 一致性 50/50 和 143 项 provider 源码
检查通过，当前进入共享 GRH 优化，最终模型/emu/两路线运行仍待验证。
随后整机 flatten 在 2727.420 秒完成，flatten 后 52 个假环全部修复，
GRH 验证通过；pre-simplify checkpoint 在 159.493 秒成功发布，共
56,437,233,305 bytes。随后按用户新要求立即终止超出 20 分钟的生成进程，
原 session 退出 130，停止位置为 simplify；尚无最终模型、emu 或运行结果。
后续 FIRRTL→C++ 总生成时限为 20 分钟，超时强制杀死；不通过阶段恢复
重置总计时，也不原样重跑仅 ingest 就超过上限的配置。
随后独立的 full20 连续实测中，mixed ingest 为 896.914 秒，xmr-resolve
为 34.554 秒，第一轮 mux-tree-fold 为 191.367 秒，
register-write-normalize 为 50.230 秒；第二轮 mux-tree-fold 在硬超时边界
被 SIGKILL，Make 返回 137。没有发布 flat/final GRH、整机 C++、emu 或
运行产物。默认两轮 mux 顺序保持不变，F10 继续实施中。
后续显式 bringup 的 full26、full27、full28 也均在完整 producer 的
20 分钟硬截止处被 SIGKILL，停止位置为 hier-flatten。full28 的 mixed
ingest 为 895.472 秒；仍无整机 C++/emu/运行产物。随后修正 dense map
共享端口的首次映射语义，并减少静态 bounds scaffold、未使用 wire mask、
不必要的 flatten 名称映射及重复节点 key qualification；验证和下一轮
整机结果见 F10-plan，未将这些改动视为整机完成证据。
full29 mixed ingest 已降为 588.498 秒，Rob lowering 操作数降到 5,830,973，
仍在 flatten 触发同一个 20 分钟 SIGKILL。随后先验证显式关闭可选 node
注解的功能 bringup：81/81、shared flow、on/off 各 4608 次实际 C++ scoreboard
及 56 项工作流检查通过。full30 的 mixed ingest、flatten、comb-loop-elim、
flat store 和转换分别为 388057、218300、37757、97076、38041 ms；
完成 7 轮仍均 `changed=1`，七轮合计 381786 ms，该 pass 未完成，
完整 producer 在 2026-11-01 07:04:29 UTC 到达 20 分钟硬截止并被
SIGKILL，Make 报 Error 137。无整机 C++、emu 或整机运行结果，F10 未跑通；
详细阶段计时及停止证据见 `full30-stop-reason.txt` 和 F10-plan。
分图后 simplify 和 clone，保留转换验证、拆分、分图/SinkSchedule 和 emit；
emit 后额外 JSON roundtrip 关闭。shared flow 5 项和 workflow 56 项通过；
backend optimized/bringup × annotations on/off 四组均实际编译执行，
每组 4608 次独立 scoreboard，四个输出 trace 逐字节相同。四组共同使用
GRH 七阶段 bringup，不能称作默认 full/prefer 对照通过。
full31 于 2026-11-01 07:06:55 UTC 从原始冻结 FIRRTL 在新目录开始，
在约 07:26:56 UTC 达到完整 producer 的 20 分钟 SIGKILL 硬截止；
输入、full27 harness、源码及加载库冻结已独立核对。两个拆分分别完成于
151669 和 147814 ms，在 nonsink 分区终止，Make 报 Error 137；仍无整机
C++、emu 或运行结果。后续显式省略非必要自动 JSON/text 导出，并仅合并
输入完全相同的重复分区 DAG 检查；必要验证和功能语义保留。不续跑
checkpoint 或用阶段恢复重置总预算；最终 full/prefer 与正式性能对照继续未完成。
随后 full32 关闭自动 flat/final JSON、整图文本和 source comments，保留
readable names/frames、identity 和所有必要验证；81/81 native、shared flow
5 项、workflow 57 项及四组 rename 模型各 4608 次执行检查通过后，从同一
冻结 FIRRTL/full27 harness 于 07:33:11 UTC 完整重跑。mixed ingest
389656 ms、flatten 251875 ms、comb-loop-elim 37792 ms、memory-init-check
7373 ms、转换 39590 ms，两个拆分分别为 149841 和 108937 ms；52 个
flatten 假环全部修复，无真环。nonsink 分区运行约 205 秒以上仍未完成，
约 07:53:12 UTC 被完整 producer 的 20 分钟 SIGKILL 终止；内部 Error 137，
外层于 07:53:14 UTC 返回 2。本轮没有自动 flat/final/text 输出，也没有
整机 C++、emu 或运行结果。完整计时见 F10-plan 和 `full32-stop-reason.txt`。
full33 只在显式 bringup 的 comb-loop 后、memory-init 前增加单次既有
`dead-code-elim`，保持声明锚点和必要 guard，不启用全 simplify，不改变
默认 full，无原生代码改动或新安装。shared flow 5 项、workflow 57 项及
四组状态模型各 4608 次实际执行检查已通过，输出 trace 一致；随后于
07:54:34 UTC 从原始冻结 FIRRTL/full27 harness 在新目录启动单次 20 分钟
完整生成，硬截止约 08:14:35 UTC。其余 flags 与 full32 相同，启动前
已冻结生产源码/库。实际 mixed ingest 389466 ms、flatten 224039 ms、
comb-loop-elim 37602 ms、raw DCE 126359 ms、memory-init-check 24460 ms、
转换 37413 ms，两个拆分分别为 134398 和 100509 ms；转换计数为
401484 operations、169336 states，并非全图 op 数。52 个 flatten 假环
全部修复。nonsink 分区仍未完成即被单次 20 分钟 SIGKILL 终止，内部
Error 137，外层于 08:14:36 UTC 返回 2；无自动 flat/final/text、整机
C++、emu 或运行结果。完整计时和证据见 `full33-stop-reason.txt`。
raw DCE 未改善总进度，bringup 撤回为七阶段。full34 的 shared flow 5 项、
workflow 57 项及 backend default/skip/one-round × annotations on/off 六组
状态模型编译执行通过，各 4608 次检查，五次 trace 比较全部一致；六组均
使用 raw GRH 七阶段 bringup，不替代默认 full/prefer 验收。原生库未改变。
full34 于 08:16:37 UTC 从原始冻结 FIRRTL/full27 harness 在新目录完整
recover/phase/clone 保持关闭，其余 flags 同 full33；硬截止约 08:36:38 UTC。
本轮实际 mixed ingest 385066 ms、flatten 217892 ms、comb-loop-elim
37667 ms、memory-init-check 18687 ms、转换 48030 ms；单轮 simplify 总计
233906 ms（round 213082 ms、fold/share 181695 ms，`changed=1` 按限制
尚未收敛）。两个拆分为 48482 和 36201 ms，nonsink 分区完成 108280 ms，
随后 sink 分区未完成即到达 20 分钟 SIGKILL；内部 Error 137，外层
08:36:39 UTC 返回 2。52 个 flatten 假环全部修复，无真环。无自动
flat/final/text、整机 C++、emu 或运行结果；完整记录见 `full34-stop-reason.txt`。
full35 只切现有 bytes 成本模型和 `readable_names=False`，沿用 raw GRH
七阶段、converted 单轮 simplify，其它 flags 同 full34，不新增原生优化。
readable frames 保持 True，生产原生实现/库均未改变。shared flow 5 项、
workflow 57 项，以及 default/skip/one-round/one-round-bytes × annotations
on/off 八组实际编译状态模型已通过，各 4608 次检查、七次 trace 比较一致；
bytes/short-names CLI 无自动 checkpoint 也完成编译执行 256 个输入值。
这些组件结果不构成默认 full/prefer 或整机通过。full35 外层于
08:39:21 UTC 启动，在用户拒绝缩减优化后于 08:57:33 UTC 主动 SIGINT
中断，退出 130，停于 sink 分区；不是超时。该路线已撤回，后续保留
完整默认 pass、simplify 轮次、packing/masked-OR/phase/clone 和校验，
只优化实现。仍从原始 FIRRTL 完整开始，共用一个 20 分钟 SIGKILL
截止，不恢复 checkpoint 或分段重置预算，F10 仍未跑通。
完整默认配置的 full36 于 09:43:49–10:03:49 UTC 按时 SIGKILL，退出
137；flatten 396.894 秒，已完成阶段合计 1171.053 秒，停在 grh.verify，
尚未进入 simplify 或 emit。实现优化已有严格 fixture A/B 和 native/编译
执行回归，但不构成整机完成，详见
[pass-optimization-20261101.md](pass-optimization-20261101.md)。
代表模块差分、原始 SV 的独立 100k/NEMU 及真实
LoadUnit lowering 的机器码成本证据见 [F10-plan.md](F10-plan.md)、
[F10-components.md](F10-components.md) 和 [F10-replacer.md](F10-replacer.md)。
这些结果不替代 native 整机退出条件，F10 保持实施中。

## F12：FIRRTL ingest 性能专项

2026-11-02 用户决定：以保留完整语义的 ingest 优化初版收尾，检查明显的
重复工作后移除临时插桩并提交。20 分钟整机目标不再作为本次初版提交门槛，
下文阶段实验记录保留历史上下文；收尾版 ingest 293.761 s，完整图 hash/诊断对照与 Make 门禁通过，
最终收尾证据见专项计划。


F12 先于 F11 执行，专门修复 FIRRTL/mixed ingest 的输入成本。当前完整路线
约 514–517 秒，纯 SV 对照约 45–49 秒；两者差异必须拆成 parser、类型和
语义 lowering、GRH 构建以及 mixed link，不能把整段时间笼统归因于 SV。

计划与验收详见 [F12-ingest-performance-plan.md](F12-ingest-performance-plan.md)。
该专项固定原始 FIRRTL、辅助 SV、harness 和库身份，建立按阶段和 module 的
低开销 profile，先解释至少 95% 的 ingest wall time，再逐项优化解析/索引、
lowering/GRH 构建和 mixed link。所有优化必须保持完整语义、annotations、
诊断、确定性顺序、roundtrip 和现有回归；不允许关闭 pass、减少 simplify、
恢复 checkpoint 或把阶段测量当作整机通过。

已实施 F12.0/F12.1 的第一版：`WOLVRIX_FIRRTL_INGEST_PROFILE=1` 输出
index/validate/parse、接口推导、lowering、事务和 top-20 module 计时；
`make benchmark_xs_firrtl_ingest` 保存固定 manifest、RSS、diagnostics 和
profile 日志。已实施的首个候选在接口推导到 lowering 之间复用 ModuleBody，
每个 module lowering 后释放；设置 `WOLVRIX_FIRRTL_PARSE_CACHE=0` 可运行严格
无缓存 A/B。小型 fixture 的 parse 调用从每 module 3 次降为 2 次，GRH/JSON
阶段 hash 保持一致；香山整机 profile 已完成：缓存开启 486.2 s、关闭
514.6 s，主要成本为 interface resolve 86.0 s、lowering 321.3 s 和 linked
design verify 51.8 s；重新安装扩展后的 self-time 复跑为 484.0 s，阶段为
resolve 85.2 s、lowering 320.3 s、verify 51.2 s。首轮香山数据还显示
`resolve_module_calls=28,461`，即
9,487 个 module 在固定点推导中完整重跑 3 轮；top-20 的 resolve 时间是递归
包含子模块的 inclusive time，不能直接相加。profile 现已增加 `resolve_self_us`；
width/Reset 依赖 worklist 已验证能减少无关重跑，lowering 继续拆分 source
location、expression/access、leaves、GRH 建立和 annotation 成本。该结果仍需
F12.5 正确性验收。已完成的 SrcLoc 单扫描候选
将同一 `Range` 的两次 `Source::position()` 合并，整机 profile 降到 452.8 s，
其中 lowering 为 290.1 s；随后完成的 width/Reset 依赖 worklist 将 profile 降到
409.2 s，resolve 调用从 28,461 降到 9,818；`make test_wolvrix` 81/81 和
`make test_xs_firrtl_workflow` 59/59 通过，图/属性/诊断未见变化。加入
Semantics 内部 leaf cache 后，历史 profile 为 378.8 s（resolve 46.7 s、
lowering 254.4 s、verify 49.6 s），同一 manifest 的无 profile 复测为 381.4 s，
峰值 RSS 72,129,188 KiB。随后对 source line map 和 schema-ready 做了单因素
A/B：source line map profile 为 329.499 s，schema-ready profile/no-profile 为
327.163/329.988 s，均未保留。当前保留的 operation operand reserve 候选 profile
为 324.235 s（resolve 47.490 s、lowering 199.633 s、verify 49.403 s），无
profile 三次为 319.421 s、324.111 s 和最终清理后二进制的 322.146 s；峰值 RSS
分别为 72,105,260、71,269,820、72,098,572 和 72,117,672 KiB。证据位于
`ptmp/firrtl-ingest/F12/operand-reserve-profile/`、
`operand-reserve-noprofile/`、`operand-reserve-noprofile-repeat/` 和 `final-noprofile/`；撤回证据位于
`source-line-index-profile/` 与 `schema-ready-*`。SrcLoc、Lowerer leaf cache、
canonical node write、worklist 和容量预留均保留完整检查与 annotation；comb/state/
memory/effects 局部回归及 81/81 CTest 通过。上述为历史记录；最新实际安装库
身份校正和单因素测量见专项计划，不能从未刷新 Python 安装库的历史候选推断
性能收益。最新无分配 canonical key 校验候选三次无 profile 为
297.350/298.779/297.960 s；完整 41,790,354,702 字节 JSON roundtrip 的
SHA-256 一致，81/81 CTest 和指定 Make 功能门禁已通过。但后续全图对照发现
source-info 缓存悬空，旧图自洽 roundtrip 不能证明原文正确；上述性能仅保留为
历史记录。缓存已改为拥有字符串，并修复生成 SV 事务路径的非确定性。
最新直接提取 source-info 的固定 CPU 0 单因素 A/B 为 **305.431→290.600 s**，
完整 40,947,736,294 字节图 SHA-256、6,007 条诊断、依赖和 metadata keys
一致。81/81 CTest、指定 Make 门禁和 64/64 workflow 通过；候选重复计时、
最终 profile/no-profile roundtrip 和完整 20 分钟端到端验收仍待完成。

F12 的第一门槛是 FIRRTL/mixed ingest 降至 300 秒以内，伸展目标为 180 秒；
完整 FIRRTL→C++ 仍使用单个 20 分钟 SIGKILL 预算，最终是否通过以整机试跑为准。
证据目录统一为 `ptmp/firrtl-ingest/F12/`，构建和测试全部经 Makefile。

退出条件：阶段计时能解释至少 95% 的 ingest；baseline/candidate 的 GRH
identity、diagnostics、JSON roundtrip、mixed binding 和代表模块执行一致；
无 profile 正式测量可复现；完整整机试跑的停止阶段、RSS 和预算消耗有记录。

## F13：层次展平、GRH 化简与 core 数据搬运优化

状态：2026-11-02 已完成。五项实现、代码审查和指定正确性回归均通过；
未新增性能测量。
详细位置、实施边界和正确性要求见
[F13-grh-performance-plan.md](F13-grh-performance-plan.md)。

交付顺序：

1. F13.1：redundant-elim 改用仅校验错误的入口，避免无用的完整 node census。
2. F13.2：CF/DCE 使用借用接口，消除筛选前完整 Operation 快照和中间副本。
3. F13.3：常量清理直接查询端口标记和 users，避免逐端口扫描与 fanout 复制。
4. F13.4：展平直接构造并移动最终限定的 node attributes。
5. F13.5：增加 Graph 自用的 consuming freeze，避免复制后立即销毁 builder。

退出条件：五项实现经代码审查和相应 Make 正确性回归，功能、node 属性、
诊断、SrcLoc、借用生命周期和 freeze 失败契约保持一致；逐项登记实际提交
和验证结果。本阶段不要求新增性能测量，也不承诺量化加速或整机时间目标。
临时产物目录为 `ptmp/firrtl-ingest/F13/`。

实施记录：wolvrix `c134542659e46bc029d5485c82171d2c5304cb7a` 完成以上
五项及必要回归；同时保留跨 mutation 的邻接/value IDs/端口快照，修复
frozen view 首次 thaw 的借用生命周期。`make test_wolvrix` 为 81/81；
通过；最终 `make py_install` 后 `make test_ingest_python` 9/9、
`make test_grhsim_flow` 5/5 及全部生成模型编译执行/八组 annotations trace
比较通过。完整命令、逐项证据和 freeze 所有权边界见专项计划文末。
F10 整机和 F11 性能消融仍按各自退出条件推进。

完成后按用户新要求执行完整默认的单次 40 分钟整机测量：实际 2400.008 秒
已完成两轮，但该阶段仍未完成，仍未生成 C++。flatten 381.999 秒、普通 simplify 全阶段 1060.191 秒；
首轮由历史样本 999.972 秒降为 603.358 秒。完整配置/输入/库身份和测量边界
见 F13 计划末节，证据目录 `ptmp/firrtl-ingest/F13/full40m/`；不构成 F10 完成。

## F14：GSIM FIRRTL→C++ 性能基线

状态：2026-11-02 已完成。使用 `reference/gsim` 的现有 `compile` Make
目标，直接读取冻结 `SimTop.fir`，配置为 `dutName=default-xiangshan`，
默认 `--supernode-max-size=2`、`--cpp-max-size-KB=8192`。外层 Make/监督器
墙钟为 **778.590 秒（12 分 58.6 秒）**，GSIM 内部 `Timer.main().total`
为 758.455 秒，退出码 0。

成功生成 244 个 C++ 文件，C++ 字节数为 2,456,873,139，模型目录总大小
为 2,565,377,923 bytes；最大 RSS 为 106,753,048 KiB（约 101.8 GiB）。
本次只覆盖 FIRRTL→C++ 生成，没有编译生成的 C++ 或运行 emu。输入、工具
身份、完整命令和日志见 [F14-gsim-performance.md](F14-gsim-performance.md)，
证据目录为 `ptmp/gsim-firrtl/full40m/`。

## F11：性能消融、默认策略和正式交付

交付：

- 按 architecture §10 固定 A（SV + 普通 simplify + 提示 off）、
  B（FIRRTL/mixed + 普通 simplify + 提示 off）、C（同 B + 提示 prefer）。
  B/C 从同一优化后 checkpoint 分叉，保留相同 attrs/cost/clone/leaf 设置；
  不以旧 source-node 隔离的图充当 B。若独立整体 node 优化保留，再增加
  D 对照其开关；它不能通过阻止 primitive CSE 制造收益。
- 记录完整构建和各阶段 wall/RSS、属性成本、图规模、超节点/边界、生成代码
  与 text 大小，区分输入路线、完整 node CSE 和 node 分图带来的变化。
  A/B 含输入及分图前优化差异，不能全算成 FIRRTL 解析收益。
- 在正确性通过后，固定 CPU、单线程、无 PGO、seed、CoreMark100k 和 NEMU，
  A/B/C 及适用的 D 各测三次，轮换顺序。按耗时总和报告分图收益 B/C 和
  总收益 A/C；额外整体优化、共同成本改进、亲和度、leaf/clone 分别消融，
  保存完整配置及身份，不混入提示收益。
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

## F15：GrhSIM 性能路径实现

F15 的差距分析和实现记录见 [F15-grhsim-performance-plan.md](F15-grhsim-performance-plan.md)。普通 simplify 已加入逐图 dirty worklist；GrhSIM 分图维护 deterministic dirty-owner 传播并记录逐轮计数；node 属性验证使用 graph revision cache，flatten qualification 与 GrhSIM CSE 字符串使用 transient node-key IDs；FIRRTL transaction 通过 `FirrtlOptions::lowerThreads` 支持固定线程池，各 worker 直接写最终 owner 的 unpublished graph，并按原依赖顺序移动发布，不复制整图。`test_ingest_driver` 检查串行/并行完整 JSON 和诊断顺序，冻结香山输入已有同库 1T/2T 与 10T 到展平终点的实测。完整 FIRRTL→C++ A/B 仍待测。

2026-11-03 的 [ingest→hier-flatten perf 分析](F15-ingest-flatten-perf.md) 定位到
flatten 的 mimalloc 周期性全堆扫描，两项 collect 叶函数占 58.90% 用户 CPU；
另记录 ingest 字符串/符号表查找与前置 pass 的完整 Operation 快照复制。
本轮只新增诊断与报告，未修改 native 性能实现。

## F16：ingest 到 hier-flatten 的三项性能修复

状态：2026-11-03 已完成实现与验收。详细范围、源码落点和验收见
[F16-ingest-flatten-performance-plan.md](F16-ingest-flatten-performance-plan.md)，
完整结果见 [F16-ingest-flatten-results.md](F16-ingest-flatten-results.md)。

交付顺序：

1. F16.1：对照默认 mimalloc、提高周期扫描间隔和关闭 slang 全局 new/delete
   替换，选择适合大图构建的分配器策略；保留 slang arena 机制。
2. F16.2：前置 pass 先筛 kind、按需借用字段，消除完整 Operation 只读快照；
   保持跨 mutation 的数据生命周期和来源信息。
3. F16.3：减少 ingest/flatten 的重复字符串查找、hash 和临时分配，
   使用图内 ID 与显式跨图映射，保留符号、annotation 和诊断契约。

退出条件：三项逐项记录实现/实验处置、完整图及有序诊断对照、阶段耗时与
峰值 RSS；最终完成同配置重复计时和 perf 复核。范围截止于展平返回，包含
八个默认前置 pass，沿用 10T direct-publish 基线，不以 simplify 或仿真运行时
收益代替本阶段结果。构建、测试和测量均经 Make，证据目录为
`ptmp/firrtl-ingest/F16/`。

验收结果：基线和最终版各三轮连续前缀中位数 **513.804→308.525 s**，
缩短 **39.95%**，峰值 RSS 基本持平；三个变体的 ingest/flatten 完整图、
metadata、来源和有序诊断均与基线一致。C++ **81/81**、工作流 **71/71**
及相关生成模型门禁通过，最终 perf 完成。主要收益由分配器策略和只读快照
消除支撑；F16.3 额外整体提速未证实。最终前缀仍为 F14 GSIM 的 **4.033×**。


## F21：comb-loop-elim 后独立 DCE 与 SemanticTree 回收

状态：已完成（2026-11-07）。计划及最终实测见 [F21-dead-code-elim-plan.md](F21-dead-code-elim-plan.md)。

交付边界：

1. 复用现有 op/value 反向可达性 DCE，不引入 GSIM Node/ENode 活跃性分析；
   FIRRTL/mixed full 与 bringup 在 `comb-loop-elim` 后先做静态数组拆分，随后由共享
   仿真流程在 `grh-to-grhsim` 前执行一次 DCE，纯 SV 序列不增加该调用。
2. DCE 后按存活 op/value 的直接 SemanticId 回收无引用来源分支，保留祖先和实例结构；
   无定义 op 的存活 input 等边界不误删。批量重编号保持路径、列表顺序和重复项，
   SemanticId 不反向保活电路。
3. 独立 checkpoint benchmark 与 GSIM 首次 `RemoveDeadNodes` 对照；另以共同起始 K 的
   删除矩阵和共同存活 Node DAG 衡量删除能力，不以原始节点数单独判优。

验证入口：`make test_transform_dead_code_elim`、`make test_grh_semantic_tree`、
`make test_f19_semantic_json`、`make test_f21_dce_asan`、`make test_wolvrix`、
`make test_transform_comb_loop_elim test_firrtl_state test_firrtl_memory`、
`make test_xs_firrtl_workflow`、`make test_grhsim_flow`、`make benchmark_f21_dce`、
`make f21_gsim_collect` 和 `make f21_dce_compare`。新增工作流均先加入 Makefile 后执行。

实施记录（2026-11-06，持续更新）：

- SemanticTree 非破坏式批量压缩、Graph 来源池及长列表哈希重映射已完成；
  无回收时不改变 Graph revision。op operands/results 改为删除前借用只读 span，
  保持同一活跃性算法并减少临时分配。
- `test_transform_dead_code_elim`、`test_grh_semantic_tree`、`test_f19_semantic_json`
  和 `test_transform_simplify` 通过；ASAN 下 DCE/SemanticTree/JSON/FIRRTL 4/4 通过。
- 完整 CTest 修改前后均为 76/84，失败名单不变：`grhsim-sink-schedule-tests`、
  `transform-hier-flatten`、`transform-origin-attribution`、`firrtl-node-attributes`、
  `firrtl-comb`、`firrtl-aggregate`、`ingest-mixed` 和 `firrtl-node-pipeline`。
  其中 sink 项对应工作树已有修改，其余为旧 provenance/node 表示问题，无 F21 新增失败。
- FIRRTL workflow 为 67/73；仍只有旧 node 属性断言 2 项和中文 locale 断言 4 项失败。
  shared flow 的旧 policy/CSE 元数据断言单独记录，不混入 F21 的删除或性能结论。
- 消环及 FIRRTL state/memory 实际执行回归通过。原始 FIRRTL 连续入口 `f21_grh_dce`
  也已跑通，454 个 false loop 全部修复，独立 DCE 为 19.066 s（非正式计时样本）。
  全量 `post-dce` 的 op SemanticId 缺失为 0，
  8,391,980,862 字节 JSON 的 store→load→store 字节数和 SHA-256 完全一致。
- 最终 F21 native 三轮 DCE 墙钟为 16.348/17.090/16.354 s，中位数 **16.354 s**；
  analysis/op-value 删除/SemanticTree 回收中位数分别为 12.996/2.546/0.484 s。
  三轮删除集合与 2,414 个声明寄存器符号检查一致，RSS 增量中位数为 988,616 KiB。
- GSIM 三轮首次 `RemoveDeadNodes` 为 35.805/36.252/33.802 s，中位数 **35.805 s**；
  F21 中位数为其 **0.457×**，达到性能门槛。共同可解析的 7,242,278 个 K 中，
  双方删除 1,386,911、仅 GrhSIM 删除 681、仅 GSIM 删除 1,149,622、双方保留 4,705,064；
  本实验不支持 op 级粒度必然带来更多 Node 删除。共同存活 DAG 共同边 6,877,133，
  精确率 **99.9272%**、召回率 **99.9639%**，残余 SCC 为 0；最终数据见 F21 文档附录。
  证据统一放在 `ptmp/firrtl-ingest/F21/`。

后续审查修订（2026-11-07）：

- 新增独立 `split-static-array`，在 `comb-loop-elim` 后、独立 DCE 前对静态组合数组读按需成员化；
  支持 assign、arrayCreate、边界内 concat、静态位切片和 shaped mux，不复制 GSIM Node/ENode 活跃性分析，
  也不把 DCE 混入 simplify。
- 拆分与独立 DCE 默认 `keep_declared_symbols=False`，声明数组不再天然保活；显式 True 可恢复保护，
  其他 pass 的默认声明策略不变。端口、状态和外部效果边界仍按各自规则处理。
- 新小图覆盖声明数组默认删除/显式保护、多维索引、MUX、动态读拒绝、SemanticTree 和图并行；
  ASAN 5/5 通过。全量 CTest 为 77/85，新增测试通过，失败名单与修改前基线一致。
- 最终 post-DCE 为 19,250,843 op；split+DCE 单轮合计 76.172 s，GSIM 同阶段 87.332 s。
  GSIM 净多删 82,252 个共同 K；共同存活 DAG 精确率 90.2274%、召回率 93.2698%，收缩后无环。
  RSS 增量仍约 8.0 GiB，DAG 独有边和内存峰值均属未闭合项。
- §13 的组合数组初版 SimTop 删除矩阵、DAG、耗时及内存保留为历史结果；§9–§12 保留开启声明保护时的历史结果和归因。

拆分闭环复核（2026-11-08）：

- split 后直接保存 checkpoint，并与 GSIM 首次 DCE 前对照：4,832/4,832 状态族、58,255 个元素全对齐，
  双向多留/少留均为 0，映射问题为 0。增量 fallback 工作队列及回滚取消已加入实现和小图回归。
- 最终 post-DCE 为 18,242,935 op、7,137,638 个 SemanticTree 节点，自赋值为 0；4,771/4,832 状态族精确一致，
  仍有 332 个 GrhSIM 多留、16 个少留元素，所有差异族均已成员化，不再存在未拆聚合表示导致的差异。
- 共同 K 中双方删除 2,504,751、仅 GrhSIM 删除 46,623、仅 GSIM 删除 31,782、双方保留 4,659,122；
  GrhSIM 净多删 14,841。DAG 精确率 88.1968%、召回率 91.9049%，仍未完全对齐。
- 将顶点扩大为双方任一端保留的 4,737,527 个可映射 Node 后，收缩 DAG 总边为 GrhSIM 6,858,586、GSIM 6,880,937，
  GrhSIM 少 22,351 条（0.3248%）；共同边 6,012,126，两端独有边合计 1,715,271，净差不代表结构已经对齐。
- ROB 的 113,226 条 GrhSIM 独有边已逐条闭合：109,677 条 split 父数组两跳、7 条普通两跳、206 条长路径、
  3,319 条 split 语义归属、16 条动态数组索引及 1 条层次时钟边；没有发现 GSIM 删除活跃依赖而 GrhSIM 漏删的证据。
  该结论仅限 ROB，且不替代动态等价验证；新增路径工具回归 7/7，通过全有效节点分析排除了中间节点过滤造成的误判。
- 全部 1,715,271 条不重合边已按形成原因闭合：单边端点 381,133、split 父数组相关 938,942、其他中转/别名路径 289,650、
  非 split 父节点无路径 105,546。GSIM 无路径边中 516,153 条在两端 split 前均存在，GrhSIM 的 88,209 条无路径边在
  GSIM split 前均不存在；结果见 F21 §16 和 `ptmp/firrtl-ingest/F21/global-edge-differences/`，不将无路径直接判为语义错误。
- 全部 array-typed value 已对比：GrhSIM/GSIM 记录在 split 后为 629,573/16,063，post-DCE 为 128,636/7,858；
  DCE 回收 79.57% 的 GRH array value、81.29% 的 split 父数组相关记录。post-DCE 的 81 个形状差异均为退化维度或外层成员化，
  split 前 259 个宽度差异均为 GSIM 未知宽度。剩余主要是常量和赋值/mux 视图，不能直接按记录数推断动态成本，详见 F21 §16.3。
- 连续生产入口与冻结 checkpoint 的 post-elim/post-dce SHA-256 均一致。专项及 ASAN 5/5、工具 5/5 通过；
  CTest 77/85、workflow 67/73，失败名单与既有基线一致。没有新增整机 C++/emu 动态等价证明。
- CPU 2 无并行干扰的三轮中位数为 split 45.867 s、独立 DCE 57.075 s、合计 102.900 s；
  GSIM 同阶段合计 84.656 s，GrhSIM 慢约 21.6%。采样峰值 RSS 中位数约 38.7 GiB，第一轮约 34.0 GiB，
  不能把后续轮的 RSS delta 当成真实内存需求，也不能宣称性能优于 GSIM。
- 最新证据与性能见 F21 文档 §15，目录为 `ptmp/firrtl-ingest/F21/state-split-v13*`。

## F23：普通 GRH 后续优化 pass

状态：F23.1–F23.3 已完成当前安全子集；未运行 XiangShan 全图性能测试。

F23 的全部 pass 位于 `grh-to-grhsim` 之前，运行在普通、未分区 GRH 上。每个
优化 pass 都保留 operation/value 行，DCE 由流程在明确边界单独调用：

```text
dead-code-elim
→ expr-opt → used-bits → split-nodes
→ dead-code-elim
→ constant-analysis
→ dead-code-elim
→ alias-analysis → pattern-detect → common-expr
→ dead-code-elim
→ grh-to-grhsim
```

F23.1 的 `split-nodes` 只覆盖无符号 scalar 纯表达式的静态位段；寄存器、数组、
有符号和算术节点仍保持原表示。F23.2 的 `constant-analysis` 按拓扑顺序折叠
可证明常量的纯逻辑操作。F23.3 的三个 pass 分工如下：

- `alias-analysis` 重定向类型一致的 scalar `assign` 和完整静态 slice，并
  保留 node roots/SemanticTree provenance；
- `pattern-detect` 将 `(concat(high, low) == constant)` 展开为两个窄 equality
  与 `and`；
- `common-expr` 按 GSIM 的计数、宽度和 fanout 门槛共享重复纯 scalar
  expression tree，并合并代表的 provenance。

F23.3 的设计、参数、保守边界和测试命令见
[F23-alias-pattern-common.md](F23-alias-pattern-common.md)。F23 pass 的默认
声明策略是不把 `declaredSymbols` 作为保活根；需要保留声明时由外层 DCE/流程
显式传入策略。

## F24：XiangShan FIRRTL → GrhSIM 系统联调

状态：已完成（按用户2026-11-11最终验收口径）。正式顺序、阶段日志和门禁见
[F24-xs-firrtl-grhsim.md](F24-xs-firrtl-grhsim.md)，提交与清理边界见
[F24-correctness-checkpoint.md](F24-correctness-checkpoint.md)。

已完成的阶段准备：

- `xs_firrtl_pipeline_manifest` 生成合法的 22 阶段 manifest；`xs-firrtl-grhsim`
  目标依赖该 manifest，并通过 `XS_FIRRTL_STAGE_LOG` 写入每个阶段的 JSONL
  `start`/`done`/`failed` 事件。
- native/Python pass factory 接受 `grhsim-dialect-translate`、
  `split-event-and-output`、`split-nonsink-and-sink`、`partition-nonsink`、
  `partition-sink` 和 `comm-expr`，旧名称保留回放兼容。
- `partition-nonsink -firrtl-nodes=auto|prefer` 按 SemanticTree 的
  Declaration/Expression family 分组，Field/Element 归入所属 family，实例
  子树使用独立 SemanticId。`semantic-nodes=1` 额外保留声明结果值边界，
  不会把携带声明 provenance 的每个表达式 primitive 都切成独立 node。
  clone 保留 operation/value SemanticIds，v3 checkpoint 拒绝沿用，当前配置为 v4。
  `test_grhsim_firrtl_nodes`、四项 GrhSIM transform CTest 和
  `firrtl-semantic-tree` 均通过。
- JSONL 区分 `pipeline`、`verification` 和 Make 父进程的 `run` 事件；
  真实 mixed 模型及 flat resume 的工作流测试 78/78 通过，恢复后完整执行
  256 个输入的独立记分板验证。
- 已重新冻结默认 SV/默认单线程 Verilator CoreMark 100k difftest 基线：Host **152.190 s**，
  端点 `238535/99996/100001/0x80000cde`；实际 binary `threads()` 返回 1，
  binary/workload/NEMU 前后哈希一致，见 F24 的 `verilator-default` 证据。
  提交 trace 与 FST 独立采集通过，二者的 231568 条提交记录逐字节一致。
- v7 已通过 dialect conversion（14.140 s；422 detectors/46 joins），在 sink
  partition 阶段触发 systemd-oomd（scope 160.2 GiB），没有正常退出记录。
  后续全图生成/编译经 `xs_firrtl_resource_capped` 独立 cgroup，默认128 GiB、
  swap0，并继续保留 generation840 s/complete compile330 s 强制截止。

v14最终结果：显式ingest请求`invalid_policy=zero`、通用默认unknown，未改XiangShan
RTL；canonical22阶段pipeline825.050s、service826.294s<840s，fresh完整编译
payload305.71s、service305.837s<330s，activation含pulse保守上界965144≤2193888。
同一原始exe以NEMU通过100k窗口，231568条提交及周期/ROB/队列/写回与默认Verilator
逐字节一致。独立补充校验区分原trace postflight误报，原始失败状态保留。
性能运行在152.190s硬截止立即停止，最后报告70k，未达到100k；用户明确决定
停止继续性能优化、以正确性通过判定F24完成，故保留失败事实但移出完成门。
旧迁移/phase probe/M0脚本及Make入口已删除，临时大产物清理后保留本轮证据；
清理后小回归不冒充全图重跑，具体身份和日志见正确性提交记录。
