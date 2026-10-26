# Stage 09 — 数组规范化与 CPU 访问映射 pass 计划

- 日期：2026-10-23。
- 状态：**未开始，仅完成规划**。本文中的新 pass、CPU 计划字段、测试 target 和验收结果均尚未实现。
- 前置：[S8 数组构造](stage-08-array-create.md) 已实施、工作树未提交；[移除独立 GrhSIM IR](../remove-grhsim-ir/README.md) 的 R0–R8 已于 2026-10-26 完成。S9 的直接基线固定为 [R7/R8 验证版本](../remove-grhsim-ir/20261026-r7-r8-validation.md)（SV→emu 1954.081s、100k Host=965.162s/无 mismatch），本阶段尚未实施。[事实审查](pre-s9-grhsim-ir-boundary-review.md) 保留历史证据。S9 不改变 S7 的整机验收状态。
- 依据：[S8 后 ROB 数组往返审计](../rob_standalone/20261023-rob-array-roundtrip-audit.md)；S8 是历史总基线，两个 pass 的增量 A/B 以前置架构收敛的验收版本为直接基线。
- 当前功能归属：数组规范化在同一 GRH 图上作为按需优化；数组访问/快照/物化分析在 emit/grhsim/cpu-st-cpp.cpp 内完成，不设 CPU planning pass。具体 S9 接口待统一图迁移验收后重写。

**2026-10-24 状态修订：** 下文 two-pass/CpuProgram/CpuValuePlan、whole/phase 与 v4 artifact 等结构是历史草案，已由新计划替代，不按原接口实施。数组位序、快照、越界、动态索引及增量 A/B 要求继续保留；S8 证据不变。

S8 让 IR 能明确表达“用这些元素构造数组”，已经解决 ROB 的 520 元素目标输出。S9 要解决下一层问题：**数组经过视图、切片、重复、拼接或状态写后，仍应按所需元素读取，而不是默认先生成整个整数。**

## 1. 要补齐的能力与完成边界

| 审计发现 | 语义规范化负责什么 | CPU 访问映射负责什么 | 优先级 |
| --- | --- | --- | --- |
| replayCause：`u1[352,11]` 写到 `u11[352]`，每写一行都打包整表 | 保留已有 source/target 类型；向后端提供可证明的常量信息 | 按目标行重分组；packed fallback 循环外采样一次；可证明时按零值写入 | 第一 |
| 内部 shaped→flat→同型 shaped assign 链 | 对内部消费者也消除无损往返 | 直接读取对应 local/frame/boundary 数组 | 第二 |
| 元素对齐的静态切片、动态子数组访问 | 把数组解释接到切片结果；可证明时恢复 sliceArray | 读取指定元素范围，保留越界和变化检测行为 | 第三 |
| 二维子数组 replicate/concat | 恢复带 shape 的已有 replicate/concat，不展开整张表 | 重复/复制子数组块；需要时保存数组快照 | 第四 |

本文中 `uE[d0,...]` 表示无符号两态 Logic：叶元素宽 E，总宽 `E×∏shape`，shape 为 `[d0,...]`；`uW` 表示无 shape 的 W-bit 值。实际规则还必须检查完整 signedness 和 domain。

审计扫描到 46 个“同型数组经过 flat assign 链再回到同型数组”的结果、27 个不同来源；链会重叠，不能当作 46 个运行时循环。368 个 C++ 文件中的 133 个 pack / 28 个 unpack 文本入口也不是全部冗余。完成条件按**数据流是否有必要物化整数**判断，不能要求所有 `_BitInt` 消失。

replayCause 的两层循环在机器码中仍存在，现有 perf 中整个写循环占 5.6005%。它只在 reset 写入生效，trace 含 52 条 reset 记录；该占比既不是稳态成本，也不是 S9 的预期收益承诺。二维 repeat/concat 的结构同样要修，但已有采样显示其成本明显更小。

本阶段先覆盖审计中的四类路径，并形成可复用的数组访问流程。真实的整体位运算、未对齐切片、不能证明安全的转换仍保留合法 packed 路径；诊断中必须说明原因。exceptionVec 的 `u24[8]` 存储类型不在本阶段改动范围内。

## 2. 现有实现与新增职责

当前不是完全没有数组优化：

- `canonicalize_compute.cpp` 已有精确 `assign(concat(...))→arrayCreate`、常量索引读取构造元素，以及数组输出的无损 assign 链重接。最后一项目前只面向 `core.output.write`。
- `const-fold`、`used-bits` 已认识 arrayCreate，分别负责常量值和活位传播。
- `cpu_phase_emit.cpp` 已有 `emitElementsInto`、direct-shaped 及 row-backed 快速路径；覆盖条件不足，且表示选择主要发生在发射时。
- `build-mem-write-plan` 已规划 LargeSink 写顺序和读者激活；它不负责通用数组表示，也不覆盖 General 中的 SmallSink 写入。

