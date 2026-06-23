# NO0204: concat+slice 未进入 reg-to-mem 的组合分类

日期：2026-06-21

## 背景

本轮问题是确认完整 XiangShan 的纯 `concat + slice` 组合里，为什么只有一部分能进入当前 `reg-to-mem` intent/true 路径。

当前 `reg-to-mem` 的 intent discovery 不是“任意 concat+slice”优化。它只识别以下读侧数组访问形态：

```text
kRegisterReadPort* -> kConcat -> kSliceArray
```

或等价的 dynamic slice：

```text
kRegisterReadPort* -> kConcat -> kSliceDynamic(start = index * sliceWidth)
```

同时要求：

- slice kind 只能是 `kSliceArray` 或可规范化的 `kSliceDynamic`。
- slice 的 packed input 必须由单结果 `kConcat` 定义。
- concat operand 数量至少为 2。
- concat 每个 operand 都必须由单结果 `kRegisterReadPort` 定义。
- read port 必须带 `regSymbol`，且该 symbol 在 graph 中对应 `kRegister` 声明。
- 每个 read value 必须是 logic。
- 每个 read value 宽度必须等于 `sliceWidth`。
- 同一 concat 内 read value 的 signedness 必须一致。

这些条件满足后才形成 reg-to-mem anchor；随后再按 `(elementWidth, elementCount, register row list)` 聚成 group，并剔除多个 group 共享同一 register 的冲突组。

## 统计口径

输入产物：

```text
build/xs/grhsim/wolvrix_xs_pre_reg_to_mem.json
```

该 JSON 是当前标准 grhsim 流程 resume 使用的 pre-reg-to-mem 产物。统计时先用纯结构口径找：

```text
kSliceStatic/kSliceArray/kSliceDynamic 的第 0 个输入来自 kConcat 输出
```

该口径不限制 concat operand 来自 register、memory 或普通组合逻辑。

## 总量

| 项目 | 数量 |
| --- | ---: |
| 全部 `kConcat` op | 257367 |
| 至少被一个 slice 读取的唯一 concat 输出 | 7830 |
| `kSliceArray(concat, index)` pair | 9420 |
| `kSliceDynamic(concat, start)` pair | 12914 |
| `kSliceStatic(concat)` pair | 617 |
| 纯 `SliceArray + SliceDynamic` concat-slice pair | 22334 |
| 全部 slice kind concat-slice pair | 22951 |

当前 reg-to-mem discovery 命中的 anchor 是 `6135` 个，全部来自 `kSliceArray`。相对纯 `SliceArray + SliceDynamic` pair 的覆盖率是：

```text
6135 / 22334 = 27.5%
```

若把 `kSliceStatic` 也算作纯 concat+slice，总覆盖率是：

```text
6135 / 22951 = 26.7%
```

## 未匹配分类

以下分类按当前 matcher 的第一失败原因计数。`kSliceArray + kSliceDynamic` 的纯 pair 总数是 `22334`。

| 分类 | pair 数 | 占 `SliceArray+Dynamic` | 说明 |
| --- | ---: | ---: | --- |
| 已匹配 reg-to-mem anchor shape | 6135 | 27.5% | 满足当前 register-array 读侧条件 |
| dynamic index 不能规范化 | 12914 | 57.8% | 全部 `kSliceDynamic` 都没有进入当前 matcher |
| concat operand 非纯 register read | 3285 | 14.7% | 主要发生在 `kSliceArray`，concat 输入混有 assign/constant/slice/mux 等 |

若包含 `kSliceStatic`，还需要额外加：

| 分类 | pair 数 | 占全部 slice kind |
| --- | ---: | ---: |
| `kSliceStatic(concat)`，当前不属于 reg-to-mem intent 目标 | 617 | 2.7% |

因此，`22951` 个全部 slice-kind pair 中：

```text
6135 matched
12914 dynamic-index-not-normalized
3285 non-register-read-concat
617 static-slice
= 22951
```

