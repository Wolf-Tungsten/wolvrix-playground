# Stage 04 — ingest 聚合保留（多维数组与结构体）

- 日期：2026-10-08（2026-10-08 晚修订：struct 改为字段级拆分；2026-10-08 三修：
  Q3 附 kArrayInsert 备选设计，第一版不引入）
- 状态：计划草案
- 依赖：stage-01（shape）、stage-02（新 kSliceArray）、stage-03（多索引 mem port）
- 对应总目标：#6

## 1. 目标

ingest 接受 SystemVerilog 多维数组（packed/unpacked）与结构体，在不违反 GRH 类型系统
（同质数组）的前提下**尽可能保留多维数组语义**，不再把一切平化成单向量。这是整个重构中
改动量最大的阶段，也是 stage-07 能否直接消费 preserve-aggregate SV 的决定性环节。

## 2. 现状事实

- 类型分析：`TypeResolution{width, memoryRows, packedDims, unpackedDims, hasUnpacked}`
  （`wolvrix/lib/core/ingest.cpp:465-473`）；`SignalInfo`/`UnpackedDimInfo`
  （`wolvrix/include/core/ingest.hpp:184-199`）是维度信息唯一栖息地。
- `computeFixedWidth`（`ingest.cpp:572-648`）：struct/union 按字段宽度累加/取 max，
  结构体在这里被压成单一总宽度。
- `analyzeSignalType`（`ingest.cpp:759-870`）：多维 unpacked 数组各维 extent 连乘进单个
  `memoryRows`（818-835）；`analyzePortType`（872-900）对 unpacked 数组端口直接平化并 warn
  （893）；`analyzePackedElementMemoryType`（674-710）把外层 packed 维度 >1 且元素宽 >1 的
  变量重解释为 memory。
- 访问 lowering：
  - 元素选择 → kSliceArray（`ingest.cpp:8447-8453, 20925-20934`），常量下标预折叠
    （21481-21503）。
  - 平化 net 数组多维下标按行优先线性化为位偏移 → 单个 kSliceDynamic
    （`collectNetArraySelectChain`/`buildNetArraySlice`，5661-5760）。
  - memory 多维下标 `buildLinearAddress` 线性化（15565-15623）→ kMemoryReadPort；
    写路径合成 mask → kMemoryWritePort（`emitMemoryWrites` 18229-18290）；整体写 →
    kMemoryFillPort（18328）。
  - **struct 成员读路径缺失**：主 lowerer（7949-8656）末尾直接 "Unsupported expression
    kind"；只有写路径有 `WriteSliceKind::MemberSelect` → `resolveMemberSlice`
    （11443-11494）。字段级拆分（§3.1-2）后该缺口自然消失——成员访问变成对拆分信号的
    直接引用，不再需要任何专用路径。
- `svPackedArray.*` 形状注解（17697-17774）：只写不读，本阶段由一等 shape 取代并移除。
- slang 类型消费：`PackedArrayType`/`FixedSizeUnpackedArrayType`/`Packed|UnpackedStructType`/
  `Packed|UnpackedUnionType`/`TypeAliasType`；范围用 `slang::ConstantRange{left,right}`
  保留原始边界。
- 现有测试 fixture：`tests/ingest/data/memory_ports.sv:279,291` 有二维 unpacked
  （含反向界 `[4:7][7:4]`），packed 多维若干；覆盖面明显不足。

## 3. 设计

### 3.1 类型映射决策树（重写 `analyzeSignalType`/`analyzePortType`/`computeFixedWidth`）

对变量/net/端口的类型，按以下优先级判定 GRH 形态：

1. **同质数组**（packed 数组、unpacked 数组、二者嵌套，元素为位类型）：**全维进 shape**。
   shape = 各维 extent 的规范序列，unpacked 维为外层（leading）、packed 维为内层，
   元素 = 最内层位类型；`value.width` = 总位宽（elementWidth = width/∏shape）。
   例：`logic [3:0][7:0] a [0:5]` → width=192、shape=[6,4]、element=8bit；
   纯 packed `logic [3:0][7:0] b` → width=32、shape=[4]、element=8bit
   （完整判定表见 stage-01 §3.1）。
   （2026-10-08 packed-first 修订：preserve-aggregate 输出全是 packed 聚合，packed 维
   始终进 shape，不再按访问模式分流；shape 不改变 op 语义，故无准入约束。存储形态
   由后端分类，见第 3 条。早期"packed 维并入元素位宽"方案作废。）
