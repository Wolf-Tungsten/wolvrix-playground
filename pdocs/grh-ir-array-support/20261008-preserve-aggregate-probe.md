# XiangShan preserve-aggregate SV 形态实证（stage-07a 探针报告）

- 日期：2026-10-08
- 状态：探针完成；mill 全链路复核进行中
- 数据：`ptmp/xs-aggr/SimTop.aggr-all.sv`（353MB / 496 万行）、`SimTop.aggr-vec.sv`（246MB / 437 万行）

## 1. 方法与结论概览

对现有 `build/xs/rtl/rtl/SimTop.fir`（1.6GB，2026-09-03 由 xiangshan mill 流程生成）
直接跑 firtool 1.135.0（即 chisel 7.3.0 配套版本，1.144.0 也已验证支持）：

```
firtool SimTop.fir --preserve-aggregate=<all|vec> -O=release --disable-annotation-unknown \
  --lowering-options=explicitBitcast,disallowLocalVariables,disallowPortDeclSharing,locationInfoStyle=none
```

- 选项存在性确认：`--preserve-aggregate=<none|1d-vec|vec|all>`（两版本 firtool 一致）。
- **`all` 档对 XiangShan 一次通过**，未触发 circt #8931（含 Clock 的 struct）类错误。
- 选项取值注意：是 `1d-vec` 不是 `1d`（stage-07 原文已修正）。

## 2. 形态总览：设计逻辑 100% 是 packed 聚合（integral）

| FIRRTL 源形态 | preserve-aggregate=all 的 SV 形态 |
|---------------|----------------------------------|
| vector | **packed 数组**：`reg [2:0][63:0] nodeOut_a_bits_data_rdata;`（3 维也存在：`reg [3:0][3:0][7:0] SBDATAFieldsReg;`） |
| bundle | **匿名 `struct packed {...}`**（无 typedef，嵌套内联；端口类型可长达数 KB 单行） |
| vector of bundle | 类型后缀：`struct packed {...}[7:0] branches;`、`}[1:0][3:0] entries;` |
| bundle 内 vector | 字段为 packed 数组：`logic [1:0][7:0][5:0] scPathResp;` |
| seqmem | 不变的 unpacked memory：`reg [358:0] Memory[0:1];`（118 处） |
| —（仿真用） | `logic [31:0] _RANDOM[0:N];`（`ifdef ENABLE_INITIAL_REG_` 内） |

**设计逻辑部分没有任何 unpacked 数组声明**（全文件仅 Memory 与 _RANDOM 两类）。
`=vec` 档只保留 packed 数组、不保留 struct（0 处 struct packed）；`=all` 档 73090 处
`struct packed`。

### 2.1 维度普查（mill 全链路 split 产物，2148 文件）

packed 数组 reg/wire（数组维数 = packed 维数−1，最内层为元素位宽）：

| 数组维数 | reg | wire | 例子 |
|---|---|---|---|
| 1 | 392 | 662 | `reg [30:0][7:0] nodeOut_a_bits_data_rdata;` |
| 2 | 75 | 55 | `reg [15:0][15:0][7:0] forward_data_candidate_reg;` |
| 3 | 4 | 4 | `reg [4:0][3:0][1:0][8:0] spec_reg;` |

struct 数组（单行声明口径，跨行声明如 robEntries 未计入，为下限）：

| 维数 | count | 例子 |
|---|---|---|
| 0（纯 struct） | 2501 | `...} data_data;` |
| 1 | 298 | `...}[7:0] enqPtrVec;` |
| 2 | 33 | `...}[19:0][1:0] _entries_io_dataSources;` |
| 3 | 9 | `...}[3:0][1:0][511:0] usefulCtrs;` |

unpacked memory 全部 1 维（118 处，FIRRTL mem 只有深度一维；多维结构在 FIRRTL 层是
向量嵌套，落到 SV 就是 packed）。**结论：多维数组真实存在（reg/wire/struct 三路都到
3 维），多维 kMemory 与多索引端口（stage-03）是硬需求，不是过度设计。**

### 2.2 数组保真度普查：是否存在"一个 FIRRTL 数组被拆成多组"（2026-10-08）

方法：`ptmp/xs-aggr/check_array_split.py`——从 SimTop.fir 提取全部数组声明（名字级去重
17161 个），到 preserve-aggregate=all 的 split SV 产物中按名字核对形态（有同名跨模块
噪音，分类按比例可信、个例已人工抽查）。

