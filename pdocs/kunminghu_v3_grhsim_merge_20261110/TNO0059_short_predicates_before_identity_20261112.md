# TNO0059：收紧短条件规则后 before 的内容一致性验收

日期：2026-11-12（America/Los_Angeles）。承接 [TNO0058](./TNO0058_short_predicate_profitability_revision_20261112.md) 的退化与收益门修正，本篇验证至少 128 个不同谓词的规则在 before seed2 上是否完全回退。

## 配置与结果

复用 before seed2 的冻结 partitioned graph、assignment、Clang 23 编译参数、完整 DiffTest harness 和既有长字段掩码/宽归约规则。使用冻结的新生成器，显式设置 `WOLVRIX_GRHSIM_SHORT_CONCAT_REDUCTION_MASKS=1`，重新发射全部分区。

- 新旧源码文件集合完全一致，共 **7,857 个** `.cpp/.hpp/.h` 文件。
- 全部文件 SHA256 相同；短规则命中 **0 个范围**，没有重新编译的 C++ 对象。
- 从相同 archive 与冻结 harness 对象重新链接后的 binary 为 **98,783,920 bytes**，与基线逐字节相同。

两侧 binary SHA256：

```text
27309399baffa03aeb1c8d538a7263bed934d0fd670f2269b54c1685ccd6c674
```

因此初始门在 before 上的 39 个范围、17 个文件改写已全部取消。这里记录的是内容一致性证明，**没有把同一 binary 的重复测量伪装成新优化收益**。该基线在本轮初始对照中已完成 smoke、100k 验证、预热和 8 次正式运行，完整 DiffTest 与放置门均通过。

这一结论只适用于冻结 before seed2。两个 after 分区的性能验收仍独立执行；本阶段尚未改变默认策略。

## 产物

- [一致性审计](../../build/xs/repcut-short-reduction-20261112/before-strict/strict-source-audit.json)
- [逐文件内容比较](../../build/xs/repcut-short-reduction-20261112/before-strict/source-comparison.json)、[输入与工具身份](../../build/xs/repcut-short-reduction-20261112/before-strict/inputs.json)
- [冻结生成器及库](../../build/artifacts/repcut-short-reduction-20261112/strict-emitter.json)、[实际配置](../../build/xs/repcut-short-reduction-20261112/before-strict/configuration.json)
- [构建日志](../../build/artifacts/repcut-short-reduction-20261112/before-strict-build.log)、[审计脚本](../../build/artifacts/repcut-short-reduction-20261112/strict_audit.py)
- [基线的本轮运行记录](../../build/xs/repcut-short-reduction-20261112/measure-before/)、[初始门的完整对照报告](../../build/artifacts/repcut-short-reduction-20261112/before-report.json)