## dynamic index 不能规范化

当前 `reg-to-mem` 只接受 `kSliceDynamic` 的 start value 由 `kMul` 定义，且其中一个乘数是常量 `sliceWidth`：

```text
start = index * sliceWidth
```

在本次统计中，`12914` 个 `kSliceDynamic(concat, start)` 都未满足该条件。按 start value 的 defining op 分类：

| start def kind | 数量 |
| --- | ---: |
| `kSliceStatic` | 3019 |
| `kConstant` | 2966 |
| `kMux` | 2750 |
| `kConcat` | 1220 |
| `kRegisterReadPort` | 910 |
| `kAssign` | 890 |
| `kSub` | 750 |
| `kAdd` | 172 |
| `kOr` | 152 |
| `kSliceArray` | 75 |
| `kSliceDynamic` | 8 |
| `kXor` | 2 |

这里不是说这些 dynamic slice 都不可优化，而是当前 matcher 没有处理这些 index 表达式。几类值得区分：

- `kConstant`：本质上可降成 static range 或直接定位 concat operand，但这已经是另一路 slice simplification/emit combine 问题，不是 register-array intent。
- `kSliceStatic` / `kRegisterReadPort` / `kMux`：索引来自控制状态或组合选择，可能仍是数组索引语义，但需要更强的 index expression 归一化。
- `kSub` / `kAdd` / `kOr`：常见于地址/字段编码，需要判断是否等价于 `idx * width + offset` 或 element index 变体。
- `kConcat`：索引本身由多个字段拼出来，是否能低成本 array access 取决于字段组合是否仍表达 element index。

### 代表案例

以下案例均来自 `build/xs/grhsim/wolvrix_xs_pre_reg_to_mem.json`。它们都是纯结构上的：

```text
kConcat -> kSliceDynamic(concat, start)
```

但 `start` 不是当前 matcher 接受的 `kMul(index, sliceWidth)`。

#### 1. 常量 start：实际是 constant bit-select

```text
slice=_op_86543
kind=kSliceDynamic
sliceWidth=1
base=cpu$l_soc$socMisc$debugModule$dtm$dtmInfoChain$io_capture_bits_dmiStatus
start=cpu$l_soc$io_pll0_lock
start_def=_op_12681 kind=kConstant const=1'b1
loc=build/xs/rtl/rtl/CaptureUpdateChain.sv:155:18
```

语义上这是从 concat 结果中取固定 bit。当前 reg-to-mem dynamic matcher 只识别 `start = idx * sliceWidth`，不会把常量 start 当作 element index。对 `sliceWidth=1` 的情况，常量 start 可以看作常量 element index；但这更接近 `slice-index-const` 或 emit 侧 constant slice retarget，而不是 register-array intent discovery。

同类样本还大量出现在 SRAM wrapper mask 逻辑，例如：

```text
array_128x138.sv:80:18
sliceWidth=1
start_def=kConstant const=1'b1
```

#### 2. 地址字段 slice 作为 start：bit index 来自总线地址低位

```text
slice=_op_58598
kind=kSliceDynamic
sliceWidth=1
base=cpu$l_soc$socMisc$syscnt$_GEN
start=_val_67163
start_def=_op_58367 kind=kSliceStatic
start_def_input=cpu$l_soc$socMisc$_xbar_auto_out_2_a_bits_address
loc=build/xs/rtl/rtl/SYSCNT.sv:269:5
start_loc=build/xs/rtl/rtl/SYSCNT.sv:99:45
```

这里 `start` 是从地址中切出的低位字段，而不是 `idx * width`。当 `sliceWidth=1` 时它可以被理解为 bit index；但如果要把它映射成 array row access，需要先确认地址字段的取值范围、bit/row 对应方向，以及 concat operand 是否正好是逐 bit 或逐 entry 的 lane。

同类还有 debug module：

