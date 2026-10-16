# Xiangshan Mux1H 与 maskedOr 覆盖审计

本文保留首版匹配器的基线。后续修复已将恢复区域扩展到 4,217 个，并覆盖本文
3,440 个结构候选的全部；详见 [匹配扩展与验证](20261016-cpu-masked-or-matching.md)。

2026-10-16。按用户要求暂停整机性能测试，复用现有 Chisel、FIRRTL、SV 和 IR
进行静态审计，没有重新 elaborate 或运行仿真。

**首版恢复范围很窄：220 个 IR 区域全部来自 TLBStorage.scala:151/152 的
perm/g_perm 两处 Mux1H。在当前 FIRRTL 有 16～64 项展开的 72 处源码调用中，
只覆盖了这 2 处。C++ 布尔长链 2108 → 1892 不能代表全局 Mux1H 覆盖率。**

## 输入与计数单位

- Chisel：`testcase/xiangshan/`，根据 `build.mill` 区分生产源码与其他副本。
- FIRRTL：`build/xs/rtl-aggr/rtl/SimTop.fir`，现存的 1.6 GB 展开产物。
- IR：`build/xs/grhsim-ir-aggr-global-enhanced/xiangshan_grhsim_ir.json`，
  5,035,938 ops，已完成 phase 划分。
- 已恢复区域：`ptmp/masked-or-xs/masked-or.tsv`。

计数单位不同，不能直接相除：

1. **源码调用点**：一个 Scala 的 Mux1H 表达式，循环、参数、模块实例会重复展开它。
2. **FIRRTL 选择器展开**：一次非退化 Mux1H；聚合结果的 wire 及子 wire 归为一次。
3. **FIRRTL 字段规约树**：Bundle/Vec 展开后的 ground field 各算一棵树。
   每个字段可以有多位，不是每 bit 一棵树。
4. **IR 区域**：经过 CIRCT、ingest、优化、去重和 phase 拆分后的 OR 区域。
   重复输出可能合并，Event/General 又可能复制同一逻辑。

FIRRTL 中 10,008 个模块定义均从 SimTop 可达，实例权重均为 1，
所以实例加权数量与模块定义内数量相同。优化前 FIRRTL 字段数与最终 IR 区域数
不构成可以直接计算覆盖率的同一个总体。

## Chisel 全局调用点

词法扫描排除字符串、行注释、嵌套块注释、import 和函数定义，支持跨行调用。
名字中包含 Mux1H 的其他标识符不算调用。

| build.mill 生产源码组件 | 源码调用点 | FIRRTL 有非退化展开的调用点 |
| --- | ---: | ---: |
| Xiangshan 自身 src/main/scala | 368 | 331 |
| yunsuan | 587 | 433 |
| Rocket Chip 主源码 | 67 | 9 |
| utility | 18 | 10 |
| huancun | 9 | 7 |
| coupledL2 | 5 | 0 |
| difftest | 1 | 0 |
| 其余生产源码根目录 | 0 | 0 |
| **合计** | **1,055** | **790** |

整个目录包含测试和多份嵌套依赖副本，共有 2,423 处调用，不适合作为本次
SimTop 的分母。未出现非退化展开的调用可能受配置、Scala 分支或退化处理影响，
不能一律当作恢复器漏匹配。

有 792 处调用的源码跨度内出现过 FIRRTL annotation，其中 790 处具有
Mux1H 自身的精确调用位置和完整选择树，统计采用后者。精确到列的匹配避免把
参数表达式内部的普通 mux 误算为 Mux1H；SInt、UInt、Bundle、Vec 以及结果的
bits/asUInt/asSInt 转换均已计入。

## 实际展开规模与长度

识别到 **16,416 次非退化 Mux1H 展开、144,688 棵字段规约树**。
所有具有精确 Mux1H annotation 的调用点均识别到了选择树。

| N，选择项数 | 选择器展开次数 |
| --- | ---: |
| 2～7 | 9,646 |
| 8～15 | 5,276 |
| 16～31 | 1,049 |
| 32～64 | 393 |
| >64 | 52 |
| **合计** | **16,416** |

