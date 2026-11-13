# FIRRTL 输入支持推进文档

建立日期：2026-10-30。已完成 F01 目录/读取层迁移和 F02 属性/作用域基础；
F03 parser 和接口索引已完成，冻结输入通过香山全模块语法与接口验收。
F04 组合 lowering、Bundle/Vector 和真实 node 标注已完成，验收见 F04-acceptance.md。
F05 寄存器、复位及有序数组写已完成，验收见 F05-acceptance.md。
F06 memory、效果与目标版本特性已完成，验收见 F06-acceptance.md。
F08 完整 node CSE、属性传播和 checkpoint 已完成，验收见
F08-acceptance.md。F09 已将 node 改为不阻碍 simplify 的 op 级软提示，
撤除 source-node 隔离并接入统一 nonsink 分图。设计与实际验收分别见
F09-plan.md、F09-acceptance.md；F02/F08 验收记录保留历史含义。
2026-10-31 当前决定：先形成统一 node——有 FIRRTL 提示按提示，无提示按
MFFC；再按 node 数划分 supernode，不感知内部 op 数/work。F09.6 已实现并验收，见 [F09.6-acceptance.md](F09.6-acceptance.md)，
取代前次“单 node 超 work 预算豁免”的规划。

2026-11-13：SemanticTree 的当前定义以 [F28](F28-semantic-tree-refactor-plan.md)
为准：内部是 Path，只有一种具名叶 Node，成员是实际 GRH op；flatten 后所有
Node 直属根。新模型的生产维护范围先截止 `ingest→xmr-resolve→hier-flatten`，
未迁移的后续 pass 明确拒绝。以下早期分图与来源标注说明保留对应阶段的历史含义。

目标是在 Wolvrix 内实现不依赖 CIRCT 的 FIRRTL 前端，与现有 SV 前端共同
构建设计。FIRRTL `node` 与 ops 的关联以 attribute 保存；普通 GRH 优化与
仿真转换不受来源标注限制，允许跨 node CSE、内联、重关联和 DCE。分图
以优化后的真实 op 图为准，有提示按提示构建 node，其余按 MFFC。共享和
语义冲突在 node 构建层规范化；supernode 只组合完整 node，按 node 数
限制容量。数组保留 shape，Bundle 按现有 SV struct 规则递归展平。

## 文档入口

