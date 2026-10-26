# Stage 08 — GRH / GrhSIM 数组构造 op 实施计划

- 日期：2026-10-23。
- 状态：已实施、验收通过，工作树未提交。完整回归、ROB 全输出对照及三轮 A/B 已完成，回放耗时降低 15.76%；记录见 §10 与 [实测报告](../rob_standalone/20261023-040804-rob-array-create-ab.md)。
- 决策：GRH 新增 `kArrayCreate`，GrhSIM IR 新增 `core.compute.arrayCreate`，两者一对一承接；数组构造保留到 CPU 后端按元素发射。
- 目标案例：`testcase/xs-components/rob` 的 aggregate-all RTL，重点检查 `io_diffCommits.info` 的 `pdest`、`rfWen`、`fpWen` 等数组输出。

§1 保留实施前的固定基线证据；§2–8 是设计与门禁约定，实施结果和兼容性边界见 §10。S8 完成不改变 S7 的整机验收状态。

后续 [S9 数组规范化与 CPU 访问映射计划](stage-09-array-normalize-mapping.md) 覆盖全量审计发现的内部视图、不同叶宽分组、切片和二维重复/拼接；当前仅完成规划，不将 S8 的目标输出验收扩展为“全部数组往返均已消除”。

## 1. 问题与证据

### 1.1 concat 的来源

ROB 原始 Chisel 对输出数组逐元素连接。简化后为：

```scala
for (i <- 0 until 520) {
    out.info(i) := renameBufferEntries(index(i)).info
}
```

源代码见 `testcase/xiangshan/src/main/scala/xiangshan/backend/rob/Rab.scala:289`；对应 FIRRTL 的第 0、1 项连接见 `testcase/xs-components/rob/Rob.fir:151737`、`:151756`。

firtool 的 `--preserve-aggregate=all` 输出仍保留数组声明，但使用 SV 位拼接语法组装整个 packed 数组。`testcase/xs-components/rob/rtl/RenameBuffer.sv:47098` 的代码简化后为：

```systemverilog
// 实际声明是包含 ldest、pdest、rfWen 等字段的 packed struct 数组。
_GEN_716 = {entry519.info, entry518.info, ..., entry0.info};
```

因此 concat 已存在于输入 SV；它表达元素的位排列，不要求软件仿真器实际物化一个巨型整数。

Wolvrix 在 `lib/core/ingest.cpp` 的 `lowerStructRhsFieldWise` / `concatPerLeaf` 中按字段拆分结构体，将上述表达变成每个字段各自的 concat。当前 `pdest` 的 GRH 快照为：

```text
%flat = kConcat(%pdest519, ..., %pdest0)
        width=4160, shape=[]
%arr  = kAssignAs(%flat)
        width=4160, shape=[520]       // 元素宽 4160/520 = 8
```

证据：`ptmp/xs-components-rob/emit_flat_grh.json` 中 `_op_2556304` 产生扁平 `_val_3825003`，`_op_2556305` 再产生带 shape 的 `rab$_GEN_716__DOT__pdest`，源位置均为 `RenameBuffer.sv:47099`。

GrhSIM 快照继续保留该结构：`core.compute.concat` 的结果 `v673652` 为扁平 4160 位，随后 `core.compute.assign` 的结果 `v673653` 带 `shape=[520]`。GRH 的类型重解释在这里映射为 GrhSIM 的 `assign`。

CPU 发射再把数组别名接回扁平值，生成实际的 `_BitInt(4160)` 拼接，并逐项移位写输出。证据见 `ptmp/xs-components-rob/grhsim-model/grhsim_Rob_tu368.cpp:3540`、`:4064`。

### 1.2 当前语义缺口

[GRH 规范](../../wolvrix/docs/grh/grh-ir.md)定义 `kConcat` 为位拼接：操作数可不同宽，第一个操作数占高位。规范另有“同形操作数可推导数组 shape”的惯例，但它不是 verifier 约束。类型系统能够表达数组，数组构造过程却没有独立、强制的类型契约。

