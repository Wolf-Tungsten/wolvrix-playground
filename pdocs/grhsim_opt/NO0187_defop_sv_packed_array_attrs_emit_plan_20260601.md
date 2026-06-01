# NO0187 DefOp SV Packed Array Attrs 与 Emit 优化计划

日期：2026-06-01

## 背景

`XsIcacheReplRegsCatLarge` 的反向实验暴露了一个比“寄存器是否离散”更底层的问题：
SV 已经保留了 packed array 语义，但 GRH ingest 后只剩 bitstream 形态，GrhSIM emit
因此按宽值动态切片生成代码。

当前案例中的关键路径：

```systemverilog
wire [127:0][2:0] _GEN_511 = {{...}, ..., {...}};
wire [63:0] out0 = {61'h0, _GEN_511[io_in1[6:0]]};
```

进入 GRH JSON 后变成：

```json
{"sym": "_GEN_511", "w": 384, "type": "logic", "def": "_op_8956"}
{"sym": "_op_8956", "kind": "kConcat", "out": ["_GEN_511"]}
{"kind": "kSliceDynamic", "in": ["_GEN_511", "..."], "attrs": {"sliceWidth": 3}}
```

也就是说，`_GEN_511` 的 `[127:0][2:0]` 形状没有作为 IR 语义留下来。后端只能看到：

```text
384-bit logic + dynamic bit slice(width=3)
```

这使 GrhSIM 生成了 `value_words_6_slots_` / `grhsim_slice_words(...)` 形态，而不是
`uint8_t lanes[128]` / 直接 lane lookup。当前 `XsIcacheReplRegsCatLarge` 上，
GrhSIM 仍约慢于 GSim `4.4x`，其中一个直接原因就是这类 packed array element select
没有在 emit 阶段恢复成数组索引。

## 设计判断

预先保留语义优于事后从 bit-level 结构中猜测语义。结构恢复虽然可行，但它需要同时识别：

- `kConcat` 的 operand 宽度一致；
- `kSliceDynamic` 的 `sliceWidth` 等于 lane 宽度；
- dynamic index 是原始 element index 乘以 lane 宽度；
- concat operand 顺序和 packed array 下标方向一致；
- 没有其他 full-width consumer 或 mixed-width consumer 破坏重写安全性。

这些条件本来都来自 SystemVerilog 类型和 select 语义。ingest 阶段已经能看到这些信息，
没有必要在 emit 阶段重新推断。

本计划采用用户提出的方向：**用 operation attrs 一步到位保留 producer shape 和
consumer select 语义**，而不是给 value 整体扩展属性。理由：

1. 当前 GRH 已经完整支持 operation attrs 的 store / load / clone 路径，落地成本低。
2. packed array 形状是“这个 op 如何构造结果”的语义，挂在 defop 上更符合 ownership。
3. packed array element select 是“这个 consumer 如何使用 base value”的语义，挂在
   `kSliceDynamic` 上更符合 ownership。
4. 如果后续 transform 改写或替换相关 operation，语义属性可以随 operation 一起保留或失效；
   比挂在 value 上更不容易形成悬空语义。
5. v1 目标就是优化 `kConcat -> packed array element select`，producer defop attrs 加
   consumer select attrs 能完整表达，不需要 emit 端猜测 dynamic index 算术结构。

## 目标

### 功能目标

- ingest 时为 packed array 形态的 defop 记录维度语义。
- JSON 中保留该语义，老 JSON 无该属性时继续按旧行为运行。
- GrhSIM emit 能基于 producer defop attrs 和 consumer select attrs 改变变量形态：
  - 对 element-select 主导的 packed array value，生成 lane array / lane scalar 形态；
  - dynamic select 直接变成 lane index load；
  - 避免无必要地构造 `N * 64-bit words` 宽值和调用 `grhsim_slice_words`。

### 性能目标

在 `XsIcacheReplRegsCatLarge` 上，目标先不是一次性追平 GSim，而是验证 packed-array-aware emit
确实把代码形态从：

```cpp
grhsim_slice_words<1>(value_words_6_slots_[...], index * 3, 384)
```

改成：

```cpp
packed_656_lanes[index & 127]
```

验收指标：

- 生成 C++ 中 `_GEN_511` 对应路径不再出现 384-bit dynamic slice。
- `activity_schedule_stats.json` 中宽值 boundary / words slot 使用下降。
- `XsIcacheReplRegsCatLarge` verify 通过，GrhSIM runtime 明显下降。

### 非目标

- 不在本阶段扩展 value attrs。
- 不在本阶段重写所有 packed struct / packed union 语义。
- 不在本阶段把所有宽值 storage 改成 lane storage。
- 不做 emit 端事后识别 dynamic index 算术结构；packed array element select 必须由
  `kSliceDynamic` 上的 `svPackedArraySelect.*` attrs 显式描述。
