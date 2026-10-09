# Stage 06 — GrhSIM IR 多维数组承接与 CPU 后端

- 日期：2026-10-08（2026-10-08 修订：mem 端口部分索引与 stage-03 §3.3 对齐
  （索引数 1..rank），Q1 关闭；补整体读写承接映射与 regLatch 路径 write 排序；
  2026-10-08 二修：类型系统改为与 GRH 同构的 width+shape（value 与 state 一视同仁），
  嵌套 core.array 方案作废；2026-10-08 三修：mem* op 一族整体退役，state 访问统一命名
  read/readArray/write/writeArray/fill（Array 后缀 = 索引变体），memWriteSeq 退役改为
  声明顺序语义；2026-10-09：Q2 宽元素×多维定稿为必须支持；Q3 FST 定稿为逐元素 +
  阈值排除（摊平方案废弃，含格式层证据）；Q4 read/write 支持带 shape state/value
  定稿为必须支持——§8 全部关闭）
- 状态：计划草案
- 依赖：stage-01（GRH shape）、stage-03（kRegister 数组端口族与新优先级语义）
- 对应总目标：#8（grhsim 数组承接）、#9/#10（基础设施与文档联动）

## 1. 目标

GrhSIM IR 完整承接 GRH 的多维数组语义：**类型系统与 GRH 同构（width + shape，
value 与 state 一视同仁，stage-01 §3.1 的 grhsim 版）**、**state 访问 op 族统一命名
（read/readArray/write/writeArray/fill；mem* 一族整体退役：访问形态是 op 语义，
regLatch/mem 存储分类是后端策略，二者解耦）**、
新写端口优先级语义，以及 CPU 后端（布局、调度、发射、持久化）的端到端落地。
**核心原则：物理存储保持线性**——多维 shape 只影响寻址表达式与语义校验，不重写后端
数据布局（`_BitInt` 宽值、双缓冲、P_mem 提交等机制原样保留）。

## 2. 现状事实

- GrhSIM 是独立 IR（`wolvrix/include/grhsim/ir/model.hpp`，`GrhSimModel` :749），
  有真正的 verifier（`include/grhsim/ir/verifier.hpp`）与 JSON 格式版本
  `wolvrix.grhsim.v2`（`include/grhsim/io/json.hpp:21`）。
- `core.array<elementType, count>` **一维**（`model.hpp:130-140`）；多维形状仅以行主序
  线性化约定存活在 metadata `DeclProvenance.shape: vector<uint64_t>`（`model.hpp:684-716`）。
- mem op 全部单 `%address` 操作数；同 array 多写 op 不得同次写同一 bit，有序覆盖必须收进
  单个 `core.state.memWriteSeq`（操作数顺序=优先级，链头最后）
  （`docs/grhsim_ir/dialects/core.md:165-178`）。
- lowering 契约明确"GRH 已扁平化的聚合不得恢复"（`core.md:43-44`）——**本阶段翻转该契约**：
  GRH 带来的一等 shape 必须保留。
- `grh_to_grhsim.cpp`：kMemory → 一维 `arrayType`（428-441）；kSliceArray →
  `core.compute.sliceArray`（92）；mem port → memRead/memWrite/memFill（106-108）；
  declProvenance.shape 从 arrayType 链推出（708-749）。
- CPU 后端：memRead（`cpu_phase_emit.cpp:1738-1754`）、emitMemWrite/emitGeneralMemWrite
  （2390-2499）、sliceArray `start=idx*width`（1593-1612、1896-1911）、布局
  `cpu_layout.cpp`、写计划 `cpu_schedule.cpp`（`memWritePlan` model.hpp:528-535）、
  P_mem 优先级原地提交、同地址后写覆盖先写（`flows/cpu-st.md:305`）。
- A7 `grhsim.select-state-stores` 的 `storeClass`（model.hpp:175-189）把状态分
  regLatch/mem 两类；mem 类仅限 `core.array`（`docs/grhsim_ir/overview.md:317-318`）。
- reg-to-mem 现状是一维 row 基址恢复；`declProvenance.shape` 的网格形状标注已支持多维
  但存储仍一维。

## 3. 设计

### 3.1 类型系统（与 GRH 同构：width + shape，value 与 state 一视同仁）

