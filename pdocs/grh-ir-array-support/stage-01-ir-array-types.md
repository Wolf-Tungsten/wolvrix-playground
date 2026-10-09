# Stage 01 — GRH IR 数组类型系统（shape 一等化）

- 日期：2026-10-08（2026-10-08 晚按 packed-first 实证结论修订）
- 状态：已实施（2026-10-09）
- 依赖：无（一切后续阶段的基础）
- 对应总目标：#1（数组类型）、#2（SSA 保持）、#9（持久化联动）、#10（文档联动）

## 实施记录（2026-10-09）

已合入：Value/GraphView/GraphBuilder 全链路 shape 支持（构造期硬校验：各维 > 0、
∏shape 不溢出 int64、width % ∏shape == 0、仅 Logic）、JSON vals.shape 读写
（writeJson + store 内联写器 + load 解析）、kRegister `shape`/init 族属性常量、
`grh.verify` 独立校验 pass（value shape / 端口方向 / kRegister·kLatch·kMemory 声明
属性 / kInstance 端口 totalBits 一致 + shape 不一致 warning / declaredSymbols 一致性）、
grh-ir.md §2.3 重写为"数组类型"+ §6.4 kRegister 属性表 + grh-json-spec.md vals.shape。

与 §5 文件级改动点的偏差：

1. `load.cpp` 的 **kMemory 族解析删除未做**——§3.3 把 kMemory 废除排在 stage-03，
   本阶段删除解析会立刻打断 reg-to-mem 产物的 JSON 往返（§8 要求门禁全绿）。
   §5 该条属笔误，实际归属 stage-03。
2. pybind **无需改动**：`run_pass` 经 `makePass` 通用注册，不存在 per-pass kwargs
   编译器（§5 所引 `actions/transform.cpp:15-119` 即通用入口）。
3. `validateDeclaredSymbols` **未改本体**，改为由 `grh.verify` 调用并集中上报。
4. `grh-ir-visualize` 的 shape 显示（只读增强、不阻塞）未做，留待后续阶段顺手补。
5. ctest 既有失败 3 例（transform-comb-lane-pack、transform-repcut、
   ingest-write-back-slice SEGFAULT），经 stash 对照验证与本次改动无关。
6. ~~kRegister `shape`/init 族属性常量~~ **已修正**（2026-10-09 拍板）：shape 是声明的
   类型契约，与 `width`/`isSigned` 同级使用裸字符串键（契约键不定义常量）；init 族同样
   保持裸字符串（沿用 kMemory 惯例）。现存的 `memoryWrite.priority*` 两枚常量属
   kMemoryWritePort 旧契约——priority 同样是契约而非自由 attr，且按 stage-03 拍板
   （同 kRegister 写口必同组、优先级=声明顺序）整个 memoryWrite 概念将随 kMemory 一并
   废除，届时常量删除。grh-ir.md §6.4 已按"类型契约 / 可选初始化属性"分组表述。

## 1. 目标

让 GRH IR 的 value 与 reg/latch/mem 声明原生支持"单一元素类型、一维到多维、每维长度编译期
确定"的数组，类型写作 `UInt8[x][y]` 形式（元素类型 + 维度表 `[x, y]`），并满足：

- 数组 value 仍服从 SSA：一个数组 value 只有一个定义 op（kConstant、kConcat、kMux、
  kRegisterReadPort、kSliceArray 等）。
- **shape 是 packed 优先的纯结构视图，不改变任何 op 语义**：value 的 `width` 恒为总位宽，
  shape 只把位布局按行主序结构化。所有现存按位/按总位宽定义的 op 与仿真行为自动正确
  （这正是 SV 对 packed 聚合的 integral 语义；实证依据见
  `20261008-preserve-aggregate-probe.md`）。
- kMemory 整体废除：寄存器获得按维度写入能力后与 kMemory 语义重合（stage-03 论证），
  数组状态由 kRegister + shape + 端口族统一承接（kLatch 保持标量，不参与）；init 族属性移到 kRegister。
- GRH JSON 格式直接演进：该格式从未对外发布，**不引入版本号/迁移机制**，旧产物随
  重新生成自然失效。