- 不改变 GRH 的 bit-level fallback 语义；`svPackedArray.*` / `svPackedArraySelect.*`
  attrs 都只是优化提示，缺失或不匹配时必须回退旧路径。

## Operation 属性设计

本节定义需要新增的 operation attrs 规范。producer-side attrs 挂在产生 packed array
value 的 defining operation 上；consumer-side attrs 挂在对应的 `kSliceDynamic`
operation 上。两者都不是 value attrs。

### 命名原则

`semanticShape` 这类名字过于泛化，容易把无关语义都塞进同一个总桶。本方案改用更窄的
flat attr namespace：

```text
svPackedArray.*
```

选择这个名字有三个约束：

- `sv` 表示来源是 SystemVerilog 类型语义，不假装是所有前端通用的抽象语义。
- `PackedArray` 表示这组 attrs 只描述 packed array lane 映射，不描述 packed struct、
  packed union、FIRRTL Vec 或 record repack。
- `*` 下的字段是扁平 key，不是嵌套 JSON object；这是为了复用现有 GRH operation
  attrs 的 store / load / clone 机制。

consumer-side select 语义也不塞进 `svPackedArray.*`。producer shape 和 consumer
select 是两个 ownership 不同的语义层，后者使用独立 namespace：

```text
svPackedArraySelect.*
```

未来如果需要表达其他语义，应新增独立命名空间，例如：

```text
svPackedStruct.*
svPackedUnion.*
firrtlVec.*
```

不得把它们挂到 `semanticShape` 这种共享总开关下面。

### 规范边界

本方案把新增 attrs 定义为 **GRH operation attr schema**，不是 SystemVerilog AST
扩展，也不是 value metadata。实现时必须遵守以下边界：

- attr owner 是产生 packed array bitstream 的 defop。
- attr 只描述 defop result 的 packed array lane 映射，不改变现有 value width、
  op kind、operand、user 关系。
- `svPackedArray.*` 和 `svPackedArraySelect.*` attr group 都是原子语义：消费者必须同时看到
  各自 group 的所有必填字段且类型、取值合法，才能使用 packed-array fast path；
  否则必须把对应 attr group 视为无效并 fallback。
- 不定义默认值。缺字段、类型不匹配、版本不支持、字段间约束不成立，均视为无效。
- 未识别的额外 `svPackedArray.*` / `svPackedArraySelect.*` attr key 必须被忽略，不得影响
  旧版本 load / emit。
- 所有整数 attr 使用现有 GRH `AttributeValue::int64_t` / JSON `{"t":"int","v":...}`
  表示；字符串 attr 使用现有 `string` 表示。

### Attr schema v1

v1 只定义一维 packed array element 语义，目标形态是：

```systemverilog
wire [INDEX_LEFT:INDEX_RIGHT][ELEMENT_WIDTH-1:0] value = packed_array_expr;
```

其中最外层 packed dimension 作为可索引 array 维度，剩余 packed dimensions 合并为
单个 element bitstream。对本次 case：

```systemverilog
wire [127:0][2:0] _GEN_511;
```

语义为：

```text
elementCount = 128
elementWidth = 3
logical index range = 127 downto 0
```

v1 attrs 的规范如下：

| attr | 类型 | 必填 | 合法值 / 约束 | 含义 |
| --- | --- | --- | --- | --- |
| `svPackedArray.version` | int | yes | 当前必须为 `1` | attr group 的识别入口和 schema 版本 |
| `svPackedArray.elementWidth` | int | yes | `> 0` | 每个 element 的 bit 宽度 |
| `svPackedArray.elementCount` | int | yes | `> 0` | 最外层 packed array 的 element 个数 |
| `svPackedArray.indexLow` | int | yes | `<= svPackedArray.indexHigh` | 逻辑下标的 canonical 最小值 |
| `svPackedArray.indexHigh` | int | yes | `>= svPackedArray.indexLow` | 逻辑下标的 canonical 最大值 |
| `svPackedArray.indexDirection` | string | yes | `downto` 或 `upto` | 原始 SV 维度方向；`[127:0]` 为 `downto`，`[0:127]` 为 `upto` |
| `svPackedArray.laneOrder` | string | yes | `lsb_index_low` 或 `lsb_index_high` | 逻辑下标与 bitstream 低位 lane 的映射规则 |
| `svPackedArray.concat.operand0Index` | int | 仅 `kConcat` 必填 | 必须落在 `[indexLow, indexHigh]` | `kConcat` 第 0 个 operand 对应的逻辑下标 |
| `svPackedArray.concat.operandStride` | int | 仅 `kConcat` 必填 | 只能为 `1` 或 `-1` | `kConcat` operand 顺序上的逻辑下标步长 |