- **放弃嵌套 `core.array` 构造子方案**（2026-10-08 二修）：那会把数组关在 state 类型里、
  value 侧全扁平，与 GRH 一等 shape 不对称（read/write 是否接受数组值都得单开
  问题，`declProvenance.shape` 沦为第二通道）。改为与 GRH stage-01 §3.1 完全相同的
  模型：**类型 = width（总位宽）+ shape:int64[]（空 = 标量），elementWidth = width/∏shape**。
  `core.array<E, n>` 退役，由 `width = E.width×n, shape=[n]` 表达（JSON 格式原地演进，
  无兼容负担，§3.5）。
- shape 挂在**类型**上，value 与 state 一视同仁：
  - read / readArray / sliceArray 的结果带 shape（k<rank → 剩余维；整体读 → 全 shape）；
  - 其余 compute op 对 shape 透明（扁平位语义），shape 推导惯例直接引用 GRH
    stage-01 §3.4（约定而非 verifier 约束；不传播只损失结构信息）；
  - verifier 规则与 GRH verify pass 同构：各维 > 0、`width % ∏shape == 0`、∏ 溢出报错。
- 物理布局不变：存储仍线性，元素连续、stride 按行主序从 shape 递推（与现行
  `cpu.array<U, n>` 一维字节布局逐字节一致，`dialects/cpu.md:42-47`）——shape 只影响
  寻址表达式与语义校验。
- `DeclProvenance.shape` 退役（shape 已进类型系统）；provenance 保留原始命名/来源等
  调试信息。
- InitSpec 的 readmem/fill start/count 保持**线性地址**语义（行主序），不引入多维 init
  寻址。

### 3.2 state 访问 op 族：统一命名 + 多索引（mem* 一族退役，2026-10-08 三修）

**mem* 一族（memRead/memWrite/memFill/memAssign/memWriteSeq）整体退役**——stage-03 把
reg/mem 之分降级为后端存储分类后，IR op 不应再按"mem"分家：访问形态（整体/索引/掩码/
填充）是 op 语义，存储分类（regLatch/mem）是后端策略，二者完全解耦。统一后的族：

```
core.state.read        无                                            整体读；array state → 结果带全 shape
core.state.readArray   [%i0, ..., %ik-1]      1<=k<=rank             索引读（原 memRead）；k=rank → 元素，
                                                                     k<rank → 带剩余维 shape 的子数组
core.state.write       [%updateCond, %nextValue, %mask, %events...]  整体写（原 regWrite 改名；吸收
                                                                     memAssign——array 整体写 = mask 全 1、
                                                                     %nextValue 带全 shape 的 write）
core.state.writeArray  [%updateCond, %i0.., %data, %mask, %events...] 索引写（原 memWrite）；
                       1<=k<=rank；k<rank 时 %data 带剩余维 shape（子数组写，stage-03 §3.3 读写对称）
core.state.fill        [%updateCond, %data, %events...]              广播填充（原 memFill；
                                                                     packed fill 例外条款保留）
core.state.latchWrite  不变（kLatch 一族保持标量，不参与）
```

- 命名约定：**访问形态命名 + `Array` 后缀标记索引变体**（read/readArray、write/writeArray
  两对），`fill` 是整体广播写，`latchWrite` 是唯一例外——latch 是电平敏感的不同状态
  种类，值得独立名字。时钟/电平差异由 event 操作数表达而非名字前缀：write/writeArray/
  fill 要求 ≥1 个 event，latchWrite 无。`reg` 前缀是冗余（方言名 core.state 已表明
  操作对象）。
- 与 GRH stage-03 端口族的映射：kRegisterReadPort → `read`；kRegisterReadArrayPort →
  `readArray`；kRegisterWritePort / kRegisterWriteMaskPort → `write`；
  kRegisterWriteArrayPort / kRegisterWriteArrayMaskPort → `writeArray`；
  kRegisterFillPort → `fill`；kLatchReadPort → `read`；kLatchWritePort → `latchWrite`。
- mask 语义 = 位掩码（stage-03 §8 Q3 定稿）；无掩码写由转换层补全 1 常量。

