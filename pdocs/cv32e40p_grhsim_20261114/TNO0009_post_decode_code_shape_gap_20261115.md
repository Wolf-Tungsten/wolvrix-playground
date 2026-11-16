# TNO0009：共享译码后的代码形态与剩余差距

继续使用 TNO0007 的冻结生产 binary 和 TNO0008 的动态计数。**新定位到两类 CSR 宽临时值：两次 2048-bit 拼装后只读 32 bit，以及 1024-bit 移位/掩码最终只更新 16 bit。** 前者被现有 indexed-concat 规则的 scalar-input 条件挡住；后者来自展开的数组写入，通用宽运算未恢复实际需求范围。再加上长 OR 消费者、逐位变化通知和条件表达式的提前计算，解释了共享译码后仍有大量工作。

本轮仅做冻结源码/IR/机器码分析、重读既有 perf 数据，以及有限域代数检查；没有生成优化候选、重跑性能配对或修改生产默认值。

## 当前差距的口径

最近一次同场八轮结果仍为 [TNO0007](./TNO0007_shared_equality_decode_20261115.md)：GrhSIM / 归一化 RTL Verilator **1.4015 倍**，GrhSIM / 原始 RTL Verilator **2.9932 倍**。应同时观察两种 Verilator：前者用于比较相同归一化 RTL 的后端代价，后者揭示原始数组、条件语义经归一化后丢失的结构优势。

| 指标 | 当前 GrhSIM | 归一化 Verilator | 原始 Verilator |
| --- | ---: | ---: | ---: |
| Host instructions / guest cycle | 13,104.52 | 9,799.12 | 5,355.19 |
| 模型 eval/compute/commit 或对应函数机器码 | 103,491 B | 65,387 B | 44,932 B |

指令量来自 TNO0007 的 GrhSIM 和 TNO0006 的 Verilator `perf stat`，核对 binary SHA 完全一致后复用。当前 GrhSIM 指令量分别为两者的 1.3373/2.4471 倍；这是既有独立 PMU 样本，不是新的同场周期或 walltime 对测。机器码使用同一符号筛选规则，排除通用 runtime 和完整 ELF 其他部分，符号列表随报告归档。

## 1. CSR 宽读取：两次 2048 bit 拼装只为取 32 bit

当前生成 [sched_4](../../build/cv32e40p/shared-equality-validated/grhsim_shared_equality/grhsim_Cv32Bench_sched_4.cpp) 第 444 行起建立 `std::array<uint64_t,32> grhsim_v41658_0{}`，另一份为 `grhsim_v41659_0`；615/616 行才做动态 32-bit slice。两者都在 group 31，**每 guest cycle 执行一次**。

映射到 `core$_13859_` / `core$_13860_`，分别是 mhpmcounter 两种 CSR 读取路径。每个 concat 的输入结构完全相同：

```text
1792-bit constant zero
+ four 32-bit state reads
+ 64-bit constant zero
+ two 32-bit state reads
= 2048 bits
唯一 IR consumer：32-bit dynamic slice
```

1792 位零填充占 87.5% 输入。`collectIndexedConcatSlices()` 位于 [emitter](../../wolvrix/lib/emit/grhsim_cpp.cpp) 第 19493 行起，要求每个 concat operand 是 scalar logic；1792-bit 常量直接不满足。这与此前已优化的寄存器堆读取是不同的剩余实例。还需保持其直接状态读取/快照边界，不能只放宽常量检查就假设其余证明全部成立。

机器码中仍可看到宽栈区清零和索引相关操作。[batch4 annotate](../../build/cv32e40p/post-decode-gap-v1/batch4-annotate.txt) 的 `0x140cd` 为 `vmovdqu64 ... 0x160(%rsp)`；第 444 行约占当前整体采样 **1.35%**。该地址的采样可能包含 skid，不能把单条 store 解释成精确瓶颈比例。

归一化 Verilator 也有两份 `VlWide<64>` 临时值，所以这类优化能削减归一化共同带来的成本。原始 RTL Verilator 直接从持久的 `mhpmcounter_q` 数组索引取 word；原始 RTL 的源语义见 [CSR 模块](../../build/cv32e40p/run2/inputs/cv32e40p/rtl/cv32e40p_cs_registers.sv) 382/404 行。

实施机会：在已有 indexed-concat 机制上支持宽常量 padding，以常量区间或按需 word 返回零；其他输入继续在原位置建立必要快照。处理任意 bit index、跨 operand 边界、越界零填充及直接状态读取，不只处理本负载的某几个地址。

## 2. CSR 写入：1024-bit 操作最后只需要 `[111:96]`

