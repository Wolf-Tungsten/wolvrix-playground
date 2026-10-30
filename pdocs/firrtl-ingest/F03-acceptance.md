# F03 验收记录

日期：2026-10-30。F03 已完成：自有 FIRRTL parser、模块接口索引、公共
扫描入口、正式文档及冻结输入复验均有实现和验证证据。行为 lowering 从
F04 开始；F00 的整机依赖和 correctness/性能基线仍需完成。
实现提交为 wolvrix `501360f`，资源/源位置边界回归及正式文档补充为
`c798118`，均在 `grh/firrtl-ingest` 分支。

## 冻结输入

[inputs.json](inputs.json) 固定 `ptmp/xs/rtl/rtl/SimTop.fir` 的 1,671,325,062
字节及 SHA-256，固定生成 `filelist.f`、生成日志、两个 FIRRTL fixture 和
规范缓存。生成日志记录一次输出 FIRRTL 与 aggregate SV 的调用：TLConfig、
issue E.b、单核、`--dump-fir`、`--preserve-aggregate=all`、difftest enabled。
生成 SV 清单含 filelist 的 2,114 份源码，连同同目录其他 SV/Verilog/头文件
共 2,146 份、367,902,780 字节；清单内容 hash 已入 manifest。完整逐文件
清单放在 `ptmp/firrtl-ingest/F03/input-verify/sv-inventory.json`。

规范固定到 FIRRTL 6.0.0 修订
`5ab37a032d822c8e3975fb9f7f36e52a019c34ec`，缓存 hash 随 manifest 校验。
目标 Chisel 文本还使用 CHIRRTL memory、variadic cat、intmodule、layer
目录字符串和 named stop；这些构造有明确语法表示。旧版本和已移除的语法
明确拒绝。该输入冻结仅用于 F03；此时未验收外部 SV 的绑定或行为等价。

## 逐项验收

| F03 要求 | 当前实现与直接证据 |
| --- | --- |
| 自有 lexer/parser，不依赖 CIRCT | `lib/ingest/firrtl/{source,lexer,parser}.cpp` 由 CMake 注册；Make 工作流只运行本地 inspector，无 MLIR/CIRCT 链接或 firtool 调用 |
| 缩进、递归表达式、目标类型/声明/语句 | 类型/表达式/语句 arena 保留有序 operands 和嵌套 body；`firrtl-parser` 断言嵌套 node 表达式结构；冻结输入全部 10,008 个模块验证通过 |
| 先建模块符号，再按需解析主体 | `indexFile/indexText` 返回接口及模块范围；`parseModule` 解析单模块；fixture 实例引用后定义模块通过，未声明模块/越域组件与别名错误有回归 |
| 版本门控、错误恢复、未知语法拒绝 | 仅接受 6.0.0，`expectedVersion` 不符失败；独立错误恢复、非法缩进、截断、未知表达式/语句等均验证；错误最多 32 条，嵌套超限失败 |
| 可识别但未 lowering 的结构不丢失 | class/formal、属性/enum、Probe、layer、memory、intrinsic 和 annotation 均有类型化或原文表示；`readFirrtl` 在扫描后明确返回未支持 lowering 的错误且无 design |
| 大输入资源控制 | Unix 单文件只读映射，名称/类型 intern；接口 arena 不持有主体 AST；全量验证每次释放一个模块 arena。最终复验峰值 RSS 4,693,952 KiB，最大模块 1,225,389 条语句 |
| 位置、原始 source info 和当前模块 | 诊断拥有 filename、行列、source snippet、source info 和 module；释放源后诊断仍有效。CRLF、末尾无换行和宽字面量附带 source info 均有回归 |
| 扫描结果供共享 driver 使用 | `scanInterfaces` 分发到 FIRRTL 完整语法验证后导出 owning signatures；Bundle 拆字段、flip 流向、Vector shape、待解析类型和原始字符串参数均有回归 |
| 退出条件：冻结输入完成语法/接口扫描 | `make verify_firrtl_inputs` 前后校验输入身份，要求全模块成功且全部持久统计一致；结果在 `acceptance.log` 及 `input-verify/inspection.log` |
| 必要回归与正式文档 | `make test_wolvrix` 69/69；`make test_firrtl_parser_inputs` 4/4；正式 API、语法和资源边界见 [firrtl-parser.md](../../wolvrix/docs/ingest/firrtl-parser.md) |

