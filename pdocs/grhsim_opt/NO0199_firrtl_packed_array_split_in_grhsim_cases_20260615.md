# NO0199 FIRRTL Vec-of-Bundle 在 GrhSIM 中被拆开的事实对比案例集

记录日期：2026-06-15

本文只列事实对比，不做分析。每个案例给出：来源（Scala/类型层级）、FIRRTL 片段、
SystemVerilog 片段、`gsim` 对应 C++、`grhsim` IR（GRH JSON）、`grhsim` 对应 C++。
读写行为尽量展开到能直接看出。

> 收录门槛：只保留**当前 HEAD 树可复现**的案例。原先的
> `XsIcacheReplRegsCatLarge`（`Vec[128] of UInt<3>` 动态下标读）案例因其 Scala 源已不在
> 当前树内（`52672b1` 引入、`a9228ee` 删除），无法从 HEAD 直接重生成，已**移除**。

口径说明（同一事实，适用于全部案例）：

- 两个案例**都没有开 `--preserve-aggregate`**。
  - 案例 1（xs-components）经 `XsComponentsMain` 走 `ChiselStage`，firtool 选项只有
    `FirtoolOption("--disable-all-randomization")`。
  - 案例 2（XiangShan 标准 flow）的 firtool 选项见 NO0198 与下方第 0 节，同样无
    `--preserve-aggregate`。
- `gsim` 读 FIRRTL `.fir`，Vec / Bundle 作为一等聚合类型保留。
- `grhsim` 读 firtool 之后的 SystemVerilog。
- 两个案例都是 `Vec-of-Bundle` 在默认 lowering 下被 firtool 完全标量化成 per-field
  标量（与 NO0197 一致：Vec-of-UInt 可留 packed，Vec-of-Bundle 被拆字段摊平）。

产物来源：

| 案例 | FIR | SV | gsim cpp | grhsim IR | grhsim cpp |
| --- | --- | --- | --- | --- | --- |
| 1 `XsReal100BackendNfmappedelemidxSmall` | `testcase/xs-components/build/XsReal100BackendNfmappedelemidxSmall/chisel-fir/` | `.../chisel-sv/` | `.../gsim/model/` | `.../grhsim/` | `.../grhsim/model/` |
| 2 XiangShan FTQ `metaQueueResolve` | `build/xs/rtl/rtl/SimTop.fir` | `build/xs/rtl/rtl/Ftq.sv` | `build/xs/gsim/gsim-compile/model/` | （见正文 op kind） | `build/xs/grhsim/grhsim_emit/` |

---

## 0. 验证记录（可复现性与 preserve-aggregate 复核，2026-06-15）

`--preserve-aggregate` 历史窗口（仅 xs-components 的 `XsComponentsMain`）：
`37771c5`（2026-05-25）加入 `FirtoolOption("--preserve-aggregate=1d-vec")`，
`f578751`（2026-05-30）移除；当前 HEAD 只剩 `--disable-all-randomization`。

各保留案例的复核：

- 案例 1 `XsReal100BackendNfmappedelemidxSmall`：源文件在当前 HEAD 树内且已注册。
  **复核动作**：用当前工具链（无 preserve-aggregate）重新生成，FIR 与 SV 与现存
  artifact **逐字节一致**。本文片段即取自该一致产物。
- 案例 2 XiangShan FTQ：`build/xs/rtl` 的 RTL 生成命令
  （`build/xs/rtl/.../time.log`）为
  `--lowering-options=explicitBitcast,disallowLocalVariables,disallowPortDeclSharing,locationInfoStyle=none --split-verilog --dump-fir`，
  **不含 `--preserve-aggregate`**；`build/xs/rtl/rtl/Ftq.sv` 中 `struct packed` 计数为
  `0`，`metaQueueResolve_*` 为 `65536` 条标量 reg。所用产物为同期构建：
  `SimTop.fir` / `Ftq.sv`（2026-06-09）、`gsim-compile`（2026-06-15）、`grhsim_emit`
  （2026-06-15），三者 `providerUsefulCtr` 维度均为 `[64][8]`，一致。