| 类别 | 数量 | 含义 |
|------|------|------|
| missing | 15102 | wire 名被优化/改名消除（wire 是中间值，优化期大量消失），非拆分 |
| scalar_flat | 1517 | 数组坍缩为扁平标量/packed 向量（如 `canEnqueue: UInt<1>[8]` → `wire [7:0]`），无损 |
| single_array | 532 | 完整保留为单一聚合 |
| **split_family** | **10** | **一个 fir 数组 → SV 多个 `name_N` 片段** |

split_family 全部落在 **wire（组合值）**上；reg/mem 状态数组零拆分。三种拆分模式
（均已人工核实）：

1. **区间分段**：`thisBank : UInt<64>[64]`（Regfile.scala:180，逐元素 connect 到
   `memForRead[i]`）→ IntRegFile.sv 中 3 个区间段数组：
   `wire [63:0][63:0] thisBank_9 = mem[8'h40 +: 64];` 等（段宽不一：64/64/32）。
2. **used-bits 拆分**：`nxt_f_r_s : UInt<72>[3]`（FloatDivider.scala:1239）→
   4 个不同形状的段：`wire [1:0][55:0] nxt_f_r_s_0;` / `[1:0][27:0] _1` / `[1:0][15:0] _2 _3`，
   按实际使用位段裁剪（其余 DCE）。
3. **部分物化**：`_s1_sramMetaInfo_waymask_WIRE : UInt<36>[4]` → 只剩 2 个
   `wire [3:0]` 片段（`..._WIRE_5`、`..._WIRE_2`），未用部分被 DCE。

结论：拆分是 firtool 对**组合中间值**的优化（DCE/used-bits/区间合并），语义等价、
对我们无害（片段本身是合法小 packed 数组/标量，ingest 直接承接）；**状态数组
（reg/mem）全部完整保留**——reg-to-mem 退休所依赖的声明结构不受影响。
对 ingest 的唯一提示：不要假设 wire 数组的声明形态与 fir 一致，也不要试图把
`name_N` 片段拼回原数组（无必要）。

1. **动态多索引读，含部分索引返回子数组**（TAGE）：
   ```systemverilog
   struct packed {logic [1:0] value;}[3:0][31:0][7:0] takenCounter;   // 3 维数组，元素是 struct
   wire struct packed {logic [1:0] value;}[7:0] _GEN = takenCounter[s2_bankIdx][s2_setIdx];
   ```
   2 个动态索引取 3 维数组 → 剩 `[7:0]` 子数组。与 stage-02 kSliceArray 的 k<n 设计完全对应。
2. **动态索引写 + 优先级链**（寄存器堆形态，reg-to-mem 的现行恢复目标）：
   ```systemverilog
   reg [31:0][6:0] states;
   states[io_trainWriteSetIdx] <= io_trainWriteState;   // else-if 优先级链
   assign io_predictReadState = states[io_predictReadSetIdx];  // 多个动态读端口
   ```
   同类站点约 18 处：`repeat_sel_sel_sources`、`a_d_addrs`/`c_d_addrs`（×8）、`states`、
   `state_vec`、`vpn/s2xlate/getGpa[enqPtr]`、`old_reqs[old_index]`、`bufferTag/bufferSet[insertIdx]`。
   对照：baseline（none 档）中它们是 `reg [4:0] repeat_sel_sel_sources_0;` 式标量族。
3. **常量索引全展开写**：takenCounter 的操作写是 4×32×8=1024 条常量索引条件写
   （`takenCounter[2'h3][5'h1F][3'h7] <= ...`），源自 Chisel 逐元素 `when`，firtool 忠实保留。
4. **整体重置用嵌套赋值模式**：`takenCounter <= '{ '{ '{value:2'h0}, ...`；全文件
   `'{` 共 200590 处。
5. **结构体字面量按字段名构造**：`'{opcode: a.opcode, param: a.param, ...}`。
6. **成员访问与位切混合**：`s2_entries[3'h0].tag`、`s2_startPc.addr[23:0]`。
7. **packed 数组整体当扁平向量用**（混合使用实例）：
   ```systemverilog
   wire [31:0][1:0] _GEN = {{15{repeat_sel_sel_sources[5'h0]}}, repeat_sel_sel_sources};
   wire [1:0] _GEN_0 = _GEN[_repeated_repeater_io_deq_bits_source];
   ```
   `repeat_sel_sel_sources` 同时被动态写（6961 行）、整体拼进 concat、再经 `_GEN` 动态读——
   "kMemory 动态写 + 整体读 + 再动态索引"三合一的案例。
8. `/*cast(bit[31:0])*/` 注释式 cast（explicitBitcast 所致）。

## 4. 对计划的影响（重要修正）

