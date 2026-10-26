# 孤立 ROB 生成 C++ 的剩余数组往返审计

2026-10-23。检查 S8 完成后用于 A/B 的候选 `ptmp/xs-components-rob-array-create/candidate/`，**仍有无意义的数组打包、拆分和重组**。原先 520 元素的 pdest/rfWen/fpWen 输出已改为数组元素拷贝，但不能据此推断所有数组路径都已消除往返。

本轮读取既有 C++、最终 GrhSIM IR、binary 和 perf 样本，没有重生或修改模型，也没有重新进行性能 A/B。binary SHA256 为 `7bba7a8056764b758d368fac1b7be28e10a15a05caec3c26e0cc761acb7ba771`，与原 A/B 及 perf 的记录相同。

完整清单、IR 类型和消费者、源文件哈希、反汇编与采样偏移保存在 [审计目录](../../ptmp/rob-array-roundtrip-audit-20261023/)；其中 [audit.json](../../ptmp/rob-array-roundtrip-audit-20261023/audit.json) 是结构化证据。

## 1. 最优先：reset 写入 replayCause 时，内层反复打包整张表

位置：[grhsim_Rob_tu346.cpp:22981](../../ptmp/xs-components-rob-array-create/candidate/grhsim-model/grhsim_Rob_tu346.cpp#L22981)，`pLargeSink_c0`。

最终 IR 的 `core.state.write` op28795 把 v662343 写入 state255：

| 对象 | 总位宽 | shape | 叶元素逻辑位宽 | 实际 C++ |
| --- | ---: | --- | ---: | --- |
| 数据 v662343 | 3872 | `[352,11]` | 1 | `std::array<std::array<bool,11>,352>` |
| 状态 debug_lsInfo.replayCause | 3872 | `[352]` | 11 | `std::array<std::uint16_t,352>` |

两边的 shape 都仍在 IR 中。这里确实需要把每行的 11 个 bit 组成一个 11-bit 元素；不需要把其他 351 行也一起打包。

实际生成的 C++ 简化如下，宽整数因存储按 64 bit 舍入而使用 `_BitInt(3904)`：

```cpp
for (std::size_t row = 0; row < 352; ++row) {
    // 实际是嵌在右值中的 lambda；每次 row 迭代都会执行。
    unsigned _BitInt(3904) packed = 0;
    for (std::size_t bit = 0; bit < 3872; ++bit)
        packed |= (unsigned _BitInt(3904))(source[bit / 11][bit % 11]) << bit;
    state[row] = (packed >> (row * 11)) & 0x7ff;
}
```

每次该写入生效，源代码会执行 `352×3872=1,362,944` 次内层迭代，每次还有宽整数移位、OR 和临时值操作。这不是每个稳态周期都执行：enable 是 reset。生成 enable 的位置是 [grhsim_Rob_tu265.cpp:3223](../../ptmp/xs-components-rob-array-create/candidate/grhsim-model/grhsim_Rob_tu265.cpp#L3223)，由 `inputStore.reset` 设置 `largeSinkEnableBoundaryStore.enabledWords[0]` 的 bit0。现有 trace 包含 52 条 reset 记录，正式回放和采样均包含这个前缀。

这个特例的数据实际上还是全零常量：`grhsim_Rob_tu1.cpp:23853` 的 `cpu_const_array_662343` 经 `:23856` 写入 payload boundary。由于执行写入时又从 mutable boundary 读取，C++ 编译器没有把它当作直接清零。

机器码保留了两层循环，见 [pLargeSink_c0.asm](../../ptmp/rob-array-roundtrip-audit-20261023/pLargeSink_c0.asm)：

```text
de9020  外层循环入口                   函数偏移 +0x22b0
de92b0  内层宽整数打包循环入口         函数偏移 +0x2540
de9b8a  cmp $0xf20, %rdx               3872 次
de9b91  jne de92b0
dea061  and $0x7ff, %eax               取回一行
dea072  cmp $0x160, %rsi               352 次
dea079  jne de9020
```

复用同一 binary 的已有 perf 数据，按原始 period 加权：

| 代码区域 | 总采样周期占比 |
| --- | ---: |
| 完整 pLargeSink_c0 | 5.6577% |
| replayCause 整数组 reset 写循环 `[+0x22b0,+0x330f)` | **5.6005%** |

第二行包含打包、取回和 store 整个循环，不能解释成单条指令的占比，也不是修复后的实测加速幅度。它说明这条冗余路径在包含 reset 的现有回放里有实质成本，不能直接外推到排除 reset 的稳态窗口。

成因在 [cpu_phase_emit.cpp:4517](../../wolvrix/lib/grhsim/backend/cpu_phase_emit.cpp#L4517)：整数组写只有在源/目标**叶元素位宽相同**时才走 `emitElementsInto`。这里 1 与 11 不相等，因此退回 `read(source)`，得到打包整张表的 lambda 文本；`rowSliceText` 又把该文本放入每行的右值，使整表打包在外层循环里重复执行。

修复应分两步约束：任何通用 packed fallback 都应先在循环外保存一次源快照；对这里的类型组合则直接逐行组装 11 bit，完全避免 3872-bit 中间整数。若保留全零常量信息，可以直接生成目标数组清零。跨写入/别名的快照语义仍须保留。

## 2. 同型数组经过无损 assign 后，被打包又拆回

一个非常直接的例子在 [grhsim_Rob_tu355.cpp:3169](../../ptmp/xs-components-rob-array-create/candidate/grhsim-model/grhsim_Rob_tu355.cpp#L3169)，`pOutput_c22`：

```text
v678300: UInt<9>[8]
  → assign v678303: UInt<72>             打包为 _BitInt(128)
  → assign v678304: UInt<9>[8]
  → assign v663342: UInt<9>[8]           拆回 std::array<uint16_t,8>
  → 8 个 sliceArray 消费者
```

这条链没有修改位图；可让数组消费者直接使用 v678300。当前顶层 `io_commits.robIdx.value` 输出已经直接使用该数组，但内部消费者仍绕过整数。顶层输出修好了，不代表内部路径也修好了。

另一个例子在 [grhsim_Rob_tu356.cpp:2687](../../ptmp/xs-components-rob-array-create/candidate/grhsim-model/grhsim_Rob_tu356.cpp#L2687)，`pOutput_c33`：

```text
v662867: UInt<8>[7]
  → assign v666900: UInt<56>             逐字节打包到 uint64_t
  → assign v666901: UInt<8>[7]           再 memcpy/拆位恢复数组
  → arrayCreate v667158 的一个操作数
```

8 个对应来源都存在同类 IR 链，后两项在 `pOutput_c34` 的 arrayCreate 消费处再次拆回七元素子数组。这表明新 `arrayCreate` 的消费者仍会受到上游 flat assign 包装的影响。

静态枚举最终 IR，共找到 **46 个“同型 shaped → 无损 assign 链经过 flat → 同型 shaped”结果**，涉及 **27 个不同源数组**。链可能互相包含，不能把它们当作 46 个独立运行时打包循环；后端也可能消去其中部分视图。上述两个例子已逐项核实实际 C++。

成因之一在 [canonicalize_compute.cpp:332](../../wolvrix/lib/grhsim/pass/canonicalize_compute.cpp#L332)：当前寻找最深同型数组的重接逻辑只处理 `core.output.write`。应扩展到内部数组消费者，在同宽、同 domain、同型结果且满足 phase/lifetime 约束时绕过中间视图。真实 flat 消费者仍保留原分支。

## 3. 元素对齐的连续切片，经整数再拆回 boundary 数组

位置：[grhsim_Rob_tu27.cpp:11225](../../ptmp/xs-components-rob-array-create/candidate/grhsim-model/grhsim_Rob_tu27.cpp#L11225)，`sn_1297`。

```text
arrayCreate v24118: UInt<2>[16]
  → sliceStatic v236931: UInt<16>        取后 8 个完整元素，打包到整数
  → assign / boundary: UInt<2>[8]        又逐元素拆回
```

同一函数中 v236901 对前 8 个元素重复相同操作。生成代码先循环组装 8 个 2-bit 元素，然后 `grhsim_slice_dynamic_u64` 再拆成 `nonSinkBoundaryStore.assign_26878/assign_26848`。这一系列 helper 在 `tu27/tu28` 中还有同类实例。

这里连续切片本身有意义，整数表示的往返没有必要。切片起点和长度都对齐元素，可以直接复制指定元素并执行原有变化检测/激活逻辑。当前部分 direct-shaped 路径要求结果本身有 shape；`sliceStatic` 先返回 flat、后由 assign 恢复 shape 的形式仍会漏过。

相关动态例子在 [grhsim_Rob_tu38.cpp:7269](../../ptmp/xs-components-rob-array-create/candidate/grhsim-model/grhsim_Rob_tu38.cpp#L7269)：`snapshots.value` 的 `UInt<9>[4,8]` 先打包为 288 bit，再动态切出 72 bit、拆回 `UInt<9>[8]`，随后取一个元素。源数组的二维结构本来足以直接索引；改写仍须保持原 OOB 零值语义。

## 4. 二维 debug_VecOtherPdest 的重复和拼接仍经过巨型整数

位置：[grhsim_Rob_tu358.cpp:6314](../../ptmp/xs-components-rob-array-create/candidate/grhsim-model/grhsim_Rob_tu358.cpp#L6314) 与 [grhsim_Rob_tu359.cpp:2](../../ptmp/xs-components-rob-array-create/candidate/grhsim-model/grhsim_Rob_tu359.cpp#L2)，`pOutput_c70/c71/c72`。

最终 IR 保留了如下链：

```text
UInt<8>[8] → assign UInt<64>
  → replicate 160 次: UInt<10240>
  → assign UInt<8>[160,8]
  → concat(该数组, UInt<8>[352,8]): UInt<32768>
  → assign UInt<8>[512,8]
  → 8 个动态 sliceArray，各读取 UInt<8>[8]
```

C++ 确实先生成 10240-bit 重复整数、拆成 1280 字节数组，随后把两个数组重新打包为 32768-bit 整数，再拆成 4096 字节数组。部分转换使用 little-endian memcpy，仍存在整个表示的重建和跨 chunk frame 暂存。

这条链的源 SV 本身确实有 replicate/concat，见 `Rob.sv:93593/93594`；这些操作的位图语义合法，但不要求 C++ 一定使用巨型整数。可以直接重复/复制数组块，或在索引消费者处选择原数组与补齐行。

后端现有 concat direct-shaped 分支主要覆盖 rank1，replicate 分支主要覆盖标量元素广播，见 [cpu_phase_emit.cpp:2427](../../wolvrix/lib/grhsim/backend/cpu_phase_emit.cpp#L2427)。这里重复的是完整的八元素子数组，结果为 rank2，且中间已有 flat op，因此没有覆盖。

已有机器码里 `pOutput_c71` 为 7515 字节/995 条静态指令，`pOutput_c72` 为 7357 字节/995 条。现有 perf 独占占比分别约 0.0450%/0.0593%，低于 replayCause；静态结构值得清理，但当前数据不足以声称其收益很大。

## 扫描范围和下一步顺序

全量扫描候选目录的 **368 个 `.cpp`**，发现 133 个 `cpu_pk` 打包表达式定义和 28 个 `cpu_packed` 拆分位置。这是文本入口数量，不是“133+28 个错误”：其中包含正确的 flat 消费、常量展开、真正 flat 状态的输出转换，以及平台 fallback。完整列表保存在 audit.json，不能只凭 `_BitInt` 或循环出现就判为冗余。

原目标 pdest/rfWen/fpWen 的 520 元素输出仍是数组直接拷贝，位置分别为 `tu358.cpp:3102/3637/4172`，没有回退。

修复优先顺序为：

1. replayCause 整表写入的循环内打包，先保证 packed fallback 只采样一次，再处理按行重新分组/常量清零。
2. 内部无损 assign 链与数组消费者重接，覆盖 UInt<9>[8]、UInt<8>[7] 等已经有完整数组类型的路径。
3. 元素对齐的 sliceStatic/动态子数组访问，消除 flat 包装后的重组。
4. 二维子数组的重复与拼接，保持块结构并避免巨型整数暂存。

S8 新 op 已经解决数组“如何构造”的表达问题，剩余问题还包括视图消除、不同叶元素位宽的按行组装，以及旧 replicate/concat 的数组消费。不能把这几类都归为 firtool 已经不可逆地丢失了 shape；上述具体路径的 shape 大多在最终 IR 中仍可辨认。

复核命令（仅静态审计与已有采样分析）：

```sh
make --no-print-directory -f ptmp/rob-array-roundtrip-audit-20261023/Makefile audit
```

当前记录的是发现与修复建议，尚无这些剩余问题修复后的正确性/速度结果。

后续先按 [GrhSIM 最小扩展与 CPU ST 目标模型](../grh-ir-array-support/pre-s9-grhsim-target-model.md) 完成边界收敛（[代码事实](../grh-ir-array-support/pre-s9-grhsim-ir-boundary-review.md)），再按 [S9 数组规范化与 CPU 访问映射计划](../grh-ir-array-support/stage-09-array-normalize-mapping.md) 处理 replayCause、内部视图、切片和二维块操作。目标模型已明确 op 白名单、数据结构字段及 CPU4 的 CpuValuePlan 接口，代码尚未重构。S8 candidate 保留为历史总基线，两个 pass 的增量以前置验收版本为直接基线。
