# Stage 04 实施工作笔记（非规范文档，规范见 stage-04-ingest-aggregate.md）

> 本文件是实施过程的工作记录，随实施进度更新；最终偏差会整理进 stage-04 头部实施记录。

## S4 实施单元划分（对 stage-04 §7 的细化）

- **S4-a 状态数组多维化**（进行中）：声明 shape（变量数组）+ 多索引端口族直连 +
  whole read/write 直连 + 同地址写合并退役 + FillPort 停产 + emitPackedAggregateWholeRead 删除
- S4-b net/packed 数组 shape 化：net 数组 value shape + kSliceArray 多索引 +
  svPackedArray.* 注解移除 + 端口 shape
- S4-c struct 字段级拆分

## S4-a 设计定稿（2026-10-09）

### 数据结构
- `SignalInfo` += `shape`(vector<int64_t>，GRH 形状，空=标量) 与
  `packedDimInfos`(vector<UnpackedDimInfo>，packed 每维 extent/left/right，写路径 lane 归一化用)；
  `packedDims`(extent 列表) 保留不动。
- `PortInfo` += `shape` / `packedDims` / `unpackedDims`（端口不再平化）。
- `MemoryReadPort/MemoryWritePort`: `address` → `addressIndices`(vector<ExprNodeId>)。
- `width` 语义不变：数组信号的元素宽（最内层位类型宽）；总位宽 = width × ∏shape。
- `memoryRows` 语义不变（兼容 $readmemh/init）：unpacked 积；纯 packed 变量 = shape[0]。
  纯 packed 变量成为数组状态的门槛保持旧值：shape[0]>1 && 元素宽>1（旧
  analyzePackedElementMemoryType 条件），低于门槛仍标量（不带 shape）。
- `isPackedAggregateVariable` 重定义：非 Net/Memory && memoryRows>0 && unpackedDims.empty()
  （旧定义 packedDims.empty() 是 reinterpretation 副作用，随 reinterpretation 删除失效）。

### analyzeSignalType
- shape = unpacked extents（leading）+ packed dims（trailing，标量元素时去掉最内层=元素位宽；
  struct/union 元素时全部 packed 维进 shape）。
- analyzePackedElementMemoryType 删除；collectVariable 不再改写 width/memoryRows。

### 读路径（pass4 + GraphAssembler）
- rank = shape.size()；允许 1..rank 个索引（k<rank = 部分读，结果子数组 shape[k:]）。
- 链式走查记录 per-level op kind：kSliceDynamic level = unpacked 维（raw index，pass4 按
  UnpackedDimInfo 归一化）；kSliceArray level = packed 维（StmtLowerer 已 lane 归一化，
  pass4 直通）。level 位置 ≥ rank 的留在 replacement 之上（行内位选，现状截断逻辑保留）。
- buildLinearAddress → 逐维归一化的 index 列表（不乘 stride 不加和）。
- emitMemoryRead: k 个索引操作数 → kRegisterReadArrayPort；result 宽 = elemW×∏shape[k:]，
  shape=shape[k:] 回填；findReusableMemoryRead 比较索引列表。
- whole read：统一 kRegisterReadPort（ensureMemoryReadValue，width=totalWidth+shape 回填，
  缓存 valueBySymbol_）；emitPackedAggregateWholeRead 与 packedAggregateWholeReadBySymbol_ 删除；
  valueForSymbol/emitExpr Symbol/createPortValues 三处调用点改走统一 ReadPort。

### 写路径（pass4）
- slices[0..k-1]  leading BitSelect = 数组索引（k = min(leading BitSelect 数, rank)）；
  之后至多 1 个 data slice（行内位/段写）。
- 归一化：dim i < unpackedDims.size() → 界归一（raw）；否则 packed lane
  （downto: idx-low；upto: high-idx，用 packedDimInfos）。
- 无 data slice → **kRegisterWriteArrayPort**（ingest 首次产出无 mask 形态，全 1 mask 合成删除）；
  有 data slice → kRegisterWriteArrayMaskPort，mask/data 宽 = 被寻址子数组宽
  （elemW×∏shape[k:]，k=rank 时=元素宽）。