90.9% 的展开少于 16 项，受当前默认 min-terms=16 限制。但长选择器仍有
**1,494 次**；其中 **1,442 次为 16～64 项**，对应
**4,690 棵字段规约树、72 处源码调用**。全部 N>=16 的源码调用有 78 处。
最大 N=352。

部分未覆盖来源，以下均为优化前 FIRRTL 的 N>=16 展开数：

| 源码调用 | 长选择器展开 | 字段规约树 |
| --- | ---: | ---: |
| Rob.scala:1044，writebackNums | 352 | 352 |
| utility/DataModuleTemplate.scala:193，addr_dec/data | 324 | 456 |
| BypassNetwork.scala:210/211 | 318 | 318 |
| StdFreeList.scala:68 | 36 | 36 |
| utility/FastArbiter.scala:57 | 20 | 388 |
| Rab.scala:166/167/168，renameBufferEntries | 20 | 200 |

完整调用列表、各处 N 分布和展开次数在 `call-coverage.csv`。
ParallelMux 等其他名字的等价规约不属于上述 Mux1H 调用点数；
下文 IR 结构扫描不依赖源码函数名。

## 220 个恢复区域的来源

全部是 **N=48、W=1**，仅来自：

```scala
resp.bits.perm(d)   := Mux1H(hitVecReg zip perm)  // TLBStorage.scala:151
resp.bits.g_perm(d) := Mux1H(hitVecReg zip gPerm) // TLBStorage.scala:152
```

每个权限 Bundle 含 pf/af/v/d/a/g/u/x/w/r 十个 bool 字段。
恢复结果引用四组 TLB 的 80 个不同字段数组：

| 实例 | FIRRTL 权限 Mux1H 展开 | FIRRTL 权限字段树 | General IR 区域 | Event IR 区域 |
| --- | ---: | ---: | ---: | ---: |
| ITLB，TLBFA | 2 | 20 | 20 | 20 |
| load DTLB，TLBFA_1 | 16 | 160 | 80 | 0 |
| store DTLB，TLBFA_2 | 4 | 40 | 40 | 0 |
| prefetch DTLB，TLBFA_3 | 12 | 120 | 60 | 0 |
| **合计** | **34** | **340** | **200** | **20** |

load/prefetch 的重复输出在后续阶段合并，ITLB 权限在 Event 和 General 各有一份。
General 中不同 mask 的数量分别为 1/4/2/3，因此
`20 × (1+4+2+3) = 200`，另加 Event 的 20。
审计器重新匹配的 220 个根 op ID 与 pass TSV 完全一致。

当前源码调用点覆盖是 **2/72，约 2.8%**。这个比例不表示运行时间覆盖或性能收益。

## IR 中的候选池和拒绝原因

沿用恢复器的 phase、类型、single-use 和 provenance 边界，扫描最大 OR 树：

| 指标 | 数量 |
| --- | ---: |
| W<=64 的候选 OR 根 | 277,101 |
| N>=16 的最大 OR 树，所有标量位宽 | 4,758 |
| 上一行中的 W=1 树 | 2,990 |
| N>=16，叶子全为 AND 或 zero-else mux/bitSelect | 4,081 |
| 上一行中的 16<=N<=64 且 W<=64 | 3,440 |
| 恢复成功 | 220 |

3,440 是结构候选池，并非已证明合法的 Mux1H 数量：任意两个 bool 的 AND
也满足叶子形状，不同规约也可能合并成一棵树。220/3,440=6.4% 只能描述
这个候选池的接受率。

对 3,440 棵树按首个阻碍互斥分类：

| 首个阻碍 | 数量 |
| --- | ---: |
| selector 不是 packed mask 的 sliceStatic | 1,276 |
| mask 类型/shape/范围不满足契约 | 238 |
| data 不是直接数组元素 | 648 |
| 各项来自不同 mask/array 身份 | 704 |
| mask bit 与数组元素索引不相同 | 332 |
| 数组维数/大小不满足契约 | 14 |
| 多位 AND 的 mask 不是 replicate(bit,W) | 8 |
| 成功 | 220 |

