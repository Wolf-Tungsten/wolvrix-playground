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