2. **结构体：字段级拆分（field-wise split，SoA 化）——struct 永远不成为 GRH value**
   （2026-10-08 定稿，取代"整体扁平 + 字段位段提取"方案；**gsim 先例**：reference/gsim
   解析期即按字段拆分为独立节点，分隔符 `$$`——AST2Graph.cpp:149-192、main.cpp:47，
   与本方案同构）。声明/net/端口/嵌套中的
   struct 一律递归拆成叶子字段信号，命名 `c__DOT__a`（DOT 编码，与 Verilator/firtool
   惯例一致）；数组维度迁移到每个字段信号上：
   - `struct { 数组 a, 标量 b } c` → `c__DOT__a`（shape = a 自身 shape）、`c__DOT__b`（标量）；
   - `struct { 标量 a, 标量 b } c [n]` → `c__DOT__a`（shape=[n]）、`c__DOT__b`（shape=[n]）；
   - 嵌套递归：外层维度在前、字段自身维度在后；嵌套 struct 继续拆
     （`struct { struct { x, y } f, 标量 b } c[n]` → `c__DOT__f__DOT__x[n]`、
     `c__DOT__b[n]`）。
   拆分后每个字段信号独立走第 1/3 条的判定（kRegister(shape) / 标量——
   存储分类归后端，见第 3 条）。
   实例（均来自 preserve-aggregate 探针报告 §7）：
   - ROB `robEntries[351:0]`（元素为 ~50 字段的 entry struct）→
     `robEntries__DOT__wflags[352]`、`robEntries__DOT__ftqIdx__DOT__value[352]`、……
     ——每个字段数组独立判定存储形态；
   - TAGE `takenCounter[3:0][31:0][7:0]`（元素 struct{value:2}）→
     `takenCounter__DOT__value`：width=2×4×32×8=2048，shape=[4,32,8]，element=2bit。
   整体操作逐字段展开：整体赋值 = 逐字段连接；整体相等 = 逐字段 kEq 归约 AND；
   整体 mux = 逐字段 kMux 同 cond；`'{字段: 值}` 字面量 = 逐字段构造。
   需要 packed 位布局的场合（streaming `{<<}`/`{>>}`、`$bits`、整体 XMR/调试引用）
   现场按声明顺序 kConcat 重建——布局是类型的纯函数，ingest 内部可查。
3. **变量级别的动态元素写**（`a[i] <= x`）：一律落成 **kRegister 数组 + 端口族**
   （stage-03：kRegisterWriteArrayPort 多索引写、kRegisterReadArrayPort 多索引读），
   下标不再线性化。**kMemory 已废除**——"reg 还是 mem"不再是 ingest 的决策，
   存储形态分类（regLatch/mem）全部由 grhsim A7 在后端按规模/访问模式推导。
   拆分后的字段数组各自独立走同一规则。
4. **端口**：数组端口不再平化（`analyzePortType` 的 warn 路径删除），端口 value 带 shape；
   struct 端口同样字段级拆分（如 `io_enq__DOT__req__DOT__bits__DOT__...`），kInstance
   端口连接按拆分后的字段端口匹配（verifier 检查 totalBits+shape 一致）；hier_flatten
   的端口 remap 同步适配。
5. 动态/关联数组、队列：维持报错。

### 3.2 访问 lowering 重写

| 源形态 | 新 lowering | 删除的旧路径 |
|--------|------------|-------------|
| unpacked 数组元素读 | kRegisterReadArrayPort 多索引（stage-03；常量索引保持） | `buildLinearAddress`（15565-15623）kSub/kMul/kAdd 树 |
| unpacked 数组元素写 | kRegisterWriteArrayPort / kRegisterWriteArrayMaskPort 多索引；行内位/段写仍合成 mask（15858-16068 逻辑保留，地址维不再线性化） | 同上 |
| packed/net 数组元素读 | 新式 kSliceArray（值带 shape）；常量索引 → kSliceStatic（带 shape 结果） | `collectNetArraySelectChain`/`buildNetArraySlice` 位偏移链（5661-5760） |
| 整数组赋值 | 直接 value 连接 / kAssign（shape 不改变 op 语义，stage-01 §3.4） | `svPackedArray.*` 注解（17697-17774）移除 |
| struct 成员读/写 | **不再需要专用路径**：字段级拆分（§3.1-2）后成员访问 = 对拆分信号的直接引用 | 主 lowerer 的 MemberAccessExpression 缺口与 `resolveMemberSlice`（11443-11494）一并退役 |
| 数组整体写（`a <= '{default:...}` 等） | kRegisterFillPort（广播填充，stage-03）/ kRegisterWritePort 整体写 | — |
| packed aggregate 整体读（`isPackedAggregateVariable`，510-514/17480-17484） | 数组 value 直读（kRegisterReadPort），不再逐行 kMemoryReadPort + kConcat（17590-17672 简化） | 逐行读拼接路径 |

