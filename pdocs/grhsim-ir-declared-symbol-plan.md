# GrhSIM-IR declaredSymbol 语义锚点实施计划

| 字段 | 值 |
|---|---|
| 类型 | 独立实施计划（不属于 coremark 节点树） |
| 日期 | 2026-09-27 |
| 状态 | IMPLEMENTED（2026-09-28 落地，验证记录见 §7） |
| 范围 | GRH ingest（含 generate 块支持）、GRH transform pass（含删除 reg-to-mem/mem-to-reg）、hier_flatten、GRH→GrhSIM 转换与 GrhSIM IR 模型 |
| 关联文档 | [grhsim-ir-xiangshan-coremark.goal.md](grhsim-ir-xiangshan-coremark.goal.md)（禁令关系见 §6） |
| 修订 | 2026-09-27 r2：S2 中 reg_to_mem/mem_to_reg 的处置由"修复锚点迁移"改为"直接删除两个 pass"；r3：S1 中 generate 块内声明由"补齐为普通 declared"升级为"支持 + 结构化副本分组标注"（面向未来并行化） |

## 1. 背景与动机

GRH IR 的 declaredSymbol 是图/设计级的"源码显式声明符号"集合（`wolvrix/include/core/grh.hpp:692-696, 800-801`；语义定义见 `wolvrix/docs/grh/grh-ir.md:447-469`），它把用户源码中真实声明的端口/wire/reg/模块名与编译器内部生成的 `_val_*`/`_op_*` 名字区分开。目前它只被 GRH 侧的 DCE 保护、SV emit 的 wire 保留、遗留 grhsim_cpp 发射器的波形选信号消费；GrhSIM IR（`wolvrix/include/grhsim/ir/model.hpp`）中没有任何等价物，转换时该信息被整体丢弃。

战略转向：declaredSymbol 不只是调试辅助，而是**语义锚点**——它标记了"哪些值曾经对应用户笔下的信号"。两个 IR 的分工由此清晰化：

- **GRH IR 描述电路**：declaredSymbol 是受保护的语义锚点，pass 不得抹除；
- **GrhSIM IR 描述仿真**：declaredSymbol 是只读的来源注解（metadata），pass 可以读取以识别模块层次与语义信号，但不被它约束，可以照常改写被注解的实体。

分层原则有两个直接推论：

1. **reg↔mem 形态转换是仿真存储结构的决策，不是电路描述的一部分**，归 GrhSIM IR 层——`grhsim.reg-to-mem`（`wolvrix/lib/grhsim/pass/reg_to_mem.cpp`）已是生产管线关键 pass（NO00021 实测其价值：隔离移除代价 +13.747% Host，不可回退）。GRH 层的 `reg-to-mem`/`mem-to-reg` 两个 pass 与新 IR 管线完全无关，只服务旧 grhsim_cpp 管线和通用 emit 流程，且正是 declaredSymbol 锚点的最大破坏者。本计划在 S2 中直接删除它们，而不是为它们补锚点迁移。
2. **generate-for 展开的逐轮副本是同构计算结构，是未来并行化（向量化/多线程求值）的天然候选**。"哪些符号是同一 generate 声明的第 i 轮副本"这一分组信息只在 ingest 期可得（slang 的 `GenerateBlockSymbol.arrayIndex`），一旦展平改名就无法重建，因此必须在 ingest 期**结构化标注**，并随 declaredSymbol 一起携带到 GrhSIM IR。

本计划覆盖该思路的第 1-4 步（ingest 记录锚点 → pass 尊重锚点 → flatten 加注层次前缀 → 带入 GrhSIM IR）。第 5 步（GrhSIM pass 可取用语义、不受修改限制）作为设计原则直接落入第 4 步的数据结构形态，不单独实施。

## 2. 现状审计

以下结论均来自代码通读，行号随代码演进可能漂移，以符号名为准。

### 2.1 ingest 覆盖面

`markDeclaredSymbol`（`wolvrix/lib/core/ingest.cpp:16856-16863`）的调用点：