1. **stage-04 开放问题 2 关闭，方向反转**：preserve-aggregate 输出全在 integral 域，
   "packed 维并入元素位宽后不管"会让 `states[31:0][6:0]` 重新折成 224bit 标量、
   动态读写变回 RMW 链，reg-to-mem 依旧退不了休。**packed 数组维度必须保留**——
   但保留方式按访问模式分流（修正 stage-01 §3.1）：
   - packed 数组 + 动态元素访问 → 保留结构：reg 提升为多维 kMemory（stage-03），
     wire/部分索引读 → 带 shape 的 value + kSliceArray（stage-02）。
   - packed 数组 + 仅整体/静态访问 → 仍为标量（SV integral 语义下折叠不丢任何语义）。
   - 该分流与现行 `analyzePackedElementMemoryType`（ingest.cpp:674-710）/
     `isPackedAggregateVariable`（ingest.cpp:510-514）的结构一致，只是结果从
     "拍平 + svPackedArray.* 注解"升级为一等 shape / 多维 kMemory。
   - stage-01 的 op 白名单不受影响：被分进"标量"轨的 packed 数组可合法参与算术；
     被分进"shape"轨的不再出现整体算术（混合使用经 kMemory 整体读承接，见 §3.7 案例）。
2. **struct 边界确认**：packed struct 整体是 integral，端口按名直连
   （`.io_resetVector(io_reset_vector)`），GRH 端口只需位宽/shape 匹配，
   **不需要 struct 类型系统**；字段访问=静态位段（stage-04 §3.1-2 结论不变）。
   数组-of-struct 的元素类型 = struct 扁平位宽。
3. **规模风险量化**：`=all` 比 `=vec` 大约 43%（353MB vs 246MB），主因是嵌套匿名
   struct 类型字符串超长（io_train 端口单行 5KB+）与常量展开写；ingest 解析负担需实测。
   `=vec` 可作为中间档（只保留 packed 数组、不保留 struct）。
4. **unpacked 数组支持优先级下调**：设计逻辑无 unpacked 数组；stage-04 的 unpacked 端口
   保留（`analyzePortType`）仍要做（firtool 其他配置/其他设计可能产出），但不再是
   验收关键路径。
5. mill 全链路（MFC_ARGS 注入 `--firtool-opt "--preserve-aggregate=all"`）**已复核通过**
   （2026-10-08，JDK17，约 6.4 分钟，产物 `ptmp/xs-aggr-build/rtl/` 2148 个 split 文件 +
   1.6GB SimTop.fir；抽查 `TLWidthWidget_2.sv`/`AheadBtb.sv` 与探针形态一致）。
   注意环境约束：mill 0.12.15 需要 JDK 17（JDK 25 会报 class file major version 69），
   mill 经仓库根 launcher 进 PATH。

## 6. 补充（2026-10-08 晚）：§4.1 的解释已被更简方案取代

§4.1 的"访问模式分流 + shape 轨准入约束"是围绕 unpacked 语义安全设计的。确认输出全为
packed（integral）聚合后，方向修正为 **packed-first**：shape 是纯结构视图、不改变任何
op 语义（扁平语义即 packed 的正确语义），因此**不需要 op 白名单，也不需要准入分流**——
packed 维始终进 shape，kMemory 提升仅按写模式决定；value.width 保持总位宽（存量代码
自动正确）。当前设计以 stage-01 §3.1/§3.4、stage-04 §3.1 为准；本节其余原始观察
（§2/§3 的形态与统计）不受影响。

另：§4.2 的"struct 字段访问 = 静态位段"亦已被取代——struct 一律字段级拆分
（`c__DOT__a[n]`，stage-04 §3.1-2），不再有 struct 扁平容器；§4.2 中"不需要 struct
类型系统""端口按名直连"的结论仍成立且被拆分方案进一步简化（字段端口各自匹配）。

再补（同日晚三修）：**kMemory 已整体废除**（stage-03 二修）——本文中所有"提升为多维
kMemory"的表述现应读作"kRegister 数组 + 端口族；regLatch/mem 存储分类归 grhsim A7"。
§3/§7 的形态观察不受影响。

## 5. 复现命令