- 整体写（slices 空）+ 有索引访问 → **kRegisterWritePort**（WritePort 整体写，
  FillPort 生产路径删除；`'{default:x}` 广播形态由全宽值 WritePort 承接）。
- 同地址写合并 mergeSameAddressMemoryWrites **删除**（S3 语义：同 regSymbol 声明顺序即
  优先级，后声明覆盖，与 SV 语句序一致；else-if 链 guard 互斥，顺序无关）。
- 多维 unpacked 部分写（k<rank）从报错变为合法（WriteArrayPort 子数组写）。

### emit 侧
- ensureMemoryOp: shape=info->shape 多维；totalWidth=width×∏shape；同时确保 ReadPort 存在。
- emitMemoryWrites: mask invalid → WriteArrayPort / valid → WriteArrayMaskPort；多索引 operands。
- emitMemoryFills 删除（memoryFills 无生产者）；createMemoryOps/isMemoryBackedPackedAggregate
  不再查 memoryFills。kRegisterFillPort kind 保留（IR 层能力，ingest 暂不产出）。
- ensureConnectionMemoryRead 同步多索引化。

### init 路径
- formatPackedAggregateInitRows: rows=shape[0]（shape 非空时），rowWidth=total/shape[0]。

### 暂缓/不做（本单元）
- MemoryPortLowererPass 整体保留（读出去重/同步降级/updateCond 处理仍需要），
  但内部多索引化；pass 完全退役评估推迟到 S4 收尾（实施偏差，登记）。
- RangeSelect 作为首 slice 的写（`states[3:0] <= x`）保持报错（旧行为）。
- struct/union 元素数组：shape 计算支持（元素=struct 扁平宽），struct 拆分布 S4-c。
- XMR 路径不动（S3 已适配端口族）。

## 验证策略（用户要求：XS preserve-aggregate 真实 SV）
- 单元关卡：现有 ctest + hdlbits + xsbug + baseline 全绿。
- S4-a/b 后：ingest `ptmp/xs-aggr-build/rtl/`（=all，2148 文件，含 struct——S4-c 前预期
  struct 模块失败）+  regenerate =vec split（firtool --split-verilog）做全量通过验证。
- S4-c 后：=all split 全量 ingest + grh.verify + 抽查形状（states → shape=[32]、
  takenCounter → [4,32,8]、robEntries 字段拆分）。
- 终极仿真验证属 S7（需 S5/S6）。

## S4-a 实施日志（2026-10-09）

已完成（待门禁确认）：
- 类型层：TypeResolution/SignalInfo/PortInfo +shape（+packedDimInfos 写路径 lane 归一化）；
  analyzePackedPart 共享 shape 计算（unpacked 前导 + packed 去内层元素位宽；struct/union
  元素全维进 shape）；analyzePackedElementMemoryType 删除；collectVariable 门槛保持旧值
  （shape[0]>1 && 元素宽>1），低于门槛折回总宽标量；端口不再平化（总宽+shape）。
- pass4：多索引读写（rank=shape.size()，1..rank 索引，部分索引=子数组）；读链 replacement
  =最后被消费层节点（修掉了多级链整链被重复发射的 bug——旧代码对多维读同样有此问题，
  只是无多维读测试覆盖）；写路径 leading BitSelect=索引 + 至多一个行内 data slice；
  无 data slice → kRegisterWriteArrayPort（ingest 首次产出无 mask 形态）；整体写（有索引
  访问）→ kRegisterWritePort；mergeSameAddressMemoryWrites/mergeIndexedMemoryWrites 删除
  （S3 声明顺序即优先级）；buildLinearAddress ×2 删除。
- GraphAssembler：whole read 统一 kRegisterReadPort（ensureMemoryReadValue 懒创建，
  emitPackedAggregateWholeRead 逐行拼接删除）；emitMemoryRead 多索引 + 结果 shape 回填；
  emitMemoryWrites 三态分派（WritePort/WriteArrayPort/WriteArrayMaskPort）；emitMemoryFills
  删除（FillPort ingest 停产，kind 保留）；ensureConnectionMemoryRead 多索引化；
  replaceWholePackedAggregateReads 接受 ReadPort 形态（rank-1 限定）。