因此，以下步骤当前都可以合法发生：

```text
同型元素 → 扁平位拼接 → 数组类型重解释 → 打包值读取 → 逐元素提取
```

`lib/grhsim/backend/cpu_phase_emit.cpp` 的通用 `read()` 会对部分已有数组存储调用 `packStoreRows`；`emitOutputWrite()` 的 shaped 输出路径又通过打包值逐行提取。已有 `directShapedExpression`、`directConcatRows` 优化仅覆盖部分情况。

修复需要同时明确数组构造语义并贯通消费路径；仅增加 op 注册、仅传播 shape，或仅改最后的输出循环，都不构成本计划的完成条件。

### 1.3 性能证据的范围

当前同一 ROB 二进制、真实 CoreMark trace 的采样中，`pOutput_c64` 占用户周期约 10.41%，全部 `pOutput*` 约 17.81%；该函数包含上述 `pdest` 和布尔数组的拼接、拆分，热点指令包括大栈临时值的存储。

这些是整个函数的独占采样占比，不是单独转换表达式的精确耗时，也不是预期可回收的加速比例。原始证据在 `ptmp/xs-components-rob/exceptionvec-profile-20261023/summary.md`。

正式速度基线见[ROB aggregate CoreMark 100k 报告](../rob_standalone/rob-aggregate-coremark100k-20261022.md)：gsim 最小耗时 11246.826 ms，GrhSIM 54147.767 ms，耗时比 4.814。新增 op 的收益必须另做同输入 A/B。

## 2. 设计范围

本阶段增加“同型值组成新数组”的操作，保留现有 `width + shape` 类型系统、数组 SSA、状态读写和仿真阶段语义。`kArrayCreate` 是纯组合值构造，不是内存分配或状态写操作。

实施必须覆盖 GRH、ingest、GRH 变换与 SV 发射、GRH→GrhSIM、GrhSIM 变换与持久化、CPU mapping 和 C++ 发射。当前既有的按位运算仍可使用带 shape 值的扁平位解释。

本阶段保留 `kConcat` 的现有合法用法，包括既有 shaped concat；不把它收紧为“结果必须无 shape”。也不把任意同宽 concat 自动解释为数组。数组构造的选择依据来自源类型或已经明确的目标数组几何。

本阶段不新增数组沿已有维度连接的 `arrayConcat`，不新增独立 pack/unpack op，也不改变 `exceptionVec` 的现有存储类型。真正需要位向量的消费者继续使用现有显式类型重解释和打包路径；宽元素仍沿用 `_BitInt`。

## 3. 新 op 的完整语义

### 3.1 两层 IR 的对应

| 项目 | GRH | GrhSIM IR |
| --- | --- | --- |
| 名称 | `kArrayCreate` | `core.compute.arrayCreate` |
| operands | `%e0, %e1, ..., %eN-1` | 相同顺序的 value operands |
| results | 一个数组 value | 一个数组 value |
| 属性 / parameters | 无 | 无 |
| object refs | 不适用 | 无 |
| 副作用 | 无；只使用输入 value | 无；不访问 I/O、state 或外部函数 |

`N >= 1`。每个操作数必须具有相同完整类型：`Logic`、相同总位宽 `W`、相同 signedness、相同 shape `S`；GrhSIM 还要求相同 logic domain。

结果类型由操作数唯一确定：

```text
width  = N * W
shape  = [N] + S
signed = 操作数的 signedness
domain = 操作数的 domain         // GrhSIM
```

`shape` 写在结果类型中，不再增加一份 op 属性。构造器推导结果类型，verifier 对载入或手工构造的模型独立复核。位宽乘积、维度乘积及 `N` 的表示范围必须检查溢出，并遵守各层 IR 的位宽上限。

只构造 Logic 数组，沿用当前 Real/String 不数组化的限制。IR 语义允许两态和四态 Logic；CPU 后端对四态 aggregate 继续明确报告不支持，不能静默转为两态。

