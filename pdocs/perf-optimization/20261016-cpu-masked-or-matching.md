# CPU maskedOr 匹配扩展与香山验证

2026-10-16。依据 [Mux1H 覆盖审计](20261016-xiangshan-mux1h-coverage.md) 修复
恢复器的结构限制。本次匹配修复阶段验证功能、静态覆盖和代码编译。
随后按用户要求完成 [CoreMark 100k 整机 A/B](20261016-cpu-masked-or-coremark100k.md)：
三对运行平均耗时下降 2.962%，六次 difftest 与执行端点一致。

## 结果

复用同一份 5,035,938-op 香山 checkpoint，默认 `min-terms=16`：

| 指标 | 首版 | 修复后 |
| --- | ---: | ---: |
| 恢复区域 | 220 | **4,217** |
| Event / General / Output | 20 / 200 / 0 | **25 / 4,192 / 0** |
| 规约项 | 10,560 | **162,574** |
| N>64 的区域 | 0 | **641** |
| W>64 的区域 | 0 | **27** |
| 清除旧 op | 16,648 | **337,752** |
| 其中 element read | 2,688 | **8,450** |
| 生成 TU | 1,269 | **1,208** |

新区域分布于 **78 个 SV 模块文件**，包括 ROB、RenameBuffer、issue queue、
DataModule、FastArbiter、TLB、TAGE、MissQueue。229 个用 dense 编码，
3,988 个用静态 views 编码。首版的 220 个区域全部保留。

独立审计固定修复前的 **3,440 个 IR 结构候选根**，确认 **3,440/3,440 全部被恢复**。
计入其本身被改写的情况，也计入同宽视图规范化后被更大的恢复区域包含的情况。
这个分母来自旧审计的 `16<=N<=64、W<=64、叶全为 AND/zero-else mux/bitSelect`
候选池，**不是 Chisel 调用点或 FIRRTL 字段树的分母**。不能称为源码 Mux1H 覆盖 100%。

当前宽松类型口径下有 4,842 棵 N>=16 的最大 OR 候选树，恢复 4,217 棵。
剩余 625 棵存在未遮罩叶子或共享/声明观察边界，例如比较结果的普通 OR、
concat/bit slice、reduceOr，以及 false arm 非零的 mux/bitSelect。
它们不能全部直接解释为本 op 的 mask/data 项。

生成 C++ 按原普查口径重新扫描，长度为二元运算节点数：

| >=16 个节点的串行布尔链 | 原模型 | 首版 | 修复后 |
| --- | ---: | ---: | ---: |
| Event | 21 | 1 | **0** |
| General | 2,083 | 1,887 | **632** |
| Output | 4 | 4 | **4** |
| 总计 | 2,108 | 1,892 | **636** |

General 最大剩余长度仍为 128；Output 为 67。IR 规约区域和生成 C++ 的串行链
是不同计数单位，不能拿区域数直接减链数。

## 补齐的结构

- **类型与包装**：透过等宽 assign、rep=1、完整静态切片，允许 signedness 和
  singleton/Vec shape 变化；按位语义一致时不再要求 TypeId 完全相同。
- **静态位视图**：沿 sliceStatic、常量多维 sliceArray/readArray、concat 和
  replicate 子范围恢复实际来源及 packed bit offset。
- **索引和来源**：接受部分覆盖、轮转/任意置换、重复项、多个 mask、独立 selector、
  独立状态及计算结果。无需构造运行时数据 gather 数组。
- **子规约**：一次建树、自底向上判断；外层失败时恢复内部最大有效子树。
  共享和声明观察边界保留原 value，可独立恢复其内部。
- **超过 64 位**：mask 分段为 64-bit words，数据和 accumulator 沿用原生
  `unsigned _BitInt`。无 N<=64/W<=64 的匹配限制。
- **嵌套 AND**：从 `(a & replicate(s,W)) & b` 提取 Boolean mask，把
  `a & b` 保留为同 phase 的数据计算；不丢失共享因子和可观察值。
- **结果截断**：mux/AND 数据 operand 比结果宽时，使用数据的低 W 位；
  不把它误判为位宽不一致。

已知样例均核对原 checkpoint 根 ID：

| 原根 op | 来源 | N / W | 修复点 |
| --- | --- | --- | --- |
| 723043 | TLBFA.sv:3478 | 48 / 2 | rep=1 叶子、最终 shape=[1] |
| 1066644 | Rob.sv:121395 | 44 / 4 | 旋转索引、多维/concat 数据视图 |
| 2737662 | EntriesFaluFmacFcvtFcmpF2v.sv:16112 | 16 / 1 | singleton mask、独立 entry |
| 1272373 | Rob.sv:328081 | 16 / 1 | 混合来源 |
| 483825 等 8 个根 | Tage.sv:10277 等 | 17 / 2 | 广播 mask 在 AND 内层 |
| 4906181 | MissQueue.sv:2584 | 16 / 30 | 50-bit mux 数据截为 30-bit |