- 修的 bug：createPortValues 对"信号为 packed aggregate 的输出端口"误建 ReadPort
  （需 isMemoryBackedPackedAggregate 区分）；WriteBackPass widthBySymbol 对 packed net
  数组取元素宽导致写投影错位（统一 signalTotalWidth）。
- 测试适配：memory-port-lowerer 5 处（多索引断言 + priority 无合并双端口断言）；
  write-back-slice 2 处（fill→整体写断言、行拼接 whole read→ReadPort 断言）；
  ingest 套件 16/17（write-back-slice SEGFAULT 与既有基线同点
  testWriteBackPackedArraySelfSliceAcyclic）。

环境/形态事实（非 bug）：
- `'{default: x}` / 位置化 `'{...}` 赋值模式在 always 块内是既有 Unsupported expression
  （非 S4 引入；firtool aggr 输出含 200k+ 处 `'{'，assignment pattern 表达式 lowering
  是后续工作项，登记）。
- split SV 文件互相引用模块（unknown module）与 xs_assert_v2 宏（未定义）——smoke 按
  依赖跳过；全量编译需 filelist 形式（S7）。
- =vec split 已生成：ptmp/xs-aggr-vec-split/（2119 文件，firtool 1.135.0）。

探针（ptmp/stage04/s4a_probe.sv）：states → kRegister w=224 shape=[32] +
WritePort(rst 整体写) + WriteArrayPort(动态写) + ReadArrayPort(动态读) + ReadPort(整体读)；
cube[16][16]×8 → shape=[16,16] + 多索引 WriteArrayPort/ReadArrayPort + 部分读
（ReadArrayPort[a0] → w=128 shape=[16]）；grh.verify 通过；SV emit 正确
（unpacked 声明、索引读、行拼接、整体写循环）。

### grhsim 过渡承接（S4-a 追加，属"下游适配"提前量）
- 数组寄存器 → **扁平 core.array 状态**（∏shape 元素一维），多维下标元组在转换边界
  行主序线性化（mul/add compute op）；rank=1 与 S3 零差异。
- 数组整体写（WritePort+shape 目标）→ memFill（packed fill，core.md §例外条款）。
- 数组整体读（ReadPort+shape 目标）→ 逐元素 memRead + 行主序 concat（S3 的
  emitPackedAggregateWholeRead 等价物下移）。
- 部分索引读（k<rank）→ 线性化前缀 + 逐元素展开 memRead + concat；部分索引写 →
  逐元素 memWrite 展开（data/mask sliceStatic 切片）。
- 修复 CASE_012 回归：WritePort 数组目标原样映射 regWrite 导致 CPU emit
  "not two-state logic"。

### 门禁快照（2026-10-09，S4-a 合入点）
ctest 56/58（基线 2 例：transform-repcut、ingest-write-back-slice SEGFAULT，同点持平）；
hdlbits 162/162；xsbug 25/25；baseline 162/162。

### XS preserve-aggregate smoke（=vec split 2119 文件，逐文件 ingest+grh.verify）
1237 OK / 766 跨文件依赖 SKIP / 复检后真失败 2：
- DstMgu：net 数组 value 缺声明 shape（S4-b 范围：createSignalValues 回填后自愈）；
- Phr：emitExpr 无限递归栈溢出——**HEAD 基线同样崩**（既有组合环无防护，登记既有）。
既有告警类（HEAD 同行为，登记不追查）：initial/final 赋值忽略（5 文件）、
组合域 memory 写跳过（ICacheReplacer/IntFile）。
=all 无结构体子集 529 文件：361 OK / 164 依赖 SKIP / 1 既有告警 / 4 崩溃已修
（packedDims 空时 analyzePackedPart 越界——`reg Memory[0:N]` 无 packed 维元素）。

## S4-b 实施日志（2026-10-09）

- 声明 shape 回填：createSignalValues（net/变量数组 value）、createInoutSignalValues、
  createPortValues 输入/输出分支——数组 value 携带声明 shape（纯结构视图）。
- unpacked net 数组元素读 → 多索引 kSliceArray（buildNetArrayIndices，逐维归一化索引，
  不再位偏移线性化）；emitExpr kSliceArray 支持 1..k 索引（全常量折叠为 kSliceStatic，
  部分索引=子数组 baseShape[k:]）；写路径 buildNetArraySlice 行宽修正（元素宽×packed 维）。
- grh_to_grhsim：多索引 kSliceArray → 线性化 lane + sliceDynamic（单索引保持 sliceArray
  过渡形态零差异）。
- svPackedArray.* 注解整体移除（写入点 annotatePackedArrayConcatDefop、调用点、3 个测试
  文件的断言——slice 测试改断言声明 shape，grh/grh_clone 测试删除冗余 attr 段）。
- 下游适配（探索子代理缺口清单）：hier_flatten/instance_inline 克隆 value 传 shape +
  端口映射 shape 传播（propagatePortShape：child 有 shape、parent 无且同宽 → 回填）；
  xmr_resolve 的 ensureInputPort/ensureInstanceOutput/PendingPort/forceSingleDriver/
  rebind_output 线程 shape。XMR 读数组寄存器仍不支持（登记 S6）；verify 的 kInstance
  shape mismatch 保持 warning（登记，暂不提 error）。
- 门禁：ctest 56/58（基线）、hdlbits 162/162、xsbug 25/25、baseline 162/162。
- smoke：=vec 2119 文件 1319 OK / 766 依赖 SKIP / 1 HEAD 既有崩溃（Phr）；=all 无结构体
  子集 366 OK / 163 依赖 SKIP / 0 真失败。DstMgu 已随 shape 回填自愈。

## S4-c 设计定稿（2026-10-09，struct 字段级拆分）

### 类型树展开
- 拆分器：`splitStructType(type, baseName) -> [{fieldPath, TypeResolution}]`，递归展开
  PackedStructType/UnpackedStructType 的 FieldSymbol（按声明序）；数组维度（unpacked+packed）
  迁移到每个叶子字段信号（外层维度在前、字段自身维度在后）；叶子字段走 analyzePackedPart
  判定 shape/宽度。命名：`c__DOT__a`、`c__DOT__f__DOT__x`（DOT 编码，gsim/Verilator 惯例）。
- 非位类型字段（Real/String/事件）→ ConvertDiagnostics error；union 首版报错
  （packed union 也是 integral，但字段重叠语义与拆分不兼容，留待评估）。
- ModulePlan 增加 struct 注册表：struct symbol → 字段列表（fieldPath + PlanSymbolId +
  叶子 TypeResolution），供表达式投影与整体操作枚举。

### 表达式表示
- 新增 AggregateValue = 按声明序的 {fieldPath, ExprNodeId} 列表（ingest 内部表示，
  不进入 GRH）。struct 类型表达式经 lowerAggregateExpression 产 AggregateValue；
  主 lowerExpression 保持标量-only。
- NamedValue(struct symbol) → 逐字段 value 引用；MemberAccess → 子组投影；
  ElementSelect(struct array) → 逐字段 kSliceArray/数组端口；`'{f: v}` / `'{v, ...}` →
  逐字段 RHS（default → 广播；嵌套递归）。
- 需要扁平位布局的场合（cast 为整型/算术/$bits/streaming/整体 XMR）：按声明序
  kConcat 现场重建（布局是类型的纯函数）。
- 整体操作逐字段展开：赋值=逐字段连接；相等=逐字段 kEq 后 kAnd 归约（不等=kOr）；
  mux/ternary=同 cond 逐字段 kMux；端口连接=按布局匹配的逐字段连接。

### 端口与实例
- struct 端口同样字段级拆分（PortInfo 叶子条目，名字 `io__DOT__bits__DOT__...`）；
  模块端口列表 = 拆分后叶子端口；kInstance 连接处（emitInstances）对 struct 端口生成
  逐字段连接（两侧同一拆分算法，名字天然匹配）。
- hier_flatten/instance_inline 的 propagatePortShape（S4-b）已承接拆分后端口。

### 写路径
- struct lvalue：resolveLValueSymbol 遇到 MemberSelect → 解析到字段信号 + 剩余 slice
  （替换 resolveMemberSlice 的位段路径）；整体 struct 写 → 逐字段 WriteIntent；
  struct 数组元素动态写 → 字段数组的 WriteArrayPort 族（S4-a 机制直接复用）。
- 存储分类：字段信号各自独立走 S4-a 决策（kRegister+shape / 标量），ROB 形态
  （robEntries__DOT__wflags[352] 等）自然落地。

### 渐进实施顺序
1. 拆分器 + 声明/注册表 + 读路径（NamedValue/MemberAccess/ElementSelect/投影）
2. 赋值模式 `'{...}` 与整体 struct 写
3. 整体操作展开（eq/mux/cast）+ 端口/实例连接
4. XS =all smoke 逐项清零（73090 处 struct packed）

