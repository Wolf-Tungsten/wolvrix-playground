# Stage 03 — kRegister 数组端口族（多索引、优先级语义、kMemory 退役）

- 日期：2026-10-08（2026-10-08 晚二修：统一为 kRegister 端口族，kMemory 废除；
  2026-10-08 三修：Q3 位掩码定稿；2026-10-08 四修：grhsim 承接 op 名同步——mem* 退役；
  2026-10-09 实施完成，六处实施偏差见下）
- 状态：已实施（2026-10-09）
- 依赖：stage-01（shape）
- 对应总目标：#4（多索引读写）、#5（写端口优先级语义）

## 实施记录（2026-10-09）

已合入：kMemory/kMemoryReadPort/kMemoryWritePort/kMemoryFillPort 四个 OpKind 删除，
数组状态统一为 kRegister + `shape` attr（width=总位宽、shape=[行数]）；新增端口族
kRegisterReadArrayPort / kRegisterWriteMaskPort / kRegisterWriteArrayPort /
kRegisterWriteArrayMaskPort / kRegisterFillPort（操作数布局与 §3.2 逐字一致）；
写端口优先级 = 同 regSymbol 唯一组 + 声明顺序（priorityGroup/priority 属性常量与
全部生产/消费点删除）；`firstEventOperandIndex` / `arrayPortIndexCount` /
`isRegisterReadPortKind` / `isRegisterWritePortKind` helper 进 grh 核心；
ingest 最小适配（kMemory 产出改 kRegister+shape，写口按全写/掩码拆分）；
grh.verify 端口族校验（regSymbol 反查声明、索引数 vs rank、子数组宽度、eventEdge 与
操作数尾匹配、updateCond 1-bit）；SV emit 全端口族发射；activity_schedule /
dead_code_elim / repcut / xmr_resolve / hier_flatten / instance_inline /
memory_read_retime / memory_init_check / redundant_elim / demo_stats / comb_loop_elim
适配；grh_to_grhsim 过渡映射（见偏差 3）。

与 §3/§4 清单的偏差：

1. **firstEventOperandIndex 不按 regSymbol 反查 rank**：§3.2 原写"按 regSymbol 反查
   rank"，但部分索引（k<rank）下声明 rank 无法唯一确定索引数——实施改为按 `eventEdge`
   attr 数量反推边界（op 自足、无需图级反查），rank 一致性由 grh.verify 交叉校验。
2. **SV emit 数组声明用 unpacked 而非 §3.5 示例的 packed**：`logic [elemW-1:0] r [0:R-1];`
   与 stage-02 拍板的扁平/线性化呈现哲学一致，且 (a) $readmemh 目标天然合法；
   (b) 旧 kMemory 发射文本逐字保留 → rank=1 门禁路径 SV 输出零差异；(c) 整体读写经
   行主序 concat/嵌套循环展开，绕开 Verilator packed 扁平 part-select 语义陷阱
   （stage-02 §8 Q1 实证）。§3.5 示例仅作 IR 语义示意，不代表发射形态。
3. **grhsim 承接为过渡形态**：新端口族映射到既有 memRead/memWrite/memFill/regWrite
   op（mem* 一族退役与 core.array 退役均归 stage-06）；kRegisterWritePort /
   kRegisterWriteArrayPort 的无 mask 形态由转换器按数据宽合成全 1 mask 常量值。
4. **activity_schedule 的 priority 机制整段删除**（validate/order/atomic-unit/guard-key
   分支）——该机制在全库无生产者（仅测试构造），是死代码；声明顺序优先级由既有通道
   兑现：SV emit 按 op 声明序排列、grhsim cpu_schedule 同 state 写按 op id 升序。
   kRegisterFillPort 在 normalizedSinkEventKey 中保持 "opaque" 桶（对齐旧
   kMemoryFillPort 行为，登记为 stage-06 评估项）。
5. **ingest 双写路径声明去重**：同 symbol 同时存在整体写（storage 路径）与索引访问
   （memory 路径）时复用同一 kRegister（宽度一致前提下），回填 shape attr 与已建
   whole-read value 的 value shape。`emitPackedAggregateWholeRead` 保持逐行
   ReadArrayPort + concat 结构（IR/SV 与旧形态一致），简化归 stage-04。
