# GRH IR 多维数组支持重构 — 总览与路线图

- 日期：2026-10-08
- 状态：计划草案（设计已定稿，未实施）；进展跟踪见 [PROGRESS.md](PROGRESS.md)
- 范围：wolvrix（GRH IR、ingest、transform、emit、grhsim IR、CPU 后端、持久化、Python 绑定、文档、测试基础设施）

## 1. 背景与动机

长期以来，无论 GRH IR 还是 GrhSIM IR，数组处理都依赖 **reg-to-mem 这条补救性质的 pass**
（`wolvrix/lib/grhsim/pass/reg_to_mem.cpp`，文档 `wolvrix/docs/grhsim_ir/passes/reg-to-mem.md`）。
它的工作是逆向工程：firtool 在 FIRRTL → SystemVerilog 的 lowering 中把聚合类型（向量、多维数组、
结构体）打散成 `_N` 后缀的标量寄存器族，wolvrix ingest 再把这些标量拼回扁平位向量，最后
reg-to-mem 靠写模式识别（地址译码 guard）和声明名网格把它们重新"猜"回 `core.array` 状态。

这条链路的代价：

- **信息先丢后猜**：维度、边界、元素类型在 firtool 输出里已经没了，reg-to-mem 的恢复是启发式的，
  存在恢复不了或恢复错误的风险面（xs-bugcase CASE_009/021/022 都是这类形态的手写复现）。
- **逻辑展开**：标量化产生海量逐位逻辑，是 P_general 超节点体积和变化检测次数的重要来源
  （对比测量见 `pdocs/perf-optimization/20261005-111210-compare-count-census.md`）。
- **reg-to-mem 是承重墙**：关闭它性能回退 +41%
  （`pdocs/perf-optimization/20261007-040954-reg-to-mem-off-negative.md`），
  但它越重要，说明前端丢信息造成的损失越大。

firtool 提供 `--preserve-aggregate` 选项（取值 `none`/`1d`/`all`，circt 1.x 起可用），
能在输出的 SystemVerilog 中保留 unpacked 数组与结构体。前提是 **wolvrix 的 IR 能承接这些形态**。
本重构的终极目标：直接消费 `firtool --preserve-aggregate=all` 产出的 XiangShan SV，
让 reg-to-mem 完全退休，仿真仍然正确。

## 2. 总目标（逐条映射到阶段）

| # | 目标 | 阶段 |
|---|------|------|
| 1 | GRH IR 类型系统扩展：value 与 reg/latch/mem 声明支持单一元素类型的一维到多维数组（如 `UInt8[x][y]`，x、y 编译期常量） | stage-01 |
| 2 | 不破坏 value 的 SSA 语义：数组 value 仍由单个 op 定义（concat、const 等） | stage-01（设计原则） |
| 3 | 重定义 kSliceArray：废弃 sliceWidth 属性判宽，只能连接数组类型 value，允许 1..N 个索引操作数 | stage-02 |
| 4 | 数组状态读写端口多索引（kRegister 端口族；**kMemory 退役**，reg/mem 之分降级为后端存储分类） | stage-03 |
| 5 | kMemoryWritePort 优先级语义变更 → kRegister 写端口：同 regSymbol 唯一组、声明顺序定优先级、同时激活时后声明者覆盖 | stage-03 |
| 6 | ingest 保留 SV 多维数组与结构体的数组语义，不再一律平化 | stage-04 |
| 7 | comb-loop-elim 把组合环上的 value 切成片段，保证组合无环 | stage-05 |
| 8 | GrhSIM IR 作为数组语义的承接层 | stage-06 |
| 9 | 每一步同步更新基础设施（持久化、diagnostics、Python 绑定、可视化） | 各阶段内嵌 |
| 10 | 每一步同步更新文档；终极验收：preserve-aggregate 的 XiangShan SV 正确仿真，reg-to-mem 退役 | 各阶段内嵌 + stage-07 |

## 3. 总体设计原则

1. **shape 是 packed 优先的纯结构视图，不改变任何 op 语义**。value 的 `width` 恒为
   总位宽，`shape` 只把位布局按行主序（row-major）结构化（elementWidth = width/∏shape）。
   任何 op 对带 shape value 的语义 ≡ 对其扁平位向量的语义——这正是 IEEE 1800 对 packed
   聚合（integral type）的规定语义，而实证表明 firtool preserve-aggregate 的输出 100%
   是 packed 聚合。shape 只新增结构信息与寻址能力（kSliceArray、多维 mem port），
   不设 op 白名单；存量按位/按总位宽代码自动正确，持久化、emit、仿真后端可分阶段迁移。
   （否决了 width+packed_shape+unpacked_shape 三层模型：packed/unpacked 是源语言的类型检查
   维度而非 IR 语义维度，合并维度表无信息损失，见 stage-01 §3.1。）