| 调用点 | 覆盖类别 |
|---|---|
| ingest.cpp:17127（createStorageOps） | register/latch 存储 |
| ingest.cpp:17169（createPortValues） | 模块端口 |
| ingest.cpp:17266（createSignalValues） | 顶层 wire/logic/reg，含 memory（unpacked 数组走同一路径） |
| ingest.cpp:21770/:21775 | Design 级用户模块名 |

缺口：

- **generate 块内声明不是"不标 declared"，而是根本不支持**。`collectSignals`（ingest.cpp:9884-9958）只扫 `body.members()` 顶层，不递归 `GenerateBlockSymbol`；`collectGenerateBlock`（:10181-10215）只收集实例；引用路径全部是裸名 `symbolTable.lookup`——表达式读（:7543-7563）失败报 "Unknown symbol in expression"，写目标（:8766-8777）失败报错，声明初始化器（:2218-2219, :2246-2250）失败**静默丢弃写意图**。唯一例外是层次路径引用（`gen_loop[3].sig`）走 XMR。另有隐患：裸名 lookup 遇同名碰撞会静默解析到错误符号。ingest 全文件未读取 slang 的 `GenerateBlockSymbol.name/arrayIndex/constructIndex/getExternalName` 中任何一个字段，`StmtLowererState` 没有作用域栈。
- 过程块内局部变量走内部符号（`handleProceduralLocalDeclaration` :2276-2334 → `internProceduralLocal` :4081），不标 declared。
- parameter/localparam 是 elaboration 常量，不产生 value/op，无锚点对象。
- 接口端口当前不支持（:9843-9847 直接拒绝），与本计划无关。

### 2.2 transform pass 守卫现状

`keepDeclaredSymbols` 全局默认 true（`wolvrix/include/core/transform.hpp:83, :241`）；`simplify` 是 const-fold + redundant-elim + dead-code-elim 的元 pass（`simplify.cpp:52-54`，:38 透传开关）。底层两个事实决定了守卫难度：

- `Graph::eraseOp/eraseValue` 删除实体时自动把符号移出 declared 列表（grh.cpp:3816-3919）——删除即锚点消失；
- `setValueSymbol/setOpSymbol`（grh.cpp:3956-3968）**不维护** declared 集合——直接改名会让旧 SymbolId 悬空。

逐个 pass 的守卫审计（`wolvrix/lib/transform/`，21 个文件）：已有正确守卫的是 dead_code_elim（:561-573, :902-906）、const_fold（`protectDeclaredSymbols` :1472，开启时折叠后物化 assign 保留 declared 值）、redundant_elim 大部分路径（`isTemporarySymbol` :159-175）、comb_lane_pack 与 xmr_resolve 使用**符号移植**范式（旧值改内部名、原 SymbolId 给语义等价的新值，comb_lane_pack.cpp:891-892、xmr_resolve.cpp:556-560）、instance_inline/repcut 克隆时传播、memory_read_retime:756-760。已确认的漏洞与处置：

| 位置 | 问题 | 处置 |
|---|---|---|
| redundant_elim.cpp:876-921 | kLogicOr always-true 路径对 1-bit result 无 declared 检查，`replaceUsers(result, constOne)` + `eraseOp` 使 declared 信号失去驱动 | S2 修复 |
| reg_to_mem.cpp:4587-4594 + :4197-4203 | 删除用户寄存器（declared 随之消失），新 memory 用合成名且不标 declared，寄存器锚点整体丢失 | **S2 删除整个 pass** |
| mem_to_reg.cpp:529-533 + :621/:693/:702 | 同上，memory 锚点丢失 | **S2 删除整个 pass** |
| strip_debug.cpp:908-924 | newTop 重建只 internSymbol 不 addDeclaredSymbol，成员身份丢失（不在主流水线，低优先级） | S2 修复 |

### 2.3 hier_flatten 改名现状

层次名机制已存在：`makeHierName`（hier_flatten.cpp:118-128）生成 `prefix$base`，`$` 分隔；实例分量经 `normalizeComponent`（:100-116）与 `uniqueInstanceComponent`（:130-146），符号冲突由 `internUniqueSymbol`（:148-161）追加 `_N`。当前行为受 `HierFlattenOptions::symProtect` 控制（`wolvrix/include/transform/hier_flatten.hpp:12-19`，默认 All；XS IR 流程 `scripts/wolvrix_xs_grhsim_ir.py:20` 用默认，HDLBits 流程 `scripts/wolvrix_hdlbits_grhsim.py:60` 用 `hierarchy`）：