### 3.3 方向/边界归一化

- 所有维度的 `left/right/downto/upto` 在 ingest 内部归一化为 `0..extent-1` 下标，
  不再进入 GRH。现有 `adjustPackedElementLaneIndex`（6322）与多维归一化
  （15590-15604, 18872-18881）逻辑保留但作用点从"位偏移"改为"索引操作数"。
- `UnpackedDimInfo{extent,left,right}` 继续作为 ingest 内部表示，但 shape 只记 extent。

### 3.4 MemoryPortLowererPass：整体退役

现行 `MemoryPortLowererPass::getMemoryCandidate`（15249-15333）是"先生成 slice 链再回溯
识别 memory 再改写"的事后修正。**kMemory 废除后该 pass 失去存在意义**：数组变量统一为
kRegister(shape)，访问直接生成 kRegister 数组端口族（stage-03），没有任何需要回溯识别
的目标。本阶段删除该 pass；XMR 路径由 xmr_resolve 直接生成 reg 端口（974 附近适配）。

### 3.5 register/latch 数组

- 整个数组一起写（`always_ff ... a <= b;`）→ kRegister 带 shape（stage-01 §3.3），
  kRegisterReadPort 返回数组 value。
- 元素级动态写 → kRegisterWriteArrayPort / kRegisterWriteArrayMaskPort（stage-03）；
  **不存在"提升为 memory"的决策**——统一是 kRegister，存储分类归 grhsim A7。
- kLatch 不支持数组（2026-10-08 拍板）：latch 数组拆成逐元素标量 latch。

## 4. 文件级改动点

| 文件 | 改动 |
|------|------|
| `wolvrix/include/core/ingest.hpp` | `SignalInfo`/`UnpackedDimInfo`/`TypeResolution` 增加 GRH shape 决策结果字段 |
| `wolvrix/lib/core/ingest.cpp` | §3.1-§3.4 全部；重点函数：computeFixedWidth(572)、analyzeSignalType(759)、analyzePortType(872)、analyzePackedElementMemoryType(674)、makeSliceArray(6150)、ElementSelect 两处(8447, 20917)、net 数组链(5661-5760, 18779-18926)、buildLinearAddress(15565, 20174)、MemoryPortLowererPass(15200-16100, 17590-17672, 18229-18290)、resolveSliceSelection/resolveMemberSlice(11443-11494, 11611+，退役)、projectRange(12314+)、createMemoryOps(17945-17953)、annotatePackedArrayConcatDefop(17697-17774, 移除)、常量预折叠(21481-21503, 通用化)、**struct 字段级拆分器（新增，含 `__DOT__` 命名与维度迁移）** |
| `wolvrix/lib/transform/hier_flatten.cpp` / `instance_inline.cpp` | 端口/实例连接的 shape 匹配与 remap；拆分后字段端口的处理 |
| `wolvrix/lib/transform/xmr_resolve.cpp` | XMR 读写数组目标的适配（974 附近生成 mem port 处）；struct XMR 指向拆分信号 |
| `wolvrix/tests/ingest/` | 新增多维 unpacked/packed/struct 拆分/数组端口 fixture；更新 memory_ports.sv 相关断言；移除 svPackedArray.* 断言（test_ingest_graph_assembly_slice.cpp） |

## 5. 基础设施联动

- 持久化：本阶段不改格式；ingest 产物直接以新格式写出。
- diagnostics：`analyzePortType` 的平化 warning 删除；含非位字段（Real/String/事件）的
  struct 明确报错（ConvertDiagnostics）。
- Python 绑定：不变（read_sv 入口不变）。

## 6. 文档更新

- `wolvrix/docs/ingest/`：类型映射决策树（§3.1）落为规范，含字段级拆分的命名与维度迁移
  规则；数组/结构体支持矩阵（哪些形态保留 shape、哪些拆分、哪些报错）。