> 已移除案例 `XsIcacheReplRegsCatLarge`：其源在 HEAD 树内不存在；从 `52672b1` 恢复源、
> 临时注册后用当前工具链重生成，去掉 source-location 注释后与现存 artifact 逐字节一致、
> 且 `struct packed=0`（即并非 preserve-aggregate 产物）。但因不满足「HEAD 直接可复现」
> 门槛，本文不再收录其片段。

---

## 案例 1：`Vec[8] of Bundle{from,until}` 整体动态选（firtool 标量化）

形态：

- FIRRTL：`wire out : { idxRangeVec : { from : UInt<8>, until : UInt<8>}[8]}`；
  写为整 Bundle-数组动态选 `connect out.idxRangeVec, shiftedRangeTable[nf]`。
- SV：被 firtool 拆成 16 条标量 `out_idxRangeVec_{0..7}_{from,until}`，每条各自
  `_GEN_k[_nf_T]`。
- 读写行为：组合逻辑；`shiftedRangeTable` 是 `{from,until}[8][8]`，用 `nf` 选一行
  `{from,until}[8]` 给 `out.idxRangeVec`。

### 1.1 FIR 片段

```firrtl
wire out : { idxRangeVec : { from : UInt<8>, until : UInt<8>}[8]}
wire rangeTable : { from : UInt<8>, until : UInt<8>}[8][8]
wire shiftedRangeTable : { from : UInt<8>, until : UInt<8>}[8][8]

connect out.idxRangeVec, shiftedRangeTable[nf]
```

`dontTouch` 注解（说明 aggregate 在 FIR 里保留到字段级）：

```
"target":"~|XsReal100BackendNfmappedelemidxSmall>out.idxRangeVec[0].until"
"target":"~|XsReal100BackendNfmappedelemidxSmall>out.idxRangeVec[0].from"
; ... [1..7].until / .from
```

### 1.2 SV 片段

16 条标量 wire，每条独立 per-field 动态选；再拼回 64-bit：

```systemverilog
wire [7:0] out_idxRangeVec_0_from  = 8'h0;
wire [7:0] out_idxRangeVec_0_until = _GEN[_nf_T];
wire [7:0] out_idxRangeVec_1_from  = _GEN_0[_nf_T];
wire [7:0] out_idxRangeVec_1_until = _GEN_1[_nf_T];
// ... out_idxRangeVec_2..7 的 from / until 同形（_GEN_2 .. _GEN_13）
wire [7:0] out_idxRangeVec_7_until = _GEN_13[_nf_T];

// 拼回（从 idxRangeVec_*_from）
{out_idxRangeVec_7_from, out_idxRangeVec_6_from, out_idxRangeVec_5_from,
 out_idxRangeVec_4_from, out_idxRangeVec_3_from, out_idxRangeVec_2_from,
 out_idxRangeVec_1_from, out_idxRangeVec_0_from};
```

### 1.3 gsim C++

按字段拆成 SoA 数组，Vec 维保留为数组下标，动态选为按下标整行拷贝。

头文件声明：

```cpp
uint8_t shiftedRangeTable$$from[8][8];  // width = 8, lineno = 96
uint8_t shiftedRangeTable$$until[8][8]; // width = 8, lineno = 96
uint8_t out$$idxRangeVec$$from[8];      // width = 8, lineno = 94
uint8_t out$$idxRangeVec$$until[8];     // width = 8, lineno = 94
```

动态选（`shiftedRangeTable[_nf_T]`）：

```cpp
_nf_T = (io$$in0 ^ (io$$ctrl & 0x7));
for(int i0 = 0; i0 < 8; i0 ++) { out$$idxRangeVec$$from[i0]  = shiftedRangeTable$$from[_nf_T][i0]; }
for(int i0 = 0; i0 < 8; i0 ++) { out$$idxRangeVec$$until[i0] = shiftedRangeTable$$until[_nf_T][i0]; }
```