## S4-c 实施日志（2026-10-09，struct 字段级拆分）

### 架构落地
- **拆分器**：`splitStructType`（类型树走查，PackedStruct/UnpackedStruct 递归 FieldSymbol，
  数组维度（unpacked+packed）迁移到叶子；union/动态数组报错）；`analyzeStructLeafType`
  （analyzePackedPart + outer-packed 预置参数）。字段信号名 `c__DOT__f__DOT__x`。
- **注册表**：`ModulePlan::structsBySymbol`（root symbol → StructTypeInfo{fields 按声明序}）。
- **声明**：collectNet/collectVariable/collectPorts 的 splitStructDecl 钩子；叶子信号是
  普通 SignalInfo（S4-a 分类直接生效：SoA 形态 robEntries__DOT__wflags[352] 自然落地）；
  struct 端口拆成叶子端口（inout struct 端口报错）。
- **表达式**（StmtLowererState 聚合子系统）：lowerAggregateValues（named/member 投影/
  element-select 逐叶/ternary 逐叶 kMux/implicit conversion/`'{...}` 模式走查/'0/'1 字面量/
  扁平回退切片）；主 lowerExpression 对 struct 类型表达式一律 aggregate→flatten
  （布局 kConcat）——一切标量上下文天然兼容；标量成员访问经 memberPath 线程的
  resolveLValueSymbol 解析到叶子信号 + 读 slices。