v1 的必填规则：

- 对任意带 `svPackedArray.version=1` 的 defop，前 7 个字段全部必填。
- 当 defop kind 是 `kConcat` 时，`svPackedArray.concat.operand0Index` 和
  `svPackedArray.concat.operandStride` 也必填。
- 当 defop kind 不是 `kConcat` 时，v1 不要求 concat 专属字段；Phase 1/2 可以直接不对
  非 `kConcat` defop 启用 lane emit。

`svPackedArray.laneOrder` 的精确定义：

- `lsb_index_low`：逻辑下标 `svPackedArray.indexLow` 对应 bitstream 的最低 element。
  逻辑下标 `i` 的 bit offset 为 `(i - indexLow) * elementWidth`。
- `lsb_index_high`：逻辑下标 `svPackedArray.indexHigh` 对应 bitstream 的最低 element。
  逻辑下标 `i` 的 bit offset 为 `(indexHigh - i) * elementWidth`。

对于 SystemVerilog 常见声明：

| SV 类型 | `indexLow` | `indexHigh` | `indexDirection` | `laneOrder` |
| --- | ---: | ---: | --- | --- |
| `[127:0][2:0]` | `0` | `127` | `downto` | `lsb_index_low` |
| `[0:127][2:0]` | `0` | `127` | `upto` | `lsb_index_high` |

更形式化地，令 `W = svPackedArray.elementWidth`，`L = svPackedArray.indexLow`，
`H = svPackedArray.indexHigh`。合法逻辑下标 `i` 必须满足 `L <= i <= H`。

当 `svPackedArray.laneOrder == lsb_index_low`：

```text
laneOrdinal(i) = i - L
bitOffset(i) = laneOrdinal(i) * W
bitRange(i) = [bitOffset(i) + W - 1 : bitOffset(i)]
```

当 `svPackedArray.laneOrder == lsb_index_high`：

```text
laneOrdinal(i) = H - i
bitOffset(i) = laneOrdinal(i) * W
bitRange(i) = [bitOffset(i) + W - 1 : bitOffset(i)]
```

这里 `laneOrdinal == 0` 永远表示 result bitstream 的最低 element，`laneOrdinal ==
svPackedArray.elementCount - 1` 永远表示 result bitstream 的最高 element。

`svPackedArray.concat.*` 的精确定义：

- GRH `kConcat` operand 0 是结果 bitstream 的 MSB 侧 operand。
- 第 `n` 个 concat operand 对应逻辑下标：

```text
svPackedArray.concat.operand0Index + n * svPackedArray.concat.operandStride
```

对任意 operand 位置 `n`，还必须满足：

```text
laneOrdinal(svPackedArray.concat.operand0Index + n * svPackedArray.concat.operandStride)
  == svPackedArray.elementCount - 1 - n
```

因此 `_GEN_511 = {lane127, lane126, ..., lane0}` 的 defop 应记录：

```text
svPackedArray.concat.operand0Index = 127
svPackedArray.concat.operandStride = -1
```

### JSON 表示

operation attrs 使用现有 GRH JSON attr 表示，不新增 JSON 顶层 schema。`_GEN_511`
对应的 `kConcat` defop 示例：

```text
svPackedArray.version = 1
svPackedArray.elementWidth = 3
svPackedArray.elementCount = 128
svPackedArray.indexLow = 0
svPackedArray.indexHigh = 127
svPackedArray.indexDirection = "downto"
svPackedArray.laneOrder = "lsb_index_low"
svPackedArray.concat.operand0Index = 127
svPackedArray.concat.operandStride = -1
```

对应 JSON 形态示例：

```json
{
  "sym": "_op_8956",
  "kind": "kConcat",
  "out": ["_GEN_511"],
  "attrs": {
    "svPackedArray.version": {"t": "int", "v": 1},
    "svPackedArray.elementWidth": {"t": "int", "v": 3},
    "svPackedArray.elementCount": {"t": "int", "v": 128},
    "svPackedArray.indexLow": {"t": "int", "v": 0},
    "svPackedArray.indexHigh": {"t": "int", "v": 127},
    "svPackedArray.indexDirection": {"t": "string", "v": "downto"},
    "svPackedArray.laneOrder": {"t": "string", "v": "lsb_index_low"},
    "svPackedArray.concat.operand0Index": {"t": "int", "v": 127},
    "svPackedArray.concat.operandStride": {"t": "int", "v": -1}
  }
}
```

### Producer-side 校验规则

ingest 写入 `svPackedArray.*` attrs 前必须满足以下条件：