- **memWriteSeq 退役**：同 state 多写 op 按 op 声明顺序应用、后写覆盖先写——与 GRH
  stage-03 §3.4 完全同构（§3.3）。旧约束"任意两写 op 不得同写同一 bit、有序覆盖必须
  收进 memWriteSeq"（core.md:176-178）删除；memWriteSeq 的"全部写口须同事件"限制
  （core.md:177-178）本来就承接不了 stage-03 允许的跨事件写口，退役后该缺口自然消失。
  **同 state 写 op 的相对顺序是 IR 语义，pass 不得重排**（与 GRH 侧同条款，verifier
  断言兜底）。
- 索引表示方案取舍：
  - (a) 多索引操作数（与 GRH 1:1 对应，转换层零逻辑）；
  - (b) 保持单线性地址，由转换层生成线性化算术。
  **选 (a)**：GRH→GrhSIM 转换契约是逐 op 承接、不在转换时引入新计算（core.md:18-20）；
  线性化推迟到 CPU mapping（C 段），与"物理线性"原则衔接。
- verifier 新增：索引数 1..rank 且不超过 state 类型 rank；索引为整数标量；
  readArray 结果 / writeArray %data 的类型 = 带剩余维 shape 的数组类型（k=rank 时为
  元素）；同 state 写 op 相对顺序保持（转换/pass 后的顺序断言）。
- `core.compute.sliceArray`（GRH kSliceArray 的承接）同样扩展多索引，result 带剩余维
  shape；其语义文档需明确它现在是**数组值访问**而非 packed 位向量切片（对应 stage-02
  的重定义）。

### 3.3 写端口优先级承接（stage-03 语义落地）

- GRH 新语义（stage-03 §3.4，2026-10-08 定稿）：同 regSymbol 即唯一组，优先级 = 写端口
  op 的声明顺序，同轮同时激活时按声明顺序依次应用、后声明者覆盖。
- 落到 GrhSIM：**同 state 写 op 声明顺序即优先级**（memWriteSeq 退役，§3.2）——
  两层 IR 共用同一条规则，转换层 1:1 保序生成，无排序信息的丢失/重建。
  - P_mem `memWritePlan`（model.hpp:528-535）：plan 顺序按声明顺序生成，
    原地提交天然"后写覆盖先写"（cpu-st.md:305），与新语义同构——**执行机制不变，
    只是排序键从"同事件组内的显式 priority 编号"变为"写 op 的声明顺序"**。
  - 跨事件写端口不再受"同顺序域"限制：P_mem 本来就在 P_general 之后统一提交，同轮多个
    事件聚类命中的写口在 P_mem 按 plan 顺序应用，语义完整覆盖。（旧 memWriteSeq 的
    "全部写口须同事件"限制随之消失。）
  - regLatch 路径（小状态）：同 state 多 write 同样按 GRH 声明顺序生成、按序叠加到
    regLatchStoreNext（继承现行 kRegister 多写口约定，stage-03 §3.4-2）。
- A7/C5 适配：`staticRow` 精确激活匹配扩展为多维下标比较（或线性化后比较，实现细节）；
  动态地址维持"任意写即激活"的保守策略。

### 3.4 lowering（grh_to_grhsim.cpp）

- kRegister（含数组）→ state 类型直接继承 GRH 的 width+shape（shape 进类型系统；
  declProvenance.shape 推导逻辑（708-749）退役）。kMemory 已废除（stage-03），不再有
  一维 arrayType 特例；kLatch 保持标量，不涉及。
- 端口族 1:1 映射（§3.2 族）：kRegisterReadPort → `read`；kRegisterReadArrayPort →
  `readArray`；kRegisterWritePort → `write`（mask 补全 1 常量）；
  kRegisterWriteMaskPort → `write`；kRegisterWriteArrayPort → `writeArray`
  （mask 补全 1 常量）；kRegisterWriteArrayMaskPort → `writeArray`；
  kRegisterFillPort → `fill`。事件操作数下标按 `firstEventOperandIndex` helper
  （stage-03 §3.2）；**同 regSymbol 的多个写端口各成一个 op、按声明顺序保序生成**
  （memWriteSeq 收编逻辑删除）。
- 类型层面由 §3.1 统一承接（value 可带 shape）；实现侧 `read`/`write` 现行只处理
  标量/位向量，需推广（实施期检查点，§8 Q4）。