### 1.4 grhsim IR

每个 `(下标, 字段)` 是独立标量值，定义为 `kSliceArray(_GEN_k, _nf_T)`：

```json
{"sym": "out_idxRangeVec_0_until", "w": 8, "type": "logic", "def": "_op_282",
 "users": [{"op": "_op_3057", "idx": 7}, {"op": "_op_3098", "idx": 7}]}

{"sym": "_op_282", "kind": "kSliceArray", "in": ["_GEN", "_nf_T"],
 "out": ["out_idxRangeVec_0_until"], "attrs": {"sliceWidth": {"t": "int", "v": 8}},
 "loc": {"file": ".../XsReal100BackendNfmappedelemidxSmall.sv", "line": 40, "col": 45}}
```

### 1.5 grhsim C++

每个字段各自重建一个 64-bit packed word（8 lane × 8-bit）再按 `idx*8` 动态移位取
字节；之后再把 8 个字段拼回输出。

索引（`_nf_T`）：

```cpp
const std::uint8_t grhsim_v17_0 =
    static_cast<std::uint64_t>(((io_in0) >> 0) & UINT64_C(7))
  ^ static_cast<std::uint64_t>(((io_ctrl) >> 0) & UINT64_C(7));
```

单字段动态切片（`out_idxRangeVec_0_until` 等，每字段一条）：

```cpp
const std::uint8_t grhsim_v20_0 =
  ((static_cast<std::uint64_t>(static_cast<std::uint64_t>(grhsim_v17_0) * UINT64_C(8)) >= UINT64_C(64))
   ? UINT64_C(0)
   : ((((static_cast<std::uint64_t>((grhsim_value_81_0_slot) & UINT64_C(255))) << 56)
      | /* << 48 | << 40 | << 32 | << 24 | << 16 | << 8 | lane0 */
      ((grhsim_value_88_0_slot) & UINT64_C(255)))
      >> static_cast<unsigned>(static_cast<std::uint64_t>(static_cast<std::uint64_t>(grhsim_v17_0) * UINT64_C(8)))))
  & UINT64_C(255);
// grhsim_v22_0, grhsim_v24_0, ... 各字段同形
```

字段拼回（输出 word）：

```cpp
const std::uint64_t grhsim_v50_0 =
    ((static_cast<std::uint64_t>((grhsim_v48_0) & UINT64_C(255))) << 56)
  | ((static_cast<std::uint64_t>((grhsim_v44_0) & UINT64_C(255))) << 48)
  | /* ... */
  | ((static_cast<std::uint64_t>((grhsim_v24_0) & UINT64_C(255))) << 8)
  | ((grhsim_v20_0) & UINT64_C(255));
```

---

## 案例 2：XiangShan FTQ `metaQueueResolve`（`Vec[64] of Bundle`，内含 `tage.entries : Bundle[8]`、`mbtb.entries : Bundle[4][2]`）

### 2.1 来源（Scala → 类型层级）

`metaQueueResolve` 是 FTQ 里存「训练 BPU 用的 meta」的寄存器队列，整条按 ftq 下标存取：

```scala
// testcase/xiangshan/src/main/scala/xiangshan/frontend/ftq/Ftq.scala
private val metaQueueResolve = Reg(Vec(FtqSize, new BpuResolveMeta))      // :103  FtqSize=64（SimTop 口径）

when(io.fromBpu.meta.valid) {                                            // :184
  val s3BpuPtr = io.fromBpu.s3FtqPtr.value
  metaQueueResolve(s3BpuPtr) := io.fromBpu.meta.bits.resolveMeta         // :186  整条写
}

io.toBpu.train.bits.meta := metaQueueResolve(resolveQueue.io.bpuTrain.bits.ftqIdx.value)  // :336  整条读
```

`BpuResolveMeta` 类型层级（`.../frontend/bpu/Bundles.scala:278` 等）——`[4][2]` / `[8]`
就是这里的嵌套 `Vec` 来的：