1. defop 有且只有一个 result。
2. result width 等于 `svPackedArray.elementWidth * svPackedArray.elementCount`。
3. `svPackedArray.elementCount == svPackedArray.indexHigh - svPackedArray.indexLow + 1`。
4. `svPackedArray.indexDirection == downto` 时，原声明 left 大于 right；`upto` 时，原声明 left 小于 right。
5. `svPackedArray.laneOrder` 必须与 SV packed array bitstream 规则一致：
   - `downto` 维度使用 `lsb_index_low`；
   - `upto` 维度使用 `lsb_index_high`。
6. 对 `kConcat` defop：
   - operand 数等于 `svPackedArray.elementCount`；
   - 每个 operand width 等于 `svPackedArray.elementWidth`；
   - `svPackedArray.concat.operand0Index + (svPackedArray.elementCount - 1) * svPackedArray.concat.operandStride`
     必须等于另一端逻辑下标；
   - 每个 operand 位置 `n` 都满足上文 `laneOrdinal(...) == svPackedArray.elementCount - 1 - n`；
   - concat operand 映射必须完整覆盖 `[svPackedArray.indexLow, svPackedArray.indexHigh]`。

任一条件不满足时，ingest 不得写入 `svPackedArray.version`，并且不应写入任何
`svPackedArray.*` 残缺字段；必须保留旧 bitstream 语义。

### Consumer-side 使用规则

v1 同时定义 producer shape attrs 和 consumer select attrs，但不改变 `kSliceDynamic`
的 IR contract。packed array element select 在 GRH 中仍表示为：

```text
kSliceDynamic(base, bitOffset), sliceWidth = svPackedArray.elementWidth
```

其中第二个 operand 仍然是 bit offset，不是逻辑下标。ingest 必须在这类
`kSliceDynamic` consumer 上写入 `svPackedArraySelect.*` attrs，明确说明这个 bit
offset 是 packed array element select 的 lane offset。

`svPackedArraySelect.*` 的职责是描述“这个 slice consumer 来源于 SV packed array
element select”，让 emit 不需要从算术子图里反推 `idx * elementWidth`。它和
`svPackedArray.*` 的分工如下：

| namespace | owner | 描述对象 | 是否改变 IR 语义 |
| --- | --- | --- | --- |
| `svPackedArray.*` | packed value 的 defop | base value 的 lane shape / bitstream 映射 | no |
| `svPackedArraySelect.*` | `kSliceDynamic` consumer op | consumer 如何从 base value 选择一个 element | no |

select attrs 的 v1 schema 如下：

| attr | 类型 | 必填 | 合法值 / 约束 | 含义 |
| --- | --- | --- | --- | --- |
| `svPackedArraySelect.version` | int | yes | 当前必须为 `1` | select attr group 的识别入口和 schema 版本 |
| `svPackedArraySelect.kind` | string | yes | 当前只定义 `element` | 该 consumer 是 packed array element select，不是 range select |
| `svPackedArraySelect.baseOperand` | int | yes | 当前必须为 `0` | `kSliceDynamic` 中 base value 的 operand index |
| `svPackedArraySelect.offsetOperand` | int | yes | 当前必须为 `1` | `kSliceDynamic` 中 bit offset 的 operand index |
| `svPackedArraySelect.laneOrdinalOperand` | int | yes | 当前必须为 `2` | `kSliceDynamic` 中 physical lane ordinal 的 operand index |
| `svPackedArraySelect.offsetEncoding` | string | yes | 当前只定义 `lane_ordinal_times_element_width` | offset operand 是 `laneOrdinal * elementWidth` |
| `svPackedArraySelect.elementWidth` | int | yes | `> 0`，且等于 `sliceWidth` | consumer 选择出的 element bit 宽度 |

`offsetEncoding = lane_ordinal_times_element_width` 的精确定义：

```text
offsetOperand = laneOrdinal * svPackedArraySelect.elementWidth
laneOrdinalOperand = laneOrdinal
0 <= laneOrdinal < base.svPackedArray.elementCount
```

这里 `laneOrdinal` 是 base bitstream 中从 LSB element 开始计数的物理 lane 编号，不是一定等同
于 SV 逻辑下标。emit 读取 select attrs 后直接使用 `laneOrdinalOperand`，`offsetOperand`
继续保留 bit-level fallback 语义：

```text
laneOrdinal = laneOrdinalOperand
```

再按 base defop 的 `svPackedArray.laneOrder` 转成逻辑下标或 lane storage 下标：

```text
logicalIndex = laneOrdinal + indexLow      // lsb_index_low
logicalIndex = indexHigh - laneOrdinal     // lsb_index_high
```

如果 lane storage 本身使用 `laneOrdinal` 编号，则不需要计算 `logicalIndex`。如果 lane
storage 使用 SV 逻辑下标编号，则必须按上式转换。

对应 JSON 示例：