| 文档 | 内容 |
| --- | --- |
| [architecture.md](architecture.md) | 源码组织、混合读取、类型与时序语义、node 属性及分图合约 |
| [steps.md](steps.md) | F00–F16 的依赖、交付、Make 验证入口及退出条件 |
| [firrtl-parser.md](../../wolvrix/docs/ingest/firrtl-parser.md) | 已实现 parser 的语法、接口签名、资源与验证边界 |
| [F03-acceptance.md](F03-acceptance.md) | F03 逐项验收、目标构造矩阵、冻结输入和复验命令 |
| [firrtl-combinational.md](../../wolvrix/docs/ingest/firrtl-combinational.md) | F04 类型、连接、聚合、逻辑域及 node lowering 的实际支持范围 |
| [F04-acceptance.md](F04-acceptance.md) | F04 逐项验收、组合执行样例和实际回归证据 |
| [firrtl-state.md](../../wolvrix/docs/ingest/firrtl-state.md) | F05 状态类型、初始化、复位屏障及有序读写的实际支持范围 |
| [F05-acceptance.md](F05-acceptance.md) | F05 逐项验收、FIRRTL/SV 多周期记分板和最终模型回归证据 |
| [firrtl-memory.md](../../wolvrix/docs/ingest/firrtl-memory.md) | F06 memory 归一化、延迟、mask、冲突及四态策略 |
| [firrtl-effects.md](../../wolvrix/docs/ingest/firrtl-effects.md) | F06 effects、layer、Probe、annotation 和外部引用边界 |
| [F06-acceptance.md](F06-acceptance.md) | F06 验收矩阵、目标模块执行和专项/全量回归证据 |
| [mixed.md](../../wolvrix/docs/ingest/mixed.md) | F07 混合读取、参数 specialization、ABI、黑盒源及事务式发布 |
| [F07-acceptance.md](F07-acceptance.md) | F07 交替层次仿真、负例、Python 和完整回归证据 |
| [F08-acceptance.md](F08-acceptance.md) | F08生产变换审计、回归和真实大模块属性成本 |
| [F09-plan.md](F09-plan.md) | 当前两层分图设计：提示/MFFC 构建 node，按 node 数划分 supernode；F09.6 已实现 |
| [F09.6-acceptance.md](F09.6-acceptance.md) | 当前统一 node / Node DAG / 节点容量、迁移及代表模块验收 |
| [F10-plan.md](F10-plan.md) | 香山混合入口、独立 Chisel 输出及分阶段正确性验证 |
| [F12-ingest-performance-plan.md](F12-ingest-performance-plan.md) | FIRRTL ingest 分阶段计时、热点定位和无语义损失加速计划；F11 的前置专项 |
| [F13-grh-performance-plan.md](F13-grh-performance-plan.md) | 层次展平、普通 GRH 化简与 core 数据搬运的五项优化及验收记录 |
| [F14-gsim-performance.md](F14-gsim-performance.md) | GSIM 直接从香山 FIRRTL 生成 C++ 的性能基线 |
| [F15-grhsim-performance-plan.md](F15-grhsim-performance-plan.md) | GrhSIM 分图、node key/cache 与并行 FIRRTL lowering 优化 |
| [F15-ingest-flatten-perf.md](F15-ingest-flatten-perf.md) | 10T ingest 到 hier-flatten 的 perf 热点、allocator 全堆扫描和 Operation 快照复制 |
| [F16-ingest-flatten-performance-plan.md](F16-ingest-flatten-performance-plan.md) | ingest→hier-flatten 的分配器策略、Operation 快照与字符串/符号表三项修复计划 |
| [F16-ingest-flatten-results.md](F16-ingest-flatten-results.md) | F16 逐项实现、native 身份、完整图正确性和性能证据 |
| [F16-node-attribute-ablation.md](F16-node-attribute-ablation.md) | node 关闭单轮与旧开启基线对照：308.525→205.778 s，缩短 33.3% |
| [F16-remaining-pipeline-analysis.md](F16-remaining-pipeline-analysis.md) | 剩余重复解析/语义分析、串行检查、逐实例构图和前置 pass 扫描的优化方向 |
| [F17-ingest-flatten-structural-plan.md](F17-ingest-flatten-structural-plan.md) | ingest→flatten 三项结构性方案：单一 SoA core 存储（基础）、列块拼接 flatten、一次解析/分析的模块流水 |
| [F17.1-grh-storage-results.md](F17.1-grh-storage-results.md) | F17.1/2/3 单一 GRH 存储、列块 flatten、单遍流水的完整正确性与最终实测；性能预算未达项按实测记录 |
| [F18-ingest-flatten-unit-cost-plan.md](F18-ingest-flatten-unit-cost-plan.md) | F17 未达预期的实测原因（node 文本、名字、Rob 长尾）及 F18 方案；含 F17 formal 数字更正 |
| [F19-semantic-tree-json-plan.md](F19-semantic-tree-json-plan.md) | 自包含 SemanticTree：字符数组、批量深拷贝、本地 ID 与单一 v4 JSON，不兼容旧格式 |
| [F20-gsim-init-alignment-plan.md](F20-gsim-init-alignment-plan.md) | 无重写 pass 的 flatten 图与 GSIM Init 图的对齐实验：对齐键、统计采集、指标及判定门槛 |
| [F21-dead-code-elim-plan.md](F21-dead-code-elim-plan.md) | comb-loop-elim 后静态数组拆分、独立 op 级 DCE、SemanticTree 回收、GSIM 删除矩阵及 Node DAG/性能对照 |
| [F22-expr-opt-used-bits.md](F22-expr-opt-used-bits.md) | GSIM 对齐的独立 ExprOpt/UsedBits、外部 DCE 边界、SemanticTree 传播及 XiangShan 全图性能 |
| [F26-native-semantic-bindings.md](F26-native-semantic-bindings.md) | 历史来源树模型的完整流程、阶段对应与来源覆盖率；旧分析脚本已退役，当前模型见 F28 |
| [F27-node-evolution.md](F27-node-evolution.md) | 历史来源模型的 split 演化／后态重放与差异记录；旧离线工作流已退役，原生 trace 设施保留 |
| [F28-semantic-tree-refactor-plan.md](F28-semantic-tree-refactor-plan.md) | SemanticTree 首阶段重构完成：统一叶 Node、正常 ingest→hier-flatten、JSON v5；原生 22/22 回归及整机跨端库存核验完成，剩余差异完整列出 |
| [pass-optimization-20261101.md](pass-optimization-20261101.md) | 保留完整优化的 flatten/simplify 实现加速、严格 A/B 与 20 分钟整机复测 |
| [F10-components.md](F10-components.md) | 真实代表模块的双路线比较、激励、记分板及当前证据 |
| [F10-replacer.md](F10-replacer.md) | AheadBtbReplacer 独立 PLRU 记分板、四路线执行与 reference 断言缩减 |
| [F09-acceptance.md](F09-acceptance.md) | F09.0–F09.5 实施、结构透明性、回归及真实模块消融结果 |
| [inputs.json](inputs.json) | FIRRTL、生成 SV、fixture、规范及语法统计的冻结身份 |