### 3.2 顺序与位布局

第 `i` 个操作数成为结果的第 `i` 个外层元素或子数组：

```text
result[i] = operand[i]
```

沿用当前规范化数组的行主序和低下标对应低位的规则。令 `flat(x)` 表示 x 的逻辑位排列，则：

```text
flat(result)[i*W +: W] = flat(operand[i])
```

所以只比较位内容时：

```text
arrayCreate(e0, e1, ..., eN-1)
等价于 concat(eN-1, ..., e1, e0) 的数组解释。
```

这不是主机内存字节序约定。逐元素实现不依赖主机大小端；只有使用对象字节镜像复制的优化需要额外检查布局。

示例：

```text
a0=8'h11, a1=8'h22, a2=8'h33, a3=8'h44
arr = arrayCreate(a0,a1,a2,a3)
arr 的 shape=[4]，元素依次为 11、22、33、44
flat(arr) = 32'h44332211
```

### 3.3 多维、单元素及类型转换

```text
a、b：width=24, shape=[3]，元素宽8
arrayCreate(a,b)：width=48, shape=[2,3]

a：width=8, shape=[]
arrayCreate(a)：width=8, shape=[1]    // 增加的维度不能作为恒等式删除
```

新 op 不隐式补位、截断、改变 signedness 或重新划分内层 shape。需要调整元素类型时在构造前显式转换；若 SV 目标的整体 signedness 不同，保留必要的显式类型重解释。

两个 shape=[3] 的操作数组成 shape=[2,3]，并不组成 shape=[6]。沿已有维度连接和添加外层维度必须保持区别。

## 4. 生产、转换与优化规则

### 4.1 ingest 直接生产

在 `lib/core/ingest.cpp` 中审计以下生产点：

- `lowerStructRhsFieldWise` / `concatPerLeaf`：目标叶子是数组、各部分恰好对应一个外层元素或子数组时，直接创建数组构造；ROB 的 520 个 `info` 元素必须命中。
- 数组 assignment pattern、`concatArrayElements` 和实例连接中的数组组装：能满足同型及目标几何规则时统一使用新 op。
- 真正的位拼接、异宽拼接、packed 布局转换和不满足元素边界的组合继续使用 `kConcat`。

SV `{entry519,...,entry0}` 是 MSB 优先顺序，数组构造使用规范化下标顺序；前端必须将操作数调整为 `entry0,...,entry519`。ascending / descending range 和多维声明沿用现有索引归一化，不能简单按源码文本顺序填数组。

数组结果仍由一个 op 定义。CPU 最终生成多条 store，不意味着 GRH 中创建多个 value 定义。

### 4.2 精确恢复已有模式

在现有规范化入口支持以下可证明的改写，供旧构造路径及变换产物使用：

```text
assignAs(concat(eN-1,...,e0)) → arrayCreate(e0,...,eN-1)
```

必要条件：操作数完整同型；转换前后总宽一致；目标 shape 恰为 `[N]+S`；结果 signedness/domain 满足新 op 契约；没有截断、补位或部分元素重排。

源 concat 若另有真实的扁平消费者，只改写数组这一支；不能把其他消费者的 value 替换为不同 shape。改写及 DCE 在 CPU mapping 之前完成，按现有机制失效并重新生成 mapping。

不以端口名、`pdest` 字段名或 ROB 专用宽度作为识别条件。此次 ROB 验收必须重新 ingest 原始 aggregate SV，不能仅依靠旧 checkpoint 的恢复改写证明前端已修复。

### 4.3 两层 IR 的变换规则