## 构造与后续语义矩阵

表中“已解析”只指 F03 语法及结构保留；对应语义由后续阶段实现。
冻结 manifest 同时保存全部 `statement.*`、`primitive.*`、`intrinsic.*`
计数，未知行不能通过跳过处理进入验收。

| 构造 | F03 证据 | 后续语义阶段 |
| --- | --- | --- |
| module/extmodule、参数/defname | 冻结输入 10,008 模块，含 521 extmodule；fixture 验证大整数/字符串/原始字符串参数 | F07 specialization、混合绑定 |
| UInt/SInt/Clock/Reset/AsyncReset、const、别名 | 目标接口索引及 fixture；推断位宽/Reset 明确标为待解析，1024-bit literal 原文保留 | F04 类型/位宽，F05 reset |
| Bundle/Vector、flip、静态/动态索引 | 共享叶子保留 `[8,4]` 等 shape；fixture 验证方向、零宽、重名冲突；mport 动态访问保留索引表达式 | F04 聚合与 flow |
| node、primitive、mux | 5,476,900 node；32 种目标 primitive 的独立计数；nested node AST 检查 | F04 lowering/注解，F08 node CSE |
| wire、connect/invalidate、when | 274,250 wire、2,042,818 connect、103,572 invalidate、155,453 when；嵌套条件及别名引用有回归 | F04 last connect，F05 有序写 |
| reg/regreset | 29,655 reg、59,849 regreset；时钟、复位和初值 operands 保留 | F05 状态 lowering |
| mem、cmem/smem/mport | fixture 验证标准 mem；目标 660 cmem、219 smem、1,858 mport；mport 数据作用域与访问嵌套分开保留 | F06 memory 语义 |
| Probe/RWProbe、read/define、force/release | 111,089 define；fixture 覆盖 probe 及 force/release，接口标记为待 ABI/类型解析 | F06 目标特性，F07 ABI |
| layer、layerblock、intrinsic/intmodule | 1 个 layer root、14,756 layerblock、6,920 `circt_chisel_ifelsefatal`；fixture 覆盖 intmodule/返回值 intrinsic | F06 效果与层特性 |
| printf/stop、assert/assume/cover、fprintf/fflush | 目标 915 printf、1 stop；fixture 覆盖其余命令并检查参数数量/标签冲突 | F06 效果 |
| class/extclass、formal、属性类型/运算、enum/match | `properties.fir` 保留嵌套 formal 值、属性 AST、enum tag/payload 和分支 | F06 目标版本构造 |
| annotation JSON、source info | 保留 27,445,349 字节 annotation；引号/转义、坏 JSON 和错误位置有回归 | F06/F07 annotation 与外部实现 |
| 老版本、缺失版本、未知/损坏语法 | 错误回归明确拒绝，不能发布可执行 design | 不作兼容承诺 |

## 复验

在现有冻结产物和规范缓存保留的工作区执行：

```sh
make test_firrtl_parser_inputs verify_firrtl_inputs test_wolvrix WOLF_ENV_SOURCED=1
```

最终运行日志为 `ptmp/firrtl-ingest/F03/acceptance.log`。四项输入校验回归
实际调用 inspector，覆盖正常 capture/verify、拒绝覆盖原清单、FIRRTL/SV/
fixture/规范/生成日志变更、增加头文件、缺失源码、统计篡改和主体语法错误。
输入身份及全模块统计复验通过，最终完整 CTest 69/69 通过。

有意更换输入时，使用 `freeze_firrtl_inputs` 和新的 `FIRRTL_INPUT_MANIFEST`
路径生成待审查清单；该命令拒绝覆盖已存在的冻结清单。逐文件 SV 清单、
inspector 输出及复验快照均留在阶段 `ptmp/` 目录，大文件不提交。