- 借机引入独立的 GRH verifier pass（现状：GRH 没有任何独立校验器，规则散落在 emitter
  与个别 pass 里，如 `system_verilog.cpp:4123-4132`、`activity_schedule.cpp:948-1000`）。

## 2. 现状事实

- `ValueData` 字段：`symbol, width:int32, isSigned, type:ValueType, isInput/isOutput/isInout,
  definingOp, srcLoc`——无 shape、无属性表（`wolvrix/include/core/grh.hpp:507-518`）。
  `GraphView` 是 SoA 列存（`grh.hpp:380-452`），`GraphBuilder` 是 AoS
  （`OperationData` 等，`grh.hpp:520-528`）。
- 声明 op：`kRegister`（attrs `width/isSigned/initValue`）、`kLatch`（`width/isSigned`）、
  `kMemory`（`width/row/isSigned` + `initKind/initFile/initValue/initStart/initLen`），
  语义见 `wolvrix/docs/grh/grh-ir.md:867-1128`。kMemory 的 `row` 是一维总行数，
  `width` 是每行（元素）位宽。
- 维度信息目前只活在 ingest 内部 `SignalInfo{packedDims, unpackedDims{extent,left,right},
  memoryRows}`（`wolvrix/include/core/ingest.hpp:184-199`），进图前被连乘折叠
  （`wolvrix/lib/core/ingest.cpp:787-868`）。
- `AttributeValue` 已支持 `std::vector<int64_t>`（`grh.hpp:101-109`），JSON 属性编码已支持
  `int[]`（写 `grh.cpp:2665-2750`，读 `load.cpp:563-722`）。
- JSON 顶层 `{graphs, aliases?, declaredSymbols, tops}`（`store.cpp:676-723`），**无版本号**；
  load 端仅靠旧键别名（`t/k/kind`、`v/value`、`vs/values`，`load.cpp:603-631`）兼容。
- ingest 给"整数组拼接"的 kConcat 打过非正式形状注解 `svPackedArray.*`
  （`ingest.cpp:17697-17774`），全库无消费者——本阶段用一等 shape 将其取代。

## 3. 设计

### 3.1 数组类型模型

```
ArrayType := { width:  int32 > 0,              // 总位宽（含全部维度，与现行语义一致）
               isSigned: bool, type: ValueType,
               shape: [d0, d1, ..., dn-1] }    // n >= 1，di > 0，编译期常量；空 = 标量
elementWidth = width / ∏shape                  // 必须整除（verifier 检查）
```

- **同质**：数组元素类型单一；结构体等异构聚合不产生 GRH value——ingest 字段级拆分
  （`c__DOT__a[n]` 形态，见 stage-04 §3.1-2），类型系统无需承接异构。
- **packed 优先**：shape 的主要来源是 packed 聚合维度——实证表明 firtool
  `--preserve-aggregate=all` 的 XiangShan 输出 100% 是 packed 数组与 packed struct
  （unpacked 只剩 FIRRTL memory 与仿真随机器）。unpacked 数组由 ingest 按行主序自定布局
  折平后同样以 shape 承载。packed/unpacked 与元素宽度无关（`logic a [0:7]` 元素宽 1 仍
  unpacked；`logic [3:0][7:0]` 元素宽 8 仍 packed）——GRH 不需要区分二者，shape 只记录
  "数组语义维度"。
- **不拆 packed_shape / unpacked_shape 两层**（2026-10-08 决策）：unpacked 相对 packed
  的全部差异（禁算术、赋值兼容性）都是前端静态检查，由 slang 在解析/elaboration 期强制，
  IR 层没有需要重检的运行时语义；位布局差异不是约束而是自由，ingest 自定行主序布局即可。
  shape 的消费者（kSliceArray、mem port、emit、FST/调试）都只需要合并维度表；~~emit 一律
  发 packed 数组声明（合法且两态语义一致）~~（**已被实证推翻，2026-10-09**：packed 声明上
  的扁平位选择在 Verilator 下按左维元素解释而非扁平位，emit 保持扁平声明——见
  stage-02 §8 Q1）。混合嵌套的顺序唯一确定
  （SV 语法天然 unpacked 维在外、packed 维在内）：shape = [unpacked 维..., packed 维...]。
  来源若需溯源，归 srcLoc / declProvenance 式调试元数据，不进类型系统；将来扩展
  unpacked 支持只是 ingest 的解析覆盖工作，IR 不变。