## 已确定的设计决策

| 项目 | 决策 |
| --- | --- |
| FIRRTL 实现 | 自有 C++ lexer/parser、类型检查与 lowering；运行和构建均不链接或调用 CIRCT/firtool |
| ingest 目录 | `lib/core/ingest.cpp` 迁移为 `lib/ingest/sv.cpp`；新增 `lib/ingest/firrtl.cpp` 和共享 driver |
| 公开头文件 | 统一放在 `include/ingest/`；删除旧 `include/core/ingest.hpp`，同步迁移全部调用方 |
| 混合输入 | 一次读取事务同时接收 FIRRTL 与 SV，先解析接口及跨语言引用，再 elaboration、链接到统一 GRH |
| 聚合类型 | Bundle/struct 递归拆字段；Vector/数组维度迁移到叶子 shape，端口也保留数组 |
| SemanticTree 重构 | F28 首阶段完成：内部仅 Path，叶子只有一种具名 Node，持有实际 op 集合；flatten 后根直接连接全部 Node。整机 7,671,189 个 Node，99.9670% 有唯一 GSIM 候选，66.2471% 在已配对边界下结构相符；行为未全部证明 |
| Node 持久化 | F28 JSON v5 保存显式 Path/Node ID、限定名字状态、实际 op/anchor 成员；v4 必须从源重新 ingest；后续未迁移 pass 明确拒绝新树 |
| simplify | node 不进入功能键、CSE 作用域或重写准入；优化后合并/更新提示，维护不了则降级，不加属性载体或保活根 |
| GSIM 策略迁移 | F09 已撤除普通优化屏障；独立整体选项采用 gsim-soft-v2，只消费仍可证明的候选，门槛不限制 primitive CSE |
| node 构建 | 有可用 FIRRTL 提示按提示构建 node；其余按 MFFC，均不因 op 数或 work cap 拆分；共享/语义冲突先规范化 |
| supernode 分组 | 统一 Node DAG，每 node 容量权重为 1，按 max-supernode-nodes 分组，不读取内部 op 数/work |
| 无注解输入 | SV、FIRRTL 无提示逻辑和混合 glue 都按 MFFC 构建 node，进入同一 Node DAG；无根不等于无提示 |
| 混合分组 | 链接后的真实 ValueId 连接两种输入，不按 node/wire 名称匹配；语言来源不阻止合法跨界合并 |
| 正确性 | 混合绑定、旧值采样、写优先级、memory 语义、DPI/效果均纳入验收 |
| 性能 | 分别测量输入路线、完整 node CSE 和 node 分图的收益；不预先承诺整机提升百分比 |