因此新增两项不同职责：

| pass | 类别 | 输入与输出 | 不承担的职责 |
| --- | --- | --- | --- |
| `grhsim.array-normalize` | SemanticTransform | 合法 GrhSIM 语义图 → 等价且保留数组结构的图 | 不决定 C++ 容器、helper 或 TU |
| `cpu.st.plan-array-access` | CPU planning transform | 冻结的 CpuProgram、分区/主要存储/写计划、fallback CpuValuePlan → 更新同一 CpuValuePlan 的数组 recipe 与物化决定 | 不改变 source/program op、phase、state 策略或写顺序 |

GRH/ingest 继续直接生产 S8 的 `kArrayCreate`，GRH→GrhSIM 保留 shape。前置收敛后两层引用同一份数组定义和几何校验；通用规范化算法通过适配器/共享接口复用，phase 内安全规则由仿真层补充，不再复制两套公共数组语义。

## 3. 两个 pass 共同遵守的语义

1. **按逻辑位布局转换。** 低下标对应低位，行主序；一个 E-bit 元素只占 E 个逻辑 bit。`std::uint16_t` 保存 11-bit 元素时的 5 个高位不是数组内容，`bool` 的对象字节也不是 packed bit。不能仅凭总宽相同就对 C++ 对象做 reinterpret/memcpy。
2. **数组 value 是一次计算的快照。** 改写可以引用原 ValueId，不能重新执行 state read、DPI、随机函数或输入采样。不得穿过边界去读取较新时刻的 state。
3. **完整类型约束。** 绕过视图后交给消费者的类型必须符合该 operand 契约。位宽变化、截断、扩展、domain 转换或带其他语义参数的 op 不属于无损视图。最终同型是必要条件，但不能代替对中间每一步的证明。
4. **保留 phase 和写入协议。** whole/phase 规范化遵守现有 scope；跨 phase 的值仍通过原接口传递。enable、事件、mask、声明顺序优先级、NBA 提交、变化检测和 reader 激活保持原语义。
5. **保留当前后端的越界结果。** CPU 的现有两态越界补零等行为必须逐项等价。不能把扁平地址检查擅自换成逐维 clamp，也不能改变索引计算中的位宽截断/溢出。这里不重新定义 GRH 的跨实现 OOB 契约。
6. **支持边界清楚。** 首批改写以两态 Logic 为实现和验收范围。四态 IR 保留 X/Z；未证明可用的规则跳过，CPU 四态 aggregate 继续明确拒绝。

## 4. 语义 pass：grhsim.array-normalize

### 4.1 插入位置与规则归属

支持 `scope=whole/phase`，复用 simplify 的 scope、phaseCompatible、来源信息和生命周期检查。接入现有固定点序列：

```text
const-fold
→ canonicalize-compute
→ array-normalize          # 新增
→ bitwise-predicates
→ bitwise-muxes
→ mux-chain-fold
→ used-bits
→ 下一轮，直到无变化
```

源图 whole simplify 在 comb-pack / pack-bit-registers 之前再运行一次 array-normalize，使打包 pass 能看到已恢复的结构。目标流程 CPU1 的 phase simplify 清理 lowered graph；CPU2 完成真实边界 clone 后冻结 CpuProgram/partitions，后续不再运行本 pass。边界克隆必须保形，不能依靠冻结后再化简补救；不再沿用旧 B8/C 段改源模型的例外通路。

S8 中数组专属的恢复/重接规则迁入本 pass，scalar 恒等式与一般 CSE 留在 canonicalize；const-fold 负责常量，used-bits 负责活性和死锥。每条规则只保留一个实现入口，避免两个 pass 互相改回对方的形态。

### 4.2 N1：内部同型数组视图消除

```text
%a : u9[8]
%p = assignAs(%a) : u72
%b = assignAs(%p) : u9[8]
%x = sliceArray(%b, %i) : u9

改写数组这一支：
%x = sliceArray(%a, %i) : u9
```

`assignAs(source)` 的唯一 operand 是源，唯一 result 是指定目标类型的等宽位图视图；此处每一步保持总位宽和逻辑位图。严格同型 assign 与 assignAs 依目标公共定义分开；旧 GrhSIM 中混为 assign 的表达在前置阶段纠正。`sliceArray(base,i)` 的两个 operands 分别为数组 base 和第一个外维下标，例中结果是标量元素。

沿 assign 链记忆最深的完整同型数组源，将原数组结果的合法使用重接到它；覆盖 sliceArray、arrayCreate 的子数组 operand、mux 的数组数据 operand、state write 数据及 output write 等，不局限于顶层端口。按 operand 契约核验，不能无差别替换一个 op 的全部 operands。