```scala
class BpuResolveMeta {
  val mbtb:   MainBtbMeta   // entries = Vec(NumAlignBanks=2, Vec(NumWay=4, MainBtbMetaEntry))  → FIR [4][2]
  val tage:   TageMeta      // entries = Vec(NumBtbResultEntries=8, TageMetaEntry)               → FIR [8]
  val sc; val ittage; val phr; val debug_utage
}
class MainBtbMetaEntry { rawHit; position; attribute{branchType, rasAction}; counter{value} }
class TageMetaEntry    { useProvider; providerTableIdx; providerWayIdx;
                         providerTakenCtr{value}; providerUsefulCtr{value}; altOrBasePred }
```

即：`metaQueueResolve` 是「64 槽 × 一个 `BpuResolveMeta`」的寄存器堆；其中
`mbtb.entries` 的 `[4][2]` = `Vec(NumAlignBanks=2, Vec(NumWay=4, …))`（FIRRTL 把内层维度
写在前面 → `[way=4][bank=2]`，bank∈[0,2)、way∈[0,4)，每槽 8 个 mbtb entry），
`tage.entries` 的 `[8]` = `Vec(8, TageMetaEntry)`。写/读都是按动态下标整条存取。

### 2.2 FIR 片段

寄存器声明（外层 `[64]`；mbtb 内层 `[4][2]`、tage 内层 `[8]` 这里完整展开，其余字段省略为 `…`）：

```firrtl
reg metaQueueResolve : {
  mbtb : { entries : { rawHit : UInt<1>, position : UInt<5>,
                       attribute : { branchType : UInt<2>, rasAction : UInt<2>},
                       counter : { value : UInt<2>}}[4][2]},
  tage : { entries : { useProvider : UInt<1>, providerTableIdx : UInt<3>,
                       providerWayIdx : UInt<2>, providerTakenCtr : { value : UInt<3>},
                       providerUsefulCtr : { value : UInt<2>}, altOrBasePred : UInt<1>}[8]},
  sc : {…}, ittage : {…}, phr : {…}, debug_utage : {…}
}[64], clock @[.../frontend/ftq/Ftq.scala 103:37]
```

写（单条整 Bundle、动态下标 `s3FtqPtr`）：

```firrtl
connect metaQueueResolve[io.fromBpu.s3FtqPtr.value], io.fromBpu.meta.bits.resolveMeta
  @[.../frontend/ftq/Ftq.scala 186:33]
```

读（单条整 Bundle、动态下标 `bpuTrain.ftqIdx`）：

```firrtl
connect io.toBpu.train.bits.meta, metaQueueResolve[resolveQueue.io.bpuTrain.bits.ftqIdx.value]
  @[.../frontend/ftq/Ftq.scala 336:...]   ; SimTop.fir:1655855
```

> FIR 里 `metaQueueResolve` 是一等 `Vec[64]`，写、读各只有一条 `connect`，下标是动态
> `s3FtqPtr` / `ftqIdx`。

### 2.3 SV 片段（firtool 默认 lowering：存储侧所有维度——含内层多维 Vec——全摊平为标量；唯一活下来的数组在读侧）

整个 `metaQueueResolve` 族在 `Ftq.sv` 中是 `65536` 条标量 `reg`
（`grep -c 'metaQueueResolve_' Ftq.sv = 65536`）；`grep -c 'struct packed' Ftq.sv = 0`。

**先说明「内层数组」的去向**：默认 lowering 下，存储侧（`reg`）**所有 Vec 维都被摊平**——
不仅外层 `[64]`，连内层一维、二维 Vec 也是。三种内层形态实证（均以 slot 0 为例）：