| 变换 | 规则与边界 |
| --- | --- |
| 常量索引读取 | `sliceArray(arrayCreate(e0,...), i)` 可替换为 `ei`；多索引继续在对应子数组上寻址，完整类型必须相符 |
| 动态索引读取 | 保留既有越界语义；降低为数组索引或选择时不重复执行输入值的生产者 |
| 全常量折叠 | 保留结果完整 shape、signedness、domain；四态保留 X/Z；超过折叠预算可原样保留 |
| CSE / 改名 | 键包含 op 种类、完整结果类型、有序 operands；不能与反序 concat 或其他 shape 合并 |
| used-bits / 死代码 | 结果第 `[i*W,(i+1)*W)` 位只映射到第 i 个输入；初期可保守保留所有输入，不能误删活输入 |
| 组合环及位依赖 | 将输出位段映射到对应输入，避免把整个构造作为所有位互相依赖而制造假环 |
| 层次展开及克隆 | 保留 op、shape、operand 顺序和来源信息；克隆不得触发无条件扁平化 |
| 打包相关 pass | 区分数组构造和位拼接；默认保留数组路径，确有整体位运算需求时才在对应分支转换 |

`arrayCreate` 的生产者可能是 state read、随机函数或 DPI 的结果。新 op 自身纯组合不代表这些生产者可重新执行；所有改写必须继续引用那一次已经计算好的 value。

## 5. CPU 后端的数组消费路径

### 5.1 分开“取打包表达式”和“向数组写元素”

在 `cpu_phase_emit.cpp` 增加或整理内部接口，区分下面两种需求。函数名为设计示意，实施时按已有命名风格确定：

```text
packedExpr(value)
    提供整个逻辑值的打包表达式，用于确实需要位向量的消费者。

emitElementsInto(destination, value, expectedGeometry)
    向已有目标写入元素，不先构造总宽整数或返回大型数组临时值。
```

数组消费接口优先处理：

1. `arrayCreate`：逐项使用其 operand，子数组按行复制。
2. 兼容的 row-backed 数组：直接索引、循环或已证明布局兼容的块复制。
3. 可证明的类型视图：沿着视图解析元素来源。
4. 真正的打包值：最后才使用位段提取。

该接口供 shaped 局部值、boundary 发布、数组状态写和 `emitOutputWrite` 共用。不能在数组入口先调用通用 `read()` 再尝试恢复元素。

### 5.2 目标代码与临时值

ROB 的目标代码形态为：

```cpp
this->io_diffCommits__DOT__info__DOT__pdest[0] = pdest0;
this->io_diffCommits__DOT__info__DOT__pdest[1] = pdest1;
// ... 直到519；允许等价循环或分块。
```

元素可以从 scalar local、frame、boundary 或合法的数组索引表达式取得。输出路径没有其他消费者时，不生成整个字段的 `_BitInt(4160)` concat，也不留下未使用的 concat 计算。

数组 value 有多个消费者时，保留一次计算的可复用元素存储。若一个消费者需要数组、另一个需要真实的扁平算术，仅为后者生成打包形式，避免为每个数组消费者重复构造或复制整个值。

宽元素仍按元素使用 `_BitInt(elementWidth)`；不得为了消除打包而引入大型按值返回 `std::array` helper。必要临时存储采用已有局部/frame 或调用方提供的目标缓冲区。

### 5.3 mapping、跨函数和阶段语义

CPU mapping 必须把新 op 作为具有全部输入依赖的纯 compute 处理。函数/TU 体积估算要反映实际元素数或复制量，不能将 520 项构造仅估算成一条普通标量语句。

先确定数组构造、融合及表示所需的依赖，再计算分块和 frame；如果 emit 阶段才决定直接使用某个 operand，必须确认该值在当前 helper 或 frame/boundary 中可见。不可引用另一个函数中已失效的局部变量。

跨相位、sink context 或边界的操作继续消费原有采样值。直接从新时刻的 state 重读来代替旧 value，或者绕过 enable/payload boundary，都不合法。无法直接融合时，物化按元素存储的数组快照作为正确路径。

状态整体写继续保留 enable、mask、变化检测、reader 激活及提交优先级；数组来源和目标可能重叠时先保留正确的源快照，不能让逐项写改变后续项的输入。输出仍在原来的输出阶段更新。