```json
{
  "sym": "_op_select_0",
  "kind": "kSliceDynamic",
  "in": ["_GEN_511", "_op_bit_offset", "_op_lane_ordinal"],
  "attrs": {
    "sliceWidth": {"t": "int", "v": 3},
    "svPackedArraySelect.version": {"t": "int", "v": 1},
    "svPackedArraySelect.kind": {"t": "string", "v": "element"},
    "svPackedArraySelect.baseOperand": {"t": "int", "v": 0},
    "svPackedArraySelect.offsetOperand": {"t": "int", "v": 1},
    "svPackedArraySelect.laneOrdinalOperand": {"t": "int", "v": 2},
    "svPackedArraySelect.offsetEncoding": {"t": "string", "v": "lane_ordinal_times_element_width"},
    "svPackedArraySelect.elementWidth": {"t": "int", "v": 3}
  }
}
```

select attrs 的使用规则：

1. emit 必须先验证 consumer op 是 `kSliceDynamic`，operand 数满足 `baseOperand` /
   `offsetOperand` / `laneOrdinalOperand`，`sliceWidth == svPackedArraySelect.elementWidth`。
2. `baseOperand` 指向的 value 必须能追到合法的 `svPackedArray.version=1` defop attrs；
   只有 select attrs 而没有 base shape 时不能启用 lane emit。
3. `svPackedArraySelect.elementWidth` 必须等于 base `svPackedArray.elementWidth`。
4. `offsetEncoding` 只免除 emit 对算术结构的识别，不免除 runtime / compile-time 下标边界
   处理。需要 mask、range check 或 fallback 时仍按现有 `kSliceDynamic` 语义处理。
5. 缺字段、类型错误、版本不支持、字段间不一致时，必须忽略整组
   `svPackedArraySelect.*` attrs，并回到旧 `grhsim_slice_words` 路径；不要再尝试从
   dynamic index 算术子图恢复 packed array select 语义。

select attrs 的生命周期规则：

- clone / load / store 必须保留 operation attrs。
- transform 如果只做 bit-identical clone，可以保留 `svPackedArraySelect.*`。
- transform 如果改变 `kSliceDynamic` 的 base operand、offset operand、`sliceWidth`、或把
  offset 改成不再满足 `laneOrdinal * elementWidth` 的表达式，必须清除或重算整组
  `svPackedArraySelect.*`。
- base defop 的 `svPackedArray.*` 被清除或失效时，select attrs 可以继续保存在 JSON 中，
  但 emit 必须把它视为不可用优化提示。

### Attr 生命周期规则

- clone / load / store 必须保留 operation attrs。
- transform 如果保持 defop 的 result bitstream 与 operand 映射完全不变，可以保留
  `svPackedArray.*` attrs。
- transform 如果改变 defop kind、operand 顺序、operand 宽度、result width 或 result
  bitstream 映射，必须清除或重算整组 `svPackedArray.*` attrs。
- emit 不得盲信 attrs。即使 attrs 存在，也必须重复检查 width、count、operand 数和
  consumer slice width，检查失败时 fallback。

## Ingest 记录规则

### 1. 信号声明阶段保留 packed dims

`SignalInfo` 当前已有：

```cpp
std::vector<int32_t> packedDims;
std::vector<UnpackedDimInfo> unpackedDims;
```

这一层已经能知道 `_GEN_511` 是 packed array，而不是普通 `logic [383:0]`。需要保证：

- packed dims 中保留每一维 extent；
- 如果可以拿到原始 range，额外保留下标方向和 low/high；
- 对 `wire [127:0][2:0]` 记录为 outer count `128`、inner element width `3`。

### 2. assignment / continuous assign lowering 阶段标注 defop

当目标 value 对应 packed array signal，且它的 defining op 是可表达 packed array 构造的 op：

- `kConcat`
- `kAssign`
- `kMux`
- 后续可能扩展到 `kMemoryReadPort` / `kRegisterReadPort` 的 aggregate 输出

则在 defop 上写入 `svPackedArray.*` attrs。

初期只支持最清晰的 `kConcat`：

```text
wire [N-1:0][W-1:0] x = {lane[N-1], ..., lane[0]};
```

条件：

- defop 只有一个 result；
- result width 等于 `svPackedArray.elementCount * svPackedArray.elementWidth`；
- `kConcat` operand 数等于 `svPackedArray.elementCount`；
- 每个 operand 宽度等于 `svPackedArray.elementWidth`。

不满足时不写 attrs，按旧 bitstream 语义处理。

### 3. element select lowering 继续保持 bit-level 正确性

当前 ingest 把 packed array element select 降成：

```text
kSliceDynamic(base, adjustedIndex), sliceWidth=elementWidth
```