- 顶图符号从不改名（:992-1001）；
- 端口映射时**父图 declared 名优先**，子图端口名丢弃（:369-372 early-return）；
- 子图 declared value/op 仅在 All 模式下改层次名并重新 `addDeclaredSymbol`（:672-680, :801-811）；其它模式下丢成 `_val_N`。

与 generate 的关系：generate 块不是 `kInstance`，flatten 不感知它；`makeHierName` 的 prefix 链只由实例名构成（:555 读 `instanceName` attr，ingest 存的是裸实例名 ingest.cpp:10115-10215，两处都不含 generate 分量）。今天 GRH 符号文本里完全没有 generate 作用域信息；ingest 期写入后，flatten 只叠加实例前缀，对 generate 标注中性。

### 2.4 GrhSIM IR 现状

`GrhSimModel`（model.hpp:536）无任何 declared 概念；字符串全部经 `StringInterner` intern 成 `StringId`（model.hpp:78-105）。最接近的 name/origin 是纯 metadata（`commitMetadataMutation`，model.hpp:554），且用户名与内部名一视同仁，无法回答"是否源码声明"。JSON（`wolvrix.grhsim.v1`，json.hpp:15）是 strict-key 顺序读（json.cpp:161-168），无未知字段跳过机制；可选尾字段有 `reader.comma()` 探测先例（json.cpp:858-867, :776-783，model.hpp:399-401 注释 "Optional for old checkpoints"）。转换器 `lowerGrhToGrhSim`（grh_to_grhsim.cpp:297-299）要求输入为展平图（:304-313），编排确认 hier-flatten 在 lower 之前（`scripts/wolvrix_xs_grhsim_ir.py:14-24, :200-227`）。

### 2.5 GRH 侧可用的注解挂载机制

为 generate 分组标注选型用的现状事实：

- **Operation attrs**（`setAttr`，grh.hpp:762；`AttributeValue` 支持 bool/int64/double/string 及 vector，grh.hpp:101-109）是唯一"免费全链路"机制：cloneGraph 复制（grh.cpp:183-186）、JSON 可选字段、load 容忍缺失（load.cpp:1467-1478）、flatten 克隆 op 时随 op 走。**但 Value 无 attrs**——wire 类声明只有 value、没有可挂靠的声明 op，op attr 覆盖不全。
- **SrcLoc**（grh.hpp:111-121）的 `origin/pass/note` 是调试字段，不应用来编码语义锚点。
- **Graph 级集合**目前只有 `declaredSymbols_`（JSON 必需字段，缺失报错 load.cpp:858）。新增 Graph 级映射需配套加成员/API/cloneGraph 复制段（grh.cpp:241-262）/store/load 字段；读侧应做成**可选容忍**（attrs 的风格），不复用 declaredSymbols 的"必需报错"风格，否则旧 JSON 全部失效。

## 3. 实施步骤

### S1：ingest 锚点补全（含 generate 块支持与副本分组标注）

目标：用户源码中声明的 wire/reg/logic/memory/端口全部进入 declaredSymbols；generate 块内声明在此基础上额外携带**结构化副本分组标注**。

改动点：

1. **支持 generate 块内声明**（前提性工作，比"标注"更大）：
   - `collectSignals`（ingest.cpp:9884-9958）递归进入 generate block 作用域收集 net/variable（含 `GenerateBlockArraySymbol.entries` 的逐轮 `GenerateBlockSymbol`），使其进入 `plan_.signals`；
   - **命名规则**：符号文本内嵌 generate 作用域分量，形如 `gen_loop$3$sig`（`$` 分隔、轮次下标为纯数字段），与 hier_flatten 的层次名风格一致。实施时确认 `normalizeComponent`（hier_flatten.cpp:100-116）的合法字符集，避免使用 `[`/`]` 等在 flatten 路径上会被清洗的字符；无名 generate 块用 slang `getExternalName()` 的 genblkN 名；
   - **作用域感知解析**：`StmtLowererState` 增加 generate 作用域栈，表达式读（:7543-7563）、写目标（:8766-8777）、初始化器（:2188-2250）的符号解析先按当前作用域前缀查找再回退裸名——同时修掉同名碰撞静默错解析与初始化器静默丢弃两个既有缺陷；
   - XMR 层次路径引用（:7565-7588）保持原样，但 XMR 目标解析到 generate 内信号时，目标名字应与新命名规则一致。