2. **数组 value 保持 SSA**：一个数组 value 有且仅有一个定义 op。部分更新（元素写）不发生在
   value 上——动态元素写的聚合走 kRegister 数组端口族（写端口带事件，stage-03），
   静态部分更新走
   kSliceStatic 位段写回的既有 RMW 路径。
3. **语义先行，实现分阶段**。先改 IR 定义与文档，再改生产端（ingest）与消费端（pass/emit/grhsim）。
4. **接受迂回**：允许中间阶段破坏部分现行仿真行为（见 §5），但不允许破坏仓库可构建性；
   每个阶段合入时 `make build` 与调整后的门禁必须可用。
5. **GrhSIM 物理存储保持线性**：多维 shape 落到 GrhSIM 后只影响寻址表达式与语义校验，
   物理存储仍是线性 `core.array`/字布局，避免重写后端数据布局。

## 4. 阶段划分与依赖

| 阶段 | 文档 | 依赖 | 一句话内容 |
|------|------|------|-----------|
| S1 | [stage-01-ir-array-types.md](stage-01-ir-array-types.md) | — | Value/声明加 shape；kRegister 数组化（kLatch 保持标量）、**kMemory 废除**；JSON 格式直接演进（格式未发布，不引入版本机制）；引入 GRH verifier |
| S2 | [stage-02-slice-array-redefinition.md](stage-02-slice-array-redefinition.md) | S1 | kSliceArray 重定义为纯数组访问 op（1..N 索引，无 sliceWidth） |
| S3 | [stage-03-memory-ports.md](stage-03-memory-ports.md) | S1 | kRegister 数组端口族（多索引、部分索引、掩码、填充）；**kMemory 退役**；写端口同 regSymbol 唯一组 + 声明顺序 |
| S4 | [stage-04-ingest-aggregate.md](stage-04-ingest-aggregate.md) | S1, S2, S3 | ingest 保留多维数组/结构体语义；数组端口；MemoryPortLowerer 重写 |
| S5 | [stage-05-comb-loop-elim.md](stage-05-comb-loop-elim.md) | S2 | 组合环按元素/片段切开，数组感知的假环修复 |
| S6 | [stage-06-grhsim-backend.md](stage-06-grhsim-backend.md) | S1, S3 | GrhSIM IR 多维数组承接、mem op 多索引、CPU 后端与 JSON schema 演进 |
| S7 | [stage-07-preserve-aggregate-e2e.md](stage-07-preserve-aggregate-e2e.md) | S4, S5, S6 | firtool preserve-aggregate 链路、reg-to-mem 退役、终极验收 |

依赖图（`──>` 表示"阻塞"）：

```
S1 ──> S2 ──> S4 ──┐
 │  ──> S3 ──> S4 ──┼──> S7
 │  ──> S3 ──> S6 ──┤
S2 ──────────> S5 ─┘
```

- S2 与 S3 可并行；S5 与 S6 可并行；S4 是 S7 的最大前置。
- 每阶段文档内含：现状事实（文件:行号）、IR/语义定义、小例子、文件级改动清单、
  基础设施联动、文档更新清单、破坏面与回退、开放问题。

## 5. 破坏性变更策略（迂回规则）

用户已明确接受"中间区段破坏当前仿真行为"的迂回策略。具体规则：

1. **可破坏**：旧 JSON 产物的可读性（GRH JSON 格式从未发布，S1 起直接改格式，
   旧产物重新生成即可）；中间阶段 HDLBits/xs-bugcase 门禁的部分用例（在阶段文档
   "破坏面"节逐条登记）。
2. **不可破坏**：`make build` 与 `make test_wolvrix` 中未被阶段文档显式豁免的部分；
   文档与代码的一致性（改了语义必须同 commit 改文档）。
3. **每阶段合入前**：更新该阶段登记的豁免清单；下一阶段开始时清零上一阶段的豁免。
4. **S7 结束时清零全部豁免**，门禁恢复到不低于当前水平（见 §6）。

## 6. 验证门禁

当前基线门禁（继承自 `pdocs/perf-optimization/README.md`）：