[sched_5](../../build/cv32e40p/shared-equality-validated/grhsim_shared_equality/grhsim_Cv32Bench_sched_5.cpp) 第 976–1041 行声明宽 mask、zero-extended write data，生成四个 `grhsim_shl_words` / `grhsim_lshr_words` 调用、两个宽 mux 和一个宽 not。第 1094 行才从中各取 `[111:96]`，更新 16-bit `_val_1066`，供 `core$_11250_` 的 register write 使用。这对应 `mhpmevent_q[3][15:0]`，不是 RAM 或通用寄存器堆读取。

group 45 执行 **0.99996446 次/周期**。当前整体采样最高的单条源码归属是第 977 行，约 **3.91%**。反汇编显示宽常量初始化确实留下栈写入：`0x170c5/0x170d0/0x170db/0x170e6` 是连续的 AVX-512 清零 stores；后面仍有 shift bounds、word index 和动态移位。编译器消除了部分宽结果，因此不能把四个源码 helper 调用等同于四次完整的 1024-bit 循环，但宽临时值及寻址成本并未全部消失。

冻结 IR 的移位来源已经核对为：

```text
signed_shift33 = 0 - concat(23'b0, csr_address[4:0], 5'b0)
mask/data 根据其符号选择左移 -signed_shift33 或右移 signed_shift33
最后只取 bit 96..111
```

因此对于这份图，移位/掩码片段满足：

```cpp
mask16 = address_low5 == 3 ? 0xffff : 0;
data16 = address_low5 == 3 ? (write_data & 0xffff) : 0;
merged16 = (old16 & ~mask16) | data16;
```

分析脚本已对全部 32 个地址和 32 个数据位基向量、全零/全一验证该恒等式。对固定地址，零扩展、移位、取 slice 均是按位线性操作，因此基向量检查覆盖任意 32-bit write data。这里仅证明组合片段；现有写使能、reset、snapshot 和 commit 语义仍必须保留，不能按 CoreMark 中 CSR 不活跃而删除更新逻辑。

归一化 [Verilator root_0](../../build/cv32e40p/run2/verilator/VCv32Bench___024root__0.cpp) 第 9686 行使用 `if (signed_shift < 0)`，只执行所选方向的两个宽移位。GrhSIM 源码先生成两侧，再通过 mask mux 选择。原始 [Verilator root_0](../../build/cv32e40p/run2/verilator-original/VCv32Bench___024root__0.cpp) 第 6047 行则在写使能条件内调用 `VL_ASSIGNSEL_WI(1024,32,address*32,...)`，保留数组元素写入语义。

已有 `localShiftDemandedBit()` 只识别直接接单个 1-bit static slice 的宽右移，这里包含双向移位、mux/not 和 16-bit slice，不满足。需要通用的 slice 需求向 shift/mux/not 传播，或在调度之前恢复数组更新；不能给地址 3 写 CV32 专用规则。完整 IR 仍有未发射的 bit-slice users，实施时必须证明活跃使用集与快照，不能仅依据最终 C++ 的一处引用删除 IR users。

## 3. 共享译码没有消除消费者：仍有 62、62、126 项 OR

此前重点记录两条，本轮补全了同组的第三条：

| IR concat / 当前 C++ 行 | 字段数 | 同源常量集合 |
| --- | ---: | --- |
| `_val_12419` / sched_4:379 | 62 | `{B80} ∪ [B82,B9F] ∪ {C80} ∪ [C82,C9F]` |
| `_val_12607` / sched_4:380 | 62 | `{B00} ∪ [B02,B1F] ∪ {C00} ∪ [C02,C1F]` |
| `_val_6808` / sched_4:435 | 126 | 上述两集合加 `{7B3}`，再 OR 一个额外 Boolean 输入 |

地址均为十六进制，源都是 `_val_6162`。三条在 group 31，每周期执行一次；C++ 中共 250 次 Boolean operand 引用，但编译器可以合并/向量化，不能据此声称 250 次 Host load。当前采样三行分别为 **0.49%、2.32%、0.36%**。机器码确有 byte OR、vector OR 和附近寄存器操作；采样归属不能精确分割消费者成本。

归一化 Verilator 同样有 one-hot 表项的长 OR，所以只是合并表更新不足以完成此优化。脚本对三个集合分别穷举全部 4096 个地址，验证区间表示与原集合一致。可在 **activity schedule 之前**合并同源等值集合，保留额外输入、其他仍需单独谓词的用户，再重建依赖/通知；不应在已调度的 C++ 中跨组读取更新时刻不明的 source 替换旧谓词槽。

## 4. 更分散的成本：细粒度通知与条件求值

TNO0008 的计数重新按类型归属后：

| 每 guest cycle | 当前值 |
| --- | ---: |
| scalar old/new 比较 | 543.0471 |
| 其中一位结果比较 | 439.2253 |
| 其中一位结果实际变化 | 44.5848 |
| 显式 activity OR 语句执行 | 300.3555 |
| compute group 执行 | 52.8751 |
| commit group 执行 | 6 |
| fixed-point rounds | 3.0000003 |