- **shape 不改变任何 op 语义**（核心原则）：任何 op 对带 shape value 的语义 ≡ 对其
  `width` 位扁平位向量的语义。对 packed 来源，这正是 IEEE 1800 的 integral 语义
  （算术进位跨元素边界是合法且正确的）；对 unpacked 来源，合法 SV 源本就不可能对数组
  产出算术/移位/归约（slang 直接拒绝），无需 verifier 设防。**因此不设 op 白名单/黑名单**
  （§3.4）。
- **行主序**：元素 `(i0, i1, ..., in-1)` 的线性位偏移为
  `(i0*d1*...*dn-1 + i1*d2*...*dn-1 + ... + in-1) * elementWidth`。
  形状 `[x][y]` 与扁平向量的位布局完全一致。
- 维度无上界/方向（`left/right/downto`）概念：那些是 SV 源语法，ingest 负责把
  `[4:7][7:4]` 之类映射为从 0 开始的规范下标（现行 `adjustPackedElementLaneIndex`
  思路的延续，`ingest.cpp:6322`）。

例（width / shape 判定规则：**最内层 packed 维是元素位宽本身，不进 shape**；shape 的
每一维都是"多少个元素"）：

| SV 声明 | width | shape | elementWidth |
|---------|-------|-------|--------------|
| `logic [7:0] a` | 8 | `[]`（标量） | 8 |
| `logic [3:0][7:0] b` | 32 | `[4]` | 8 |
| `logic [1:0][3:0][7:0] c` | 64 | `[2,4]` | 8 |
| `logic [3:0][7:0] d [0:5]` | 192 | `[6,4]` | 8（unpacked 维 6 在外层） |
| `logic [7:0] e [0:3][0:5]` | 192 | `[4,6]` | 8（unpacked 二维） |

位布局与 SV 完全一致：如 `b[i]` = `bits[8i+7 : 8i]`，`b[0]` 是最低字节（packed `[3:0]`
降序约定下 index 0 = LSB，与行主序 offset(i) = i×8 对齐）。注意 packed 升序声明
（`logic [0:3][7:0]`）的 `b[0]` 是**最高**字节——方向信息不进 shape，由 ingest 在下标
归一化时映射掉，GRH 中 shape 恒对应"canonical index 0 = 最低元素地址"的布局。

### 3.2 Value 扩展

- `ValueData` 增加 `shape: std::vector<int64_t>`（空 = 标量）。`GraphView` 增加对应 SoA 列；
  `Graph::createValue` / `GraphBuilder::addValue` 增加可选 shape 参数（默认空，源码级兼容
  现有标量调用点）。
- 不变式：**`width` 恒为总位宽**（与现行语义一致）。所有现存读 `valueWidth()`/`width`
  拿总位宽的代码（pass、emit、store）自动正确；`elementWidth = width / ∏shape` 只有
  shape 感知的消费者（kSliceArray、mem port、FST/调试）才使用。
  （早期草案曾取 width=元素宽，已否决：那会让全部现存 width 消费端静默出错；
  packed-first 方向下无任何收益。）
- 端口（input/output/inout）是普通 value，天然获得数组类型；kInstance 端口连接校验
  totalBits 一致，shape 不一致给 warning（`hier_flatten.cpp:784`、`instance_inline.cpp`
  附近）。

### 3.3 声明 op 扩展

| op | 新增/变更属性 | 语义 |
|----|--------------|------|
| kRegister | 新增可选 `shape: int64[]` + init 族（`initKind/initFile/initValue/initStart/initLen`，shape 非空时可用，从被废除的 kMemory 并入） | `width` 保持总位宽；shape 声明数组结构；数组的读写全部经 stage-03 端口族（整体/索引/掩码/填充） |
| kLatch | 不变（不加 shape） | latch 保持标量——kLatch 一定很简单，不需要数组支持（2026-10-08 拍板）；latch 数组由 ingest 拆成逐元素标量 latch |
| ~~kMemory~~ | **废除**（stage-03） | reg 可按维度写入后与 kRegister 语义重合；reg/mem 之分降级为 grhsim 后端存储分类（A7）；`init*` 的线性行主序语义并入 kRegister |