2. **副本分组标注**：Graph 新增 `generateGroups` 集合——每个 generate 声明（作用域路径 + 裸名标识）对应一组逐轮副本的 SymbolId 列表。选型理由：op attr 虽"免费全链路"但 Value 无 attrs、wire 声明无可挂靠的 op；Graph 级集合表达"分组"语义最直接。配套：成员 + API、cloneGraph 复制段（grh.cpp:241-262）、store/load 新字段（读侧**可选容忍**，沿用 attrs 风格，旧 JSON 不受影响）；组内成员符号同时照常 `addDeclaredSymbol`（declared 语义不变，分组是叠加信息）。
3. 明确**不纳入**的类别，写入文档：parameter/localparam（elaboration 常量，无实体）；过程块内局部变量（过程内临时量，不对应模块级信号）。若未来需要覆盖过程块变量，作为独立可选项另立项。

验收：含 generate-for（N 轮、块内有 reg/wire 声明且被引用）的 SV 用例 ingest 后——每轮副本符号出现在 `graph.declaredSymbols()` 且名字含作用域分量；`generateGroups` 组数与每组 N 个成员正确；generate 内与顶层同名碰撞的用例解析正确（不再静默错解析）；初始化器不再静默丢弃；`wolvrix/tests/{grh,ingest}` 既有测试全过；更新 `wolvrix/docs/grh/grh-ir.md` 4.3.2 节（覆盖范围 + generateGroups 定义）与 `wolvrix/docs/grh/grh-json-spec.md`（新字段）。

### S2：pass 守卫收敛（含删除 reg-to-mem / mem-to-reg）

先形式化不变量（写入 `wolvrix/docs/grh/grh-ir.md`）：

- **I1**：携带 declaredSymbol 的 value/op 不被任何 pass 删除（既有 keepDeclaredSymbols 机制承载）。
- **I2**：携带 declaredSymbol 的 value/op 不被直接改名；唯一允许的改名是**符号移植**（原 SymbolId 转移给语义等价的新值），declared 身份随 SymbolId 自然转移。
- **I3**：GRH 层不做实体合并/形态转换类变换（reg-to-mem/mem-to-reg 因此删除）；克隆/内联类 pass 必须传播 declared 身份与 generateGroups 分组信息（instance_inline、repcut 的已有传播路径需扩展到分组）。
- **I4**：`Graph::eraseOp/eraseValue` 的 declared 自动维护（grh.cpp:3816-3919）扩展到 generateGroups——删除实体时同步从分组中移除，避免悬空成员膨胀。

改动点：

1. **删除 GRH 侧 `reg-to-mem` / `mem-to-reg` 两个 pass**。XS IR 新管线（`scripts/wolvrix_xs_grhsim_ir.py` 的 GRH_PIPELINE）不调用它们，删除对新管线零影响；reg↔mem 需求由 GrhSIM 侧 `grhsim.reg-to-mem` 承载。删除清单：
   - 源与头：`wolvrix/lib/transform/reg_to_mem.cpp`、`mem_to_reg.cpp`、`wolvrix/include/transform/reg_to_mem.hpp`、`mem_to_reg.hpp`；
   - 注册：`wolvrix/lib/core/transform.cpp` 的 include（:12/:16）、known-passes 清单（:425-426）、工厂分支（mem-to-reg :1542-1589、reg-to-mem :1607-1666）；
   - 构建：`wolvrix/CMakeLists.txt:157-158` 源文件条目与 `transform-reg-to-mem` 测试目标（:702-705 起）；
   - 测试：`wolvrix/tests/transform/test_reg_to_mem_pass.cpp` 删除；`wolvrix/tests/emit/test_emit_grhsim_cpp.cpp`、`wolvrix/tests/transform/test_activity_schedule_pass.cpp` 中依赖 reg-to-mem 的用例改写或删除；
   - pybind：`wolvrix/app/pybind/wolvrix/__init__.py` 的分发分支（:545-548）与 `_compile_mem_to_reg_kwargs`/`_compile_reg_to_mem_kwargs`（:659-701）；
   - 流水线脚本：`scripts/wolvrix_xs_grhsim.py`（旧 grhsim_cpp 管线）删除 reg-to-mem 段（:481-490）、mem-to-reg 可选段（:504-508）、`pre_reg_to_mem_json` resume 机制（:352-362, :538-545, :572-576）与相关 env 开关和日志（:387-397, :440-447）；`scripts/wolvrix_emit.py:110` 移除 `mem-to-reg` 阶段；`scripts/wolvrix_xs_emit.py:71` 清理已注释的 mem-to-reg 行；`Makefile:158` 的 `XS_WOLF_GRHSIM_PRE_REG_TO_MEM_JSON` 及其引用处；
   - 文档：`wolvrix/docs/emit/grhsim-scheduling.md` 等涉及 GRH reg-to-mem 的描述。
