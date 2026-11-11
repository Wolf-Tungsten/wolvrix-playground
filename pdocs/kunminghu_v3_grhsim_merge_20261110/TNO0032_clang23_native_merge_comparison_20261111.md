# TNO0032 Clang 23 下单核 native GrhSIM merge 前后结果与总核对

## 构建与功能门

按 [TNO0029](./TNO0029_all_clang23_rebuild_protocol_20261111.md)，原 before/after native GrhSIM 生成源码均以 Clang 23.1.2 重新编译，使用 `-std=c++20 -O3 -march=native`、原 PCH 和 Makefile，各自 DiffTest harness 使用 `-O3`。原历史 native binary 也使用 Clang 23；本次是冻结源码重编译后在新窗口的完整复测，不是单核 Clang 19/23 对比。

node030、CPU96、NUMA1 strict membind、ASLR disabled，固定 CoreMark/NEMU、100,000 周期、完整 DiffTest。两侧均完成 10k smoke、两组 100k trace 验证、预热和 8 对 AB/BA，共 **24 次有效运行、0 次拒绝**。

正式签名稳定，且与本轮对应 RepCut revision 一致：before PC=`0x80000cde`、instrCnt=238,535、cycleCnt=99,996；after PC=`0x80000c1a`、instrCnt=250,838、cycleCnt=99,995。共同 Guest cycles=100,001，cycle-limit 终止，UART 为 `Running CoreMark for 2 iterations`。每个版本的 trace 分别通过 NEMU 及覆盖检查；跨版本按 schema-change 规则检查共同终止条件和 workload 输出。

## 8 对 AB/BA

正数表示 after 更慢；固定 seed 20261102，10,000 次 paired bootstrap。

| 指标 | before 均值 / 中位数 | after 均值 / 中位数 | 配对均值 / 中位数 delta | 95% CI | after 更慢 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Host time | 110.014500 / 109.876000 s | 140.255250 / 140.289000 s | **+27.4892% / +27.1876%** | **[+27.0661%, +27.9633%]** | 8/8 |
| 外部 walltime | 110.062287 / 109.923642 s | 140.314696 / 140.343713 s | **+27.4879% / +27.1805%** | **[+27.0622%, +27.9645%]** | 8/8 |

本轮单核 native GrhSIM 的 merge-after 稳定更慢。该变化包含整个 revision 的硬件模型、DefaultConfig 和所跟踪 DiffTest，不能直接归因为 emitter 的某一优化。

## 统一 Clang 23 的三组结果

| 模拟器 | before Host 均值 | after Host 均值 | after 配对 delta | 95% CI |
| --- | ---: | ---: | ---: | ---: |
| GSIM 单核 | 78.974 s | 106.913 s | +35.378% | [+35.129%, +35.615%] |
| native GrhSIM 单核 | 110.015 s | 140.255 s | +27.489% | [+27.066%, +27.963%] |
| RepCut GrhSIM 32 线程 | 11.702 s | 17.883 s | +52.845% | [+51.392%, +54.038%] |

三组各 8 对，after 均为 8/8 更慢；全部 **70 次运行通过，0 次拒绝**。六份模型与 harness 均以相同 Clang 23.1.2 重编译，单核 CPU96、32 线程 CPU96–127，均 NUMA1、ASLR disabled。计时组串行，未与本实验构建重叠。

RepCut 使用 before 新 seed2 与 after 原 retained seed7，before 比 after 多做了一轮分区搜索；这一项不能视为对称随机搜索的平均结果。GSIM 与 native 的具体编译选项沿用各自原 pipeline，统一编译器不意味着把不同模拟器的所有编译选项改为一样。各组单独统计，没有混合不同运行窗口的数据。

## 归档与最终核对

- [综合机器可读报告](../../build/artifacts/kunminghu-v3-clang23-retest-20261111/report.json)、[报告校验脚本](../../build/artifacts/kunminghu-v3-clang23-retest-20261111/report.py)、[六份 build-complete](../../build/xs/kunminghu-v3-clang23-retest-20261111/build-complete.json)。
- [native 运行 manifest](../../build/xs/kunminghu-v3-clang23-retest-20261111/measurements/grhsim-single/manifest.json)、[summary](../../build/xs/kunminghu-v3-clang23-retest-20261111/measurements/grhsim-single/summary.json)、[逐对 CSV](../../build/xs/kunminghu-v3-clang23-retest-20261111/measurements/grhsim-single/pairs.csv)、[逐对 JSON](../../build/xs/kunminghu-v3-clang23-retest-20261111/measurements/grhsim-single/pairs.json)。
- [native trace seed0](../../build/xs/kunminghu-v3-clang23-retest-20261111/measurements/grhsim-single/trace-s0.json)、[trace seed1](../../build/xs/kunminghu-v3-clang23-retest-20261111/measurements/grhsim-single/trace-s1.json)、[原始日志/locality](../../build/xs/kunminghu-v3-clang23-retest-20261111/measurements/grhsim-single/)。
- [RepCut 记录 TNO0030](./TNO0030_clang23_repcut_merge_comparison_20261111.md)、[GSIM 记录 TNO0031](./TNO0031_clang23_gsim_merge_comparison_20261111.md)。

六份完整构建、生成源码原件/副本的编译前后哈希、二进制与 schema 身份、三组功能/placement 门、Python 编译检查、文档相对链接与 `git diff --check` 通过。本次没有修改通用 emitter、默认 pipeline 配置或原实验产物。