- **赋值**：handleStructAssignment（LHS 逐叶 resolveStructLValueLeaves + RHS 逐叶
  （模式/聚合/扁平回退三态）+ 按寻址宽度 resize）；数组模式 lowerArrayPatternValue
  （packed 位置序、unpacked 反序拼接）；analyzePackedPart 标量宽修正（外层 packed 维
  参与元素宽判定）。
- **端口/实例**：collectPorts 叶子端口；emitInstances struct 分支（输入=扁平连接+
  静态切片；输出=逐叶 result + resolveStructOutBindings 绑定到父侧叶子——slang 会把
  输出连接包成 AssignmentExpression，需解包 left()）；ConnectionExprLowerer 独立实现
  struct 扁平化（连接侧）。
- **提升共享**：countStructLeaves/peelToStructScope/structMemberLeafRange/
  structLeafFlatWidth 提为自由函数；GraphAssemblyState 的 makeSliceStatic/makeZero/
  makeReplicate/resizeValueToWidth 由 lambda 提升为成员函数。

### 排雷记录
- slang 语法陷阱：`table` 是 SV 关键字（UDP），探针命名撞车（非解析 bug）。
- analyzeStructLeafType 裸标量叶子宽度错（outer packed 维未参与）→ analyzePackedPart
  预置参数重构。
- memberPath 线程必须贯穿 ElementSelect/RangeSelect 分支并在选择符前解析叶子。
- 扁平回退（'0 等无类型字面量）必须先 resize 到结构总宽再切片。