若 `%p` 同时参与真实的整数运算，那条分支继续保留；只有没有真实消费者的包装才由 DCE 删除。不同 phase、带未知语义参数或可能改变位图的链停止追踪。不能仅凭相同名字、总宽或状态来源建立别名。

### 4.3 N2：数组构造恢复与索引化简

承接 S8 已有精确规则：

```text
assignAs(concat(eN-1,...,e0)) : width=N*W, shape=[N]+S
→ arrayCreate(e0,...,eN-1)
```

每个 `ei` 为相同完整类型、总宽 W、shape S 的 value。concat 的第一个 operand 占高位；arrayCreate 的第一个 operand 是外维元素 0，因此需要逆序。singleton 仍保留新增的 `[1]` 维，两个 `[3]` 构造的是 `[2,3]`，不是 `[6]`。

`sliceArray(arrayCreate(e0,...),constant i,...)` 可接回 `ei` 并继续处理剩余索引；只使用原 value，不复制 producer。动态索引先保留数组访问，不展开成 N 路标量选择。

### 4.4 N3：带数组目标的切片

静态例子：

```text
%a : u2[16]
%s = sliceStatic(%a){sliceStart=16,sliceEnd=31} : u16
%b = assignAs(%s) : u2[8]

数组分支规范化为：
%b = sliceStatic(%a){sliceStart=16,sliceEnd=31} : u2[8]
```

sliceStatic 唯一 operand 是被截取值，两个参数是包含端点的 LSB 位编号。此例取元素 8..15。现有切片结果允许声明等总宽 shape，因此不需要新 range op；有真实 flat 共消费者时保留原 `%s` 分支。

只有起点和长度对齐源元素、目标几何确切时才标为数组范围；完整子数组优先使用现有 sliceArray。任意连续元素范围不一定能表示成一次 sliceArray，不能强行套用前缀索引 op，也不为大范围展开成逐元素 arrayCreate。

动态例子：

```text
%a : u9[4,8]
%off = mul(%i, 72) : 原表达式的整数类型
%s = sliceDynamic(%a,%off){sliceWidth=72} : u72
%b = assignAs(%s) : u9[8]

若证明所有索引值下地址与越界行为等价：
%b = sliceArray(%a,%i) : u9[8]
否则保留原 off 运算，将切片结果保形并交给 CPU 规划。
```

sliceDynamic operands 为 `[base,bitOffset]`，bitOffset 按无符号解释，sliceWidth 是结果逻辑位宽。证明必须包含原 `%off` 的乘法位宽、截断和越界补零；不能只因乘数是 72 就删掉该运算。未对齐或无法证明的切片保留位操作。

### 4.5 N4：子数组重复和沿已有维度拼接

沿明确的目标几何，把 `assignAs(flat op)` 的数组分支恢复为带 shape 的现有 op：

```text
%block : u8[8]                 # 一行，8 个字节
%body  : u8[352,8]
%pad   = replicate(%block){rep=160} : u8[160,8]
%all   = concat(%pad,%body)          : u8[512,8]
```

replicate 唯一 operand 是要重复的整个子数组，rep 是次数。这里 `pad[r][c]=block[c]`；重复的是同一次采样的 block，不是重新读取它 160 次。concat operands 按高位到低位排列，所以 `all[0..351]=body`、`all[352..511]=pad`。

判定依据是目标类型、连续位段和一致的内层几何，不能仅以总宽可整除就猜 shape。已有 concat/replicate 的扁平位语义保持，恢复结果和可安全绕过的同宽输入包装；其他 flat 分支保持原样。不同外维长度的子数组拼接不满足 arrayCreate 的“新增一维”契约，不能误改为 arrayCreate。

本阶段复用这两个 op，不新增 arrayConcat、reshape、pack/unpack。重复次数和大表长度保留为参数/shape，不展开成数千个 scalar op；CPU plan 负责循环或块访问。索引下推只在不会重采样、跨快照或造成图膨胀时采用。

### 4.6 终止性与规模控制

- 改写方向固定为“去掉无损视图 / flat 包装”或“恢复一个带 shape 的计算”；本 pass 不反向降为 concat 整数。
- 追踪以 value、完整目标类型、scope 为键缓存，并设置环守卫；避免每个消费者重新遍历长链产生二次复杂度。
- 默认不展开 repeat 和范围数组，不复制有副作用的 producer。必要新分支只共享现有输入，记录新增节点和预算拒绝原因。
- 第二次运行应无变化，semanticRevision 不增加；与整个 simplify 联跑也必须收敛。达到预算或无法证明等价时保留合法原图并诊断。

