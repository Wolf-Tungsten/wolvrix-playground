# F36 第四次 DCE 后的状态与读写访问对齐

香山 `SimTop` 第四次 DCE 后，GRH 有 **145,103 / 147,100（98.6424%）** 个状态与 GSIM 同名同形配对，其中 **145,007 / 145,103（99.9338%）** 个读写访问形状一致。128 个基线写侧差异全部消除，配对状态仍有 96 个读侧差异。最新全图结果见第 9 节。

## 1. 观察点与指标

GRH 取 `dead-code-elim#3` 返回后、`grhsim-dialect-translate` 前的图。GSIM 取 `RemoveDeadNodes3` 返回后、`graphPartition` 前的图，此次调用的原生计时 ID 为 `RemoveDeadNodes#2`。正式基线采用 F35 收尾提交（主仓 `91ca726`、Wolvrix `5091685`、GSIM `15e4983`），同一份 FIRRTL、输入清单、生产 pass 顺序和语义配置。F35 的第十四轮全图早于两项模块级收尾改动，保留其运行身份供复核。[F35 观察点与收尾记录](F35-fourth-dce-alignment-plan.md)

| 计数 | 每个 GRH 状态通过的条件 |
| --- | --- |
| N | R4 图中存活的存储声明，无名、零端口、当前无法配对的声明均计入 |
| S | 在 GSIM 活状态中找到唯一同名同形对应，且反向也唯一 |
| A | 已计入 S，读侧及写侧的访问形状集合分别相等 |

主表报告 S/N、A/N 和 A/S。读、写两侧各自对账，缺少访问形状证据的状态留在分母并标记为未决。

## 2. 状态清单与配对

- **GRH** 遍历展平图全部存活的 `kRegister`、`kLatch` 声明，用声明 operation ID 去重。包括标量、数组、FIRRTL memory 的存储叶、同步读地址或数据等生成的流水寄存器，以及图中可见的其他来源状态。一个有 256 行的 memory 存储叶计 1 个，已拆成 256 个独立存活声明时按实际声明数计。黑盒可见端口只作连接证据，其内部状态以 R4 图中实际存在的声明为准。[GRH 状态类型接口](../../wolvrix/include/core/state.hpp) · [FIRRTL memory 表示](../../wolvrix/docs/ingest/firrtl-memory.md)
- **GSIM** 枚举 R4 的 `graph.regsrc` 和 `graph.memory`，对照原生状态和存活记录。每个寄存器 current/next 对由 current 代表，next 提供写动作证据。每个存活 memory 叶计一项。已常量化、拆分退役的来源、memory 端口成员及其地址和数据引线均保留作归因证据。一个独立的存活地址寄存器仍有自己的一行。[DCE 清理](../../reference/gsim/src/deadNodes.cpp) · [常量寄存器清理](../../reference/gsim/src/constantNode.cpp)
- **名称** 采用两端 R4 存储对象的当前完整层级路径。解码 `name_path_json`，逐段精确比较，保留数组下标、拆分后缀及生成的路径段，记录原生 symbol、声明 ID、来源位置。GRH 从声明的语义归属取名，GSIM 从 current 或 memory 的 `identityPath()` 取名。只有一对一的「完整路径 + 形状」能通过 S。同名重载可由完整形状唯一消歧，同名同形的多候选保留为歧义。别名、历史代表、一对多拆分可解释差异。[GSIM 当前路径定义](../../reference/gsim/include/Node.h)
- **形状** 比较 R4 的存储种类（寄存器、锁存器、存储器）、叶数据类型及位宽、符号性、有序维度。用 GRH 声明的 `stateLogicalType(...).leafWidth()` 和 `shape`，GSIM 用叶宽与 `dimension`，原生 memory 另将 `depth` 放在最外轴。保留单元素轴，`UInt<8>[2][3]` 与 `UInt<8>[3][2]` 计形状差。GRH 用 `kRegister` 承载的 memory 按实存几何、来源与 lowering 记录识别。已标量化的深度一 memory 按当前寄存器匹配，原始 memory 身份另存。签名保留真实存储宽度，`used_width`、二态/四态执行域和初始化策略另列供核查。[GRH 类型读取](../../wolvrix/lib/core/state.cpp) · [深度一标量化与存储几何](../../wolvrix/lib/ingest/firrtl/lower.cpp) · [GSIM memory 字段](../../reference/gsim/src/GraphDumper.cpp)

