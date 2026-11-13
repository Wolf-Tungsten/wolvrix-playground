# TNO0064：短条件公共因子成本门实现与候选验证

日期：2026-11-12（America/Los_Angeles）。依据 [TNO0063](./TNO0063_short_predicate_cost_diagnosis_20261112.md) 的动态与静态复查，实现更细的短条件收益判断。

## 实现

在 `collectPackedScalarConcatReductions` 中，初筛不同谓词数恢复为 16。短条件仍需满足全部稳定输入、用途、作用范围、字段宽度、输入上限和复用检查；长字段规则保持原判断。

新增仅供生成阶段使用的 `estimateFactoredBooleanOps`。对 16–127 个不同短谓词，按 AND/OR 分别估计公共二元因子复用后的运算数 `C`，要求 `C >= 2P + I`；128 以上保留原已验证路径。函数使用有序 pair 计数和确定性 tie-break，每次替换均减少表达式项数，不添加运行时分支、模型字段或图节点。这个判断是静态启发式，不是对 Clang 最终指令的预测保证。

安全证明和实际 lowering 没有放宽：满足条件的范围仍只共享同一个稳定输入词；不满足条件的范围仍采用旧源码。完整重新发射时逐范围核对两者，与候选源码及旧基线进行内容比较。

## 新增验证边界

focused fixture 在保留原用例的基础上，增加：

- 32 个不同谓词共享 11 个公共字段：成本低，拒绝打包。
- 32 个较复杂 AND 谓词：通过成本门。
- 独立的 32 个复杂 OR 谓词：通过成本门。
- 15 个不同谓词，即使重复实例较多也不通过最低数量门。
- 127 个复杂谓词可以通过成本门，128 个谓词继续使用原路径。

每个测试范围单独核对是否出现 pack，不能靠“总 pack 数相同”掩盖接受/拒绝错位。默认/on、显式关闭、属性与环境变量优先级、父规则关闭继续验证。生成源码检查已通过；O0/O3 ASan/UBSan 和完整 emitter 回归另行完成后归档。

## 隔离候选的方向性检查

先在冻结 after seed7 的生成 C++ 中，按同一成本规则选择已验证的整段活动范围。保留 196 个范围，比当前 128 门多 145 个；相对当前版本只需替换 43 个 C++ 文件，不改变 header、状态布局、分区或 harness。

node030、CPU96–127、NUMA1 bind、ASLR off、Clang 23、完整 DiffTest、CoreMark 100k。双方通过 smoke、完整验证、预热，并运行 **2 对诊断 AB/BA**：相对当前 128 门 binary，Host time 分别变化 **−3.3159% / −3.0379%**，均值从 **13.9600 s** 降至 **13.5165 s**。该两对结果仅用于确认方向，不作为正式性能验收。

随后冻结实际 emitter，开始串行重新发射 before seed2、after seed7、after seed1。after seed7 最终 binary 必须与这个候选逐字节一致，before 必须与已有基线一致；最终性能另做 8 对。对 seed7 还将直接比较未启用短规则的基线，不通过不同轮次百分比的乘积估算恢复程度。

## 产物

- [隔离候选选择](../../build/xs/repcut-short-profitability-20261112/generated-candidate/selection.json)、[候选构建](../../build/xs/repcut-short-profitability-20261112/generated-candidate/complete.json)
- [两对诊断结果](../../build/xs/repcut-short-profitability-20261112/candidate-measure-generated/summary.json)、[原始运行](../../build/xs/repcut-short-profitability-20261112/candidate-measure-generated/)
- [冻结 emitter 身份](../../build/artifacts/repcut-short-profitability-20261112/emitter.json)、[完整发射与审计脚本](../../build/artifacts/repcut-short-profitability-20261112/emit_build.py)
- [源码边界测试日志](../../build/artifacts/repcut-short-profitability-20261112/focused-source.log)、[特性说明](../../wolvrix/docs/emit/grhsim-short-reduction-masks.md)
