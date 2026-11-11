# TNO0026 历史标准 pipeline 与 merge-before 的 Verilog 内容核对

## 对象和方法

核对 [TNO0025](./TNO0025_repcut_historical_standard_pipeline_audit_20261111.md) 的两份实际输入：历史 `grhsim32_fresh_rtl_20261028/rtl/rtl` 与当前 merge-before `before/repcut/rtl/rtl`。按相对文件名配对，比较完整字节及 SHA256；不是比较绝对路径，也不是仅比较 Git revision。

两份 RTL 都有 2,097 个 `.sv/.v/.svh/.vh` 文件，文件名集合相同；**2,053 个文件逐字节相同，44 个不同**。完整 [逐文件 manifest](../../build/artifacts/repcut-before-retry-20261111/verilog/report.json)、[全部差异](../../build/artifacts/repcut-before-retry-20261111/verilog/diffs/)、[复现脚本](../../build/artifacts/repcut-before-retry-20261111/audit_verilog.py) 已保留。

## 内容差异

| 文件数 | 差异性质 | 证据和范围 |
| ---: | --- | --- |
| 32 | 仅断言消息中的 Scala 行号 | 屏蔽 `Assertion failed at …scala:<line>` 后，保持字符串和标识符的 token 序列相同 |
| 2 | Git commit 常量 | `CommitIDModule.sv`、`NewCSR.sv` 从 `40'hC35B27D778` 改为 `40'h77ED568FCB` |
| 3 | 信号或实例前缀重命名 | `CompressUnit.sv`、`VIAluDecoder.sv` 的 `decoder_decoded_` → `decoder_`；`VIAluFix.sv` 的 `vIAluFixPoints_` → `pointModules_`，归一化这些前缀后 token 序列相同 |
| 4 | 组合表达式和中间信号变化 | `IBuffer.sv`、`Ifu.sv`、`PredChecker.sv`、`RequestBuffer_4.sv` |
| 3 | 性能统计、日志及其连接顺序变化 | `Ftq.sv`、`LogPerfEndpoint.sv`、`SimTop.sv` |

自动报告把 `NewCSR.sv` 保留在一般 token 差异内；其单行常量差异经人工核对，记录在 [reviewed-differences.json](../../build/artifacts/repcut-before-retry-20261111/verilog/reviewed-differences.json)。这使上表与自动分类可以相互追溯。

具体例子：`RequestBuffer_4.sv` 的插入下标由临时取反向量加优先选择表达式，变为直接对 `valids_0/1/2` 的嵌套选择；`IBuffer` 与 `Ifu` 的 PopCount 展开和临时信号发生变化；`PredChecker` 的 `remaskIdx` 优先选择展开发生变化。因此不能把全部差异归为路径、注释或单纯文件格式。

[对应 Scala diff](../../build/artifacts/repcut-before-retry-20261111/verilog/source-excerpts.diff) 显示，`c35b27d778` 到 `77ed568fc` 之间引入了 `utility.PopCount`、`utility.PriorityEncoder`，并调整 Seq/Vec/UInt 的调用方式；`utility` 和 `coupledL2` gitlink 也不同。即使两次都走硬件回退，这些源代码调整仍能改变生成的逻辑表达式。

上述是内容和表达式层面的判断，**不是全设计形式等价证明，也不能据此直接声称 ISA 功能不等价**。历史与当前 binary 在同一 100k 周期窗口内的提交进度也不同，已有 DiffTest 验证仅说明各自执行通过 NEMU 检查。

## 外部 Verilog 和边界

两份 `input.f` 都有 2,100 项：2,097 个生成 RTL，加 `SimJTAG.v`、`assert.v`、`ref.v`。三个公共 Verilog 在各自 XiangShan revision 所指向的 DiffTest Git blob 中逐字节相同：历史 DiffTest `5b7a0963…`，before `26af3a5e…`。Git blob 比较没有把当前已变化的源码路径当成历史内容。

历史构建没有单独冻结 `DifftestMacros.svh`；当前可变目录的 header 不能充当历史 header 的证明。这个归档缺口不影响“已冻结的源 Verilog 内容不同”的结论，但不应宣称完整预处理输入已经证明一致。

## 对此前判断的补充和勘误

TNO0025 中“历史分区更好是主要原因”的表述过强。已知同时存在源 RTL、编译器和 assignment 差异；仅凭最大分区的 **未加权 entry 数**，无法证明加权负载或 barrier 开销的原因。本次对当前 before 冻结图进行独立 8-seed 重试，结果另见 [TNO0027](./TNO0027_before_partition_retry_20261111.md)。

TNO0025 的 HGR 描述还有一处次序/对象勘误：`296526 301184 11` 是 replay 阶段单权重 HGR，表示 **296,526 条边、301,184 个节点**，不是求解用 reduced HGR。实际求解的完整六维 HGR 是 `584259 301184 11 6`，隔离 oversized 节点后的 reduced HGR 是 `575747 301183 11 6`；两次 header 相同，但内容 SHA256 不同。保留原记录，在此追加修正。