6. **comb_loop_elim 边界表即时生效**：kRegisterReadArrayPort 作为状态读加入边界 op
   表（§3.6 既定修正；旧 kMemoryReadPort 不在表中，新分类更正确）。
7. repcut 顺带修正：kRegisterFillPort 补入 isSinkOpKind（对齐其他 pass 既有归类，
   旧表遗漏 kMemoryFillPort）。demo_stats：kRegister+shape 并入 memory 统计族。
   XMR 寄存器写固定产 kRegisterWriteMaskPort（驱动布局 [cond,data,mask,events] 直传，
   与旧 kRegisterWritePort 发射文本一致）。
8. 文档补记（2026-10-09 用户指出）：grh-ir.md §1.1 Value 字段清单漏列 `shape`
   （stage-01 遗留）、§2.3 shape 推导惯例未覆盖 kRegisterReadArrayPort 的 result
   shape 规则（k==rank → 标量；k<rank → 剩余维）——均已补上。

## 1. 目标

1. **kMemory 整个废除**：数组状态统一由 kRegister（带 shape）承接。理由：寄存器获得
   按维度写入能力后，kRegister 数组与 kMemory 的 IR 语义完全重合（异步读 = 状态的组合读；
   时钟写端口、掩码、初始化一一对应）；reg/mem 之分降级为 **grhsim 后端的存储分类**
   （A7 select-state-stores 本来就在做 regLatch/mem 重分类），不属于 IR。
2. 端口族支持 **1..N 个索引操作数**与**部分索引**（下标不足 rank 时读写高维子数组），
   与 kSliceArray 的下标规则（stage-02）完全对齐。
3. 写端口优先级语义：**组 = 同 regSymbol 的全部写端口**（priorityGroup/priority 属性废除），
   同时激活时按声明顺序应用、后声明者覆盖。

## 2. 现状事实

- kRegisterReadPort 无操作数整体读；kRegisterWritePort `[updateCond, nextValue, mask,
  events...]`（事件从操作数 3 起，`system_verilog.cpp:4318`）；同一 kRegister 允许多写端口
  （`grh-ir.md:992-1059`）。
- kMemory（`width`+`row`+init 族）、kMemoryReadPort（`[addr]` 异步读）、kMemoryWritePort
  （`[updateCond, addr, data, mask, events...]`，事件从操作数 4 起）、kMemoryFillPort
  （全行填充，`ingest.cpp:18326-18348`；grh-ir.md 未记录）。
- 现行优先级：`memoryWrite.priorityGroup/priority`（`grh.hpp:89-90`），同组须同事件、
  0 最高；校验 `activity_schedule.cpp:948-1000`。
- grhsim 侧早已不把 reg/mem 当绝对二分：A7 `select-state-stores` 把状态分 regLatch/mem
  两类（`model.hpp:175-189`，mem 类现仅限 `core.array`——overview.md:317-318），
  memWritePlan 优先级原地提交、后写覆盖先写（cpu-st.md:305）。
- **结构性事实**：同一声明的全部写端口在 xmr_resolve 之后必然位于同一 graph
  （XMR 写解析回宿主图，`xmr_resolve.cpp:974` 附近）。
- comb-loop-elim 边界表现状：kRegisterReadPort 是边界 op，kMemoryReadPort **不是**
  （`comb_loop_elim.cpp:110-122`）——见 §3.6 的修正。

## 3. 设计

### 3.1 统一论证（为什么可以废除 kMemory）

| 能力 | kMemory | kRegister + shape + 端口族 |
|------|---------|---------------------------|
| 异步读 | kMemoryReadPort(addr) | kRegisterReadArrayPort(idx...)（状态的组合读） |
| 整体读 | — | kRegisterReadPort（数组 value，SSA） |
| 时钟写 | kMemoryWritePort(cond,addr,data,mask,events) | kRegisterWriteArray(Mask)Port |
| 整体写/掩码写 | —（写口模拟） | kRegisterWritePort / kRegisterWriteMaskPort |
| 广播填充 | kMemoryFillPort | kRegisterFillPort |
| 初始化 | initKind/initFile/initValue/initStart/initLen | 同组属性移到 kRegister（shape 非空时可用） |
| 多写端口顺序 | priorityGroup/priority 属性 | 同 regSymbol 唯一组 + 声明顺序（§3.4） |