### 探针
- mini6：SoA 拆分（ent__DOT__lanes → kRegister shape=[2] w=16）+ WriteArrayPort。
- struct_probe：字段数组/嵌套 struct/struct 数组/`'{...}` 模式/整体赋值/flatten/
  ternary/eq——read+verify+emit 全过。
- struct_port_probe：拆分端口声明与实例连接（in_entry__DOT__tag 等名字两侧匹配）——
  read+verify+emit 全过，发射 SV 正确。

## S4-c 收官（2026-10-09）

### slang 修复（wolvrix/keyword-member-names 分支，976f2b2f7）
firtool 会用 SV 关键字当字段名（`from`/`until`，Chisel 源信号名），slang 按关键字严格
拒绝。在自有分支修复（与上游 Unique/And/Or/Xor 成员名特例同理，语法位置本无歧义）：
- parseDeclarator/parseDeclarators：关键字可当声明名（新谓词
  isIdentifierOrCommaOrKeyword/isNotIdOrCommaOrKeyword + Parser::expectIdentifier）；
- parseNamePart：点分名段接受关键字；parseMemberAccess 成员名同；
- 结构化赋值模式：首键/后续键接受关键字键名（isPossibleAssignmentKeyOrCommaOrDefault）。

### 关键 bug 修复（=all smoke 驱动）
- 数组-of-struct 的赋值模式（`queue <= '{'{...}, '{...}}` ROB 复位形态）：
  lowerArrayOfStructPattern 逐索引逐叶拼接；
- 成员链解析：ElementSelect/RangeSelect 只在叶子位置解析 memberPath
  （`io_in.tdata1Vec[2'h1].DATA[11]`）；
- 结构整体初始化（`wire struct x = '{...}` 与变量声明初始化）走
  handleStructRootInitializer（net/variable initializer 此前直达无值根符号）；
- **own/outer packed 边界**：walk 在每个 struct 层级记录边界，只有叶子自身声明的
  packed 维可降级为元素位宽——`logic [4:0] ssid` 的 [5] 不再被外层数组维吃掉，
  `logic flag` 的 [3:0] 外层维不再被当元素宽（robIdxVec__DOT__flag shape=[32,4] elem 1）；
- 叶子阈值放宽为 shape.front()>1（struct 叶子 1-bit 元素也进数组态——成员链访问
  要数组视图，无旧行为兼容负担）；
- 折回叶子元素宽保留（SignalInfo.elementWidth）+ 折回叶子的元素选择走子数组位切片；
- struct 数组的元素范围选择（`arr[base +: n]`）→ 逐叶子数组范围切片。

### =all smoke 终态（2115 文件逐文件 ingest + grh.verify）
1190 OK / 925 SKIP（跨文件模块依赖+xs_assert 宏）/ **0 FAIL / 0 CRASH**。
Phr.sv 也已随修复通过（此前的 HEAD 既有崩溃消失——系组合环相关路径改变后不再触发，
待全量编译复核）。

### 全量设计编译（filelist.full2.f，SimTop 顶层）驱动的两轮修复（2026-10-09）
- **并行崩溃（SIGSEGV/SIGBUS）**：applyReadSlices 的 SignalInfo shrunk 池是
  函数级 `static std::deque`（非 thread_local），并行 ingest worker 并发
  push_back 破坏 deque 内部块指针；Rob 闭包（12 模块）与全量编译分别表现为
  SIGSEGV（intern/deque 空块写）与 SIGBUS。修复：与文件内另两处池点一致改
  `static thread_local`。教训：ingest 并行化后函数级 static 可变容器一律
  thread_local，审计确认 ingest.cpp 无其它遗漏点。
- **O(n²) 扫描消除**（全量编译 25min+ 卡死 → 正常推进）：
  MemoryPortLowererPass 读去重（readUseBuckets 结构哈希桶 + 桶内全等校验）、
  降级后 hash 版 re-dedup、两个降级检查改 per-memory 可达集
  （writeReachByMemory）、GraphAssembler findReusableMemoryRead 改
  emittedReadBuckets_ 结构哈希。