## 6. 文件与基础设施清单

以下为实施审计入口，不表示每个文件都必须增加特判；通用遍历已正确的地方用测试证明即可。

| 范围 | 主要文件 / 工作 |
| --- | --- |
| GRH 定义与持久化 | `include/core/grh.hpp`、`lib/core/grh.cpp`：枚举、名称解析、构造与类型推导；审计 `lib/core/{store,load}.cpp` 的新 op roundtrip |
| GRH 校验 | `lib/transform/verify.cpp`：完整的输入/输出几何检查，带 op 和源位置诊断 |
| ingest | `lib/core/ingest.cpp`：字段拆分、数组 pattern/组装和实例连接生产新 op |
| GRH 变换 | `lib/transform/{const_fold,redundant_elim,comb_loop_elim,hier_flatten,instance_inline}.cpp`：类型、位依赖、克隆及规范化 |
| SV 发射 | `lib/emit/system_verilog.cpp`：按规范下标输出元素赋值或等价合法 SV，不改变次序 |
| 两层 IR 转换 | `lib/grhsim/convert/grh_to_grhsim.cpp`：一对一映射 op，完整保留类型和来源 |
| GrhSIM 注册与校验 | `lib/grhsim/dialect/core.cpp`、`lib/grhsim/ir/verifier.cpp`：注册与强类型契约 |
| GrhSIM 持久化 | `lib/grhsim/io/json.cpp`、`include/grhsim/io/json.hpp`：新 op 及 shape 的 roundtrip 和指纹测试 |
| GrhSIM 变换 | `lib/grhsim/pass/{canonicalize_compute,const_fold,used_bits,comb_pack,pack_bit_registers}.cpp` 及相位/锥提取相关 pass：规则及保守处理 |
| CPU mapping | `lib/grhsim/backend/{cpu_partition,cpu_clone_shared,cpu_layout,cpu_schedule,cpu_emit_plan}.cpp`：依赖、布局、估算和跨 helper 生命周期 |
| C++ 发射 | `lib/grhsim/backend/cpu_phase_emit.cpp`：新 op、目标写入、边界/状态/输出共用数组消费路径 |
| 测试与驱动 | `tests/{grh,ingest,transform,store,emit,grhsim}`、`CMakeLists.txt`、仓库根 `Makefile`、`testcase/xs-components/rob.mk` |

本计划不改变 JSON 容器的字段布局：GrhSIM 保留 `wolvrix.grhsim.v3`，core 方言指纹由当前 `wolvrix.grhsim.core.v2` 更新为 `wolvrix.grhsim.core.v3`。同步 fixture 和指纹校验；旧指纹 checkpoint 按现有验证规则拒绝并重新生成，不静默把未知 op 当成 concat。

GRH 的名称解析与 JSON 要能明确识别 `kArrayCreate`。Python 绑定、图统计和可视化中若有 op 白名单需同步；基于通用字符串/operand 遍历的接口不新增专用 ABI。

同步修订正式规范 `docs/grh/{grh-ir,grh-api,grh-json-spec}.md`、`docs/ingest/aggregate-types.md`、`docs/grhsim_ir/{overview,dialects/core,backends/cpu,flows/cpu-st}.md` 及实际改变规则的 pass 文档。明确数组构造是新的 shape 强校验点，移除将所有构造都交给可选 concat shape 推导的表述。

## 7. 实施顺序与完成条件