约 89.85% 的一位 old/new 检查结果不变。该统计不包含新共享译码的 cache guards，activity OR 统计也不包含 helper 内部更新，不能当作全部调度指令数。轮数和各组执行次数在共享译码前后完全一致，说明这次没有减少消费者被唤醒的次数。

例如寄存器 `core$_11281_` 的 36 个物化 bit-slice 分散于四组，合计执行 31.5632 次比较/周期；值来自多次 read-port SSA，但最终读取同一状态存储。当前 packed-slice 规则要求连续八个 slice、递增相邻 Boolean 槽和相同解析后的源表达式；生成代码中部分槽位递减/散布，不能直接套用既有批存规则。这是后续恢复 word 表达、改存储布局和合并通知的证据，尚未证明扩大 guard 或减少通知必然有收益。

aligner `next_state` 的 [sched_8:149](../../build/cv32e40p/shared-equality-validated/grhsim_shared_equality/grhsim_Cv32Bench_sched_8.cpp) 仍有五个嵌套 `grhsim_mux_u64`，所在组约 0.99998134 次/周期，源码行采样 **2.94%**。反汇编已有 `cmov`，因此不能说每个 helper 都原样变成 mask 运算，也不能只把 helper 函数体改成 `?:` 就获得延迟求值：函数实参已提前计算。若继续做该方向，必须在 emitter 的表达式/调度边界选择纯分支，保留副作用和快照；性能收益仍需独立验证。

## 后续实施顺序与边界

新的宽值证据使下一步可以更具体：

1. **先扩展按需 concat 读取对宽常量 padding 的支持**，消除两处 2048→32 CSR 读取的完整临时值；沿用已有规则的快照证明和边界测试。
2. 处理 narrow slice 经 shift/mux/not 的需求传播，覆盖 1024→16 CSR 写入片段；要先明确活跃 use、shift 越界与 signed index 语义。
3. 对同源等值长 OR 做调度前集合化简。它仍是输入有限、代数关系明确的独立机会。
4. 再单独评估条件化求值与 Boolean 存储/通知合并，避免以全局替换 mux 或调度循环掩盖语义和成本差异。

这里的顺序基于规则可证明性、当前形态和已有采样，**不是运行多个候选后的选优**。3.91%、1.35%、2.32% 等源码归属不能相加作为预期 walltime 收益；本轮没有实现或测量这些新规则。整机还包含多个数据通路，消除这些局部形态不能保证一次追平 Verilator。

这些规则也可能用于 XiangShan 的带 padding 的 Vec 读取、CSR 子字段更新和译码集合。其 packed-array/reg-to-mem/intrinsic 可能已经覆盖部分路径，snapshot 和跨分区边界也不同；本轮未重建 XiangShan，不外推收益。

## 复现与证据

在 node030 项目目录，对已有冻结 perf 数据运行下列只读命令；重现到新目录时，将 `post-decode-gap-v1` 替换为目标目录：

```bash
mkdir -p build/cv32e40p/post-decode-gap-v1
perf report --stdio --no-children --call-graph none --sort symbol,srcline --percent-limit 0 \
  -i build/cv32e40p/shared-equality-validated/grhsim_shared_equality-perf.data \
  > build/cv32e40p/post-decode-gap-v1/grhsim-lines.txt
for b in 4 5 8; do
  perf annotate --stdio --stdio-color never --no-source \
    --symbol "GrhSIM_Cv32Bench::eval_compute_batch_${b}()" \
    -i build/cv32e40p/shared-equality-validated/grhsim_shared_equality-perf.data \
    > "build/cv32e40p/post-decode-gap-v1/batch${b}-annotate.txt"
done
python3 scripts/cv32e40p_post_decode_gap.py --output build/cv32e40p/post-decode-gap-v1
```

- [完整机器报告](../../build/cv32e40p/post-decode-gap-v1/report.json)、[分析脚本](../../scripts/cv32e40p_post_decode_gap.py)
- [源码行归属](../../build/cv32e40p/post-decode-gap-v1/grhsim-lines.txt)、[带原始表达式的 JSON](../../build/cv32e40p/post-decode-gap-v1/hot-lines.json)
- [batch4 机器码](../../build/cv32e40p/post-decode-gap-v1/batch4-annotate.txt)、[batch5 机器码](../../build/cv32e40p/post-decode-gap-v1/batch5-annotate.txt)、[batch8 机器码](../../build/cv32e40p/post-decode-gap-v1/batch8-annotate.txt)
- [逐值/组动态计数](../../build/cv32e40p/shared-equality-counts-v1/counts.json)、[IR/RTL 映射](../../build/cv32e40p/remaining-gap-v1/sources.csv)

身份检查覆盖生产构建、诊断构建、当前 Wolvrix tracked patch 和相同 normalized graph。源码行数据来自既有 843 个 `cycles:u` 样本，lost samples 为 0；采样粒度和 skid 限制如上。报告附输入 SHA、符号列表与映射，便于实施下一条规则时复核。