- 提交：wolvrix 仓 `1426789`（代码）、`a3a2615`（文档：aggregate-types.md 新建
  + grh-ir.md §2.3 ingest 视角——此前 S4-c 提交遗漏）。

### 终版复测（2026-10-09，thread_local 修复后）
- 门禁链：ctest 56/58（transform-repcut、ingest-write-back-slice 为 HEAD 既有失败）、
  hdlbits 162/162、xs-bugcase 25/25、sim-refactor 基线全过。
- =all smoke：1190 OK / 925 SKIP / 0 FAIL / 0 CRASH（与修复前终态一致）。
- =vec smoke：1319 OK / 766 SKIP / 0 FAIL / 1 CRASH——Phr.sv（=vec 档）rc=139，
  系 HEAD 既有 emitExpr 组合环无限递归栈溢出（S4-a/S4-b 历次 =vec smoke 均同点
  崩溃，已验证未改动 slang 的 HEAD 同现），与 S4 无关，归 stage-05 comb-loop-elim
  范畴处理；=all 档 Phr.sv 为 SKIP（跨文件依赖分类），不发生。

### 全量设计编译深入（2026-10-09 晚，三连定位）
- **崩溃根因三独立问题，前两个已解**：(1) 并行 worker 共享 static deque（已修，
  1426789）；(2) Phr emitExpr 组合环无限递归（HEAD 既有，=all/=vec 单文件
  `--top Phr -D SYNTHESIS` 均确定性复现，栈溢出点函数/偏移完全一致）——该问题
  在全量编译中表现为**掷骰子**：某次运行 28min 单线程自旋后 SIGSEGV（日志停在
   slang 阶段尾部——ingest 的百万级诊断在 stdout 块缓冲里随崩溃丢失），下一次
  40s 全过。判定依据：run 日志出生/修改时间差 19s 证明 slang 仅数秒级，
  其余时间单线程 100% CPU。归 stage-05 comb-loop-elim 范畴。
- **design 未落盘的假象**：read_sv 不抛异常（diagnostics_raise_min_level=none）
  但 grh.verify 报 `design key not found: design.main`——ingest 有 error 级诊断
  时 read_sv 返回 success=false、design 不存。错误普查：2,097,153 条
  "Unsupported expression kind" + 2 条杂项**全部来自 Mem1R1WHelper.v**
  （诊断缓冲约 2M 封顶）。该文件在 -D SYNTHESIS 下走 `DISABLE_DIFFTEST_RAM_DPIC`
  分支，仿真专用的 initial 块（foreach + $fread + $value$plusargs + break）
  为 ingest 合法不支持项；foreach 对 13.1 万项 memory 的展开尝试 × 多实例
  放大到百万级报错。
- **处置（scratch 补丁，登记第三处）**：ptmp/xs-aggr-build/rtl/Mem1R1WHelper.v
  删 initial 预载块（仿真专用，与 DUT 及聚合校验无关；前两处补丁为
  DifftestMem1R1W RAM_SIZE ×4 与 parameter [63:0]）。基线流程无此问题：
  不定义 SYNTHESIS 时该文件走 DPI 分支，根本不含这段代码——但 aggr 全量必须
  SYNTHESIS 来剥离 xs_assert_v2 裸实例（`ifndef SYNTHESIS` 守卫，已现场确认）。

### Phr 崩溃最终定性与修复（2026-10-09 深夜）
- **定性翻案：不是组合环，是超深但有限的表达式链**。`ulimit -s 2G` 下单文件
  Phr（=all/=vec）均 ZYGO_OK；默认 8MiB pthread 栈确定性 SIGSEGV。全量编译的
  "掷骰子"实为不同 elaboration/dedup 结果下链深是否超过栈容量。
- **修复一（健壮性）**：emitExpr 加 in-flight 守卫——操作数递归前先记忆化
  （valueByExpr_），重访在飞节点即真组合环，报 "Combinational cycle in
  expression graph" 干净诊断而非栈溢出（守卫仅影响原本必崩的输入，门禁无回归）。