SV 层同样成立：packed 数组的动态下标读写、`always_ff` 内索引写全部合法（integral）。
唯一真实的区别是**仿真后端的存储/调度策略**（regLatch 双缓冲逐行检测 vs mem 类边界采样
+ P_mem 原地提交），那本来就是 grhsim A7 重新推导的，IR 不需要提前承诺。

### 3.2 端口族定义

声明 op：`kRegister`（attrs：`width`=总位宽、`isSigned`、可选 `shape:int64[]`、
`initValue`、数组时可用 `initKind/initFile/initStart/initLen`）；`kLatch` 保持标量、
一族完全不动（2026-10-08 拍板，见 §3.2 末条）。
**kMemory/kMemoryReadPort/kMemoryWritePort/kMemoryFillPort 从 OpKind 删除**（JSON 格式
未发布，旧产物不兼容即可）。

读端口：

```
kRegisterReadPort        ops: []                     result: 全数组 value（shape 继承声明）
kRegisterReadArrayPort   ops: [i0, ..., ik-1]        1<=k<=rank
                         result: k==rank → 元素标量；k<rank → 子数组 value（shape=剩余维）
```

写端口（均带 `updateCond` 1bit 与事件尾；属性 `regSymbol`、`eventEdge:string[]`）：

```
kRegisterWritePort           [updateCond, nextValue, events...]               整体写（nextValue=全数组 value）
kRegisterWriteMaskPort       [updateCond, nextValue, mask, events...]         整体写+位掩码（mask 宽=总位宽）
kRegisterWriteArrayPort      [updateCond, i0..ik-1, data, events...]          索引写（k>=1；k<rank 时 data 为子数组）
kRegisterWriteArrayMaskPort  [updateCond, i0..ik-1, data, mask, events...]    索引写+位掩码（mask 宽=data 宽）
kRegisterFillPort            [updateCond, data, events...]                    广播填充（data=元素宽，写满全部 ∏shape 元素）
```

- 事件操作数起始下标随端口种类与索引数变化，由 `firstEventOperandIndex(op)` helper
  集中计算（按 regSymbol 反查 rank）——取代现在写死的"操作数 3/4 起"。
- **kLatch 不参与数组化**（2026-10-08 拍板）：kLatch 保持标量、一族完全不动（含 mask
  内建的 kLatchWritePort），不引入 shape 与数组端口族——kLatch 一定很简单；
  latch 数组由 ingest 拆成逐元素标量 latch 承接。
- 越界索引：与 kSliceArray 同条款（实现定义，不写死）。

### 3.3 部分索引规则（与 kSliceArray 对齐，读写对称）

下标数 k < rank 时作用在**高维子数组**上：

```
声明: kRegister width=128 shape=[4,4] element=8bit（ UInt8[4][4] ）

%whole = kRegisterReadPort()                 → value width=128 shape=[4,4]
%row   = kRegisterReadArrayPort(%i)          → k=1<2，子数组 width=32 shape=[4]
%e     = kRegisterReadArrayPort(%i, %j)      → k=2=rank，标量 width=8

kRegisterWriteArrayPort(%we, %i, %rowData, %clk)        // k=1：写一行（data width=32 shape=[4]）
kRegisterWriteArrayMaskPort(%we, %i, %j, %d, %m, %clk)  // k=2：掩码写元素（mask width=8）
kRegisterFillPort(%rst, %zero8, %clk)                   // 全部 16 元素填充
```

线性位偏移一律按行主序公式（stage-01 §3.1）；IR 层不出现 kMul/kAdd 寻址树。
该规则与 kSliceArray（stage-02 §3.1：k<n → 子数组）逐字对齐——**kSliceArray 作用于
组合 value，kRegisterReadArrayPort/WriteArrayPort 作用于状态**，两者共享同一套
"下标不足 = 高维子数组"语义。

### 3.4 写端口优先级（2026-10-08 定稿，逐字沿用前版结论）

1. **组 = 同 regSymbol 的全部写端口**（含 kRegisterFillPort）；priorityGroup/priority
   属性废除——全部写端口必然同 graph（§2 结构性事实），组无需圈定；不要求相同事件/边沿。