这是“首个阻碍”，一次规范化还可能遇到下一项约束，拒绝数不能直接当作可新增融合数。
部分拒绝是保留不同来源和观察边界所需的行为。4,758 棵长 OR 树中另有 759 棵
超过 64 项，它们也不全是 Mux1H；Event/General/Output 分别有 25/4,729/4 棵。

### TLB 的多位字段为何漏掉

TLBStorage.scala:149/150/153 的 pbmt/g_pbmt/s2xlate 都是 48×2-bit
直接 mask/array 选择。以 ITLB s2xlate 为例，实际叶子是：

```text
replicate(rep=1,
  mux(sliceStatic(hitVecReg, i, i),
      readArray(entries.s2xlate, i),
      2'b0))
```

最终 OR 的类型为 `core.logic<width=2, shape=[1]>`，前缀 OR 的 shape 为 []。
当前匹配器要求直接 mux/AND 叶子、scalar 结果、相同的精确类型，因此 scalar
前缀表现为 47 项，完整 48 项的最终根又因 shape 被排除。
对应前缀根 op 为 723042、最终根为 723043，已与 JSON 和
SV `TLBFA.sv:3478` 核对。这是首版对实际规范化形式的覆盖缺口。
PPN 还有逐项 genPPN 运算，剥离 wrapper 后仍不满足直接数组元素条件。

### 其他结构差异

- Rob.scala:228 的 shiftBank 是轮转视图。例如根 1066644 的 mask[0]
  对应 bank[1]、mask[1] 对应 bank[2]，不满足当前强制 i==row 的规则。
- 部分 issue queue selector 经 assign 保留 shape=[1]，总位宽虽然为 16，
  仍不满足 scalar mask 契约；数据还可能来自各 entry 的独立 state。
- Rob.sv:328081 的一棵 16 项 bool OR 合并了多个 mask/array 来源；
  最大根失败不代表内部没有可恢复子区域，也不允许直接混合来源。
- RAB 的 N=352 等结构超过 64-bit mask 接口，需要进一步考虑分段视图。

## 后续改进顺序

1. 规范化位布局相同的 rep=1、assign、singleton shape，在观察点允许的范围内
   透过转换，保留语义类型和 phase。先补齐同 TLB 的 2-bit 字段。
2. 穿过 concat/assign/sliceArray 等视图恢复 mask/array 来源，识别 bank、
   字段、静态偏移/轮转/置换，并评估独立 bool selector 的打包成本。
   不应为匹配 op 而在热路径搬运整份临时数组。
3. 最大根失败时寻找仍满足最小规模的完整子规约，保留共享/provenance 边界。
4. 再按 RAB/free-list 的实际形态扩展 N>64，定义分段扫描和代价模型。

后续同时报告源码调用点、FIRRTL 的 N/字段展开、IR 匹配与拒绝原因和规约项数，
再用相同流程的 baseline 做整机 A/B；静态数量不能替代动态成本。

## 复现与验证

按仓库要求先加载 env.sh，通过 Makefile 运行：

```sh
make test_xs_mux1h_census
make analyze_xs_mux1h
make analyze_grhsim_masked_or_coverage
```

- `scripts/xiangshan_mux1h_census.py`：源码词法扫描、精确源位置匹配、
  FIRRTL 规约树/聚合结果归并、SimTop 可达性和实例加权。
- `scripts/grhsim_masked_or_coverage.py`：匹配契约审计、拒绝分类、
  TSV 根 ID 全量校验、原始操作图样本。
- 3 个回归用例通过，包含跨行/嵌套调用、注释排除、聚合归并、实例权重、
  SInt/UInt/cast/bit 提取和参数内部 mux 排除。
- 数据：`ptmp/mux1h-census/` 下的 summary.json、source-calls.csv、
  call-coverage.csv、fir-expansions.csv、fir-trees.csv、ir-long-roots.csv、
  ir-coverage.json。输出路径由 XS_MUX1H_CENSUS_OUTPUT 指定。
- 日志：`ptmp/mux1h-census.log`、`ptmp/mux1h-ir-coverage.log`、
  `ptmp/mux1h-census-tests.log`。

本轮统计现有 FIRRTL 中保留精确 Chisel 位置信息的直接 Mux1H 展开；
在 Scala/Chisel 阶段已经退化为连线的调用不算非退化选择器。