## 阶段看板

| 阶段 | 交付 | 状态 |
| --- | --- | --- |
| F00 | 固定输入、特性清单和对照基线 | 进行中；F03 输入身份已冻结，整机依赖及基线验收待补 |
| F01 | ingest 目录迁移和公共读取边界 | 已完成（2026-10-30，验证见 steps.md） |
| F02 | node attribute schema、CSE 作用域及验证器 | 历史实现已完成；F09 已迁移为 schema 2 / soft-node-v2 |
| F03 | FIRRTL parser、版本检查和模块接口索引 | 已完成（2026-10-30，冻结输入和验收见 F03-acceptance.md） |
| F04 | 类型推导、组合语义、Bundle/Vector 和 node lowering | 已完成（2026-10-31，验收见 F04-acceptance.md） |
| F05 | 寄存器、复位及有序数组写 | 已完成（2026-10-31，验收见 F05-acceptance.md） |
| F06 | memory、效果及目标版本特性 | 已完成（2026-10-31，验收见 F06-acceptance.md） |
| F07 | FIRRTL/SV 混合 elaboration、链接和 Python API | 已完成（2026-10-31，完整验收见 F07-acceptance.md） |
| F08 | GSIM 模式 node 级 CSE、属性传递和 checkpoint | 历史实现已验收；F09 已迁移普通优化与独立 CSE 配置 |
| F09 | 统一 node 构建与 nonsink 分图 | F09.0–F09.5 为旧版验收；F09.6 提示/MFFC node + 按 node 数划 SN 已完成（F09.6-acceptance.md） |
| F10 | 香山混合输入和差分正确性 | 实施中；full20 已在 20min 硬时限由 SIGKILL 终止（第二轮 mux-tree-fold），尚无最终 C++、整机 emu/运行 |
| F12 | FIRRTL ingest 性能分解与实现加速 | 初步版本收尾；已保留完整语义优化并移除原生插桩。收尾版固定 CPU 0 为 293.761 s，完整 40.95 GB 图 hash 与 6,007 条诊断对照通过；81/81 CTest、65/65 workflow 和指定 Make 门禁通过。完整 FIRRTL→C++ 20 分钟目标留待后续整机工作 |
| F13 | 层次展平、GRH 化简与 core 数据搬运优化 | 已完成（2026-11-02）；五项实现及正确性门禁通过。后续完整默认 40 分钟试跑推进至后端 simplify，仍无 C++；flatten 381.999 s，普通 simplify 首轮 603.358 s，详见 F13-grh-performance-plan.md |
| F14 | GSIM FIRRTL→C++ 性能基线 | 已完成（2026-11-02）；`default-xiangshan` 直接生成 244 个 C++ 文件，外层墙钟 778.590 s（12 分 58.6 秒）；详见 F14-gsim-performance.md |
| F11 | 前端/node CSE/分图性能消融、默认策略和正式文档 | 待实施；依赖 F12、F13、F15、F16 |
| F15 | GrhSIM 化简诊断与 dirty 调度、node key/cache、并行 FIRRTL lowering | 核心实现完成；ingest 1/2/10T 与展平 perf 已记录，完整 FIRRTL→C++ A/B 待测 |
| F16 | ingest→hier-flatten 分配器、Operation 快照和字符串查询修复 | 已完成（2026-11-03）；三轮中位数 513.804→308.525 s，完整图/诊断及最终 perf 通过；F16.3 额外提速未证实，见实施结果 |
| F17 | ingest→hier-flatten 结构性提速：单一 SoA core 存储、列块拼接 flatten、单遍模块流水 | 已完成（2026-11-04）；F17.1/2/3 代码、81/81 CTest、Python/workflow、oracle、完整图 identity 与 roundtrip 全部通过；最终 fused 约 195.45 s、峰值 RSS 约 67.2 GiB，≤50/10/60 s 与热点 ≤25% 预算按实测未达 |
| F18 | ingest→hier-flatten 单位成本：SemanticTree 来源模型、内部名延迟生成、flatten 真批量化、Rob 并行可行性结论 | 已完成（2026-11-05）；三轮 formal 中位数 70.64 s、flatten 19.60 s，达到 ≤75 s 目标；F18.4 不做模块内并行，见 F18-ingest-flatten-unit-cost-plan.md |
| F19 | 自包含 SemanticTree 底层改造与统一 JSON 导入导出 | 功能与性能达标；生产默认省略 def/users/loc，实测体积减少 65.54%，调试时可显式开启，见 F19-semantic-tree-json-plan.md |
| F20 | ingest→flatten 与 GSIM AST2Graph 对齐实验 | 已完成（2026-11-06）；普通寄存器、memory、地址 pipeline、写口、false loop 和 Node DAG 按既定口径验收，见 F20-gsim-init-alignment-plan.md §3.13 |
| F21 | comb-loop-elim 后静态数组拆分、独立 DCE 与 SemanticTree 回收 | 原验收完成；2026-11-08 完成拆分闭环复核。split 后 4,832/4,832 状态族、58,255 个元素与 GSIM 全对齐；post-DCE 为 18,242,935 op，GrhSIM 净多删 14,841 个共同 K，但仍有 332/16 个状态元素双向差异。三轮 split+DCE 中位数 102.900 s（GSIM 84.656 s），共同存活 DAG 精确率 88.1968%、召回率 91.9049%；4,737,527 个存活并集 Node 上，GrhSIM/GSIM 总边为 6,858,586/6,880,937；ROB 的 113,226 条 GrhSIM 独有边已逐条归因，未见 DCE 漏删活跃依赖的证据；全部 1,715,271 条不重合边已按形成原因分类闭合；全部 array-typed value 已对比，post-DCE 为 GrhSIM/GSIM 128,636/7,858 条，81 个形状差异均已解释。无新增整机动态等价证明，见 F21-dead-code-elim-plan.md §15–16 |
| F22 | GSIM ExprOpt/UsedBits 独立 pass | 已完成；DCE 保持外部可见，F22 不调用 simplify；XiangShan 全图单轮 17.371 s（ExprOpt 2.059 s、UsedBits 15.312 s），总位宽下降 1.87%，operation/value 行未被删除，详见 F22-expr-opt-used-bits.md |
| F23.1 | GSIM SplitNodes 的 GRH 前置安全子集 | 已完成 `split-nodes` 独立 pass；接在 `used-bits` 后、显式第二次 DCE 前；当前覆盖无符号 scalar 纯表达式的静态位段，寄存器/数组/有符号/算术节点留待后续步骤 |
| [F23.2](F23-constant-analysis.md) | GSIM ConstantAnalysis 的 GRH 前置独立 pass | 已完成 `constant-analysis`；接在 SplitNodes 后的显式 DCE 之后，按拓扑顺序折叠可证明常量的纯逻辑操作；不执行 DCE 或 simplify |
| [F23.3](F23-alias-pattern-common.md) | GSIM AliasAnalysis、PatternDetect、CommonExpr 的 GRH 前置独立 pass | 已完成 `alias-analysis → pattern-detect → common-expr`；三者均不执行 DCE，最后由流程中的显式 DCE 回收别名、模式中间值和重复表达式 |
| [F23.3](F23-alias-pattern-common.md) | GSIM AliasAnalysis、PatternDetect、CommonExpr 的 GRH 前置独立 pass | 已完成；接在 ConstantAnalysis 后，三者均不执行 DCE，最后由流程显式 DCE；默认不把 `declaredSymbols` 作为保活根 |
| [F24](F24-xs-firrtl-grhsim.md) / [正确性提交](F24-correctness-checkpoint.md) | XiangShan 全图 FIRRTL → GrhSIM canonical 联调、CoreMark 100k、difftest 与分图门禁 | 已完成；22阶段、生成/完整编译预算、activation及100k NEMU/231568条精确提交通过；用户将性能移出本阶段完成门，旧工具和临时产物已清理 |
| [F25](F25-simulation-performance.md) | 保留 GrhSIM 模型能力，对齐 GSIM 全图 CoreMark 100k 仿真性能 | 按用户“做完v14就先停一下”要求暂停；v14本轮完整身份/资源/正确性/profile验收链PASS，新的主性能观测quiet143.02s wall/142.98s user、独立profile149.85/149.73s；231568 commits字段/顺序/周期/导出字节一致，122runtime/9CTest/9effects、selected122/generated206/extra84及13串行330s/128GiB/swap0/omit服务通过，原最终审计status=pass/failures=[]。主/独立对账14809samples/770023179677period/lost0及8942 symbol+DSO闭合；NS+其dispatch估算47.371771s、writer78.181119s，混合general dispatch另计1.100926s、不含在NS，正式NS/GSIM报告已展示并显式record。真实安装/230controls、原始raw22stage生成773.223699471s与fresh完整编译263.774657780s均通过；实际1134batches/34groups覆盖1064/max5events/scalar265397保持，不能套旧44组/1019的机器样本包络。历史v13原主155.55s/user155.51s、单B同期149.95s、旧suite库存FAIL/补充118runtime与原最终审计PASS均保留，v12仍拒绝；原v9→v13→v9 157.48→149.95→157.58s只是single-B诊断。可选v13→v14→v13诊断仅部分准备，准备/review已中断，未授权或执行paired freeze/run、未验收；单次v14观测不证明稳定收益，GSIM端点/组件分母不同，不声明严格parity，F25仍远未完成；[新证据与限制](F25-simulation-performance.md#v14完整-writer-指令调查与调用端-fresh-fire-分组) |
| [F26](F26-native-semantic-bindings.md) | 历史 SemanticTree 来源与 op 归属覆盖 | F28 前模型的冻结记录（2026-11-12）：核验到 comb-loop-elim，旧来源对应率99.940245%、op owner覆盖99.945505%；旧离线脚本及入口已退役，不能作为新Node对齐结论 |
| [F27](F27-node-evolution.md) | 历史来源模型的原生演化与重放 | 历史全量重放／比较完成：79,279,752个after、2,321,461条事件，联合通过仍为0；旧离线工作流已退役，原生trace设施保留；F28新树的后续pass尚待迁移 |
| [F28](F28-semantic-tree-refactor-plan.md) | SemanticTree 重构：内部路径＋唯一具名 Node 叶子及 op 集合，先接通 ingest→flatten | 首阶段完成（2026-11-13）；正常生产链及 v5 已迁移，原生22/22、比较器20/20；整机库存／差异清单完成，不等于全部行为对齐 |

F08 曾以本地 GSIM `a3ecb26` 的 `commonExpr()` 为依据保留源表达式边界。
当前方案保留 simplify 自由：之后才按提示/MFFC 形成执行 node，再按
node 数形成 SN；迁移及阶段顺序见 [architecture.md](architecture.md) 第 8–10 节。

## 推进记录规则

每阶段开始时核对两仓状态、输入身份及前置阶段；完成后在本表记录状态，并在
[steps.md](steps.md) 对应阶段追加实际提交、Make 命令、结果和证据目录。
未通过退出条件的阶段保持进行中，后续阶段可以做独立准备，不能把缺失语义
包装为已支持。设计变更先同步架构合约，再调整实现和回归。

工作流日志、临时源码和测量数据放在 `ptmp/firrtl-ingest/Fxx/`；CMake 测试
fixture 放在 `wolvrix/tests/ingest/data/`，测试产物沿用
`wolvrix/build/artifacts/`。不提交生成的香山 FIRRTL、SV 或仿真模型。