- kSliceArray → 多索引 sliceArray（result 带剩余维 shape）；其余一切 op 按其扁平位宽
  lowering——shape 是纯结构视图、不改变 op 语义（stage-01 §3.4 无限制原则），shape
  感知点只有 kSliceArray 与 state 访问 op。
- write 整数组写（kLatch 保持标量，走现有路径不变）。

### 3.5 CPU 后端

- C3 布局：按 shape 行主序 stride 递推（字节布局与现行一维逐字节一致）；named store
  字段粒度不变。**元素宽 >64bit × 多维组合必须支持**（§8 Q2 定稿）：最内层元素为
  _BitInt(N) limb 数组，线性偏移 = 线性下标 × elementWidth 公式不变，布局
  static_assert 中"宽元素仅一维"类假设需核对放宽。
- C5 写计划：多维下标的静态/动态判定。
- **A7 存储分类收敛（2026-10-08 拍板）**：P_mem 相的本意是避免大状态复制；kMemory 废除、
  统一 kRegister 后，storeClass 的**唯一分类标准 = 状态总大小**（字节阈值，现行
  mem-min-bytes=64 量级）——小状态 regLatch（NBA 双缓冲 + 逐行变化检测），大状态 mem
  （P_mem 原地提交）；与访问模式无关。
- emit：
  - readArray 多索引 → 嵌套下标表达式 `store.f[i0][i1]` 或线性化 `store.f[i0*d1+i1]`，
    以生成代码的 clang 友好度实测为准（参照 bitint 经验，控制发射形状）。
  - emitWriteArray（原 emitMemWrite）的 rowOf/writeCell/越界钳位（2390-2469）多维化；
    packed fill 行切片（2417-2444）按行主序推广。整体数组写的发射策略参照 gsim
    `arrayCopy`（`reference/gsim/src/instsGenerator.cpp:135`）三档：常量折叠 /
    逐元素展开（RHS 元素结构已知时）/ 嵌套 for 循环拷贝；元素写始终是单条索引 store，
    不拼位。
  - sliceArray 的 `idx*width`（1593-1612）→ 行主序多索引偏移。
  - dumpState 数组哈希按 ∏shape 行数推广；FST 改逐元素注册（§8 Q3 定稿：方括号名、
    总字节 > kWaveMaxBytes=512 不 dump，4211-4226 的摊平规则改写）。
- JSON：类型条目增加 `shape` 字段（与 GRH JSON 同构，stage-01 §3.5），`core.array`
  编码退役；readArray/writeArray 多索引操作数编码；mem* op 编码删除；
  declProvenance.shape 字段删除。
  GrhSIM JSON 与 GRH JSON 一样从未对外发布——**格式直接原地演进，io/json.cpp 读端不做
  新旧兼容**，旧 checkpoint 重新生成即可（现有的格式字符串常量
  `wolvrix.grhsim.v2` 是否随格式更新只是落地时的一行实现细节）。
- 求值粒度对照（2026-10-08，gsim 实证）：组合数组 value firing 即全量求值是 oblivious
  模拟器的通行语义——gsim 对数组节点甚至不做 old/new 变化检测（`activateUncondNext`，
  `reference/gsim/src/cppEmitter.cpp:944-951`）；我们 regLatch 类数组提交时的逐行真变化
  检测已比它细。元素粒度只来自拆分（stage-05 之于我们 = splitArray 之于 gsim），
  不存在"部分赋值"；SSA 全量赋值语义不引入额外损失。
- 数组 reg 写入对照（2026-10-08，gsim 实证）：gsim 的 reg 数组 = SRC 数组 + 持久 `$NEXT`
  镜像数组；动态下标写是"守卫条件 + 直写 `$NEXT[dynIdx]`"（激活提交超节点），提交 =
  被激活时全量 `for i: SRC[i] = NEXT[i]`——与我们的 regLatchStoreNext（NBA 缓冲）+
  P_publish 提交同构，且我们有逐行真变化检测（更细）。两侧均不拼位。
  （证据：`build/xs/gsim/gsim-compile/model/SimTop98.cpp:55088` 的 `wSourceVec$NEXT`
  动态写与 `SimTop89.cpp:33801` 的提交循环。）