## 3. 访问形状

每种访问以方向、索引消耗的前缀轴数、访问所得的有序形状和叶位宽表示。例子中状态声明为 `UInt<8>[4][3]`。

| 读操作 | 索引轴数 | 读出形状 | 叶位宽 |
| --- | ---: | --- | ---: |
| 整值读取 | 0 | `[4,3]` | 8 |
| `state[i]` | 1 | `[3]` | 8 |
| `state[i][j]` | 2 | `[]` | 8 |

写侧按写入目标的形状使用相同规则。广播填充计为整值写，有实际写入的复位分支按目标形状计入。一个读写共用口分别提供读和写。相同方向和形状的重复访问归为一类，整值访问和索引访问可以同时存在。索引具体值、访问次数、使能、掩码、时钟、触发条件和延迟均从比较键中省略。先整值读再做组合切片，在状态边界记为整值读。

GRH 从状态读操作的索引操作数、写操作的索引与数据操作数恢复形状。GSIM 从 current 引用、next 赋值左值和实际复位写恢复寄存器访问，从 `OP_READ_MEM` 和 `OP_WRITE_MEM` 恢复 memory 访问。memory 地址消耗最外层深度轴，写入左值上的行内索引继续消耗行内维度。两端各自保留原生操作证据。[GRH 操作数定义](../../wolvrix/docs/grh/grh-json-spec.md) · [GSIM 原生导出](../../reference/gsim/src/SemanticNodeExchange.cpp) · [GSIM memory lowering](../../reference/gsim/src/AST2Graph.cpp)

## 4. 采集与核验

两端在生产停止点导出存储声明和动作，按同一份 FIRRTL 与输入清单校验采集报告，再核对库存 SHA-256。比较器逐状态输出存储 ID、双侧访问集合、单侧独有的访问形状及提取失败的理由。汇总按读写方向和状态类型统计，并检查 `A ≤ S ≤ N`。工具测试覆盖整值访问和索引访问共存、重复形状、子数组、复位写入和 memory 行内索引。

## 5. SimTop 首次全图测量

两端在 R4 导出的原生表均有完成标记。GRH 有 146,811 个存储声明、651,087 条状态动作，GSIM 有 150,791 个存储声明、1,253,484 条状态动作。首轮 GSIM 在写完原生表后遇到 Python 模块导入错误，执行二进制哈希未落盘。修复后复采的状态表与首轮逐字节相同，动作表多了 6,870 条记录。全图比较校验了两端输入、清单及原生库存的 SHA-256。[GRH 采集报告](../../ptmp/firrtl-ingest/F36/capture-v2/grh/capture.json) · [GSIM 复采报告](../../ptmp/firrtl-ingest/F36/capture-v3/gsim/capture.json) · [首次 GSIM 收尾日志](../../ptmp/firrtl-ingest/F36/launch/gsim-inventory-20261126T062448170518752.log)

| GRH 状态配对结果 | 状态数 |
| --- | ---: |
| 同名同形且双向唯一 | 143,317 |
| GSIM 无同名状态 | 998 |
| GSIM 有同名状态，形状不同 | 1,864 |
| GRH 无语义路径 | 416 |
| GRH 有多个路径候选 | 216 |
| 合计 | 146,811 |

另有 7,474 个 GSIM 状态未形成一对一配对。[状态汇总](../../ptmp/firrtl-ingest/F36/analysis-simtop-states-verified/summary.json)

| 已配对状态的访问对账 | 一致 | 差异 | 未决 |
| --- | ---: | ---: | ---: |
| 读写均一致 | 143,093 | 224 | 0 |
| 读侧 | 143,221 | 96 | 0 |
| 写侧 | 143,189 | 128 | 0 |

