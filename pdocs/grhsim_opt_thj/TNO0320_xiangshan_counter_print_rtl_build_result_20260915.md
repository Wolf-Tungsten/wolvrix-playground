# TNO0320: XiangShan counter-print RTL build result

日期：2026-09-15

状态：`RTL BUILD PASS; NO RUNTIME CLAIM`。

## 1. 输入与构建结果

承接 [TNO0318](./TNO0318_xiangshan_counter_print_regeneration_plan_20260915.md) 与
[TNO0319](./TNO0319_xiangshan_counter_print_isolated_build_runbook_correction_20260915.md)。
`build/asc_counter_print_20260915/candidate_v4/run.json`：node039，compile exit 0，
generator exit 0，status pass，wall 751.119s。该时间包含本次缓存核验和生成，不是 Host 仿真时间。

设计仍只有 utility/PerfCounterUtils.scala 的 XSPerfAccumulate 打印参数变更。
文件 SHA-256：`e3f1ddc1abd95f263348884461fcb99f5568f3671a3b618856dc173228ef0ced`。
XiangShan HEAD：`4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`；utility HEAD：
`1db5122533808bcde35c1f4c8bbc62c99777e292`。

固定 TLConfig / E.b / 1 core / difftest G、firtool 1.135.0、Chisel 7.3.0、Scala 2.13.17、
Mill 0.12.15、GraalVM JDK21.0.9；完整 argv/env 和 SHA 清单见 launch/compile/run.json。
原配置的 release/lowering/layer/difftest 选项以及 assert 后处理均保留。
生成阶段有159条硬件展开 warning，未导致失败。

## 2. 产物与隔离

新 arm 输出 2,097 个 .sv/.v 和7个 difftest generated helper；另保留 FIR 与生成器辅助输出。
仅使用本轮独立 Mill class 输出，JVM cwd、NOOP_HOME 与 RTL target-dir 均隔离。
旧2,100个 RTL/common 输入及7个 generated helper 在对照导入前后身份保持不变。

全 RTL 文件集合与旧版一致，2,091个字节相同，6个不同：LogPerfEndpoint、Ifu、PreDecode、
CommitIDModule、NewCSR、SimTop。不能简单称为“只有一个 RTL 文件不同”；具体归因见
[TNO0321](./TNO0321_xiangshan_counter_print_rtl_semantic_audit_20260915.md)。

差异清单与 unified diff：`build/asc_counter_print_20260915/rtl_diff_v1/`。
旧 LogPerfEndpoint SHA：`9301b078b65cefd44285b3629659d71e0da1e1119f16467192c830c6e738e0f3`；
新 SHA：`efa9833d9e3bd4659315a19b5cbac0f512f4462734c5dc6ae8be04f08c1f885a`。

## 3. 后续范围

仅进入原/new RTL 的同流程 GRH/ASC 结构 gate，不构建 partition simulator，不进行
N=1/8/32 仿真，不由 RTL 字节量或生成 wall time 推断加速。