| 阶段 | 工作 | 本阶段完成条件 |
| --- | --- | --- |
| P0 基线 | 固定源 SV/FIRRTL、trace、二进制与生成参数，记录当前工作区修改 | 原始基准证据可追溯，后续产物使用独立目录 |
| P1 两层 IR 契约 | 两个新 op、构造器、转换、verifier、JSON 与指纹、规范 | 正例/负例和两层 roundtrip 通过，op 次序与类型契约一致 |
| P2 变换与分析 | 常量/索引/CSE/恢复改写、位依赖、克隆、活性与相位 | 运行现有变换链后无类型丢失、假环或活输入误删 |
| P3 CPU 后端 | 新 op 发射、统一元素写入、布局/分块/frame 和输出路径 | 生成并执行 C++，多 helper/TU 的数组输出及状态写正确，无目标总宽整数往返 |
| P4 前端接通 | ingest 直接生产、SV 发射往返、小型同构案例到 ROB | 从原始 SV 到 C++ 全链路命中新 op，不依赖旧 checkpoint 补救 |
| P5 ROB 验收 | 同 trace 的正确性、源代码/机器码审计、性能 A/B | 结构与行为门禁全过，提交实测收益及范围说明 |

P1–P3 可先用手工模型和测试 fixture 验证；生产管线在消费端就绪后接通。阶段状态不得提前标为整体完成。每阶段先运行相关 Makefile 门禁，发现新的失败再扩大排查范围。

## 8. 验证计划

### 8.1 必要测试

| 层次 | 用例与判定 |
| --- | --- |
| 类型正例 | 1/8/24/96-bit 元素；一维与子数组构造；`N=1` 保留维度；相同 signed 元素；两态/四态 IR |
| 类型负例 | 空 operands、多结果、非 Logic、元素宽/shape/signedness/domain 不同、结果缺 shape、错误外维/内维、位宽溢出 |
| 元素顺序 | 用非对称值如 `11/22/33/44` 验证每项及扁平位图；覆盖 SV ascending/descending、多维及 struct 叶子字段 |
| 优化 | 常量索引接回元素，子数组继续索引，常量折叠完整类型，CSE 不跨 shape；保留真实扁平消费者 |
| 依赖 | 按元素依赖的组合图不制造假环；used-bits/DCE 不删除活输入；动态索引越界沿用现有行为 |
| 持久化 | GRH/GrhSIM 各自 roundtrip，注册名/指纹错误有明确诊断，操作数次序和完整类型不变 |
| 运行语义 | 输出、数组状态写及 boundary；enable/mask/change detection；输入值来自有副作用生产者时只采样一次 |
| 分块 | 强制小 helper/TU，检查 frame 保存及跨边界快照；融合不可见时按元素物化，结果不变 |
| 性能结构 | 520×8-bit、520×1-bit 同构 fixture；C++ 中不为这些数组构造生成总宽 concat 和后续移位拆分 |
| 混合消费者 | 同一构造既供数组输出又供整体位运算，数组路径保持直接，打包仅服务真实需要的分支 |

测试以执行结果和类型/结构契约为主；生成代码检查用于确认目标多余工作确实消失，不钉死局部变量名、helper 编号或无关格式。

### 8.2 Makefile 门禁

所有构建、测试、安装和脚本工作流通过 Makefile。日志和临时文件放仓库 `ptmp/`。已有针对性入口：

```sh
make test_ingest_struct_array_write
make test_grhsim_ir
make test_grhsim_cpu_phases
make test_grhsim_cpu_stores
make test_grhsim_cpu_phase_emit
```

实施时为缺少独立入口的新 GRH/GrhSIM 测试先添加 Makefile target，再调用该 target。功能接通后执行 `make test_wolvrix` 和受影响的 `make run_xs_bugcase_grhsim` 回归；不要手工拼接编译器、CMake、CTest 或 Python 测试命令。

### 8.3 ROB 正确性与性能 A/B

输入固定为已验证的真实 CoreMark 100k trace：

```text
路径：ptmp/xs-components-rob/trace/rob_trace.bin
记录：100050 条，其中 reset 52 条
SHA256：cf8035e21cde579dbcf9ee0abced4f1b4c5d5c66260c9369689c225de83fddb1
现有严格比较 checksum：0x048c94f0d417ffac
```