- 多维写入对照（2026-10-08，gsim 实证，`putBuffer[insertIdx][count].data` 案例）：
  FIRRTL 多维写 = 多重 subaccess 链（各维独立动态；嵌套动态下标真实存在——
  `valids[set][accessPtrs[set].value]`，印证"索引操作数是任意组合 value"）；
  gsim 侧 = bundle 字段先拆分（`putBuffer__DOT__data[8][2]`，元素 `_BitInt(256)`，
  物理维度 pow2 向上取整、逻辑循环用真实维度）+ 嵌套 if 守卫的二维索引 store
  `$NEXT[insertIdx][count] = v` + 嵌套 for 提交循环
  （`build/xs/gsim/gsim-compile/model/SimTop91.cpp:47746` / `SimTop22.cpp:22737`）。
  与 stage-03 多索引写端口、stage-04 字段拆分的组合一一对应。

### 3.6 reg-to-mem 在本阶段的定位

- 保持可用：legacy（非 preserve-aggregate）输入仍产生标量寄存器族，reg-to-mem 继续恢复
  一维 array。
- 多维族恢复**不扩展**：reg-to-mem 的多维支持随 stage-07 退役一起取消，不做双重投资。
- 输入为已带 shape 的 GRH 时，reg-to-mem 应自动空转（无可恢复族），加测试钉死。

## 4. 文件级改动点

| 文件 | 改动 |
|------|------|
| `wolvrix/include/grhsim/ir/model.hpp` | 类型系统 width+shape 化（arrayType 退役，value/state 类型带 shape）；state 访问 op 族（mem* 退役）；memWritePlan 排序键注释 |
| `wolvrix/lib/grhsim/ir/verifier.cpp` | §3.2 校验 |
| `wolvrix/lib/grhsim/convert/grh_to_grhsim.cpp` | §3.4 |
| `wolvrix/lib/grhsim/pass/select_state_stores.cpp` | 多维容量/阈值判定（总字节 = 元素宽×∏shape） |
| `wolvrix/lib/grhsim/backend/cpu_layout.cpp` | 按 shape 的 stride 递推；宽元素（>64bit _BitInt 行）× 多维组合支持（§8 Q2） |
| `wolvrix/lib/grhsim/backend/cpu_schedule.cpp` | memWritePlan 多维 staticRow、声明顺序排序键 |
| `wolvrix/lib/grhsim/backend/cpu_phase_emit.cpp` | §3.5 emit 清单 |
| `wolvrix/lib/grhsim/io/json.cpp` + `include/grhsim/io/json.hpp` | 类型 shape 字段编码、arrayType 编码删除、mem* op 编码删除、readArray/writeArray 多索引编码 |
| `wolvrix/lib/grhsim/pass/reg_to_mem.cpp` | 输入带 shape 时空转的短路逻辑 + 测试 |
| `wolvrix/docs/grhsim_ir/` | core.md（§2 类型、§5 state 访问 op 族重写、§8 映射表、§43-44 契约翻转）、cpu.md、cpu-st.md、overview.md 同步 |
| `wolvrix/tests/grhsim/` | 多维 readArray/writeArray、声明顺序优先级、多维 shape 布局（含 >64bit 宽元素组合）、FST 逐元素 dump 与阈值排除、JSON roundtrip、reg-to-mem 空转测试 |

## 5. 基础设施联动

- 持久化：JSON 编码更新（§3.5）；checkpoint 相关调试开关（`--dump-post-lower-json` 等）
  不变。
- diagnostics：verifier 错误带 state 符号与 rank 信息。
- Python 绑定：`lower_grhsim`/`run_grhsim_pass` 接口不变；`store_grhsim` 写新格式。

## 6. 文档更新

- `docs/grhsim_ir/dialects/core.md`：§2 类型（width+shape，arrayType 退役）、§5 state
  访问 op 族整体重写（mem* 退役、readArray/writeArray/fill、声明顺序优先级、
  "bit 不相交"旧约束删除）、§8 GRH 映射表、"不得恢复聚合"契约的翻转说明。
- `docs/grhsim_ir/flows/cpu-st.md`：P_mem 排序键说明更新。
- `docs/grhsim_ir/backends/cpu.md`：多维布局（按 shape 的 stride 递推）、发射形状。
- `docs/grhsim_ir/overview.md`：A7 storeClass 多维判定；"mem 类仅限 core.array"约束
  删除（任何 state 按总字节数分类，storeClass 与 op 族解耦）。