```systemverilog
// (a) tage.entries[8]（一维 Vec-of-Bundle）-> _<entry>_<field>
reg  [1:0]  metaQueueResolve_0_tage_entries_0_providerUsefulCtr_value;   // :3588  entry 0
reg  [2:0]  metaQueueResolve_0_tage_entries_0_providerTakenCtr_value;
reg         metaQueueResolve_0_tage_entries_0_useProvider;
// ... entries_1..7

// (b) mbtb.entries[4][2]（二维 Vec-of-Bundle）-> _<bank>_<way>_<field>
reg         metaQueueResolve_0_mbtb_entries_0_0_rawHit;     // bank0 way0
reg  [4:0]  metaQueueResolve_0_mbtb_entries_0_0_position;
// ... entries_0_1 .. _1_3（bank∈{0,1}, way∈{0..3}）

// (c) sc.scPathResp（二维 Vec-of-UInt，FIR: UInt<6>[8][2]）-> 仍然全摊平成 16 条标量
reg  [5:0]  metaQueueResolve_0_sc_scPathResp_0_0;   // :3632
reg  [5:0]  metaQueueResolve_0_sc_scPathResp_0_1;
// ... _0_2 .. _0_7, _1_0 .. _1_7（共 8×2=16 条；slot 0 这一字段就 16 个标量）
```

> 注意 (c)：`sc.scPathResp` 是 **Vec-of-UInt**（地面类型），按 NO0197「Vec-of-UInt 可留
> packed」似乎应保成 `reg [7:0][5:0]`，但那是 `--preserve-aggregate` 档下的行为；本
> **默认 lowering** 下它照样被摊成 16 条标量。也就是说：`Ftq.sv` 里 `metaQueueResolve` /
> `metaQueueRedirect` 这些 `Reg(Vec(64, Bundle))`，**存储侧没有任何内层数组幸存**
> （`reg [a:b][c:d]` 0 条命中该族）。

每个槽是 `metaQueueResolve_<slot>_…` 一族，槽与槽之间只是 `_0_`/`_1_`/`_2_` 的区别：

```systemverilog
reg  [1:0]  metaQueueResolve_0_tage_entries_0_providerUsefulCtr_value;   // :3588  slot 0
reg  [1:0]  metaQueueResolve_1_tage_entries_0_providerUsefulCtr_value;   // :3844  slot 1
reg  [1:0]  metaQueueResolve_2_tage_entries_0_providerUsefulCtr_value;   // :4100  slot 2
// ... 一直到 metaQueueResolve_63_tage_entries_0_providerUsefulCtr_value（共 64 槽）
```

写：动态下标被展开成**每槽一个 `==` 比较的写使能**，对 64 个槽各写一遍：

```systemverilog
// Ftq.sv:48716-48719 —— 逐槽写使能
wire _GEN_482 = io_fromBpu_meta_valid & io_fromBpu_s3FtqPtr_value == 6'h0;  // slot 0
wire _GEN_483 = io_fromBpu_meta_valid & io_fromBpu_s3FtqPtr_value == 6'h1;  // slot 1
wire _GEN_484 = io_fromBpu_meta_valid & io_fromBpu_s3FtqPtr_value == 6'h2;  // slot 2
// ... _GEN_485(==6'h3) ... 共 64 个

always @(posedge clock) begin
  if (_GEN_482) begin                                          // Ftq.sv:68617  slot 0
    metaQueueResolve_0_tage_entries_0_providerUsefulCtr_value
      <= io_fromBpu_meta_bits_resolveMeta_tage_entries_0_providerUsefulCtr_value;
    // ... slot 0 的其余 tage / mbtb / ... 字段
  end
  if (_GEN_483) begin                                          // Ftq.sv:69244  slot 1
    metaQueueResolve_1_tage_entries_0_providerUsefulCtr_value
      <= io_fromBpu_meta_bits_resolveMeta_tage_entries_0_providerUsefulCtr_value;
    // ...
  end
  if (_GEN_484) begin                                          // Ftq.sv:69871  slot 2
    metaQueueResolve_2_tage_entries_0_providerUsefulCtr_value
      <= io_fromBpu_meta_bits_resolveMeta_tage_entries_0_providerUsefulCtr_value;
    // ...
  end
  // slot 3..63 各有同样一段（注意 RHS 都是同一个 io_fromBpu_..._tage_entries_0_...，
  // 只有 LHS 的槽号不同——这正是“整条 indexed write”被摊成 64 段的形态）
end
```