```text
TLDebugModuleInner.sv:5226:5
start_def=kSliceStatic
start_def_input=...auto_out_5_a_bits_address
```

#### 3. Mux 选择出的 start：运行时选择 readIdx

```text
slice=_op_174368
kind=kSliceDynamic
sliceWidth=1
base=cpu$l_soc$core_with_l2$core$frontend$inner_bpu$abtb$banks_0$writeBuffer$_GEN_5
start=cpu$l_soc$core_with_l2$core$frontend$inner_bpu$abtb$banks_0$writeBuffer$readIdx
start_def=_op_173888 kind=kMux
start_def_inputs=[
  readValidVec_0_0,
  2'b0,
  nested_mux
]
loc=build/xs/rtl/rtl/WriteBuffer.sv:559:40
start_loc=build/xs/rtl/rtl/WriteBuffer.sv:252:5
```

这是 Chisel 常见的 priority/read-index 选择形态：`readIdx` 由一串 mux 决定。它可能仍然是合法的 element index，但当前 matcher 没有穿透 mux，也没有证明 mux 结果就是 element index。对这类情况，正确扩展方向不是简单 unwrap，而是新增受限 index-expression 归一化。

#### 4. 字段 concat 形成 start：index 本身由多个字段拼出

```text
slice=_op_76338
kind=kSliceDynamic
sliceWidth=1
base=cpu$l_soc$socMisc$timer$_GEN_0
start=cpu$l_soc$socMisc$timer$out_oindex
start_def=_op_68744 kind=kConcat
start_def_inputs=[
  kSliceStatic(...),
  kSliceStatic(...)
]
loc=build/xs/rtl/rtl/TIMER.sv:2487:32
start_loc=build/xs/rtl/rtl/TIMER.sv:777:5
```

这里 index 不是单个 value，而是由字段拼成的 `out_oindex`。这类需要先理解字段拼接后的数值语义，不能直接当作 `row`。若后续要支持，应该在 index normalizer 中处理 “concat of address/index slices” 的常见编码，并保留失败诊断。

#### 5. 寄存器读值直接作为 start：指针寄存器是 bit index

```text
slice=_op_132612
kind=kSliceDynamic
sliceWidth=1
base=cpu$l_soc$core_with_l2$core$frontend$inner_icache$missUnit$_GEN
start=_val_134233
start_def=_op_129486 kind=kRegisterReadPort
loc=build/xs/rtl/rtl/ICacheMissUnit.sv:539:33
start_loc=build/xs/rtl/rtl/ICacheMissUnit.sv:666:5
```

这里 `start` 直接是某个寄存器读值，通常是 pointer/index 状态。对 `sliceWidth=1` 来说，`start` 本身就是 bit index；但当前 matcher 要求动态 slice 先写成 `start = idx * sliceWidth`，因此不会接受这种“裸 index”。如果未来支持 `sliceWidth == 1` 的特殊归一化，可以把裸 index 视作 element index。

#### 6. 加减偏移 start：环形/相对位置索引

加法样本：

```text
slice=_op_5011665
kind=kSliceDynamic
sliceWidth=1
base=...$lfst$_GEN_823
start=...$lfst$_check_position_T
start_def=_op_5003890 kind=kAdd
start_def_inputs=[
  allocPtr_0 read,
  2'b1
]
loc=build/xs/rtl/rtl/LFST.sv:5195:19
start_loc=build/xs/rtl/rtl/LFST.sv:2202:43
```

减法样本：

```text
slice=_op_1663392
kind=kSliceDynamic
sliceWidth=1
base=...$ibuffer$_GEN_215
start=...$_outputEntries_4_bits_T_12
start_def=_op_1643593 kind=kSub
start_def_inputs=[
  3'b100,
  outputEntriesValidNum
]
loc=build/xs/rtl/rtl/IBuffer.sv:13802:41
start_loc=build/xs/rtl/rtl/IBuffer.sv:5701:52
```