2. **连带清理 intent 死代码**（建议作为独立子任务、单独提交）：GRH reg-to-mem 的 intent 模式（旧管线默认开启，`scripts/wolvrix_xs_grhsim.py:387-388`）只在寄存器上打标记，实际聚合由 grhsim_cpp 发射器完成。pass 删除后 intent 属性再无生产者，消费方成为死代码：`grhsim_cpp.cpp` 的 intent 存储合并与校验（:2219 stats 原因位、:4517-4520 字段命名、:4733-4737 别名、:7069-7127 校验）、`activity_schedule.cpp:2369` 的 intent group 重叠检查。注意 grhsim_cpp 同时是 declaredSymbol 的消费方（波形选信号/调试索引），那部分保留，只移除 reg-to-mem intent 路径。
3. `redundant_elim.cpp:876-921`：kLogicOr always-true 路径补 `isDeclaredValue` 检查，命中时跳过替换（或按 const_fold:866-870 范式物化 assign）。
4. `strip_debug.cpp:908-924`：newTop 重建补 `addDeclaredSymbol`（低优先级）。
5. I4 落地：`eraseOp/eraseValue` 系列（grh.cpp:3816-3919）增加 generateGroups 成员清理。
6. 确认两条 Python 流水线脚本均未显式关闭 `keepDeclaredSymbols`；在 pass 文档或 transform.hpp 注释中固化"默认不得关闭"。
7. 可选增强：在 Graph 增加调试期校验接口（遍历 declaredSymbols，每个 SymbolId 应能 findValue/findOp；generateGroups 成员同理），供测试调用，把不变量变成可执行断言。

验收：ctest 全过（含移除相应测试目标后的套件）；hdlbits 回归全过；XS IR 新管线 checkpoint 与删除前语义数组一致（它不调用被删 pass，预期零差异）；旧 grhsim_cpp 管线与通用 emit 流程可运行，输出形态变化（寄存器不再聚合进数组存储、memory 不再拆成寄存器）经抽查等价；为 redundant_elim 漏洞构造最小回归用例；generateGroups 的 erase 清理有单测覆盖。

### S3：flatten 层次化前缀

目标：flatten 消除模块边界时，所有 declaredSymbol 一律加注实例路径前缀，形成 `inst$inst$...$name` 层次化路径（generate 副本符号则为 `inst$gen_loop$3$sig`，实例前缀叠加在 ingest 期已写入的 generate 分量之前）；顶图符号保持原名（路径之根）。

改动点：

1. `shouldProtectValue`（hier_flatten.cpp:594-606）与 `shouldProtectOp`（:607-619）的判定与 symProtect 模式解耦：凡 `isDeclared` 一律走层次名 + `addDeclaredSymbol`，不再只有 All 模式保护。这使 `hierarchy` 模式的 HDLBits 流程也保留全部用户符号，行为变化需回归确认。
2. **generateGroups 的 flatten 移植**：子图克隆进主图时，分组信息随 declared 身份一起传播（与 :672-680/:801-811 的 declared 传播同路径），组内 SymbolId 重映射到克隆后的新符号；分组键中的作用域路径叠加实例前缀。
3. 端口映射冲突维持现状：父图 declared 名优先（:369-372 不变），子图端口名丢弃。决策 D1：不引入双名/alias——端口映射两侧是同一电气节点，父名本身就是更外层的层次路径，满足"可解析"要求；若未来波形需要同时看到子模块端口名，在 S4 之后作为独立增强评估。
4. 顶图符号保持原名，写入不变量。