读：这才是**唯一在 SV 里以数组形态活下来的维度**。`metaQueueResolve[ftqIdx]` 的整条读，
被还原成**每个 (entry, 字段) 一条 `wire [63:0][W:0] _GEN_k`**——把 64 个槽的同一标量收集成
一个真正的 packed array，再按 `ftqIdx` 动态选（与已删除的 `_GEN_511` 同构，只是这里每
(entry,字段) 一份、共数百份）。我们这个字段对应的就是 `_GEN_90`：

```systemverilog
// Ftq.sv:30053 —— 把 64 个槽的 tage.entries[0].providerUsefulCtr 收集成 [64] packed array
wire [63:0][1:0] _GEN_90 =
  {{metaQueueResolve_63_tage_entries_0_providerUsefulCtr_value},
   {metaQueueResolve_62_tage_entries_0_providerUsefulCtr_value},
   // ... _61 .. _0
   {metaQueueResolve_0_tage_entries_0_providerUsefulCtr_value}};

// Ftq.sv:147948 —— 按 train ftqIdx 动态选 1 个槽
_GEN_90[_resolveQueue_io_bpuTrain_bits_ftqIdx_value];
```

> 关于「内层数组」的精确事实：连读侧也**没有保留内层 Vec 维度**。`tage.entries[8]` 不是被
> 还原成一个三维 `wire [63:0][7:0][1:0]`，而是被拆成 **8 条** 各自独立的
> `wire [63:0][1:0] _GEN_*`（entry 0 一条、entry 1 一条……）。`Ftq.sv` 里三维 packed
> 数组（`[a:b][c:d][e:f]`）命中数为 `0`；活下来的只有「64 槽 × 单字段」这一层 packed array。

### 2.4 gsim C++（外层 64 保留为动态下标，内层展开为定长数组）

头文件声明——Vec 维度全部保留为 C 数组维：

```cpp
// tage.entries[8]    -> [ftq=64][entry=8]
uint8_t ...metaQueueResolve__DOT__tage__DOT__entries__DOT__providerUsefulCtr__DOT__value[64][8];       // width=2
uint8_t ...metaQueueResolve__DOT__tage__DOT__entries__DOT__providerUsefulCtr__DOT__value$NEXT[64][8];
// mbtb.entries[4][2] -> [ftq=64][bank=2][way=4]
uint8_t ...metaQueueResolve__DOT__mbtb__DOT__entries__DOT__rawHit[64][2][4];                            // width=1
```

写（`when(meta.valid)` → 在动态选中的 `s3_ftqPtr` 槽位整条写；外层 O(1)，内层展开）：

```cpp
// tage.entries：在 [s3_ftqPtr] 槽位写 8 个 entry
..._providerUsefulCtr__DOT__value$NEXT[ ...s3_ftqPtr ][0] = ...s3_resolveMeta_tage_r..providerUsefulCtr__DOT__value_0;
..._providerUsefulCtr__DOT__value$NEXT[ ...s3_ftqPtr ][1] = ...value_1;
// ... [2..7]
// mbtb.entries：同一个 [s3_ftqPtr] 槽位写 bank×way
..._mbtb..rawHit$NEXT[ ...s3_ftqPtr ][0][0] = ...s3_resolveMeta_mbtb_r..rawHit_0_0;
..._mbtb..rawHit$NEXT[ ...s3_ftqPtr ][0][1] = ...rawHit_0_1;
// ... [bank][way]
```

读（在动态选中的 `ftqIdx` 槽位整条读；外层 O(1)，内层 8 拷贝）：

