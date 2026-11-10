# TNO0012 RepCut 无驱动 wrapper 信号兼容

## 完整 after 构建暴露的问题

after 的 frontend、memory conversion、8 个 solver seed 和 partition replay 均成功；选中 seed 7。package emitter 随后报告 `Unsupported top wrapper value used as unit input driver`，尚未生成可运行的 after RepCut binary，正式配对驱动因此自动停止等待。

从冻结 `initial/partitioned.json` 提取顶层 wrapper 后，发现 64 个没有定义操作的 50-bit logic 值，全部为上游 store queue 的 `physicalQueue_dataEntries_0..63_debugVaddr`。其 consumer 位于 part 29；这些值不是额外的顶层输入，也没有 instance output 驱动。上游 `NewStoreQueue.scala` 定义该 debug 字段，但未给这些寄存器字段赋值。

错误日志、顶层图、64 项清单、诊断和首次停止状态保存在 [repcut-wrapper-failure](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/repcut-wrapper-failure/)。原始 RTL、分区及 assignment 均保留。

## 与单核既有两态语义对齐

native GrhSIM 的无驱动 logic 存储使用默认零初始化。RepCut pass 保留这些无驱动值到 wrapper，但 package 输入连接此前要求所有值必须来自 top input、unit output 或 constant，因此拒绝了这个合法的 native 两态边界。

Wolvrix 本地分支 `thj/kunminghu-v3-grhsim-compat-20261110` 的 commit `3a749d2a519d77a9e974c026db41601f36e99560` 补充：

- 仅在 GrhSIM package 路径，将没有 defining operation、没有已有 driver、位宽为正的 logic 值视为同宽零常量。
- top input 和正常 unit output 保持原有驱动；alias 仍通过现有解析传播。
- 有 defining operation 的不支持计算仍明确报错。
- Verilator package 路径和 native C++ emitter 未修改；XiangShan/完整 DiffTest 没有裁剪。

## 验证与基线约束

新增 fixture 覆盖 1/64/130-bit 无驱动值、直接和 alias 连接、共享 unit 的独立寄存器状态、reset/reinit、serial/parallel API，并验证不支持的实际计算不会被当作零。

`emit-grhsim-repcut-package` 与 `emit-verilator-repcut-package` 均通过；构建和运行日志为 [focused build](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/logs/undriven-focused-build.log)、[GrhSIM test](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/logs/undriven-grhsim-test.log)、[Verilator test](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/logs/undriven-verilator-test.log)。

由于本阶段增加了必要的 backend 兼容修复，正在用新 emitter 从冻结的 before candidate partitioned graph 重新生成全部 C++/headers。只有逐文件字节一致，才允许继续复用旧 before binary；审计脚本为 [audit-before-package.py](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/audit-before-package.py)。此约束已加入新版配对调度驱动，审计失败会阻止正式计时。

after 使用 [after-repcut-resume-emit.py](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/after-repcut-resume-emit.py) 从冻结 partitioned graph 恢复 package emission，未重复 RTL、frontend、memory conversion 或 solver。后续仍执行相同 compile、完整 DiffTest、trace/migration 和标准 retained 选择。

正式测量的新调度记录为 [paired-measurements-v2.py](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/paired-measurements-v2.py)。本记录形成时旧 C++ 一致性审计和新 package 发射仍在运行，尚无正式前后 walltime 结果。