该输入来自 plain Verilator 整机参考，GrhSIM 使用 aggregate-all ROB SV，gsim 使用对应 FIRRTL；100k 是运行周期窗口，非 CoreMark 运行到退出。沿用正式报告中的观测覆盖和历史排除项，并单独报告排除项失配，不扩大排除范围来获得通过。

已有正确性驱动屏蔽了部分历史输出差异，因此另外增加“旧 GrhSIM 与新 GrhSIM”输出回放比较，覆盖此次改变的全部 520 行 `pdest/rfWen/fpWen` 等字段，包含原先未纳入 gsim 严格比较的行。新旧 GrhSIM 对这些被改动输出必须逐项一致，不能只看原 checksum。

已新增 Makefile 入口 `rob-array-create-ab`，以及独立的 prepare/build/run、全输出 dump、audit 和 profile 入口。复用现有 ROB 构建和回放流程，保证：

1. 基线、候选和日志分目录放在 `ptmp/xs-components-rob-array-create/`；现有正式基准模型、trace 和证据不覆盖。
2. 候选从同一原始 aggregate SV 重新生成，不复用旧 flat GRH；逐项核对输入、布局、参考掩码及编译参数的哈希。
3. 共享 trace 为只读输入，来源清单和 `bench_trace_sources.sha256` 等输出写入各自实验目录。现有 Makefile 路径相互绑定，不能直接复用 trace 目录导致覆盖旧证据。
4. 先跑全部 100050 条记录正确性，再计时。保持 CPU 0、同版本编译器与 `-O3`、无 PGO、相同两相 eval/采样/checksum 规则。
5. 每侧预热一轮，至少测三轮；记录各轮、min、median。正式计时时不并行编译或运行其他重负载。
6. 既比较旧/新 GrhSIM，也复测同条件 gsim 参照。回放计时仍包含驱动与 checksum，不冒充纯 eval 耗时。
7. 审计生成 IR/C++，确认目标字段经数组构造到输出，未留下无用巨型 concat；结合反汇编或 perf 检查大临时值搬运是否减少。
8. 优化后 helper 编号可能变化，按目标字段及来源追踪；不能只查旧 `pOutput_c64` 名称。

性能报告给出实际差值及波动。若没有稳定改善，继续定位元素复制、frame 或调度成本，不能仅以新增 op、代码行减少或历史函数占比作为性能成功证据。

## 9. 最终验收清单

- [x] GRH 和 GrhSIM 均有独立数组构造 op，类型和操作数顺序受 verifier 强制校验。
- [x] 原始 aggregate SV 的同型元素组装能直接生产新 op，多维/单元素/方向规则正确。
- [x] 转换、优化、持久化、克隆及 CPU mapping 保留构造语义和完整依赖。
- [x] 数组局部值、boundary、状态写和输出通过元素路径消费，生命周期与阶段语义不变。
- [x] ROB 目标输出不再物化仅为随后拆分而存在的总宽整数；其他真实位向量运算仍正确。
- [x] 针对性执行测试、相关回归及全部 trace 校验通过；改变的全部数组输出另有新旧 GrhSIM 对照。
- [x] 同输入同条件 A/B、生成产物哈希、结构/机器码证据和性能结果已归档。
- [x] 正式规范、实施状态及实际执行的 Makefile 门禁记录同步更新。

## 10. 实施与验收记录（2026-10-23）