**A/N 为 97.4675%，A/S 为 99.8437%。** 128 个写侧差异均为 GRH 用一个索引发出带掩码的整行写操作，GSIM 保留行地址和行内索引。根因和原生证据见第 6 节。读侧差异涉及 38 个标量寄存器、58 个数组寄存器。按访问类型分，54 个涉及 GRH 独有的单轴索引读，42 个涉及 GRH 独有的整值读。逐状态记录反映 R4 原生访问边界。[访问汇总](../../ptmp/firrtl-ingest/F36/analysis-simtop-access/summary.json) · [逐状态对账](../../ptmp/firrtl-ingest/F36/analysis-simtop-access/states.jsonl)

```bash
make f36_compare F36_COMPARE_GSIM=ptmp/firrtl-ingest/F36/capture-v3/gsim \
  F36_COMPARE_ARGS=--verify-captures
```

## 6. 缺陷记录：CHIRRTL mport 的行内写索引丢失

**状态：已修复，并在 SimTop R4 逐项复核。** FIRRTL 向 `mport[lane]` 写入时，存储目标是 `mem[row][lane]`。修复前 GRH ingest 将行内索引编码进整行数据和掩码，状态写操作只携带 `row`，使 R4 观察到整行访问。修复后写操作保留两个索引和叶元素形状。

### ICache 实例