这个表示可以保留。packed-array-aware emit 通过 base value 的 `svPackedArray.*` attrs
以及 consumer op 的 `svPackedArraySelect.*` attrs 识别优化机会。

ingest 在 packed array element select lowering 时同步写入 consumer-side attrs：

```text
svPackedArraySelect.version = 1
svPackedArraySelect.kind = "element"
svPackedArraySelect.baseOperand = 0
svPackedArraySelect.offsetOperand = 1
svPackedArraySelect.laneOrdinalOperand = 2
svPackedArraySelect.elementWidth = 3
svPackedArraySelect.offsetEncoding = "lane_ordinal_times_element_width"
```

这组 attrs 只声明现有 offset operand 的编码方式，不新增 operand，也不把 `kSliceDynamic`
改成“按 element index select”的新 op。若 lowering 无法证明 offset operand 满足
`laneOrdinal * elementWidth`，则不写 `svPackedArraySelect.*`，该 consumer 按旧 bit-slice
路径 emit。

## GrhSIM Emit 方案

### 1. Shape analysis

emit model 构建阶段增加一次轻量 shape analysis：

1. 扫描所有 value 的 defining op。
2. 如果 defop 有合法的 `svPackedArray.version=1` attr group，登记 `SvPackedArrayInfo`：

```cpp
struct SvPackedArrayInfo {
    ValueId value;
    OperationId defop;
    int elementWidth;
    int elementCount;
    int indexLow;
    int indexHigh;
    bool indexDownto;
    bool lsbIndexLow;
    int concatOperand0Index;
    int concatOperandStride;
};
```

3. 扫描该 value 的 users，统计 consumer 类型。对 `kSliceDynamic` user，必须解析合法的
   `svPackedArraySelect.version=1` attrs 才能归类为 packed array element select：
   - element select consumer：`kSliceDynamic`、`sliceWidth == elementWidth`，且
     `svPackedArraySelect.*` 与 base `svPackedArray.*` 一致
   - full-width consumer：直接使用整个 packed value
   - unsupported consumer：宽度不匹配、range slice、bitwise whole-value 操作等

只有当 consumer 形态安全时启用 lane emit。否则保留旧宽值 emit。

### 2. Lane materialization

对安全的 packed array value，emit 不再生成一个 `words_N` 宽值 slot，而生成 lane 容器。

局部 supernode 内可生成：

```cpp
std::array<std::uint8_t, 128> grhsim_packed_656_lanes{};
```

如果该 value 需要跨 supernode materialize，则分配 persistent lane storage：

```cpp
std::array<std::uint8_t, 128> value_packed_u8_128_slots_[...];
```

v1 直接支持跨 supernode 的 persistent lane storage；`XsIcacheReplRegsCatLarge` 的 producer
和 select consumer 正是跨 supernode 形态，只做 local / same-supernode 优化无法解决目标 case。

### 3. kConcat emit

对本例：

```text
_GEN_511 = concat(lane127, lane126, ..., lane0)
```

emit 为：

```cpp
lanes[127] = expr_operand_0 & 0x7;
lanes[126] = expr_operand_1 & 0x7;
...
lanes[0] = expr_operand_127 & 0x7;
```

如果 `svPackedArray.concat.operand0Index` 不是 `svPackedArray.indexHigh`，按 attr 映射计算 lane index。

### 4. kSliceDynamic emit

当 user 是 packed array element select：

```text
kSliceDynamic(_GEN_511, adjustedBitIndex, laneOrdinal), sliceWidth=3
```

emit 只接受合法 `svPackedArraySelect.*`。命中后直接使用 `laneOrdinalOperand` 做 lane
lookup；`offsetOperand` 仍表示 `laneOrdinal * elementWidth`，供旧 bit-slice fallback
保留原语义。缺失或无效时 fallback 到旧 `grhsim_slice_words`，不再从 `adjustedBitIndex`
的算术结构恢复 packed array select。

如果 lane storage 使用 SV 逻辑下标编号，可按 base attrs 转成逻辑下标后生成：

```cpp
const auto elementIndex = ...;
const std::uint8_t selected = lanes[elementIndex & 127] & 0x7;
```

如果 lane storage 按 physical lane 编号，则生成：

```cpp
const auto laneOrdinal = ...; // laneOrdinalOperand
const std::uint8_t selected = lanes[laneOrdinal & 127] & 0x7;
```

对于非 2 的幂 count，不能直接 `&`，用范围语义对应的 trunc / modulo / mask 逻辑：

```cpp
lanes[normalize_index(elementIndex)]
```

`XsIcacheReplRegsCatLarge` 的 count 是 `128`，可以直接使用 `& 0x7f`。

### 5. Mixed consumer fallback

如果 packed value 同时有 full-width consumer 和 element select consumer，有三种策略：