- `grh-ir.md` §2.3 同步最终形态（stage-01 已重写，本阶段补 ingest 视角）。

## 7. 破坏面与回退

- 破坏：stage-02 登记的临时桥接被正式路径替换；一切依赖"ingest 产物一律标量"假设的
  下游 pass 会在本阶段集中暴露问题——**这是刻意设计**：问题在 GRH 层（有 verifier）暴露，
  而不是在仿真结果里暴露。
- 门禁：HDLBits/xs-bugcase 预期出现用例级差异（数组形态改变 → 仿真模型结构改变），
  逐个核对波形/轨迹后更新黄金基线；豁免清单登记在本节并跟踪到 stage-07 清零。
- 回退：本阶段改动集中于 ingest，但下游适配是渐进的——建议本阶段拆 2-3 个合入单元：
  (a) kRegister 数组端口族 + 访问路径；(b) net/packed 数组 shape 化；(c) struct 字段级拆分。
  每个单元独立可 revert。

## 8. 开放问题

1. ~~unpacked struct~~ **已基本解决（2026-10-08）**：字段级拆分与 packed/unpacked 无关
   （从不构造扁平容器，异构性随拆分消失），只要叶子字段都是位类型即可支持；含
   Real/String/事件等非位字段的 struct 仍报错。剩余风险仅是拆分后信号数量与命名长度
   （ROB 端口拆分后单端口名可达数百字节），实测后定。
2. ~~packed 多维是否进 shape？~~ **已定（2026-10-08 两次迭代）**：packed 维**始终**进
   shape（不再按访问模式分流）。第一版"packed 并入元素位宽"被探针推翻（preserve-aggregate
   输出全是 packed 聚合，折平即丢失 reg-to-mem 需要的信息）；第二版"动态访问才进 shape +
   op 白名单准入"被 packed-first 原则取代（packed 聚合是 integral，扁平语义即正确语义，
   shape 不改变任何 op 语义，准入约束没有必要）。存储形态（regLatch/mem）由 grhsim A7
   后端分类，与 shape 记录相互独立（kMemory 已废除，stage-03）。
3. ~~`kArrayInsert`（数组 value 的元素级 SSA 更新 op）是否引入~~ **已定（2026-10-08）：
   第一版不引入**。触发条件：preserve-aggregate 输出出现"wire/net 数组 + 动态元素写"且无法由
   kRegister 数组端口族表达的形态（探针未发现：动态写全在 reg 上）。备选设计已备妥
   如下，触发后可直接采用：

   **备选设计：kArrayInsert = kSliceArray 的写侧对偶**（共享同一套下标规则）

   ```
   kArrayInsert   ops: [array, i0, ..., ik-1, data]     1 ≤ k ≤ rank(array)
     result: width/shape 与 array 完全相同（SSA 完整定义）
     data:   k == rank → 元素标量；k < rank → 子数组 value（shape = array.shape[k:]）
     语义:   result 在 (i0..ik-1) 位置 = data，其余位 = array 原样（函数式更新）
   ```

   - 纯组合函数：无 cond/event/priority；条件更新 = `kMux(cond, kArrayInsert(a,i,d), a)`，
     状态更新 = kRegisterWriteArrayPort，三者分工不重叠；越界条款同 kSliceArray。
   - SV/grhsim 发射：packed 移位拼接 `res = (a & ~(M << off)) | (zext(d) << off)`
     （off/子宽按行主序公式，_BitInt 下为三条宽位运算）；静态下标由 const_fold
     折成 kConcat(kSlice...)。
   - 代数规则：`insert(a,i,slice(a,i)) → a`；`insert(insert(a,i,x),i,y) → insert(a,i,y)`；
     `slice(insert(a,i,d),j)` 在 i≡j / i≠j 可证时分别折为 d / slice(a,j)（动态下标不可证，
     insert 链不可重排）；全常量 insert 链（逐元素构造）重排为单 kConcat。
   - 唯一真实生产者是将来的 mux 树结构恢复 pass（`res[j]=(idx==j)?d:arr[j]` →
     kArrayInsert），属优化而非正确性需求；无生产者期间引入只会增加
     verifier/emit/持久化表面。
4. ~~memory 整体读~~ **已消解（2026-10-08）**：kMemory 废除后，数组整体读 =
   kRegisterReadPort 直接返回数组 value（SSA 单定义），无需逐行拼接，也无需新增 op。