验收：多实例嵌套用例 flatten 后，子图 declared 符号全部为 `$` 连接的层次路径且可 `findValue` 解析；顶图原名保留；冲突时 `_N` 去重仍生效；嵌套实例内含 generate-for 的用例，flatten 后分组完整、组内名字为 `inst$...$gen_loop$i$sig` 形态；GRH JSON 往返集合一致（扩展 `wolvrix/tests/grh/test_grh.cpp:274-279` 的断言到层次名与分组形态）；hdlbits 与 XS IR 两条流水线的扁平化结果 diff 符合预期（仅命名形态变化，无语义变化）。

### S4：GrhSIM IR 携带 declaredSymbol 与 generateGroups

目标：flatten 后的 declaredSymbol 集合与 generateGroups 分组（已是层次路径形态）完整进入 GrhSIM IR，并随 checkpoint 往返。

设计原则（第 5 步落地）：GrhSIM 侧两者都定位为**只读 metadata**——纯符号名（组）列表，不存实体 ID、不构成语义约束、pass 无维护义务。理由：`compact()` 会重编号全部 Value/State/Op（model.cpp:401-486，全库 8 处调用点），存 ID 必然悬空；而"锚点实体已被改写"恰恰是仿真 IR 的常态。这正是两个 IR 分层在数据结构上的体现。未来并行化 pass 消费 generateGroups 时按名字 `findValue` 现查、自行验证同构性，分组信息只作候选提示——这符合 goal.md:7"方案必须由语义、依赖、位宽、读写属性等通用特征触发"的纪律（分组提供候选集，等价性由语义验证兜底）。

改动点：

1. **模型**：`GrhSimModel` 新增 `declaredSymbols_`（`std::vector<StringId>` + 去重集）与 `generateGroups_`（组列表，每组为 `std::vector<StringId>`，附组标识字符串），镜像 GRH `Graph` 的 API 形态；变更走 `commitMetadataMutation()`。**必改 `clone()`**（model.cpp:147-183 逐字段显式拷贝，漏掉即静默丢数据）；可选加 `ModelReserve` 计数与 verifier 的 StringId 合法性校验（`writeGrhSimJson`/`readGrhSimJson` 均强制 verify，json.cpp:1410/:1434，加了即双向覆盖）。
2. **转换**：`lowerGrhToGrhSim` 尾部（return 前）遍历 `graph->declaredSymbols()` 与 `graph->generateGroups()`，取文本、去空去重（可参照 grhsim_cpp.cpp:9286-9295 的 seenSymbols 模式），intern 后写入模型。新增 `GrhToGrhSimOptions::keepDeclaredSymbols`（默认 true，独立于 keepOrigins——origins 量大可关，符号与分组列表小，默认保留），pybind 同步（`wolvrix/app/pybind/native/actions/grhsim.cpp:42-46`、`wolvrix/app/pybind/wolvrix/__init__.py:238-268`）。
3. **JSON**：在 mappings 之后追加可选尾键 `declaredSymbols` 与 `generateGroups`，读侧用 `reader.comma()` 探测（沿用 json.cpp:858-867 先例），缺省为空集合；**不 bump 版本号**。旧 checkpoint 新 reader 可读；新 checkpoint 旧 reader 报错，与既有尾字段先例一致。
4. **pass 影响面**：`wolvrix/lib/grhsim/pass/` 13 个 pass **零改动**——名字（组）列表与实体无引用关系，任何 pass 改写实体都不会使其悬空。未来若出现"按锚点选实体"的需求（如波形信号选择、并行化候选），在消费侧 `findValue` 现查或另建诊断索引，不进 IR。