## 7. 破坏面与回退

- 破坏：mem* op 一族整体退役（全部模式匹配点改名/删除，memWriteSeq 收编逻辑删除）；
  grhsim v2 JSON checkpoint 全部失效（重新生成）；`ptmp/sim-refactor-baseline`
  黄金 trace 在 stage-04 接入后必然变化（数组形态改变 op 序列）——基线重钉归 stage-07，
  本阶段先保持单维路径 trace 不变。
- 门禁：本阶段结束时，**单维路径**（现状 HDLBits/xs-bugcase 经 stage-04 前的 ingest）
  应保持全绿；多维路径用新增单测覆盖。
- 回退：emit 多维逻辑为独立函数，可单独 revert 多维部分；JSON 读端只认当前格式。

## 8. 开放问题

1. ~~memRead 部分索引（k < rank，读子数组）是否需要对应 op~~ **已定（2026-10-08）：
   直接支持**。stage-03 §3.3 已把 k<rank 子数组读写定为一等对称规则；GRH→GrhSIM
   转换契约"逐 op 承接、不引入新计算"（core.md:18-20）否决"连续行块读出+拼接"
   （那在转换层引入了新计算）。readArray k<rank 结果类型 = 带剩余维 shape 的数组类型；
   writeArray 索引数 1..rank（§3.2 已改；memWriteSeq 已随 mem* 一族退役）。
2. ~~多维 shape 与"元素宽 >64bit 的 _BitInt 行"的组合~~ **已定（2026-10-08 拍板）：
   必须支持**。真实案例存在（gsim 侧 `putBuffer__DOT__data[8][2]` 元素 _BitInt(256)，
   §3.5 对照）。设计要点：shape stride 递推与元素位宽正交——最内层元素为 _BitInt(N)
   （N>64）时元素存储为 limb 数组（ceil(N/64)×8 字节），行主序线性偏移公式不变
   （offset = 线性下标 × elementWidth），emit 的索引表达式与 _BitInt 截断/扩展规则
   照常作用于元素。实施项：cpu_layout 布局相关 static_assert 逐一核对放宽，补
   多维 × 宽元素的布局/emit/FST 摊平用例。
3. ~~FST 波形对多维数组的展示层级（摊平 vs 层次）~~ **已定（2026-10-09 二修）：
   数组一律逐元素注册 FST var，超过阈值不 dump**。逐元素 var 用方括号规范名
   （`arr[i0][i1]...`），GTKWave 折叠为数组树——FST 格式无一等数组变量类型
   （fstapi.h:120-172），逐元素 var + 命名约定是生态标准做法（Verilator 同款），
   纯发射器改动、不动 IR。阈值沿用现行 `kWaveMaxBytes=512` 总字节上限
   （`cpu_phase_emit.cpp:4216`）：超过则整个数组不进 FST（不做截断式部分 dump）。
   原"摊平为单 var"方案废弃。附带收益：逐元素化解除现行"元素宽 ∈ {8,16,32,64}"
   限制（每元素独立 dump，宽元素走 _BitInt u64-word 镜像路径，与标量相同）。
   实施要点：逐元素 dump 以元素可独立寻址为前提，非字节对齐元素宽的存储布局由
   发射器按位提取（cpu_layout 元素存储规则实施期核对）；句柄数 = ∏shape，阈值已
   隐含上限（512B 内最坏 4096×1bit），实测后再定是否另加元素数上限。mem-class
   状态维持不进 FST（若将来要进，优先评估 `FST_VT_VCD_SPARRAY` 稀疏行变更，
   fstapi.h:144，而非逐元素）。
4. ~~`read`/`write` 现行只处理标量/位向量 state，需推广~~ **已定（2026-10-09 拍板）：
   必须支持**。`read` 对 array state 返回带全 shape 的整体值（承接 kRegisterReadPort）；
   `write` 接受带全 shape 的 `%nextValue`（mask 位掩码宽 = 总位宽）。CPU emit 与标量
   同一路径推广（全宽 _BitInt/limb 拷贝），大数组整体写的发射策略参照 §3.5 的
   arrayCopy 三档（常量折叠 / 逐元素展开 / 循环拷贝）。纯实现工作，无 IR 语义增量。
