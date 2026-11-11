# TNO0034 after 新 seed1 的功能拒绝与重复诊断

## 结果

[TNO0033](./TNO0033_after_partition_retry_protocol_20261111.md) 的独立 8-seed 重试选中 seed1，完整图 `km1` 从原 seed7 的 42,318,476 降为 40,769,428（−3.66045%）。生成、Clang 23 编译和链接完成，但新模型在完整 DiffTest 验证中失败，**本次没有得到可用于性能比较的新 after binary**。

旧 after seed7 的同窗口 10k smoke、100k verify 和 warmup 均通过，新 seed1 的 10k smoke 通过，100k verify 在结束前出现：

```text
a4 different at pc = 0x00800010de,
right = 0x0000000080003cc0, wrong = 0x0000000000000042
Core 0: ABORT at pc = 0x800010de
Core-0 instrCnt = 226,022, cycleCnt = 95,572
Guest cycle spent: 95,577
```

该错误在功能门期间发生，原计划的两个 8 对 AB/BA 均没有启动。失败运行没有达到 100k 周期，不能用其耗时评判新旧模型快慢。性能样本数为 **0**，原 seed7 retained 和原报告保持不变。

## 重复诊断

使用同一新 binary、冻结 CoreMark/NEMU 和 seed=0，记录以下独立诊断：

| 运行 | host 执行线程 | guest cycles | PC | a4 差异 | 结果 |
| --- | ---: | ---: | --- | --- | --- |
| 原 verification | 32 | 95,577 | `0x800010de` | `0x80003cc0` / `0x42` | 拒绝 |
| repeat32-a | 32 | 95,577 | 相同 | 相同 | 重现 |
| repeat32-b | 32 | 95,577 | 相同 | 相同 | 重现 |
| serial32part | 1 | 95,577 | 相同 | 相同 | 重现 |

`serial32part` 仍保留同一份 **32 个图分区**，仅将 `XS_EMU_THREADS=1`，进程绑 CPU96。运行中 `/proc` 观察确认一个线程、affinity=`96`。诊断命令保留 NUMA1 strict membind 和 `setarch -R`；外部观察进程无法读取它的 personality，证据文件如实注明这一限制。该诊断没有作为单核性能测量。

两次 32 线程复跑和单线程执行均重现同一差异，说明此失败**不依赖 worker 并发**。应优先检查新 assignment 下分区、状态/激活传播、生成代码与 DiffTest 观察行为的等价性；具体根因尚未定位。该结果尚不能区分 DUT 计算错误、观察/提交错误或生成代码问题，也没有单独排除编译器与代码形状的交互。

## 已排查的变量

- 新旧 after 使用相同 `defb18e13` / DiffTest `b17a43a`、Clang 23.1.2、冻结 CoreMark/NEMU。
- 原 graph、HGR、solver、partition/replay 工具、生成参数身份在构建前后核对；分区随机性是本实验有意改变的输入。
- 新旧六个 generated DiffTest 文件逐字节相同，配置一致，见 [接口相等检查](../../build/artifacts/repcut-after-retry-clang23-20261111/interface-equality.json)。
- 旧 seed7 同窗口 100k DiffTest 通过，PC=`0x80000c1a`、instrCnt=250,838、cycleCnt=99,995、Guest cycles=100,001；新 seed1 的失败不应简单归因于 workload/NEMU 不兼容。
- 四次成功的前置运行（旧 after 三次、新 after smoke 一次）均通过严格 CPU96–127/NUMA1/ASLR/codepage 门。新 verify 的原始运行和 locality 日志保留，状态明确记为 `rejected_functional`。

## 归档与后续边界

新 binary：117,517,136 B，SHA256 `608eb217d01c7d68e85e9c8a76071af9ac75addbd27a300a084648c01e172c61`。全部八个 solver 结果、selected assignment、partitioned graph、生成 C++、命令和日志均保留，便于在相同输入上定位问题。

- [综合拒绝报告](../../build/artifacts/repcut-after-retry-clang23-20261111/report.json)、[拒绝证据校验脚本](../../build/artifacts/repcut-after-retry-clang23-20261111/failure-report.py)、[最终证据核对](../../build/artifacts/repcut-after-retry-clang23-20261111/final-verification.json)。
- [首次失败日志](../../build/xs/repcut-after-retry-clang23-20261111/measurements/retry_after/verify.log)、[精确命令](../../build/xs/repcut-after-retry-clang23-20261111/measurements/retry_after/verify.command.json)、[功能拒绝 JSON](../../build/xs/repcut-after-retry-clang23-20261111/measurements/retry_after/verify.rejected.json)。
- [诊断入口](../../build/artifacts/repcut-after-retry-clang23-20261111/diagnose.py)、[三次诊断结果](../../build/xs/repcut-after-retry-clang23-20261111/diagnostics/results.json)、[诊断日志目录](../../build/xs/repcut-after-retry-clang23-20261111/diagnostics/)、[单线程实际观察](../../build/xs/repcut-after-retry-clang23-20261111/diagnostics/serial32part.observed.json)。
- [生成包 manifest](../../build/artifacts/repcut-after-retry-clang23-20261111/generated-package-manifest.json)、[构建完成身份](../../build/xs/repcut-after-retry-clang23-20261111/build-complete.json)。

本次结论是“重新求解获得更低静态目标，但选中方案功能失败”，不是性能改善或退化结论。保留原可用 seed7；应先定位这份可重复的失败模型，再继续接受新分区进入 walltime 测量。