- `make test_wolvrix`（CTest 全绿）
- `make run_all_hdlbits_grhsim_ir_tests`（162/162）
- `make run_xs_bugcase_grhsim`（25/25）
- `make check_sim_refactor_baseline`（161/161 黄金 trace）
- XiangShan CoreMark difftest（轨迹钉死 instrCnt=663,688 / cycleCnt=297,291）
- 性能口径：`make benchmark_grhsim_ir`（S7 要求相对基线不回退，具体阈值见 stage-07）

每个阶段必须在该阶段文档中登记：哪些门禁保持、哪些豁免、新增了哪些测试。

## 7. 文档与命名约定

- 本目录采用 `stage-NN-<topic>.md` 编号命名（不同于 perf-optimization 的日期时间戳命名），
  因为阶段间有强顺序依赖；每篇文档头部标注日期与状态。
- 每篇阶段文档遵循：元信息 → 目标 → 现状 → 设计（含例子） → 改动点 → 基础设施联动 →
  文档更新 → 破坏面与回退 → 开放问题。
- **进展跟踪在 `PROGRESS.md`**（活账本：阶段状态、合入单元、门禁快照、豁免计数、日志；
  填写规则见该文件头部）。每次合入/状态变化必须更新；豁免与破坏的权威登记仍在各
  stage 文档 §7/§8，PROGRESS 只做聚合快照与链接，不双记账。
- 实施过程产生的实验/测量记录仍按日期前缀落在 `pdocs/perf-optimization/` 或本目录
  （文件名 `YYYYMMDD-hhmmss-<topic>.md`），并在对应阶段文档里补链接。
- 规范类文档的最终落点：`wolvrix/docs/grh/grh-ir.md`、`wolvrix/docs/grh/grh-json-spec.md`、
  `wolvrix/docs/grhsim_ir/` 各方言与流程文档。阶段文档是计划，规范文档是承诺。

## 8. 关键事实速查（现状）

- Value 目前只有 `{symbol, width, isSigned, type, ...}`，**无 shape、无属性表**
  （`wolvrix/include/core/grh.hpp:507-518`）。
- kMemory 只有 `width`+`row` 一维（`wolvrix/docs/grh/grh-ir.md:1065-1128`）。
- kSliceArray 现状：`[flatArray, index]` + `sliceWidth` 属性，多维靠级联
  （`grh-ir.md:817-834`）。
- kMemoryWritePort 优先级现状：`memoryWrite.priorityGroup/priority`
  （`wolvrix/include/core/grh.hpp:89-90`），同组必须共享相同事件/边沿，priority 0 最高、
  最后应用并获胜，由 activity-schedule 校验（`wolvrix/lib/transform/activity_schedule.cpp:948-1000`）。
- ingest 把多维 unpacked 数组各维连乘进 `memoryRows`（`wolvrix/lib/core/ingest.cpp:787-868`），
  下标线性化在 `buildLinearAddress`（`ingest.cpp:15565-15623`）；数组端口直接平化并 warn
  （`ingest.cpp:872-900`）。
- GRH JSON 无版本号（`wolvrix/lib/core/store.cpp` / `load.cpp`）——格式从未对外发布，
  本重构直接改格式，不引入版本机制；GRH 无独立 verifier。
- GrhSIM `core.array` 一维（`wolvrix/include/grhsim/ir/model.hpp:130-140`），但
  `DeclProvenance.shape` 已支持多维（`model.hpp:684-716`）；GrhSIM JSON 有格式版本
  `wolvrix.grhsim.v2`（`wolvrix/include/grhsim/io/json.hpp:21`）。
- XiangShan firtool 调用在 `testcase/xiangshan/Makefile:79`，当前未开 preserve-aggregate。

## 9. 风险登记（跨阶段）

| 风险 | 影响 | 缓解 |
|------|------|------|
| firtool `--preserve-aggregate=all` 对 XiangShan 规模设计有已知问题（如含 Clock 的 struct，circt #8931） | S7 链路不通 | S7 先做小步实证（xs-components 合成用例），必要时 `1d` 档过渡 |
| 数组保留后 P_general 体积/编译时间回升 | 性能回退 | S6 起每阶段跑 `benchmark_grhsim_ir`；参照 bitint 经验控制发射形状 |
| kSliceArray 语义重定义波及全部 pass | 大面积适配 | S2 提供完整消费端清单与迁移表；旧语义一次性废除不并存 |
| 组合环切开引入编译期/内存膨胀 | S5 回归 | 片段粒度可控（先按 leading-dim，不够再到元素）；保留 failOnTrueLoop 诊断 |
| struct 语义只能部分保留（异构类型） | 目标打折 | S4 明确 struct 的保留边界：字段仍扁平布局，数组字段保留 shape |