- **修复二（根因）**：runPlanQueueParallel 的 worker 线程改用
  pthread_attr_setstacksize(512MiB)（惰性提交，空闲 worker 零开销；非 unix
  平台回退 std::thread）。修复后单文件 Phr 与全量 read_sv 在默认环境下通过。
- 遗留：emitExpr 迭代化（显式工作栈）才是彻底解，归 stage-05 comb-loop-elim
  一并评估；单线程模式（singleThread）下主线程栈仍受 ulimit 约束，已记录。

### WriteBackPass 二次热点与 FlashHelper（scratch 补丁 #4）
- 栈修复后全量 read_sv 仍现单线程长磨：perf 定位 WriteBackPass::lower 内
  unordered_set<uint> 插入循环（二次扫描形态）。临时 WBProbe 探针（入门打印
  模块+规模，待移除）锁定 **FlashHelper.v**：SYNTHESIS 下走非 DPI 分支，4MB
  flash_mem 的 initial 预载循环被前端展开为 13.1 万条语句（signals=11 /
  stmts=131097），WriteBackPass 在其上二次扫描。仿真专用代码，补丁删除
  （登记 scratch 补丁 #4；SDCardHelper 在 SYNTHESIS 下为空体，无需处理）。
- 附带：RAM_SIZE scratch 补丁由 1048576 进一步降为 65536（difftest 助手
  memory 深度与聚合校验无关，减小无关负载）。
- WriteBackPass 对大 stmt 数组的二次扫描登记为性能遗留（S6/S7 评估；
  真实 DUT 模块 Ftq 61k / LogPerfEndpoint 92k stmts 需复核是否同样命中）。

### WriteBackPass 悬空引用修复（2026-10-09 深夜，= HEAD 基线 ingest-write-back-slice SEGFAULT 同根因）
- v3 全量 27s 即 SIGSEGV：栈底采样证明**不是**栈溢出（rsp 距 512MiB 栈顶仅
  ~15KB），而是 `mov 0x4(%rcx)` 野指针读。定位：WriteBackPass 的
  replaceTargetStaticSlicesWithProjection / replaceStaticSlicesForSymbolSet
  两个 lambda 族（projectRange/replace 共 4 处）把
  `const ExprNode& node = lowering.values[id]` 持有**跨过递归**——递归内
  builder.makeConcat/makeSliceDynamic/makeOperationWithWidth → registerExprNode
  → lowering.values push_back → vector 重新分配 → node 悬空；kConcat 分支
  循环里 `node.operands[i]` 二次读即崩（反汇编逐指令吻合：读 operands[0] OK、
  递归、读 operands[1] 崩）。kMux/kNot/kAndOrXor 分支的 `node.op/node.location`
  收尾读同属此型。
- 修复：4 处全部改为按值拷贝 `const ExprNode node = lowering.values[id]`（操作数
  vector 随节点一并拷贝，递归重分配不再影响当前帧）。
- 该根因与 HEAD 基线 ctest 失败 `ingest-write-back-slice`（SEGFAULT，
  testWriteBackPackedArraySelfSliceAcyclic）同源——修复后该基线失败应一并消除
  （待 ctest 复核）。

### 收官（2026-10-09 深夜）
- **XS preserve-aggregate=all 全量设计（SimTop）read_sv 139.4s + grh.verify 3.8s +
  store_json 14.5s 全部通过，0 error 诊断**，产出 6.17GB simtop_aggr.json。
  过程确认：此前 40s 的"好局"实为 error 模块早退、design 未落盘的假象；
  真全量在 WriteBackPass 悬空引用修复后一次性通过、无掷骰子路径。
- 门禁：ctest 57/58（ingest-write-back-slice 治愈，余 transform-repcut 基线）、
  hdlbits 162/162、xsbug 25/25、baseline 全过；=all/=vec smoke 双 0 FAIL 0 CRASH
  （=vec Phr 转 OK，1320/766）。
- 提交：wolvrix 仓 e1f0b27（WriteBackPass 修复 + emitExpr 守卫 + worker 大栈）。
- stage-04 文档头部实施记录、PROGRESS S4 区段已同步，S4 标记完成。