1. 第一阶段直接 fallback：全部按旧宽值 emit。
2. 第二阶段 dual materialize：生成 lanes，同时在需要 full-width 时按 lanes 组装 words。
3. 第三阶段 lazy full-width：只有 full-width consumer 激活时才组装。

建议第一阶段选择 fallback，确保正确性边界清晰。

## Transform / Store / Load 影响

### Store / Load

operation attrs 已经支持 JSON 序列化和反序列化。本计划优先使用 int / string / int-array
这些现有 attr 类型，不需要新增 JSON schema。

旧 JSON 没有该 attrs 时：

```text
svPackedArray attr miss -> old emit path
svPackedArraySelect attr miss -> old emit path for that kSliceDynamic
```

### Clone / Rewrite

已有 clone 路径会复制 operation attrs。需要额外定义 transform 规则：

- 保持 bit-identical defop 时保留 attrs。
- 重写 `kConcat` operand 顺序、operand 宽度、result width 时必须清除或重算 attrs。
- 删除 defop 或替换 result producer 时不迁移 attrs，除非 pass 明确证明语义等价。
- `svPackedArray.*` / `svPackedArraySelect.*` attrs 只能作为优化提示，不能作为 correctness
  唯一来源；emit 必须重新检查 width/count/user 形态。

## 实施阶段

### Phase 1: Ingest 标注、GrhSIM lane emit 与诊断

目标：一步到位生成 producer `svPackedArray.*`、consumer `svPackedArraySelect.*`，并让
GrhSIM 对验证通过的 `kConcat -> kSliceDynamic element select` 使用 lane storage。

工作项：

- 在 `SignalInfo` 中确认 packed dims / range 方向对 `_GEN_511` 可用。
- 在 continuous assign / expression lowering 完成后，为符合条件的 `kConcat` defop 写入 attrs。
- 在 packed array element select lowering 时，为符合条件的 `kSliceDynamic` 写入
  `svPackedArraySelect.version=1` attr group。
- emitter model 增加 `SvPackedArrayInfo` / `SvPackedArraySelectInfo` 识别。
- 为跨 supernode packed array value 分配 persistent lane storage。
- 对符合条件的 `kConcat` 生成 lane 写入。
- 对带合法 `svPackedArraySelect.*` 的 `kSliceDynamic` 生成 lane load。
- 任一 attrs 缺失、字段不一致、width/count/user 形态不安全时回到旧宽 bitstream emit。
- 增加诊断统计：
  - `sv_packed_array_attr_defops`
  - `sv_packed_array_attr_concat_defops`
  - `sv_packed_array_select_attr_ops`
  - `sv_packed_array_attr_dynamic_select_users`
  - `sv_packed_array_attr_unsupported_users`
  - `packed_array_lane_emit_values`
  - `packed_array_lane_emit_selects`
  - `packed_array_lane_emit_select_attr_invalid`
  - `packed_array_lane_emit_fallback_full_width`

验证：

- `XsIcacheReplRegsCatLarge.json` 中 `_op_8956` 出现 `svPackedArray.*` attrs。
- `_GEN_511[io_in1[6:0]]` 对应 `kSliceDynamic` 出现 `svPackedArraySelect.*` attrs。
- `load -> store` roundtrip 后 producer / consumer attrs 都保留。
- `XsIcacheReplRegsCatLarge` 生成代码不再对带合法 select attrs 的 `_GEN_511` select
  使用 `grhsim_slice_words`。
- `make -C testcase/xs-components CASE=XsIcacheReplRegsCatLarge BENCH_REPEAT=3 -B one` 通过 verify。
- 比较 `stats/model_stats.json`，确认 GrhSIM runtime 和 text size 下降。

### Phase 2: Mixed consumer / dual materialize 扩展

目标：处理 packed value 同时存在 element select consumer 和 full-width consumer 的形态。

工作项：

- 对 full-width consumer 仍 fallback 或 lazy assemble。
- 必要时增加 dual materialize：生成 lanes，同时在 full-width consumer 激活时按 lanes 组装 words。

验证：

- 新增小 case 覆盖 mixed consumer。
- full XiangShan 不因 lane storage 破坏 state/value 生命周期。

### Phase 3: 默认启用与回归

目标：默认启用安全子集。

要求：

- `XsIcacheReplRegsCatLarge` 正向。
- `XsIcacheReplRegsLarge` / `XsIcacheReplRegsDiscreteLarge` 不回退。
- `XsIcacheReplacerLarge` verify 通过，runtime 不回退。
- `ctest` 中 ingest/store/load/emit 相关测试通过。

## 测试计划

### 单元测试

新增 ingest fixture：