```cpp
for(int i0 = 0; i0 < 8; i0 ++) {
  ...io__DOT__toBpu__DOT__train__DOT__bits__DOT__meta__DOT__tage..providerUsefulCtr__DOT__value[i0]
    = ...metaQueueResolve__DOT__tage..providerUsefulCtr__DOT__value[ /* ftqIdx */ ][i0];
}
```

### 2.5 grhsim IR（每个 `(槽, entry, 字段)` 都是独立标量寄存器）

```
// op _op_1811210  [kRegisterWritePort] reg=...metaQueueResolve_57_tage_entries_2_providerUsefulCtr_value
// op _op_11969901 [kRegisterReadPort]  reg=...metaQueueResolve_49_tage_entries_2_providerUsefulCtr_value
```

仅 `tage.entries[*].providerUsefulCtr.value` 这一个字段，在 `[64][8]` 维度下就是 `512`
个标量寄存器、对应 `512` 个 `kRegisterWritePort`：

```
grep -ohE 'metaQueueResolve_[0-9]+_tage_entries_[0-9]+_providerUsefulCtr_value' build/xs/grhsim/grhsim_emit/*.cpp | sort -u | wc -l
# 512
```

### 2.6 grhsim C++（每个标量各一段 guarded masked commit；读侧 64 路 gather）

写——每个标量寄存器各自一段：先按**该槽写使能** `value_bool_slots_[…]`
（= `meta.valid & s3FtqPtr==该槽`）gate，再 masked write + 变化检测 + 重激活下游：

```cpp
if ((value_bool_slots_[12227]) != 0) {   // slot 57 的写使能
    // op _op_1811210 [kRegisterWritePort] reg=...metaQueueResolve_57_tage_entries_2_providerUsefulCtr_value
    {
        const auto next_value = static_cast<std::uint8_t>(
            (grhsim_value_storage_ref<std::uint8_t>(state_logic_storage_, 298696) & ~value_u8_slots_[0])
            | (value_u8_slots_[3980] & value_u8_slots_[0]));
        if (grhsim_value_storage_ref<std::uint8_t>(state_logic_storage_, 298696) != next_value) {
            grhsim_value_storage_ref<std::uint8_t>(state_logic_storage_, 298696) = next_value;
            commit_activated_readers_ = true;
            supernode_active_curr_[2953u] |= UINT8_C(128);
        }
    }
}
// 相邻字段 metaQueueResolve_57_tage_entries_2_altOrBasePred 等各自同形一段；64 个槽各一份
```

读——`metaQueueResolve[ftqIdx]` 的整条读被拆成「对每个字段，把 64 个槽的标量都读出来再按
`ftqIdx` 选」，表现为一大簇逐槽 `kRegisterReadPort`：

```
// op _op_11969672 [kRegisterReadPort] reg=...metaQueueResolve_50_tage_entries_0_providerUsefulCtr_value
// op _op_11975012 [kRegisterReadPort] reg=...metaQueueResolve_44_tage_entries_0_providerUsefulCtr_value
// op _op_11979731 [kRegisterReadPort] reg=...metaQueueResolve_38_tage_entries_0_providerUsefulCtr_value
// ... 同一字段的 64 个槽各一条，最后按 ftqIdx 选 1 个
```

---

## 附：未带 FIR 的最小复现（手写 SV，HEAD 树内）

下列 bugcase 直接手写 packed aggregate SV（无 FIR），可用 `make -C testcase/xs-bugcase/CASE_0xx run` 复现同类形态：

- `testcase/xs-bugcase/CASE_010/rtl/PackedWideMemoryFillCase010.sv`：`reg [3:0][31:0] regs`，整体 fill + 逐行读。
- `testcase/xs-bugcase/CASE_011/rtl/PackedAggregateBitSelectCase011.sv`：`reg [1:0][1:0] priorityVecReg`，整行写 + 行内 bit-select。
- `testcase/xs-bugcase/CASE_012/rtl/PackedAggregateMixedSelectCase012.sv`：同上 + 采样/断言混合读路径。
