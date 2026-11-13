# TNO0037 before seed2 与补丁 after seed1 的 8 对性能及最终核验

## 测量范围

接续 [TNO0036](./TNO0036_patched_after_seed1_walltime_20261111.md)，使用同一套 performance runner 比较 before seed2 与补丁 after seed1。两侧均是 Clang 23.1.2 的冻结构建；after 仅包含 [TNO0035](./TNO0035_after_seed1_clang23_mask_codegen_20261111.md) 已验证的一条指令修正。

统一 node030、CPU96–127、32 线程、NUMA1 strict membind、ASLR disabled、原 performance code-page/preload 和 phase timing。固定 CoreMark/NEMU、100,000 周期上限，完整 DiffTest 开启，trace/runtime profile 关闭；不检查外部 CPU 空闲情况。

三份模型各自完成 smoke、100k verification 和预热后，串行执行旧 after/补丁 after、before/补丁 after 两组各 8 对 AB/BA。补丁 after 的功能门和预热在两组间共用；两组统计独立计算，不混合样本。

## before/补丁 after 结果

正数表示补丁 after 更慢。固定 seed 20261102、10,000 次 paired bootstrap：

| 指标 | before 均值 / 中位数 | 补丁 after 均值 / 中位数 | 配对均值 / 中位数 delta | 95% CI | after 更慢 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Host time | 11.221125 / 11.173000 s | 23.174250 / 23.151000 s | **+106.5447% / +106.7409%** | **[+104.9234%, +107.9903%]** | 8/8 |
| 外部 walltime | 11.314804 / 11.267755 s | 23.283148 / 23.258104 s | **+105.7971% / +105.9048%** | **[+104.1730%, +107.2549%]** | 8/8 |

补丁 after 在本轮约为 before 的 2.07 倍 Host time。该结果同时包含 revision、DefaultConfig、DiffTest 和已选分区的差异，不能解释成单独的仿真器后端或补丁开销。

两个 after 对照的功能签名完全一致。跨 revision 则保留各自固定周期下的提交进度，逐次通过完整 NEMU 检查：

| 版本 | PC | instrCnt | cycleCnt | Guest cycles |
| --- | --- | ---: | ---: | ---: |
| before seed2 | `0x80000cde` | 238,535 | 99,996 | 100,001 |
| old / patched after | `0x80000c1a` | 250,838 | 99,995 | 100,001 |

各版本内部签名稳定；共同终止条件为 cycle-limit，UART 均为 `Running CoreMark for 2 iterations`。

## 阶段数据和结论

本组标准 phase timing 中位数：before / 补丁 after 的 `part_eval` 为 **8.874534 / 20.946180 s**，`input_load` 为 0.430731 / 0.453293 s，`global_update` 为 1.517700 / 1.484265 s。

在 TNO0036 的同 revision 对照中，原 seed7 最慢分区为 part_8，累计 eval 中位数约 11.955 s；补丁 seed1 最慢分区为 part_14，约 18.114 s。不同 assignment 的分区编号不能按相同语义模块对应，多个分区并行执行的累计时间也不能相加作为 walltime。这些数据将下一步分析范围指向分区计算负载和生成代码，而不支持把静态 `km1` 降低直接视为速度改善。

**本轮重分区没有性能收益，继续保留原 after seed7。** 补丁 binary 已证明能正确运行，但不采用它替换原 retained。原失败 binary、诊断补丁和本轮测量副本分别保留；默认编译选项及默认流程未修改。

## 最终核验与身份

两组共 **41 次运行全部通过**：old after 11 次、补丁 after 19 次、before 11 次；其中包含 9 次功能/预热运行和 32 个正式计时样本。拒绝样本为 0。

核验脚本重新计算了两组 Host time 和外部 walltime 统计，逐项检查功能签名、实际 32 个 singleton affinity、CPU96–127、NUMA1、ASLR disabled、code-page PASS、runtime dependency 和 binary 哈希。结果见 [verification.json](../../build/artifacts/repcut-after-seed1-patched-perf-20261111/verification.json)。

| binary | SHA256 |
| --- | --- |
| before seed2 | `8727684319c75f4ef0338c6d3efd38a2bcb1e832f1db21376b168b64b6ffbd39` |
| old after seed7 | `bd65a10ecc828cd6b0cf232cb0097cf57b103947248f9c1281e171e3de674281` |
| patched after seed1 | `3fd5e4c954af43d73e4ea98ed8015c3ebe26cb86dc424243e2c875c1333a94ef` |

runner/统计相关的 18 项 Python 测试通过，新增实验脚本编译检查、文档相对链接检查和 `git diff --check` 通过。本轮复用 binary，没有重新构建 RTL 或修改生产代码。

## 归档

- [两组综合 JSON](../../build/artifacts/repcut-after-seed1-patched-perf-20261111/report.json)、[实验产物索引](../../build/artifacts/repcut-after-seed1-patched-perf-20261111/README.md)。
- [before/补丁 after 摘要](../../build/xs/repcut-after-seed1-patched-perf-20261111/measurements/before-vs-after-patched/summary.json)、[逐对 CSV](../../build/xs/repcut-after-seed1-patched-perf-20261111/measurements/before-vs-after-patched/pairs.csv)、[逐对 JSON](../../build/xs/repcut-after-seed1-patched-perf-20261111/measurements/before-vs-after-patched/pairs.json)。
- [标准阶段与分区计时摘要](../../build/artifacts/repcut-after-seed1-patched-perf-20261111/phase-report.json)、[阶段汇总脚本](../../build/artifacts/repcut-after-seed1-patched-perf-20261111/phase_report.py)、[最终核验脚本](../../build/artifacts/repcut-after-seed1-patched-perf-20261111/verify.py)。
- [构建/运行身份](../../build/xs/repcut-after-seed1-patched-perf-20261111/provenance.json)、[完整原始记录](../../build/xs/repcut-after-seed1-patched-perf-20261111/measurements/)、[完成状态](../../build/xs/repcut-after-seed1-patched-perf-20261111/complete.json)。