2. **优先级 = 写端口 op 的声明顺序**：先声明先应用，后声明者覆盖同地址先写者。
   该规则**继承现行 kRegister 多写口的既有约定**（2026-10-08 拍板）：SV emit 按源码顺序
   在 always 块内排列（后写覆盖先写）、grhsim regWrite 按序叠加到 regLatchStoreNext
   （同轮多写口读改写叠加）——数组写端口复用同一约定，不另立规则。
   **同 regSymbol 写端口 op 的相对顺序是 IR 语义的一部分**——pass 不得重排
   （verifier 断言兜底；JSON ops 数组有序，持久化免费）。
3. 同轮同时激活时按声明顺序依次应用。"同时激活"在 GrhSIM 执行模型良定义
   （同 eval 轮内 eventAct 聚类命中，`cpu-st.md:262-286`）；跨事件/跨时钟同轮命中
   正是优先级唯一被消费的场景，唯一组无代价。
4. 迁移：删除现行 priority 生产者写入（ingest、`xmr_resolve.cpp:974` 附近）；
   `activity_schedule.cpp:948-1000` 校验整段删除；SV emitter 同 always 块按声明顺序
   排列（天然"后写覆盖先写"）；grhsim 同 state 写 op 按声明顺序保序生成
   （memWriteSeq 已随 mem* 一族退役）、memWritePlan 按声明顺序生成（stage-06）；
   删除 `grh.hpp:89-90` 属性常量。

### 3.5 SV emit 形态

```systemverilog
logic [15:0][3:0][7:0] r;                       // kRegister width=1024 shape=[16,4]
always_ff @(posedge clk) begin
  if (we)  r[a][b] <= d;                        // kRegisterWriteArrayPort k=2
  if (wm)  r[a]    <= (r[a] & ~m32) | (rowData & m32);   // ArrayMaskPort k=1
  if (rst) r       <= '{default: 8'h0};         // kRegisterFillPort
end
assign q   = r[x][y];                           // kRegisterReadArrayPort k=2
assign row = r[x];                              // k=1 部分索引读
```

packed 数组的动态下标读写、`always_ff` 索引写、`'{default:}` 全部合法（integral）。
跨事件写端口仍是 SV 无法表达顺序的形态：emitter 报 warning 并按事件分块、块内按声明
顺序输出（best-effort；语义以 GrhSIM 后端为准——写入 grh-ir.md）。

### 3.6 语义差异修正点（相对现状）

- **comb-loop-elim 边界**：kRegisterReadArrayPort 是状态读 = 边界 op。现行
  kMemoryReadPort 不在边界表里（`comb_loop_elim.cpp:110-122`）——memory 内容只在时钟
  边沿变化，异步读本质是状态读，新分类**更正确**；stage-05 边界表随之更新。
- **kRegisterWritePort 操作数布局变化**：mask 拆为独立 op（kRegisterWriteMaskPort），
  非掩码写事件从操作数 2 起（原从 3 起）——现存生产者（ingest 等）迁移；
  **kLatchWritePort 不动**（kLatch 一族不参与本次重构）。
- **dump/FST**：原 kMemory 不逐元素进波形；统一后数组状态的波形展开按规模阈值或
  hint attr 决定（实现细节归 stage-06，不进 IR 语义）。
- **memory-read-retime**（`memory_read_retime.cpp`）：同步读 = 索引读 + 寄存器捕获，
  pass 保留，模式匹配从 kMemoryReadPort 改为 kRegisterReadArrayPort。

## 4. 文件级改动点

| 文件 | 改动 |
|------|------|
| `wolvrix/include/core/grh.hpp` | OpKind 删除 kMemory 族 4 项、新增 kRegister 数组端口族（kLatch 不参与）；删除 :89-90 优先级属性常量；`firstEventOperandIndex` helper 声明 |
| `wolvrix/lib/core/grh.cpp` | `kOperationNames` 表同步（**只允许删改、不重排既有项位置**……格式未发布，直接同步即可）；helper 实现 |
| `wolvrix/lib/core/load.cpp` / `store.cpp` | kMemory 族解析/写出删除；新端口族无属性变化（事件/helper 化） |
| `wolvrix/lib/transform/verify.cpp`（stage-01 新设） | 端口族操作数/索引数/rank 校验；同 regSymbol 写端口相对顺序断言 |
| `wolvrix/lib/emit/system_verilog.cpp` | kRegister 数组声明（packed 形态）、端口族发射（§3.5）、同 always 块声明顺序排列（1850-1902）、跨事件 warning；kMemory 发射路径（4665-5054）删除 |
| `wolvrix/lib/transform/activity_schedule.cpp` | kMemory* 模式匹配改 reg 端口族；组/priority 校验删除 |
| `wolvrix/lib/transform/dead_code_elim.cpp` | storage liveness 的 kMemory* 判定改 reg 端口族 |
| `wolvrix/lib/transform/repcut.cpp`、`xmr_resolve.cpp`、`hier_flatten.cpp`、`memory_read_retime.cpp`、`const_fold.cpp`、`demo_stats.cpp` | 模式匹配改名/适配；XMR 按声明顺序生成写端口 |
| `wolvrix/lib/grhsim/convert/grh_to_grhsim.cpp:106-108, 428-441` | kRegister 数组 → 带 shape state（core.array 退役）；端口族 → read/readArray/write/writeArray/fill（mem* 一族退役，细节归 stage-06） |
| `wolvrix/lib/core/ingest.cpp` | 本阶段仅最小适配（rank=1 路径不变，kMemory 产出改 kRegister+shape）；正式生产端归 stage-04 |