验收：XS IR 全流程生成 checkpoint，declaredSymbols 非空、generateGroups 与 GRH 侧逐组一致；checkpoint 往返后两者一致；旧格式 checkpoint 可读；更新 `wolvrix/docs/grhsim_ir/overview.md`（metadata 清单）与 `wolvrix/docs/grhsim_ir/flows/cpu-st.md`。

## 4. 全局验收

- S1-S3 只改命名与锚点保留，不改电路语义：hdlbits 全量回归 + XS IR 流程 checkpoint **语义数组口径**比对（沿用 NO00020 修订 1 的判据，不用字节口径，因为命名会变）。
- S1 的作用域感知解析改动 ingest 深层路径，可能影响既有设计的解析结果：除单元测试外，用 XS 与 hdlbits 全套设计做 ingest 前后对照（op/value 语义集合一致，仅符号命名与 declared 集合变化）。
- S2 的删除改动影响两条非生产流程：旧 grhsim_cpp 管线（`wolvrix_xs_grhsim.py`）与通用 emit 流程（`wolvrix_emit.py`）。两者须各跑一次端到端确认可用、输出经抽查等价；hdlbits 回归覆盖 emit 侧大部分风险。
- S2 的守卫修复让原本被消掉的 declared 信号存活到 DCE 之前，可能改变 GRH op 数与生成时间：在 XS IR 流程实测一次完整生成，确认无超门槛回退；仿真性能预期在噪声内（declaredSymbol 在 GrhSIM 侧无保护作用，影响止步于 GRH 阶段）。
- generate 端到端：含 generate-for 的设计走完 XS IR 全流程，checkpoint 中分组与 declared 完整，仿真结果与基线等价。
- 全部测试经 Makefile 目标执行，产物落 `ptmp/`。

## 5. 风险与开放问题

- R1：generate 副本命名规则与 `normalizeComponent` 合法字符集的兼容性需实施时确认；若 `$`/数字段不足以消歧（嵌套 generate、无名块与命名块混合），命名规则需扩展但保持 flatten 路径安全。
- R2：作用域感知解析是 ingest 深层改动，存量设计若依赖了"裸名命中顶层符号"的（错误）行为，修复后解析结果会变——靠 §4 的对照验收兜底，不设单独开关。
- R3：旧 grhsim_cpp 管线删除 reg-to-mem 段后，输出形态与性能会变化（寄存器不再聚合进数组存储）。该管线已被 XS IR 管线取代，判为可接受；若仍需旧管线性能可比性，实施前须单独评估。名称配对诊断脚本里的 `__reg_to_mem_` 前缀来自 GrhSIM 侧 pass（`scripts/grhsim_gsim_module_compare.py:250-256`），不受 GRH 侧删除影响。
- R4：通用 emit 流程移除 mem-to-reg 阶段后，memory 保持存储形态 emit，依赖"memory 拆寄存器"形态的下游（若有）需回归确认。
- R5：D1（端口映射不引双名）使子模块端口名在扁平化后不可见，波形/调试场景若需要再评估。
- R6：与"禁止名称匹配优化"纪律的关系：declaredSymbol 与 generateGroups 是来源属性，不是名称文本匹配，作为诊断/锚点/候选集不违反禁令。未来并行化 pass 以 generateGroups 为**候选来源**时，触发与等价判定必须落在语义验证上（见 S4 设计原则）；若想让 declared 身份本身成为优化触发条件，须先回到 goal 层面由用户裁定。本计划 S1-S4 不引入任何此类优化。

## 6. 与 coremark goal 的关系

goal.md:7 禁止"修改冻结的 GRH IR、GRH 上已有 pass"。S1-S3 恰好修改 GRH ingest、既有 pass（含删除两个 pass）与 hier_flatten，因此本计划**不能**作为 coremark 节点树的节点执行，是独立的基础设施变更。若实施：

- 实施期间 coremark 优化节点应暂停，或以本计划完成后的代码重建基线；
- 完成后 coremark 侧的 checkpoint 复现判据（语义数组口径）不受影响，但一切名称配对类诊断脚本需按新命名形态适配；
- 本计划预期改善 NO00020 式模块级对比的名称锚点配对率，长期服务于 goal.md:11-14 所述"消除 Firtool/GRH 转换造成的形态差异"方向，但它本身不承诺性能收益。