| 阶段 | 已完成工作与证据 |
| --- | --- |
| P0 | 原 binary、trace、RTL、布局及参考 mask 哈希固定，工作树修改预先归档；候选独立目录，从原始 aggregate SV 重新 ingest |
| P1 | 两层新 op、推导构造器与独立 verifier、GRH→GrhSIM、JSON roundtrip、core.v3 指纹及正式规范完成；正负例、溢出与旧指纹拒绝通过 |
| P2 | 完整类型 CSE、常量折叠与 X/Z、常量外层 slice 接回元素、精确 concat 恢复、按位依赖与假环处理完成；真实 flat co-consumer 保留 |
| P3 | `emitElementsInto` 共用元素写入，arrayCreate 逐项写 local/frame，兼容数组来源直接读行；boundary 快照、状态写语义、分块估算和全部 operand 依赖完成 |
| P4 | struct concat、`concatArrayElements`、`lowerArrayPatternValue/Conn` 直接生产新 op；packed 升降序、nested/unpacked pattern、singleton 与 SV 往返顺序测试通过 |
| P5 | 完整 ROB 回放、机器码及 perf、同条件 gsim/旧/新 GrhSIM 三轮 A/B 全部通过；详见[实测报告](../rob_standalone/20261023-040804-rob-array-create-ab.md) |

原始 SV 直接生产 813 个 kArrayCreate，最终 GrhSIM 保留 373 个 arrayCreate。`RenameBuffer.sv:47099` 的 520 项 pdest/rfWen/fpWen 字段直接构造数组，最终输出直接使用其数组 value。候选对应函数没有总宽打包表达式；旧三个字段共处的函数为 77537 字节，新对应三函数合计 2505 字节。

ROB 实测促成两项必要修复：数组输出须沿无损 assign 链继续找到最深同型数组，不能停在第一个 shaped 包装；used-bits 对 arrayCreate/assign 视图以存活标记追踪，使绕过后的无用包装和 packed 生产者可删。只改最后 store 不能消除旧工作量。

CPU 执行测试同时修复并覆盖 shaped sliceArray 子数组越界清零、多个 enable-hoisted 数组写的临时变量作用域、数组输出 dumpState 错用宽整数打印的问题。四种 state/frame/boundary 配置均通过执行和 UBSan。具体覆盖范围包括动态/OOB、掩码与重叠写、宽元素、多 helper/TU、真实 flat 分支和有副作用生产者只采样一次。

门禁均通过 Makefile 执行，日志放 `ptmp/array-create-20261023/`：

| 门禁 | 实际结果 | 日志 |
| --- | --- | --- |
| `test_array_create`、`test_ingest_struct_array_write` | 两层 IR、GRH→SV→ingest、CSE/恢复、原始 pattern 顺序等通过 | `array-order-tests.log` |
| `test_array_create_cpu` | 四种生成模型 + UBSan 通过，27.59 s | `array-final-targeted4.log` |
| `test_wolvrix` | 67/67，94.27 s | `full-final-tests2.log` |
| `run_xs_bugcase_grhsim` | 27/27 | `xs-bugcases.log` |
| `run_all_hdlbits_grhsim_ir_tests` | 162/162 | `hdlbits-and-golden.log` |
| `check_sim_refactor_baseline` | 162/162 黄金 trace 相同 | `hdlbits-and-golden.log` |
| `rob-array-create-build` | 重新 ingest、构建成功，无旧 checkpoint resume | `rob-build3.log` |
| `rob-array-create-run` | 全 100050 周期、5491 输出字，旧/新无排除逐字节一致；三方既定严格校验通过 | `rob-ab.log` |
| `rob-array-create-profile`、`rob-array-create-audit` | 结构/机器码/采样及哈希完整 | `rob-profile.log`、`rob-audit-final.log` |

最小耗时：gsim 10905.952 ms、旧 GrhSIM 54227.731 ms、新 GrhSIM 45683.073 ms；新侧降低 15.76%，中位数降低 15.69%，仍为 gsim 耗时的 4.189×。全部测量轮 checksum 一致。该收益是当前候选管线的净改善，不是单条 op 的精确归因，不推断整机加速比。

兼容性与破坏登记：没有测试豁免；保留既有 shaped concat 和 exceptionVec 存储。JSON 容器保持 v3，core 方言指纹升级至 core.v3，旧 core.v2 checkpoint 明确拒绝并要求重新生成。四态 IR/X/Z 合法，CPU 四态 aggregate 仍明确不支持。正式规范与 PROGRESS/README 已同步；本次改动尚未提交或合入。