`initValue` 字符串编码不变（扁平位串），数组元素数由 shape 推出。kMemory 及其 `row`
属性直接废除，load 端不做兼容（格式未发布，旧产物重新生成即可，见 §3.5）。

### 3.4 op 级 shape 规则：无限制原则

**shape 不改变 op 语义，因此全部 58 个 op 对带 shape value 一律合法，语义 = 对其扁平
位向量的语义。** 不设白名单/黑名单，理由有三：

1. packed 聚合在 SV 是 integral type，扁平语义就是其规定语义（`a+b` 跨元素进位合法）；
2. unpacked 数组在合法 SV 源里不可能有算术/移位/归约（slang 拒绝），ingest 自定布局折平
   后同样不可能产出此类 op——危险形态没有来源；
3. ~~emit 侧带 shape 的 value 声明为 **packed 数组**（`logic [3:0][7:0] x`，integral），
   emitted SV 中任何表达式都合法，不存在"unpacked 声明导致非法表达式"的问题。~~
   （**已被实证推翻，2026-10-09**：packed 声明上的扁平位选择在 Verilator 下按左维元素
   解释而非扁平位；emit 保持扁平声明——见 stage-02 §8 Q1。本条论据改为：扁平
   `logic [W-1:0]` 声明下一切表达式天然合法。）

shape 感知点（真正读 shape 的地方）只有四个：

- **kSliceArray**：输入 value 必须 shape 非空（stage-02 重定义，1..N 索引）；
- **声明 op** 的 shape 属性（§3.3）与读口 result 的 shape 继承；
- **kRegister 数组端口族**（stage-03：索引读/写、部分索引、掩码、填充）；
- **实例端口连接**的 shape 匹配（不一致 warning）。

shape 推导惯例（供 ingest/pass 构造 result value 时使用，**不是 verifier 约束**；
shape 缺失/未传播只损失结构信息，不影响正确性）：

- kConcat：操作数全同形 `[s..]` → result `[n, s..]`（n=操作数个数，沿 leading 维拼接，
  对应 SV 赋值模式/FIRRTL aggregate connect）；操作数全标量同型 → result 标量（现行）
  或 `[n]`（ingest 的数组构造路径）；其余组合 → 标量。
- kMux / kRegisterReadPort / kLatchReadPort / kRegisterReadArrayPort：result 继承相应 shape。
- kSliceStatic / kSliceDynamic：result 默认标量；需要时可在 totalBits 一致下声明 shape
  （把位段重解释为数组视图）。
- 其余 op：result 默认标量（即 shape 不传播）。
- shape 只配 `ValueType::Logic`；Real/String 不数组化（已定稿）。

### 3.5 JSON 持久化

- **不引入版本号**：GRH JSON 格式从未对外发布，直接改格式，不做新旧兼容与迁移逻辑。
  仓库内所有落盘的 flat_grh.json 类产物都是构建中间产物，格式变更后重新生成即可；
  load 端读到旧格式（如 kMemory 带 `row`）按普通解析错误处理。
- vals 条目增加可选 `"shape": [d0, ...]`；ops 的 attrs 直接复用现有 `int[]` 编码
  （kRegister 的 `shape` 等都是普通属性）。
- `Graph::writeJson`（`grh.cpp:4102-4312`）与 `store.cpp` 内联写器同步；vals 的
  `def`/`users` 字段仍是只写不读（维持现状）。
- `wolvrix/docs/grh/grh-json-spec.md` 同步改写为新格式。

### 3.6 GRH verifier（新设）

新增独立校验 pass（放 `lib/transform/`，命名如 `grh.verify`，经 `transform.cpp` 的
`availableTransformPasses()`/`makePass()` 注册），把散落规则集中：

- value：shape 各维 > 0；width > 0；**width % ∏shape == 0**；shape 仅配 `Logic`；
  端口方向一致性。
- op：操作数个数/属性表；kSliceArray 输入 shape 非空且索引数 1..rank（stage-02）；
  kRegister 的 shape 合法（各维 > 0、整除；kLatch 无 shape）；声明 op 符号唯一。
- 连接：实例端口 totalBits 一致（shape 不一致 warning）。
- 作为 simplify 等管线收尾的可选开关 + store/emit 入口的调试模式校验。