```bash
# 探针（本报告数据）
~/.cache/llvm-firtool/1.135.0/bin/firtool build/xs/rtl/rtl/SimTop.fir \
  --preserve-aggregate=all -O=release --disable-annotation-unknown \
  --lowering-options=explicitBitcast,disallowLocalVariables,disallowPortDeclSharing,locationInfoStyle=none \
  -o ptmp/xs-aggr/SimTop.aggr-all.sv

# 全链路（JAVA 需 17，mill 经仓库根 launcher 进 PATH）
cd testcase/xiangshan && JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 \
  PATH=/usr/lib/jvm/java-17-openjdk-amd64/bin:<repo>:$PATH NOOP_HOME=$PWD \
  make sim-verilog BUILD_DIR=<repo>/ptmp/xs-aggr-build NUM_CORES=1 RTL_SUFFIX=sv \
  MFC_ARGS='--target systemverilog --firtool-opt "-O=release --disable-annotation-unknown \
    --lowering-options=explicitBitcast,disallowLocalVariables,disallowPortDeclSharing,locationInfoStyle=none" \
    --firtool-opt "--preserve-aggregate=all" --split-verilog --dump-fir'
```

## 7. 案例研究：ROB（2026-10-08，mill 全链路产物）

对象：`ptmp/xs-aggr-build/rtl/Rob.sv`（68MB；baseline `build/xs/rtl/rtl/Rob.sv` 38MB）。

### 7.1 FIRRTL 层（`ptmp/xs-aggr-build/rtl/SimTop.fir`）

```firrtl
regreset robEntries : { vls : UInt<1>, ..., debug_commitType : UInt<2>}[352], clock, reset,
  _robEntries_WIRE    // Rob.scala:169 —— 单个 352 元素 struct 向量寄存器声明，reset 值为聚合 wire
```

写入形态（全部三类的原文实例）：

```firrtl
// (a) 动态下标 + 字段级 + when 守卫（写）——动态写入的唯一形态
when canEnqueue[0] :                                                  // Rob.scala:460
  connect robEntries[allocatePtrVec[0].value].perfDebugInfo.dispatchTime, timer
  connect robEntries[allocatePtrVec[0].value].perfDebugInfo.enqRsTime, timer
  ...
// (b) 动态下标 + 字段级（读）
connect io.debugRobHeadFuType, robEntries[deqPtrVec[0].value].debug_fuType
// (c) 静态下标 + 字段级（Chisel for 循环展开）
connect robEntries[0].wflags, _WIRE.wfflags
```

- 动态下标引用共 **898 处**；**没有整元素动态写**（`connect robEntries[ptr], v` 零处），
  **没有整数组 connect**（`connect robEntries, _WIRE` 零处）——所有动态写都是字段级的
  `connect robEntries[ptr].field, value`。
- 正是"字段级动态写"这个形态导致 firtool 在 SV 侧全部展开（对照 §7.3：ground-type 向量的
  **整元素**动态写 `states[io_trainWriteSetIdx] <= ...` 被保留为动态下标）。

### 7.2 preserve-aggregate=all 的 SV 层

- **声明聚合保留**：`struct packed {...}[351:0] robEntries;`（单符号，元素 = entry struct
  扁平位宽）；`robBanks` 为 `}[7:0][43:0]` 的 bank 视图（wire，strided connect）。
- **但动态下标访问全部消失，0 处动态索引、43152 处常量索引访问**：
  - 读 → 常量索引 mux 树（`cond ? robEntries[9'h102].f : ...` 逐级嵌套）；
  - 写 → **每 entry 无条件下一次状态赋值**（`robEntries[9'h15F] <= _GEN_77303;`，
    守卫折进 RHS 的优先 mux 链），reset 分支用 `'{...}` 全展开。
- 对照 baseline（none 档）：`robEntries_0_vls` × 352 × ~50 字段的标量族。
- 文件体积反而更大（68MB vs 38MB）：struct 类型字符串在展开表达式中反复出现。

### 7.3 动态访问保留/展开的规律（初步归纳）

| 形态 | firtool 行为 | 例子 |
|------|-------------|------|
| ground-type 向量的整体动态写 | **保留** | `states[io_trainWriteSetIdx] <= io_trainWriteState;` |
| struct 向量的动态读 | **保留**（部分索引也保留） | `takenCounter[s2_bankIdx][s2_setIdx]` |
| struct 向量的动态读 | **展开为 mux 树** | `robEntries[...]`（原因待查：可能与读写混合/写已展开有关） |
| 字段级动态写 | **展开为常量索引** | `robEntries`（896 处 FIRRTL 动态写全部消失） |

规律待 stage-07a 续查确认（firtool 内部 ExpandSubaccesses/LowerTypes 的交互），
不排除与"写已展开的数组读也随之展开"这类级联有关。

### 7.4 对计划的含义

1. **声明结构一等保留**是直接的收益：单符号 + shape，不再需要按命名模式猜家族
   （reg-to-mem 的 shape 网格恢复路径整个不需要了）。