## 5. CPU pass：cpu.st.plan-array-access

### 5.1 在目标 CPU 流程中的确定位置

接线按 [目标模型 §12](pre-s9-grhsim-target-model.md#12-生产流程冻结点和-s9-接口) 确定，保持“表示决定先于 helper/TU 分块”。这些是编译顺序，不增加持久化 stage 枚举。

```text
CPU0  独立 lowered CpuProgram / phase / state policies
CPU1  phase simplify（包含 array-normalize）
CPU2  分区、真实边界 clone，然后冻结 program/partitions
CPU3  主要 named stores、事件绑定、writes、activation
CPU4  plan-values 的完整 fallback
      plan-array-access             # 更新同一 CpuValuePlan
CPU5  functions/helper 分块          # 消费 recipe 依赖和 cost
CPU6  local/frame/scratch 绑定        # 不重采样 producer
CPU7  TU 装箱与完整 CpuStArtifact 校验
      emit-cpp                      # 只读计划
```

选在 CPU3 之后，是为了使用最终边界身份、状态物理类型和写采样计划；选在 CPU5 之前，是为了让 helper 分块、frame 生存分析、TU 估算与发射使用同一个表示决定。不能先按巨型整数估算/分块，最后到 emitter 才临时改成数组。

本 pass 不修改源图、冻结的 CpuProgram、主要具名 store 分类/布局或写位置。遇到跨 supernode/phase 的值，先绑定现有 boundary 快照；只有同一物化区域内的纯计算才能继续解析来源。需要改变边界类型的结构由冻结前的 array-normalize 完成。无法越过的已物化 flat 边界保留一次合法转换并报告，不能引用没有布局的远端值。新增 scratch 先取得 CpuSlotId，CPU6 再确定 local/frame home。

### 5.2 持久化的数据计划

使用目标模型 §9 的 `CpuValuePlan/CpuUse/CpuAccessRecipe/CpuMaterialization`，不再定义平行数组计划。访问/物化决定按“consumer CpuOpId + operand role + 目标完整类型”索引，计算结果物化另以 CpuValueId 标识。至少记录：

| 字段 | 含义 |
| --- | --- |
| use / destination | 哪个 op 的哪个数据或 mask operand；或哪个 local/boundary/state/output 目标 |
| source / geometry | 源 CpuValueId、逻辑叶宽、完整 shape、目标几何及对应位区间 |
| recipe | 下面的结构化访问方式及子计划引用，不保存 C++ 表达式字符串 |
| snapshot binding | 原 phase/owner、使用哪个已采样的 store/value、是否需要先保存源 |
| materialization | 可借用已有数组，还是在 local/frame/调用方缓冲区物化一次 |
| dependencies / cost | 实际引用的 CpuValueIds、读写量、临时空间和预计发射规模，供后续共同消费 |
| fallback reason | 无法按元素处理的具体原因；正常标量/真实 flat 消费也要可区分 |

结构化 recipe 使用已有 CPU SSA 值组成 DAG，tag/payload 采用目标模型 §9.2 的定义：

| recipe | 输入及参数 | 目标元素如何取得 |
| --- | --- | --- |
| ReadValue（Elements） | snapshotId、source geometry、既定物化绑定 | 直接按行主序读已存数组；slot/capturePoint 由 snapshot 表唯一给出 |
| Create | 按下标顺序的元素/子数组 sources | 第 i 个外维元素来自第 i 个 source |
| Slice | source、原 bitOffset/范围、长度和越界规则 | 只读取覆盖该输出元素的源位段 |
| Repeat | 已采样 source、重复次数 | 子数组块循环复制，或通过模运算选原块 |
| Concat | 按低位到高位排列的 source segments 和长度 | 根据目标偏移选择所属段；与 IR concat 顺序相反 |
| Regroup | source、源叶宽 Es、目标叶宽 Ed | 按逻辑位偏移重新分组，不经过总宽整数 |
| ConstantFill | 定宽元素值、数量、可重验的 constant/snapshot proof | 使用定宽元素值写入，仍执行原变化检测 |
| PackedOnce | source、总逻辑宽、capturePoint、scratchSlot | guard 内、目标行循环前整体打包一次，各行从快照取片 |

计划的 referencedValues 必须包含真正发射时使用的依赖。后续分块如使一个依赖跨 helper/TU，就保存对应快照到 frame，不能重跑它的 producer。已有 named-store/boundary 绑定不可因分块重新指向当前 state。对数据、mask、部分索引结果和输出统一使用该计划；LargeSink 和 General 中的 SmallSink 写入都覆盖。

同一 value 的使用必须完整分类：按元素读取、需要数组快照、需要真实 packed 值。只有所有使用都已由 recipe 覆盖、且 producer 是允许融合的纯 compute 时，计划才能省去它的独立整体物化；否则保留一次必要的物化。这个决定也写入计划并供分块/emit 共用，避免“下游直接取元素了，上游仍照常发射无用打包”。state read、DPI、随机和系统操作继续执行原有 producer，recipe 只消费它们的结果。

### 5.3 优先修复 replayCause 的重新分组

对于源叶宽 Es、目标叶宽 Ed，总逻辑宽相同的无损写入，目标线性元素 r 的 bit b 来自：

```text
t = r*Ed + b
源线性元素 = t / Es
源元素内 bit = t % Es
```

再用源 shape 把线性元素解码为多维下标。所有乘加检查溢出，按逻辑叶宽 mask；更高效实现可以按相交位段批量搬运，不必逐 bit。

replayCause 为 Es=1、Ed=11，因此目标代码应等价于：

```cpp
// 在原事件/enable 生效区域内，从原 payload 快照取数。
for (std::size_t row = 0; row < 352; ++row) {
    std::uint16_t data = 0;
    for (std::size_t bit = 0; bit < 11; ++bit)
        data |= std::uint16_t(source_snapshot[row][bit]) << bit;
    // 把 data 交给既有 writeCell：mask、优先级、比较、激活仍在。
}
```

一次写入读取 3872 个源 bit，替代 352 次打包全部 3872 bit；不会生成 3872-bit 中间整数。上面展示的是数据读取部分，不是替换状态提交协议的独立 store。

该源在当前 ROB 中还是全零常量。ConstantFill 必须证明此快照在使用时恒零，包括 boundary 初始化和所有可能更新；仅沿 producer 找到一个 constant 不足以越过 mutable boundary。证明成立则直接按零元素走 writeCell，mask/变化检测仍保留。必须另有非零、逐行不同数据的 fixture，防止只修好清零特例。

### 5.4 所有 packed fallback 的共同保护

无论数据、mask、fill 还是其他数组消费，只要确实需要 packed fallback，必须遵守：

```text
原事件/enable guard 内：
    取得这次写入所需的源快照
    packed_source = pack(源快照)       # 一次
    for each destination row:
        extract(packed_source, row)   # 不能内嵌 pack 整表的 lambda
```

不能把 pack 文本作为逐行右值反复插入。也不能为了复用而跨越 enable、不同 writer 或采样时刻，改变读取次数与别名结果。

源/目标可能重叠时，在第一次写之前保存本次需要的源快照；证明不别名且 source 是稳定 SSA/boundary 时才借用引用。部分重叠复制不能简单依赖正向循环。snapshot 使用现有 local/frame 或调用方缓冲区，避免新增大型按值返回 `std::array` helper。

### 5.5 消费者、布局和分块联动

- `emitElementsInto`、boundary 发布、state write/fill、output write 消费同一份计划，不各写一套 shape 猜测。
- 逻辑读取方式和物理存储类型分开：仍保留多维 `std::array` 声明，11-bit 元素可存 uint16，宽元素和真实宽运算继续使用现有原生 `_BitInt` 路径。
- 参考 legacy 的调用方缓冲、别名与数据移动方式；布局兼容且语义允许时才使用块复制。常量、bool 数组、非整字元素不能直接套对象字节拼接。
- 同一结果被多次使用或跨 chunk 时，选择一次数组物化；只有真正需要整数的分支打包。重复、拼接不能靠反复重建大临时值实现。
- CPU5/CPU7 共享 plan 的预计发射行数、数据量和 scratch 需求。循环体的代码规模与运行读写量分别估算；不能把大数组一律当一条 scalar，也不能因保留 compact loop 就按完全展开代码估算。
- CPU2 的分区不因本 pass 重做；CPU5 helper、CPU6 frame 和 CPU7 TU 必须尊重实际依赖与物化边界。emitter 不再重新分析 frame/view roots；强制小 helper/TU 的执行测试是必要门禁。

### 5.6 verifier、版本与生命周期

- 不保留旧 mapping stage 机制，不新增 `CpuMappingStage::ArrayAccessPlan`。CPU4 更新 CpuValuePlan，完整 CpuStArtifact 必须具备本阶段全部 use/recipe/fallback，未完成 builder 不能传给 emitter。
- 更新分块前置条件及后续 verifier 的 payload 要求。校验 recipe 覆盖、完整类型、逻辑位区间、source 可见性、快照绑定、DAG 无环和代价一致性；篡改/缺失计划必须拒绝。
- 新计划进入 CPU artifact copy、JSON 读写、等价往返、本地 CPU ID 重映射与失效测试。源 semantic revision/摘要、CpuProgram、partition/layout/config 变化使计划失效；源 ID 与 CPU ID 不混用。
- checkpoint 使用前置定义的 `wolvrix.grhsim.v4` + `cpu.st.artifact.v1`。recipe 契约已定义，前置先生产正确 fallback，S9 增加消除打包的规划规则；不另引入 core op 或旧 mapping schema。缺少完整 recipe、未知 tag 或绑定不一致必须拒绝。
- diagnostics 至少区分 view bypass、aligned slice、repeat/concat、regroup、constant fill、packed-once 和因 boundary/alias/domain/alignment 保留的路径，并报告新增临时空间。不能只打印“优化 N 个数组”。

## 6. 实施顺序与文件清单

先完成前置架构收敛，再按以下六个可独立审阅的单元推进；本轮只完成计划，均未开工。结构和接口按目标模型定义，不再另选 stage/schema。

| 单元 | 工作与交付 | 进入下一单元的条件 |
| --- | --- | --- |
| P0 固定基线 | 保存 S8 历史基线及前置架构验收版本的 binary/IR/C++/RTL/trace 哈希、实现版本/差异，扩展结构审计；建立独立目录和 Make target | 两份基线不覆盖；S9 增量比较使用前置验收版本；可区分合法 pack 与四类遗漏 |
| P1 访问计划最小闭环 | 在已有 CpuValuePlan/fallback 上注册数组规划 pass，接通 ReadValue/Regroup/PackedOnce/常量 proof；先打通 replayCause 对应写入 | JSON/verifier/分块联动可用；非零分组、mask、别名和 reset 测试通过；机器码无循环内整表打包 |
| P2 内部数组视图 | 注册 array-normalize，接入 whole/phase 固定点；迁移 S8 专属规则，覆盖内部使用和真实 flat 共消费者 | 审计中 UInt9[8]/UInt8[7] 视图链消失；幂等、phase、used-bits 回归通过 |
| P3 对齐切片 | 静态范围保形、可证明的动态子数组；增加 Slice recipe 规划和越界/偏移证明 | UInt2[16]→UInt2[8]、UInt9[4,8]→UInt9[8] 直接消费元素；未对齐负例保留 |
| P4 二维块操作 | repeat/concat 保形、紧凑 recipe、跨 chunk 数组物化和复用 | 160×8/512×8 路径无整表整数往返；不展开大图；小 helper/TU 执行通过 |
| P5 收口验收 | 回归、原 SV 重生 ROB、全输出无排除新旧对照、正式同 trace A/B、机器码与 perf | §7 门禁全满足，记录收益与剩余合法转换，再更新为已实施 |

CPU plan 骨架、fallback、JSON 和共同消费接口属于前置 R3；P1 在此闭环上实现数组规划，不先堆 ROB 专用 emitter 特判。P2–P4 逐步增加语义规则和 recipe；常量清零不可替代通用分组验收。

| 范围 | 主要改动入口（新增文件为计划） |
| --- | --- |
| 新语义 pass | 公共数组规范化规则放 `wolvrix/include/ir/`、`lib/ir/`；`grhsim/pass/array_normalize.*` 为源图/CPU图适配与注册、选项、诊断入口 |
| 固定点与既有 pass | `pass/simplify.cpp`、`simplify_internal.*`、`canonicalize_compute.cpp`、`const_fold.cpp`、`used_bits.cpp`；审计 comb-pack / pack-bit-registers，防止重新制造无用 flat 包装 |
| CPU 值计划扩展 | `wolvrix/lib/grhsim/backend/cpu_array_access.cpp`；定义使用前置新建的 `include/grhsim/backend/cpu_plan.hpp`，不回填通用 model.hpp |
| CPU planning/emit | `backend/cpu.cpp`、分区/激活/写/value/codegen planner 与 `cpu_phase_emit.cpp`；共用 cost 和 recipe，CPU2 clone 保形，CPU5–CPU7 消费同一计划 |
| 持久化和实体维护 | 前置新建的 `io/cpu_st_json.*`、CPU本地ID重映射、artifact verifier；不得保存不可重建的进程内缓存 |
| 标准入口 | `scripts/wolvrix_xs_grhsim_ir.py` 的源图/CPU管线；`scripts/reemit_grhsim_ir.py` 及 XS/HDLBits/ROB 使用者；不能只接入 ROB 实验脚本 |
| 测试和构建 | `wolvrix/tests/grhsim/` 新 pass/CPU fixture，现有 simplify/phase/store/emit suite，CMake 注册与项目 Make targets 同步 |
| 审计和 A/B | `testcase/xs-components/rob.mk`、相邻 scripts；新工作目录 `ptmp/xs-components-rob-array-normalize/`，与 S8 证据隔离 |

实施时同步正式文档：`wolvrix/docs/grhsim_ir/passes/` 的新 pass 文档及 simplify/canonicalize/const-fold/used-bits，`backends/cpu.md`、`flows/cpu-st.md`、mapping/JSON 规范及 pass 总览。规范须定义 operand role、recipe 参数、位序和例子；本计划不替代正式规范。

## 7. 验证门禁与豁免

### 7.1 小模型与负例

| 类别 | 必须覆盖 |
| --- | --- |
| 类型/视图 | u9[8]、u8[7]、singleton、多维、长链；混合 flat/array 消费；截断、扩展、不同 signedness/domain 和未知参数拒绝；二次运行无变化 |
| 构造/顺序 | 非对称 11/22/33/44、arrayCreate 与 MSB-first concat 顺序；新增维与沿原维拼接不能混淆 |
| 分组 | u1[352,11]→u11[352]，每行不同的非零值；反向拆分；跨源元素边界、非整字叶宽、>64-bit 目标元素；全零证明的正例和 boundary 可能非零的负例 |
| 切片/OOB | 静态前后半段、非零起点、多维子数组、动态 0/末项/越界；索引乘法截断/溢出、部分越界和未对齐片段；与原 CPU packed 语义对照 |
| repeat/concat | 子数组重复、不同外维长度拼接、异宽真实位拼接负例、多消费者；动态选 body/pad 两段，首尾和越界 |
| 状态/快照 | SmallSink 与 LargeSink；enable 为假、event-free、多 writer 后声明覆盖、mask、重叠源目标、变化检测、reader 激活和收敛 |
| 采样/分块 | 同一随机/DPI 结果重复引用但只执行一次；跨 phase/boundary 快照；强制小 helper/TU，frame 可见性与较大数组执行 |
| 基础设施 | semantic/core verifier、mapping 缺失/篡改/过期负例、copy/compact/JSON roundtrip、旧 schema 拒绝、UBSan；四态 X/Z 保留及 CPU aggregate 明确拒绝 |

功能检查必须执行生成的模型并对照期望值/旧 packed 路径，不能只有 C++ 文本匹配。结构断言只用于证明没有再次走整表打包、重复求值或大图展开。

### 7.2 IR、C++、机器码三层结构门禁

1. IR：可规范化的同型往返不再被内部数组使用依赖；对齐切片、repeat/concat 保形。真实 flat 共消费者仍合法，origin/declProvenance 不因优化失真。
2. C++：四类目标路径按元素/块处理，packed fallback 在目标行循环外；没有大型按值返回数组 helper、循环内整表 lambda 或无用打包 producer。520 元素的 S8 输出保持直接数组路径。
3. binary：按源字段和数据流定位函数，确认 replayCause 没有“外层352×内层3872”的整表打包；其他目标无对应的巨型整数重建链。函数编号、ValueId、编译器生成的循环形式可以变化，不能硬编码成验收条件。

所有保留转换列出 consumer、类型、原因和估算工作量；未覆盖的新情况登记到报告，不以“pack 个数不为零”直接判失败或判完成。

### 7.3 ROB 正确性与性能

新候选必须从固定的 `preserve-aggregate=all` 原始 SV 和完整 ROB 子模块闭包重新 ingest，不用旧优化后 checkpoint 代替前端验收。P0 记录原始 manifest 和模型哈希。

固定输入和比较口径：

- trace：`ptmp/xs-components-rob/trace/rob_trace.bin`；SHA256 `cf8035e21cde579dbcf9ee0abced4f1b4c5d5c66260c9369689c225de83fddb1`。
- 100050 条记录、52 条 reset，真实 CoreMark 100k 周期窗口；每周期输入 5245 个 u64，输出 5491 个 u64。不得描述成程序完整退出。
- **历史总基线是 S8 candidate**：`ptmp/xs-components-rob-array-create/candidate/`；binary SHA256 `7bba7a8056764b758d368fac1b7be28e10a15a05caec3c26e0cc761acb7ba771`。前置架构若有代码改动，先单独对照 S8 验收；**S9 两个 pass 的直接基线为前置验收版本**，由 P0 固定。S8 之前的 54.228s 不能用于计算 S9 增量收益。
- 新旧 GrhSIM 比较每周期全部输出，排除数为 0。S8 dump SHA256 `688ac2f6e9c5509eb00dad368ead600a07ec27d956b1ec9a429d8e46309a7df1`；保留低相求值后、上升沿前采集的时序。
- gsim/GrhSIM/trace 继续现有严格比较，历史排除不扩张；该检查不能表述为三者全输出完全一致。

正式速度在相同 CPU 0 / Ryzen 7950X3D / Clang 22.1.2 / -O3 / 无 PGO 下，每侧预热1轮、测量3轮，并复测 gsim。固定同一驱动、输入、采样/checksum 和计时边界；构建、dump、perf 不与计时混跑。

S8 历史 min 为 45683.073 ms、median 为 45720.394 ms，同批 gsim min 为 10905.952 ms。先记录 S8→前置架构版本，再用同批重测的前置版本与数组优化候选计算 S9 增量 min/median、耗时减少比例和相对 gsim 的耗时比；不能将不同批次单次时间拼成结论或把前置收益归到两个数组 pass。checksum 应为 `0x048c94f0d417ffac`。

完整回放含 reset 的结果为正式主表。若增加稳态窗口，必须先实际执行原 reset/前缀使模型到达相同状态，再只计相同后缀；不能删除 reset 记录后从新模型直接运行。两种窗口分别报告，perf 单独采集并校验 binary 哈希。

完成门槛为功能与结构全部通过、完整回放无可重复的性能回退；若改善落在测量波动内，增加成对测量并如实标为未证实加速。收益量级必须由测量给出，不以 5.6005% 采样值设定加速承诺。

### 7.4 Make 入口与豁免登记

既有入口继续使用 `make test_wolvrix`、`test_array_create`、`test_array_create_cpu`、`run_all_hdlbits_grhsim_ir_tests`、`run_xs_bugcase_grhsim`、`check_sim_refactor_baseline`。S8 的 67/67、162/162、27/27、162/162 是历史快照，S9 必须重新运行，不能继承为本阶段结果。

实施时计划新增 `test_array_normalize`、`test_cpu_array_access`，以及 ROB 的 `rob-array-normalize-{build,run,audit,profile}` Make targets；定义后才可使用。可复用 S8 驱动，但必须支持 S8 历史基线和前置验收基线的显式选择，并固定单独的 S9 目录，不能默认比较 S8 之前的模型。

所有 build/test/install/Python workflow 均经项目 Makefile，缺 target 时先补 target；命令日志和临时产物统一放 `ptmp/`。本轮仅文档检查，不运行这些尚未实现的门禁。

- 豁免：**0**。不新增功能失败或输出比较排除项。
- 兼容性：checkpoint 的结构/版本与重生策略按目标模型 §13，详见 §8。
- S7 的精确计数和整机性能门槛继续独立跟踪，ROB 的 S9 通过不能替代 S7。

## 8. 兼容性、风险与回退

- 前置采用 v4 容器与 cpu.st.artifact.v1，不让旧 cpu.st.v1 mapping 被误当成完整新访问计划。最终验收从 SV 重生；semantic-only checkpoint 不含 CPU 产物，不能直接交给 emitter 或静默补空计划。
- 访问计划绑定语义 revision 及相关分区/布局；依赖变化后失效重建。避免为弥补职责放置错误而在已完成计划后再次修改语义、反复全流程规划。
- 首批采用保守的 boundary/alias/offset 证明；不能证明时保留一次正确 packed 快照，并输出理由。合法 fallback 不豁免循环内反复打包问题。
- 新表示可能增加源快照或 frame 空间，需记录 scratch、生成代码体积、构建耗时与运行 RSS；避免用无界 scalar 展开换取少量运行时间。
- 按 P1–P4 逐单元验证和审阅，出现回归定位对应 recipe/规则。调试禁用仍须生成有完整 fallback recipe 的有效 CpuStArtifact，不能伪造完成或让 emitter 使用隐藏旧路径。

## 9. 已定功能与接口、待测参数

| 项目 | 本计划决定 |
| --- | --- |
| 是否继续新增语义 op | 本阶段先复用 arrayCreate、带 shape 的 slice/replicate/concat；不新增 arrayConcat/pack/unpack |
| 是否给四个问题各建一个 pass | 两个 pass 按语义与 CPU 映射分工，模式作为规则/recipe 扩展 |
| CPU 访问规划位置 | CPU4 更新同一 CpuValuePlan，先于 CPU5函数/CPU6frame/CPU7TU；无新 stage 枚举 |
| 是否只优化 ROB | 模式只依赖类型、位布局、scope 与访问语义；名字、固定宽度、ValueId 不作匹配条件 |
| 最先修什么 | replayCause 通用重新分组和 packed-once 保护，再内部视图、切片、二维块操作 |
| 尚需实测确定 | 数组借用/物化的代价阈值、最坏 scratch 与编译时间、完整回放和稳态的实际收益；不阻塞上述语义设计 |
| 优先前置事项 | 共享定义、独立 CpuProgram、typed CPU plans、删除 task/mapping 壳，按目标模型 R1–R4 实施 |

实施进度回填 [PROGRESS.md](PROGRESS.md)，新测量另建 `pdocs/rob_standalone/` 报告并链接；本文在验收前保持“未开始/进行中”，不预填通过结果。