## 7. 实施记录（2026-09-28）

S1-S4 已全部落地（wolvrix 子模块未提交工作区 + 根仓库 Makefile/scripts）。实施中的解释性决策与偏差：

- **D2（S3 组 name 不加前缀）**：flatten 传播时 generateGroups 的 `scope` 叠加实例前缀（`u_m1$gen_loop`）、`name` 保持裸声明名，成员符号为完整层次名（`u_m1$gen_loop$i$sig`）。只有 name 保持裸名时"成员 = scope`$i$`name"才可重建，与 §3-S3"分组键中的作用域路径叠加实例前缀"一致。测试已锁定该形态。
- **S1 作用域解析的实现选型**：未采用文本前缀链作用域栈，改用 slang 符号指针恒等映射（`ModulePlan::signalBySlangSymbol` + 自由函数 `lookupPlanSignal`，指针映射优先、裸名兜底），覆盖 14 处解析点；同时修复同名碰撞静默错解析与初始化器静默丢弃（解析失败现报诊断）。
- **GrhSIM metadata 的 revision 约定**：`addDeclaredSymbol`/`addGenerateGroup*` 不自调 `commitMetadataMutation()`——模型既有纪律是构建方法从不自提交 revision，由 PassManager/construction 边界统一提交，且 JSON 读侧要求 loaded revision 从 1 开始。契约写入 model.hpp 注释。
- **新增调试校验**：`Graph::validateDeclaredSymbols()`（declared/generateGroups 成员悬空检查），单测覆盖正负用例；顺带实证 `setValueSymbol` 改名不维护 declared 的既有缺口可被该接口捕获。
- **XMR 进 generate 作用域**为新支持能力（此前必然失败）：`xmr_resolve` 在 `findInstanceOp` 失败后尝试把剩余段组合为 generate 叶名（`gen_loop[3].sig` → `gen_loop$3$sig`）。跨实例+generate 混合路径逻辑支持、未加专门测试。
- **S2 删除执行**：GRH 侧 reg-to-mem/mem-to-reg 全链路移除（源/头/注册/CMake/测试/pybind/脚本/Makefile/文档），intent 死代码（grhsim_cpp 发射器 intent 合并/校验、activity_schedule intent group）同步清理；`scripts/wolvrix_xs_grhsim.py` 的 stats pass 改挂 pre_sched_pipeline（行为等价重构）。GrhSIM 侧 `grhsim.reg-to-mem` 未动。
- **遗留偏差（有意保留）**：旧管线 `scripts/wolvrix_xs_grhsim.py` 对 simplify 仍默认 `keep_declared_symbols=False`（env 可开），翻转默认会改变旧管线行为/性能，超出本计划范围；新 IR 管线与 hdlbits 管线均未关闭。
- **预存失败基线**：ctest 54 测中 3 个预存失败（transform-comb-lane-pack、transform-repcut、ingest-write-back-slice SEGFAULT，经 stash 基线实证与本改动无关）；hdlbits IR 套件 161/162（105 为预存 grhsim.used-bits 失败）、Verilator 套件 154/162（042/043/060/062/071/116/117/118 均为预存 TB 对 Verilator 宽信号 `get_bit` 族helper 不兼容的编译失败，测试源码冻结不修）。改动后两轮回归与该基线逐点一致、零新增失败。

验证（2026-09-28，wolvrix `c69ac80`）：XS coremark 100k 全流程（继承生产开关 + 动态 profile 自举 + clang 三阶段 PGO）9 次运行端点全一致（`240349/99996/100001/0x80000c0c`）、DIFFTEST 干净；完整生成 828.10 s、PGO 构建 656.99 s，均过 1800 s 门槛；checkpoint 携带 declaredSymbols 1,208,313 条（层次路径形态）、generateGroups 空（XS 无 generate 块）。Host 48.798 s（3 次有效，SD 0.168 s），同窗口 NO00024 归档 48.947 s，统计不可分辨（p=0.35）——预期回退未实测出现。新基线已登记到 [grhsim-ir-xiangshan-coremark.goal.md](grhsim-ir-xiangshan-coremark.goal.md) 当前性能锚点节，后续优化从该基线出发。