源模块 `sram_array_1p128x138m69s1h0l1b_icache_meta` 声明 `smem array : UInt<69>[2][128]`。最外层 128 是深度，行内有两个 69 位元素。下面省略读回连线，保留写入条件与目标。两个掩码位可独立选择行内元素。[SimTop.fir 声明](../../build/xs/rtl/rtl/SimTop.fir#L1001772) · [SimTop.fir 写入](../../build/xs/rtl/rtl/SimTop.fir#L1001788) · [SramProto.scala](../../testcase/xiangshan/utility/src/main/scala/utility/sram/SramProto.scala#L108)

```firrtl
smem array : UInt<69>[2][128]
when RW0.en :
  rdwr mport RW0_rdata_MPORT = array[addr], RW0.clk
  when RW0.wmode :
    when mask0 : connect RW0_rdata_MPORT[0], data0
    when mask1 : connect RW0_rdata_MPORT[1], data1
```

取实例 `cpu.l_soc.core_with_l2.core.frontend.inner.icache.metaArray.banks_0.tagArray.array_0_0_0.array.array.$storage`。该实例两端存储形状均为 `[128,2]`，叶宽均为 69。读侧均为一个索引读出 `[2]`。

| 证据 | R4 原生写入 | 写入形状 |
| --- | --- | --- |
| GRH graph `6866`，状态 op `586129`，写 op `586137` | `kRegisterWriteArrayMaskPort [enable, row, data, mask, clock]`。行地址 value `753681` 为 7 位，数据 `754206` 与掩码 `754209` 均为形状 `[2]`、叶宽 69，共 138 位 | 1 个索引，剩余 `[2]` |
| GSIM 状态 `207295`，读写口 `207303`，写动作 `7349`、`7351` | 两个 `OP_WRITE_MEM` 共享行地址 node `207289`。赋值左值分别携带 `OP_INDEX_INT(0)`、`OP_INDEX_INT(1)`，数据 node 分别为 `207296`、`207297` | 2 个索引，每次剩余 `[]` |

[GRH 原生记录](../../ptmp/firrtl-ingest/F36/capture-v2/grh/state-actions.jsonl#L154912) · [GSIM 原生记录](../../ptmp/firrtl-ingest/F36/capture-v3/gsim/actions.tsv#L7351)

### 修复前的 lowering 路径

1. 静态行内写进入 `Lowerer::connect()`。它把行内索引转换成行内位偏移，将写数据合入 `driver.current` 对应位段，并将相同位段的掩码按连接条件累积到 `driver.memoryMask`。数据和掩码累积器均为完整行形状。
2. 动态行内写走 `appendUpdate()` 和 `finishUpdates()`。行内索引暂存在组合数组更新的条目里，最终发布为整行数据和整行掩码。L3 四个 RefillBuffer 是本次动态样本，其 FIRRTL 写目标为 `MPORT[io.w.beat]`。[RefillBuffer FIRRTL](../../build/xs/rtl/rtl/SimTop.fir#L8474358)
3. `Lowerer::memories()` 从 mport 提取外层地址，从 driver 取整行数据与掩码，再发出只带外层写地址的 `kRegisterWriteArrayMaskPort`。GSIM 的 `whenConnect()` 将 `OP_WRITE_MEM` 放在带原左值的赋值树里，发射时把左值的行内索引拼到 memory 行地址后面。[GSIM 赋值树](../../reference/gsim/src/AST2Graph.cpp#L1239) · [GSIM 写入发射](../../reference/gsim/src/instsGenerator.cpp#L1328)

GRHSIM 按被寻址子数组的叶数遍历，对每个叶执行 `(old & ~mask) | (data & mask)`。掩码为零的位按该公式保持原值。这里确认的是**写操作的寻址粒度被扩大**。该 ICache 实例的逐周期写回和性能影响尚待实测。已有 `partialArrayPort` 用例包含先写两项、再单独写一项并读回另一项的断言，可用于后续验证掩码保持语义。[GRHSIM 掩码合并](../../wolvrix/lib/emit/grhsim/cpu-st-cpp.cpp#L2388) · [现有部分写用例](../../wolvrix/tests/ingest/test_firrtl_memory.cpp#L309)

### 全图范围与修复验收

128 个状态均为 CHIRRTL memory，每个状态恰有一个五操作数 GRH `kRegisterWriteArrayMaskPort`，数据和掩码均为一维行。对应 GSIM 共 1,332 条叶元素写动作，其中 1,328 条保留常量行内索引，4 条保留动态行内索引。

| 实例范围 | 受影响状态 |
| --- | ---: |
| Frontend | 44 |
| MemBlock | 30 |
| L2 | 25 |
| L3 | 29 |
| 合计 | 128 |

逐项证据按 GRH `grh_symbol` 与动作 `target_symbol`、GSIM `gsim_state_id` 与动作 `owner_state_id` 回查。GSIM 筛选表沿用原 TSV 的列顺序，省略表头。[128 个状态](../../ptmp/firrtl-ingest/F36/memory-write-geometry/states.jsonl) · [128 条 GRH 写操作](../../ptmp/firrtl-ingest/F36/memory-write-geometry/grh-write-actions.jsonl) · [1,332 条 GSIM 写动作](../../ptmp/firrtl-ingest/F36/memory-write-geometry/gsim-write-actions.tsv) · [GSIM 列定义](../../ptmp/firrtl-ingest/F36/capture-v3/gsim/actions.tsv#L2)

## 7. 修复与全图复验

CHIRRTL mport 的写连接分别保留条件、行内索引、数据和源码位置。lowering 按连接顺序为同一 mport 生成写操作，将行地址置于行内索引之前，数据和掩码使用被寻址子数组的形状。动态索引的越界检查同时约束写入和跨 Bundle 字段共享的读写模式。标准 `mem` 仍按其声明端口的地址、数据、掩码及延迟降低。[连接采集](../../wolvrix/lib/ingest/firrtl/lower.cpp#L816) · [写操作生成](../../wolvrix/lib/ingest/firrtl/lower.cpp#L1301) · [操作数示例](../../wolvrix/docs/ingest/firrtl-memory.md#L60)

修复后的 ICache 样本在 R4 有两个 `kRegisterWriteArrayMaskPort`，op `570425`、`570428` 分别对应 FIRRTL 第 `1001791`、`1001793` 行。两条写操作各带一个 7 位行地址、一个行内索引，以及各 69 位的数据和掩码，写入形状均为 `[]`。[候选 GRH 原始清单](../../ptmp/firrtl-ingest/F36/mport-fix/capture/grh/state-actions.jsonl)

| 指标 | 修复前 | 修复后 |
| --- | ---: | ---: |
| GRH 存活状态 N | 146,811 | 146,812 |
| 同名同形配对 S | 143,317 | 143,318 |
| 读写访问一致 A | 143,093 | 143,222 |
| A/N | 97.4675% | 97.5547% |
| A/S | 99.8437% | 99.9330% |
| 读侧差异 | 96 | 96 |
| 写侧差异 | 128 | 0 |

候选导出含 652,293 条动作。比较复用 `capture-v3/gsim`，校验了同一输入、清单和捕获文件哈希。以原路径、状态形状和 GSIM ID 逐项核验，原有 128 个写侧差异全部对齐，原有 96 个读侧差异逐项一致。新增配对为 L3 的 6 位寄存器 `cpu.l_soc.l3cacheOpt.tpmeta.rdata.hartid`，其保留原因尚未追踪。[采集报告](../../ptmp/firrtl-ingest/F36/mport-fix/capture/grh/capture.json) · [全图汇总](../../ptmp/firrtl-ingest/F36/mport-fix/comparison/summary.json) · [逐项差量](../../ptmp/firrtl-ingest/F36/mport-fix/comparison/delta.json)

FIRRTL array update、memory、SemanticTree 共 3 项通过，38 个生成的 GRHSIM 内存模型运行通过。回归覆盖静态与动态行内索引、重叠写优先级、越界保持、独立部分写和同步读写口。此轮全图证据为 R4 结构对账，SimTop 整机仿真与性能待测。[原生回归](../../ptmp/firrtl-ingest/F36/lane-regression/tests/test.log) · [生成模型回归](../../ptmp/firrtl-ingest/F36/mport-fix/logs/memory-retry.log)

## 8. R4 读侧差异实例

### PTW `l0BitmapReg` 保留一次子数组读

寄存器形状为 `[64,4,8]`，每个 set 有 4 个 way，每个 way 有 8 个单比特元素。FIRRTL 的 `connect r, l0BitmapReg[l0_ridx]` 将选中 set 的全部 32 个 bit 读给 `r`。[FIRRTL 声明](../../build/xs/rtl/rtl/SimTop.fir#L7090239) · [FIRRTL 读取](../../build/xs/rtl/rtl/SimTop.fir#L7095055)

| R4 | 状态边界的读动作 | 每条动作的读出形状 |
| --- | --- | --- |
| GRH | 一条 `kRegisterReadArrayPort`，唯一操作数是 6 位索引 `l0_ridx` | `[4,8]`，共 32 bit |
| GSIM | 32 条单比特读引用，共用动态索引 `l0_ridx`，后两轴分别遍历 `0..3` 和 `0..7` | `[]`，1 bit |

两边读取同一个 set 的同一组 bit。GRH 用一条操作直接保留了 FIRRTL 的整 set 读，IR 更紧凑，也给后端保留了按块读取的机会。实际执行成本取决于后续生成的代码，尚无性能测量。[GRH 读操作](../../ptmp/firrtl-ingest/F36/mport-fix/capture/grh/state-actions.jsonl#L439521) · [GSIM 读引用](../../ptmp/firrtl-ingest/F36/capture-v3/gsim/actions.tsv#L1226303)

### LoadQueueReplay `uop.exceptionVec` 裁掉一个不用的读

寄存器形状为 `[72,24]`。每条回放路径按自己的 `s1_oldestSel[i].bits` 选中一个队列项，将其中的 `uop` 送入 `s2_replayUop`。输出 `replay_req[i]` 复制该 `uop` 后，将 `exceptionVec[4]`（`loadAddrMisaligned`）固定写成 0。[FIRRTL 队列读取](../../build/xs/rtl/rtl/SimTop.fir#L7392385) · [FIRRTL 输出覆盖](../../build/xs/rtl/rtl/SimTop.fir#L7392692) · [异常位定义](../../testcase/xiangshan/src/main/scala/xiangshan/package.scala#L839)

| R4 | 每条回放路径在状态边界的读动作 | 每条动作的读出形状 |
| --- | --- | --- |
| GRH | 一条 `uop.exceptionVec[idx]`，读取所选队列项的全部 24 位 | `[24]` |
| GSIM | 23 条 `uop.exceptionVec[idx][bit]`，`bit` 覆盖 `0..23` 中除 `4` 外的全部下标 | `[]`，1 bit |

三条回放路径各符合这一模式。GRH 保留了源程序的子数组读，GSIM 逐位读取并裁掉了输出用不到的下标 `4`。这里既有索引轴数的差别，也有实际读取元素范围的差别。[GRH 第一条路径](../../ptmp/firrtl-ingest/F36/mport-fix/capture/grh/state-actions.jsonl#L463348) · [GSIM 第一条路径](../../ptmp/firrtl-ingest/F36/capture-v3/gsim/actions.tsv#L1227803)

## 9. 单元素轴、寄存器切分与声明归属

FIRRTL 生产流程在 `hier-flatten` 后运行 `remove-singleton-state-axis`，将符合条件的 `[1]` 内部寄存器改为标量。整值读取按需重建单元素数组，动态访问保留越界语义。`split-nodes` 的寄存器分析将临时读结果视作状态来源，使引用分析能沿消费端恢复真正被读取的位段。[去轴实现](../../wolvrix/lib/transform/remove_singleton_state_axis.cpp) · [寄存器引用分析](../../wolvrix/lib/transform/split_nodes.cpp#L472) · [去轴回归](../../ptmp/firrtl-ingest/F36/singleton-axis/transform-test.log)

全图复采发现 588 个拆分后的寄存器同时带有原声明路径和读值别名路径，分别来自 372 个单元素数组视图位段和 216 个浮点发射队列 wire 别名位段。`split-nodes` 生成物理位段时曾把两类语义所有者都加到 `kRegister` 声明上，导致 F36 无法唯一取名。现在拆分声明只继承原声明所有者，读值别名仍绑定到对应位段的读结果。定向回归检查声明归属、别名投影绑定和 AliasAnalysis 前后的输出，并将 `EnqEntry_12`、`EnqEntry_26` 重放到第四次 DCE。[归属实现](../../wolvrix/lib/transform/split_nodes.cpp#L1979) · [原生回归](../../ptmp/firrtl-ingest/F36/alias-owner-tests/split-nodes/tests/test.log) · [EnqEntry_12 重放](../../ptmp/firrtl-ingest/F35/module-repro/f36-storage-owner-EnqEntry12/summary.json) · [EnqEntry_26 重放](../../ptmp/firrtl-ingest/F35/module-repro/f36-storage-owner-EnqEntry26/summary.json)

| 第四次 DCE 后的指标 | 声明归属修复前 | 修复后 |
| --- | ---: | ---: |
| GRH 存活状态 N | 147,100 | 147,100 |
| 同名同形配对 S | 144,515（98.2427%） | 145,103（98.6424%） |
| 读写访问一致 A | 144,419 | 145,007 |
| GRH 未配对状态 | 2,585 | 1,997 |
| GRH 有多个路径候选 | 588 | 0 |
| 已配对状态的读侧差异 | 96 | 96 |
| 已配对状态的写侧差异 | 0 | 0 |
| F35 同名 Node | 2,499,594 / 2,515,898（99.35196%） | 2,499,594 / 2,515,898（99.35196%） |

复采校验了两端输入、清单和库存文件哈希。按原 `grh_symbol` 逐项回查，588 个状态均获得唯一声明路径及唯一 GSIM 配对，读写访问均一致。其余逐状态结果和 F35 各类差异计数均保持一致。剩余 1,997 个未配对状态包括 927 个 GSIM 无同名状态、654 个同名形状差和 416 个 GRH 无语义路径。已归因于 GSIM 常量化的 545 个状态按用户决定保留现有处理。[修复前 F36 汇总](../../ptmp/firrtl-ingest/F36/full-r4/comparison/summary.json) · [修复后 F36 汇总](../../ptmp/firrtl-ingest/F36/r4-storage-owner/comparison/summary.json) · [F35 Node 对账](../../ptmp/firrtl-ingest/F35/measure-tests/f36-storage-owner-r4.json)