RAB 在 FIRRTL 中为 352 项；当前优化后的 IR 在 RenameBuffer 中主要表现为
88 项子规约，此处恢复 640 个区域。真实恢复结果的最大 N 为 112，最大 W 为 512；
352 项未拆分路径由生成程序运行测试覆盖。

## IR 与生成代码

精确接口见 [CPU dialect](../../wolvrix/docs/grhsim_ir/dialects/cpu.md#2-cpucomputemaskedor)
和 [恢复 pass](../../wolvrix/docs/grhsim_ir/passes/recover-masked-or.md)。

Dense 仍是 `maskedOr(mask, array)`。Views 的 operands 是已有 SSA 值，唯一参数
`views` 每四个整数描述 `[selectOperand, selectBit, dataOperand, dataOffset]`。
选择范围为 1 bit，数据范围为 W bits。它允许恢复离散来源，但不在运行时搬运数据
以拼出数组。比如 `[0,0,1,8, 0,2,2,0]` 对应
`(operand[0][0] ? bits(operand[1],8,W) : 0) | (operand[0][2] ? operand[2] : 0)`。

Emitter 按 selector 来源和 word 分组扫描置位 bit。连续数据使用偏移表达式，
置换使用静态 offset 表，不同 SSA 数据用 switch。已有 row-backed 数组直接读行；
无法直接索引时保留 packed/snapshot 路径。计算型数据及离散 selector 的 producer
仍需正常求值；本轮没有消除这部分成本。已有 boundary/frame 快照按原规则保留。

W=1 可在结果为 true 时退出；W>1 合并全部命中项。始终保留零命中为零和
多命中按位 OR，不假定 one-hot。相位和 provenance 边界不跨越。
C1/C2 按 2N-1 估算规约工作，残余数据 AND 单独计费；C6/C8 计入视图展开大小。

## 验证与复现

以下 targets 通过，日志在 `ptmp/masked-or-expanded-regression.log`：

- `make test_grhsim_masked_or`
- `make test_grhsim_ir`
- `make test_grhsim_cpu_phase_emit`
- `make test_grhsim_cpu_phases`
- `make test_grhsim_cpu_stores`
- `make test_grhsim_whole_opt`
- `make test_grhsim_simplify`

最后补齐 TAGE/截断后再次通过专项测试，日志
`ptmp/masked-or-expanded-tests-final.log`：19 组生成程序，每组 1,024 步，使用 UBSan。
包括小规模穷举、零/单/多命中、全零数据、64/65/352 项、65/129-bit 数据、旋转、
多维 concat 的不同内容、多个 mask、独立状态/计算数据、重复 selector、部分覆盖、
有符号广播、嵌套 AND、非零高位截断、General 旧值采样、Output、派生时钟和极小
helper/TU 边界。另含非法视图拒绝、随机 producer 保留、观察/共享前缀、JSON 往返。

完整香山恢复、semantic seal、C1–C8 重映射、C++ 发射和 checkpoint 存储成功：

```sh
make reemit_grhsim_ir \
  GRHSIM_REEMIT_MODEL=build/xs/grhsim-ir-aggr-global-enhanced/xiangshan_grhsim_ir.json \
  GRHSIM_REEMIT_FLOW=ptmp/masked-or-xs-expanded-final GRHSIM_REEMIT_MASKED_OR=1
make analyze_grhsim_masked_or_coverage \
  GRHSIM_MASKED_OR_COVERAGE_REPORT=ptmp/masked-or-xs-expanded-final/masked-or.tsv \
  XS_MUX1H_CENSUS_OUTPUT=ptmp/masked-or-xs-expanded-final/coverage
make analyze_grhsim_bool_chains \
  GRHSIM_BOOL_CHAIN_MODEL=ptmp/masked-or-xs-expanded-final/model \
  GRHSIM_BOOL_CHAIN_OUTPUT=ptmp/masked-or-xs-expanded-final/bool-chains.json \
  GRHSIM_BOOL_CHAIN_CSV=ptmp/masked-or-xs-expanded-final/bool-chains-ge16.csv
```

按仓库要求先 source env.sh；本机使用 `.venv/bin/python`。默认阈值仍为 16，
需要更短规约时可配置为 2；开关默认仍为 0。

审计器独立核对全部 4,217 个恢复区域、4,842 个候选决策及 3,440 个旧候选。
生成 TU18/39/284/373/919 通过模型 Makefile 的 Clang 22 `-O3` 编译，包含
Event、TLB 多位字段、置换/离散数据和 512-bit accumulator。

最终产物：`ptmp/masked-or-xs-expanded-final/` 下的 `masked-or.tsv`、
`masked-or.tsv.candidates.tsv`、`coverage/ir-coverage.json`、`coverage/ir-recovered.csv`、
`bool-chains.json`、生成 C++ 和映射 checkpoint。对应日志均以
`ptmp/masked-or-xs-expanded-final` 为前缀。

以上匹配修复阶段的候选覆盖、链数下降和编译成功只作为进入整机 A/B 的条件。
实际仿真计时见 [CoreMark 100k 报告](20261016-cpu-masked-or-coremark100k.md)；
稀疏程度、分支、缓存、已有数据计算和调度激活都会影响最终收益。