这类表达式有明确的 index 语义，但包含偏移或反向编码。当前 matcher 不做 `idx + const`、`const - idx`、wraparound 或方向推导，因此保守跳过。

#### 7. Or/mux 编码 start：dispatch 组合编码索引

```text
slice=_op_3926608
kind=kSliceDynamic
sliceWidth=1
base=cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$dispatch$_GEN_419
start=cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$dispatch$_GEN_364
start_def=_op_3903280 kind=kOr
start_def_inputs=[
  kOr(...),
  kMux(...)
]
loc=build/xs/rtl/rtl/NewDispatch.sv:93130:48
start_loc=build/xs/rtl/rtl/NewDispatch.sv:86560:5
```

这类 start 不是简单 arithmetic index，而是由控制逻辑编码出来。它可能是 one-hot/priority 编码的一部分，也可能只是 bit-level 条件组合。没有额外语义证明时，不应纳入 reg-to-mem intent。

### 对 matcher 的含义

这些案例说明 `dynamic index 未规范化` 不是单一缺口：

- `sliceWidth == 1` 的裸 index、常量 index、地址低位 index 可能是最容易扩展的安全子集。
- `kAssign` 包装可以考虑透明 unwrap，但要限制宽度和类型不变。
- `kAdd` / `kSub` / `kConcat` / `kMux` / `kOr` 需要表达式归一化和方向证明，不能直接接入 array row access。
- 对无法证明为 element index 的 dynamic slice，应继续保留普通 concat+slice emit，避免改变仿真语义。

2026-06-21 更新：已先落地第一档扩展。`reg-to-mem` 在 `kSliceDynamic.sliceWidth == 1` 时直接把 `start` 当作 row index 接受，因为 1-bit element 下 bit offset 与 element row index 等价。该扩展覆盖 dynamic miss 中最大的安全子集；宽度大于 1 的 dynamic slice 仍要求 `start = index * sliceWidth`，避免把 bit offset 误当 row index。

## concat operand 非纯 register read

`3285` 个 pair 的 slice/index 形态是当前支持的 `kSliceArray`，但 concat 的第一个失败 operand 不是 `kRegisterReadPort`。按第一个失败 operand 的 defining op 分类：

| operand def kind | 数量 |
| --- | ---: |
| `kAssign` | 1736 |
| `kConstant` | 371 |
| `kSliceArray` | 285 |
| `kSliceStatic` | 237 |
| `kMux` | 210 |
| `kSliceDynamic` | 144 |
| `kOr` | 101 |
| `kAdd` | 92 |
| `kConcat` | 65 |
| `kXor` | 33 |
| `kShl` | 5 |
| `kSub` | 4 |
| `kAnd` | 2 |

按“该 concat 的所有 operand def kind 集合”看，出现过的主要 kind 是：

| operand def kind in concat | pair 数 |
| --- | ---: |
| `kAssign` | 1869 |
| `kConstant` | 472 |
| `kMux` | 433 |
| `kSliceStatic` | 420 |
| `kSliceArray` | 308 |
| `kSliceDynamic` | 263 |
| `kConcat` | 177 |
| `kOr` | 129 |
| `kAdd` | 121 |
| `kRegisterReadPort` | 118 |
| `kNot` | 65 |
| `kXor` | 42 |
| `kReplicate` | 17 |
| `kShl` | 13 |
| `kAnd` | 12 |
| `kSub` | 12 |

这部分不是当前 reg-to-mem 的目标，因为 intent storage 需要把一组 scalar register 映射成 array-like state；operand 若来自组合逻辑、常量、切片或 mux，就没有一个直接对应的 register row storage。

可以继续拆成几类后续方向：

1. **alias/assign 包装**
   - `kAssign` 占比最高。
   - 如果它只是透明 alias，理论上可以在 matcher 中 unwrap。
   - 但需要确认不会跨过 signedness/width/cast 语义，也不能把需要 materialize 的中间值误当成 state row。