2. **ROB 这类"每拍全量写"的数组其自然映射是 kRegister(shape) 整体写口 +
   组合 next-value**，而不是 kMemory——没有稀疏写可利用。这也再次支持
   "kMemory 提升按写模式判断、与 shape 记录解耦"的决策（stage-04 §8-2）。
3. 常量展开的 mux 树读在 oblivious 仿真里是普通数据流节点，功能正确；代价是
   激活粒度粗（读全数组）。是否做"mux 树 → 动态读"的逆向识别（轻量版 reg-to-mem，
   对象从标量族变为单数组的常量访问集合，可靠性高得多）留作 stage-06 的性能议题，
   不属于正确性关键路径。
4. 编译负担预警：68MB 单模块、5KB+ 的匿名 struct 类型字符串反复出现，对 slang 解析
   与 ingest 的类型比较是实测点（stage-04 风险项）。

## 7.5 ROB 写入的完整链条（FIRRTL → SV 展开对照）

### 源语义（SimTop.fir，Rob.scala）

```firrtl
; Rob.scala:193 —— allocatePtrVec: 第 i 个入队请求分配到的 ROB entry 指针（9bit 值 + flag）
wire allocatePtrVec : { flag : UInt<1>, value : UInt<9>}[8]
connect allocatePtrVec[0], enqPtrVec[0]                    ; 第 0 个 = 当前 enq 指针
connect allocatePtrVec[1], enqPtrVec[_allocatePtrVec_T]    ; 第 i 个 = enqPtrVec[前 i-1 个有效首 uop 的累计数]
...

; Rob.scala:197 —— canEnqueue[i] = req[i].valid & req[i].bits.firstUop & io.enq.canAccept
wire canEnqueue : UInt<1>[8]
connect canEnqueue[0], _canEnqueue_T_1
...

; Rob.scala:460-464 —— 动态下标 + 字段级 + when 守卫的写入（源语义）
when canEnqueue[0] :
  connect robEntries[allocatePtrVec[0].value].perfDebugInfo.dispatchTime, timer
  connect robEntries[allocatePtrVec[0].value].perfDebugInfo.enqRsTime, timer
  ...（7 个 perf 字段）
```

### SV 展开（Rob.sv，preserve-aggregate=all）——对每个 entry e（0..351，以 e=9'h15F 为例）

```systemverilog
// (1) 地址译码：本 entry 是否第 i 个入队端口的分配目标（8 个端口各一位，one-hot 命中向量）
wire _GEN_32545 = _GEN_456.value == 9'h15F;    // _GEN_456 ≙ allocatePtrVec[7]
wire [7:0] _GEN_827 =
  _GEN_475                                     // 全局使能
  & {{_GEN_456.value == 9'h15F}, ..., {enqPtrVec[3'h0].value == 9'h15F}};
assign enqOH_703 = _GEN_827;                   // enqOH_703[i] = 端口 i 写入 entry 9'h15F

// (2) 每个字段一个 8 源优先 mux（canEnqueue 链）或 one-hot OR（enqOH 链），兜底保持旧值
wire _GEN_36409 = canEnqueue[3'h7] & _GEN_32545;   // 端口 7 有效 且 目标是本 entry

_GEN_77303 =    // entry 9'h15F 的下一状态（整个 entry struct）
  '{vls: (_GEN_36409 ? io_enq_req[3'h7].bits.vlsInstr     // 端口 7 写入
          : _GEN_31490 ? io_enq_req[3'h6].bits.vlsInstr   // 否则端口 6……
          : ...
          : robEntries[9'h15F].vls),                       // 都不写 = 保持
    ...
    perfDebugInfo: '{...
      tlbRespTime: (enqOH_703[3'h7] ? io_enq_req[3'h7].bits...tlbRespTime : 64'h0)
                 | (enqOH_703[3'h6] ? ... : 64'h0) | ...
                 ... 合成的下一值 ...}};

// (3) always 块：每个 entry 每拍无条件写下一状态
always @(posedge clock) begin
  if (reset) robEntries[9'h15F] <= '{...全零...};
  else       robEntries[9'h15F] <= _GEN_77303;
end
```

### "展开"的本质

动态下标写 `robEntries[ptr].f <= v`（语义：ptr 指向的 entry 的 f 字段更新）被 firtool
物化成 **地址译码 + 按 entry 分发**：每个 entry 一份静态写，RHS 是"所有可能写到本 entry
的来源"的优先 mux，选择条件是 `allocatePtrVec[i].value == 本 entry 常量地址`。
352 entry × 8 入队端口 × 每字段一条 mux 链，这就是 68MB 的来源。