## 5. 基础设施联动

- 持久化：kMemory 族与优先级属性从格式中删除（格式未发布，旧产物报错即可）；
  **op 顺序语义化条款写入 grh-json-spec.md**。
- diagnostics：SV emitter 跨事件写端口 warning 走 EmitDiagnostics；activity_schedule
  旧校验文案随删除而去。
- Python 绑定：无变化。

## 6. 文档更新

- `grh-ir.md`：§6.4 寄存器节整体重写（端口族 + 优先级 + op 顺序语义化条款），
  §6.5 存储器节**删除**（kMemory 不复存在；顺带解决 kMemoryFillPort 从未记录的旧账——
  新形态 kRegisterFillPort 在 §6.4 内完整定义）；每个 op 显式定义操作数并给例子。
- `docs/grhsim_ir/dialects/core.md` §5/§8：映射表更新（待 stage-06）。

## 7. 破坏面与回退

- 破坏：**kMemory 族整体删除**——所有模式匹配点改名适配（§4 表）；旧 JSON 产物不可读
  （重新生成）；优先级规则变为声明顺序。
- 门禁：rank=1 路径行为应与现状等价（kRegister 数组 = 原 kMemory 语义子集）；
  HDLBits/xs-bugcase 逐个核对，豁免登记并跟踪到 stage-07 清零。
- 回退：单阶段 revert 即恢复 kMemory 族；与 stage-04/06 的耦合点在合并窗口期不要
  单独 revert。

## 8. 开放问题

1. ~~priority 分组/缺省语义~~ **已定**：同 regSymbol 唯一组 + 声明顺序（§3.4）。
2. ~~写端口部分索引~~ **已定（2026-10-08）**：读写对称支持 k<rank 子数组（§3.3）。
3. ~~mask 语义是否扩展到"元素掩码"~~ **已定（2026-10-08 拍板）：不扩展，位掩码为唯一
   mask 语义**。理由：(a) FIRRTL 元素掩码的粒度是"聚合类型每叶子字段 1 bit"，bundle 的
   字段宽度异构——`ram_2x359` 实例点 `W0_mask = {342'h全1, {7{_GEN_0}}, 10'h3FF}`
   （SimTop.aggr-all.sv:4741-4746），与 IR 的均匀 elementWidth 模型对不上；且 firtool
   在 SV 边界已把 mask 复制成位级（ram_* 模块 W0_mask 宽 == 数据宽、逐 bit `[k +: 1]`
   门控，:3904-3911），"贴近 FIRRTL 源语义"的动机在 SV ingest 路径拿不到。(b) 表达力
   严格子集：元素掩码表达不了跨元素边界的 part-select 写与真实逐位写，缺失时只能
   全读改写全写、丢 indexed-write 结构（P_mem 分类与按行脏检测依赖该结构）。
   (c) kRegisterWriteMaskPort 同服务标量 reg，元素粒度对标量退化为 1 bit（与
   updateCond 冗余）。(d) _BitInt 下位掩码应用为三条原生宽位运算，元素掩码省的是
   mask 值长度而非应用代价。后端对 `{N{en}}` 复制形态可本地识别后按元素应用，
   无需 IR 语义承诺。
4. ~~kLatch 镜像族~~ **已定（2026-10-08 拍板）：不实现**——kLatch 保持标量、一族完全
   不动；latch 数组由 ingest 拆成逐元素标量 latch。