## 4. 小例子

SV 输入（ingest 目标形态，stage-04 才真正实现）：

```systemverilog
logic [7:0] a [0:3][0:5];   // 或 preserve-aggregate 的 packed 形态 logic [3:0][5:0][7:0]
logic [7:0] b [0:3][0:5];
assign b = a;               // 整数组赋值
```

GRH 表示（S1 完成后）：

```
%0 = value width=192, shape=[4,6] "a"     // elementWidth = 192/24 = 8
%1 = value width=192, shape=[4,6] "b"     // def = kAssign(%0)，单一定义
```

旧表示是 192bit 标量 + `svPackedArray.*` 注解；新表示 shape 是一等的，且 `width=192`
对所有存量代码保持原义。

## 5. 文件级改动点

| 文件 | 改动 |
|------|------|
| `wolvrix/include/core/grh.hpp` | `ValueData`/`Value`/SoA 列/createValue 签名；~~kRegister 属性常量（shape + init 族）~~（已否决：契约键用裸字符串，见头部实施记录 #6）；kLatch 不变；注释契约 |
| `wolvrix/lib/core/grh.cpp` | 构造/冻结/克隆/writeJson（vals 写 shape；ops attrs 不变）；`validateDeclaredSymbols` 扩展 |
| `wolvrix/lib/core/store.cpp` | vals shape 写出 |
| `wolvrix/lib/core/load.cpp` | vals shape 解析；kMemory 族解析删除 |
| `wolvrix/lib/core/transform.cpp` + `include/transform/` | 新增 verify pass 注册 |
| `wolvrix/lib/transform/verify.cpp`（新） | §3.6 规则实现 |
| `wolvrix/app/pybind/native/actions/` | Session API 基本不动；新增 pass 需注册 kwargs 编译器（`actions/transform.cpp:15-119`） |
| `grh-ir-visualize/` | value tooltip/详情显示 shape（只读增强，不阻塞） |

## 6. 基础设施联动（目标 #9）

- **持久化**：见 §3.5。仓库内所有落盘的 flat_grh.json 类产物属构建中间产物，
  格式变更后重新生成即可，无兼容负担。
- **diagnostics**：verify pass 走 `PassDiagnostics`（`include/core/transform.hpp:33-42`）；
  load 的解析错误维持 `std::runtime_error` 现状（load 不走 Diagnostics）。
- **Python 绑定**：`run_pass("grh.verify")` 注册；文档 `wolvrix/docs/python/python-binding-architecture.md` 补一句。

## 7. 文档更新（目标 #10）

- `wolvrix/docs/grh/grh-ir.md`：§2.3"数组扁平化"整节重写为"数组类型"；§6.3/6.4 声明 op
  属性表更新；**§6.5 存储器节删除**（kMemory 废除，stage-03）；新增"shape 规则"小节
  （本文 §3.4 的规范化版本）。
- `wolvrix/docs/grh/grh-json-spec.md`：vals.shape；kMemory 族条目删除。
- kMemoryFillPort 从未记录的旧账随 kMemory 废除自然消解——其新形态 kRegisterFillPort
  在 §6.4 完整定义（stage-03）。

## 8. 破坏面与回退

- 破坏：旧格式 JSON 产物（含 `row`、无 shape）直接不可读，重新生成即可；`svPackedArray.*`
  注解的测试断言（`tests/ingest/test_ingest_graph_assembly_slice.cpp`）在 stage-04 移除
  生产者前先保留。
- 不破坏：本阶段不改任何 op 语义、不改 ingest 行为；`width` 语义不变（恒为总位宽），
  标量路径完全不变，门禁全绿要求保持。
- 回退：纯增量字段，revert 即回退。

## 9. 开放问题（全部关闭，2026-10-08 拍板）

1. ~~按位 op 的 shape 白名单/广播规则~~ **已取消**（2026-10-08 packed-first 修订：
   无限制原则，§3.4）。
2. ~~`ValueType::String/Real` 数组化~~ **已定：不允许**，shape 只配 `Logic`。
3. ~~shape 维数上限~~ **已定：不硬编码**维数上限；verifier 对 `∏dims` 溢出 int64 报错。
