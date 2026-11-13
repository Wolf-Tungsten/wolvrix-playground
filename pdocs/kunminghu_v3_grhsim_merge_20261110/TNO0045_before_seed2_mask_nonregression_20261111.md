# TNO0045：before seed2 的掩码规则无变化门

日期：2026-11-11（America/Los_Angeles）。默认启用前的收益门修正见 [TNO0044](./TNO0044_reduction_mask_default_profitability_guard_20261111.md)。

## 固定条件

基线为已有 `repcut-before-seed2-clang23-20261111`，冻结其分区图、assignment、Clang 23、全部模型和 harness 对象。候选使用加入“至少 16 个不同谓词”收益门的 emitter，显式开启 `WOLVRIX_GRHSIM_SCALAR_CONCAT_REDUCTION_MASKS=1`，完整重新生成 32 分区 package。

## 结果

- 比较 **7,857 个源码/头文件**，全部 SHA256 一致，变化文件数为 0。
- 规则没有在此图形成需要改写的谓词族；模型 ABI、调度、状态、计算及 wrapper 代码均保持一致。
- 复用相同对象、相同 Clang 23 链接命令重新链接后，两侧 binary 也逐字节相同。

```text
bytes   98,878,808
SHA256  3d2d9ecb5245b4da2bf0c4f701227872e21c3977fb5dc1ae5f59db39404cb463
```

这里通过源码及 machine code 的内容一致性排除了新规则引起的运行代码退化，因此不另做同 binary 的 walltime 比较，也不把环境噪声解释成开关收益。既有该 binary 的功能及性能记录保持有效。本轮没有新增 before 的计时结论。

这也说明新规则没有改变 before 已验证的长 mux/LLVM SimplifyCFG 加速路径。after 的独立分区仍需单独的实际计时门。

## 归档

- [无变化核验](../../build/xs/reduction-mask-default-20261111/before/no-change-proof.json)
- [7,857 项内容比较](../../build/xs/reduction-mask-default-20261111/before/source-comparison.json)
- [图、assignment、compiler、archive、binary 身份](../../build/xs/reduction-mask-default-20261111/before/inputs.json)
- [构建结果](../../build/xs/reduction-mask-default-20261111/before/complete.json)
- [生成和链接日志](../../build/artifacts/reduction-mask-default-20261111/before-build.log)