```systemverilog
module packed_array_shape(
  input  logic [6:0] idx,
  input  logic [383:0] in,
  output logic [2:0] out
);
  wire [127:0][2:0] lanes = in;
  assign out = lanes[idx];
endmodule
```

期望：

- `lanes` defop 或 assign defop 有合法的 `svPackedArray.version=1` attr group。
- `lanes[idx]` 仍表示为 `kSliceDynamic`，base defop 可追到 `svPackedArray.*` attrs，
  consumer op 有合法 `svPackedArraySelect.version=1` attr group。

新增 concat fixture：

```systemverilog
wire [127:0][2:0] lanes = {lane127, ..., lane0};
assign out = lanes[idx];
```

期望：

- `kConcat` defop 有 element count/width/order attrs。

新增 select attrs fixture：

```systemverilog
wire [127:0][2:0] lanes = {lane127, ..., lane0};
wire [2:0] out = lanes[idx];
```

期望：

- `kSliceDynamic` 保留 bit offset operand。
- `kSliceDynamic` 上的 `svPackedArraySelect.offsetEncoding` 为
  `lane_ordinal_times_element_width`。
- 手动移除 `svPackedArraySelect.*` 后，JSON 仍能 load，emit 必须 fallback 到旧 bit-slice
  路径。

### Emitter shape test

构造小型 grhsim-cpp emit 测试，检查生成代码：

- 包含 lane array。
- 不包含对应 value 的 `grhsim_slice_words`。
- dynamic index load 结果与 reference bit slice 一致。
- 对带 `svPackedArraySelect.*` 的 case，检查 stats 中 select attr hit 增加。
- 对故意损坏 select attr 的 case，检查 emit 忽略该 attr 并 fallback 到旧路径。

### xs-components gate

重点 case：

```text
XsIcacheReplRegsCatLarge
XsIcacheReplRegsLarge
XsIcacheReplRegsDiscreteLarge
XsIcacheReplacerLarge
```

记录：

- verify pass/fail；
- `bench_ms`；
- `instruction_count`；
- `text_size_bytes`；
  - `activity_schedule_stats.json` 中 packed-array attr 命中统计。

## 风险与边界

1. 下标方向错误

   `[127:0][2:0]` 的 bitstream LSB 对应 index `0`，concat operand 0 对应 index `127`。
   这是最容易写错的地方，必须有专门 fixture 覆盖。

2. mixed consumer

   同一个 packed value 如果既被 element-select，又被 full-width bitwise 使用，第一阶段必须 fallback。

3. attrs 过期

   transform 改写 defop 后如果 attrs 没清理，会导致错误 lane emit。emit 阶段必须重复校验
   result width、operand width、operand count 和 user slice width。

4. select attrs 与 base attrs 不一致

   `svPackedArraySelect.*` 只描述 consumer，不能单独启用优化。select attrs 的
   `elementWidth`、operand index 或 offset encoding 与 base `svPackedArray.*` 不一致时，
   必须忽略 select attrs；否则会把 bit offset 错当 lane 下标。

5. C++ 类型宽度语义

   3-bit lane 存在 `uint8_t` 里时必须显式 mask，不能依赖上游表达式已经截断。

6. 过度 lane 化

   不是所有 packed array 都适合拆成 lane array。element count 很小、full-width consumer 多、
   或 lane width 很大时，旧 words 形态可能更好。需要阈值控制。

## 启用策略

Phase 1 直接按 v1 attrs 启用安全子集，不再增加额外功能开关。GrhSIM emit 只有在
producer `svPackedArray.*` 和 consumer `svPackedArraySelect.*` 两组 attrs 都完整合法，
且所有 consumer 形态满足本计划约束时，才生成 lane storage / lane lookup；任一检查失败
都回退旧宽值路径。

诊断统一进入 `activity_schedule_stats.json` 中的 packed-array 统计字段，例如
`sv_packed_array_select_attr_ops`、`packed_array_lane_emit_values` 和
`packed_array_lane_emit_fallback_full_width`，不再另设诊断开关。

## 预期结论

这条路线的核心不是“从 bit slice 模式恢复数组”，而是让 ingest 把 SV 类型语义预先传给后端：

```text
SV packed array element select
  -> defop svPackedArray attrs + consumer svPackedArraySelect attrs
  -> GrhSIM lane emit
```

对 `XsIcacheReplRegsCatLarge` 这类 case，理想代码形态应从：

```cpp
std::array<std::uint64_t, 6> packed;
grhsim_slice_words<1>(packed, index * 3, 384)
```

变成：

```cpp
std::array<std::uint8_t, 128> lanes;
lanes[index & 0x7f]
```

后续可以把同一语义通道扩展到 packed struct、record slot repack、以及 register/memory
aggregate 输出，逐步减少 GrhSIM 在宽值动态切片上的生成代码和 runtime 成本。