2. **常量 lane / padding lane**
   - `kConstant` 常见于 packed aggregate padding、固定字段、默认值。
   - 这类可以考虑 array storage + synthetic constant row，或者 emit 侧直接在对应 index 返回常量。
   - 但它不是纯 register group，不能直接 true rewrite 成 `kMemory`。

3. **operand 自身是 slice**
   - `kSliceStatic` / `kSliceArray` / `kSliceDynamic` 表明 concat 拼的是已有宽值的一部分或数组元素。
   - 可优化方向更像“slice(concat(slice(...))) retarget”，不是 reg-to-mem。

4. **operand 是 mux/逻辑表达式**
   - `kMux` / `kOr` / `kAdd` / `kXor` 等说明 concat lane 是计算结果。
   - 这类若要优化，应走 emit combine 或局部表达式重写，目标是避免先物化大 concat，而不是改 state layout。

5. **嵌套 concat**
   - `kConcat` operand 说明有多级拼接。
   - 可以考虑 concat flatten 后再判断 lane 边界，但需要保证 sliceWidth 与 flatten 后 lane 宽匹配。

## 匹配后又被 group 冲突剔除

`6135` 个 anchor 通过读侧 matcher 后，会按 layout 合并：

```text
layoutKey = elementWidth : elementCount : rowKey(reversed regSymbols)
```

当前结果：

| 项目 | 数量 |
| --- | ---: |
| matched anchors | 6135 |
| candidate groups | 2466 |
| conflict groups | 764 |
| conflict anchors | 2995 |
| accepted groups | 1702 |
| accepted anchors | 3140 |

冲突规则是：如果同一个 register symbol 被多个 group 拥有，则这些 group 全部剔除。它防止同一个 register 被多个 intent storage 布局重复接管。

这解释了为什么 `6135` 个 anchor 最后只剩 `1702` 个 group 参与 true/intent：

- `2995` 个 anchor 属于冲突 group，被当前策略整体放弃。
- 剩下 `3140` 个 anchor 聚成 `1702` 个 accepted group。
- accepted group 中 `280` 个 true rewrite 成 `kMemory`，`1422` 个打 `regToMem.intent.*`。

冲突组是后续提升覆盖率的另一个重点。当前策略偏保守，完全拒绝重叠 group；后续可以按“同一 register set 但粒度不同/相同”细分：

- 粒度一致、row list 一致：应共享同一个 intent group。
- 同一 register set 但不同 sliceWidth 或 elementCount：需要选择 canonical layout，或只接管收益最大的一个。
- register set 部分重叠：继续保守拒绝，除非能证明两个 layout 不会同时改写 storage ownership。

## 结论

当前未进入 reg-to-mem 的 concat+slice 不是单一问题：

1. 最大项是 `kSliceDynamic` index 归一化不足，`12914` 个，占 `SliceArray+Dynamic` 纯 pair 的 `57.8%`。
2. 第二项是 concat operand 不是纯 register read，`3285` 个，占 `14.7%`。
3. `kSliceStatic` 有 `617` 个，属于另一个 direct-slice/concat-retarget 优化方向。
4. 已匹配的 `6135` 个 anchor 里，还有 `2995` 个 anchor 因 group ownership 冲突被剔除。

因此，若继续扩大 reg-to-mem intent 覆盖，优先级建议是：

1. 先改善 group 冲突处理，因为这部分已经满足 register-read array 语义，只是布局 ownership 策略过保守。
2. 再扩展 dynamic index 归一化，优先处理 constant、assign、simple add/sub/mul 等可证明等价形式。
3. 对 `kAssign` 包装的 concat operand 做受限 unwrap，验证能否安全扩大纯 register-read 覆盖。
4. 对 constants/slices/mux/logic operands 不应强行纳入 reg-to-mem；更适合放到 emit combine 或 slice-retarget pass。
