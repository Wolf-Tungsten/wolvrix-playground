# TNO0028 新 seed2 模型的 Clang 19 / Clang 23 对测

## 目的与固定输入

将 [TNO0027](./TNO0027_before_partition_retry_20261111.md) 新选出的 seed2 模型用 Clang 23.1.2 重编译，与同一模型的 Clang 19.1.1 binary 做当前窗口的配对计时，检查编译器版本对性能的影响。

直接复制冻结的生成包：7,759 个 C++ 文件、98 个 header 和 1 个 Makefile，共 **7,858 个文件**。复制前、复制后及编译后都逐文件核对长度和 SHA256。不重新 elaboration、前端转换、分区或发射 C++；assignment 仍为 seed2，完整图 km1=27,714,651。

完整源码清单：[generated-package-manifest.json](../../build/artifacts/repcut-before-seed2-clang23-20261111/generated-package-manifest.json)。输入、工具与源码 commit 身份：[provenance.json](../../build/xs/repcut-before-seed2-clang23-20261111/provenance.json)。

## 编译与运行条件

| 项目 | A | B |
| --- | --- | --- |
| 模型与 DiffTest C/C++ 编译器 | Ubuntu Clang 19.1.1 | Clang 23.1.2，LLVM commit `85ac560262434c9ccfc0c183ec22d4138ed647fb` |
| 模型编译参数 | `-std=c++20 -O3 -march=native -pthread` | 相同 |
| 归档/代码节工具 | `/usr/bin/llvm-ar`、`/usr/bin/llvm-objcopy` | 相同 |
| 对象可执行节对齐 | 64 bytes | 相同 |
| harness 源码 | XiangShan `77ed568fc`、DiffTest `26af3a5e` | 相同，使用冻结 generated headers |
| 模型 assignment 和生成 C++ | TNO0027 seed2 | 逐文件相同 |

B 的模型和 DiffTest harness 均用 Clang 23 重编译，因此结论涵盖整个 emulator 的编译器变化。`-march=native` 在同一 node030 上执行；具体优化与指令选择由各编译器决定。保留 Clang 19 binary，所有新产物写入独立目录。

运行使用现有严格 `grhsim32_pair_compare.Runner`：node030、CPU96–127、NUMA1 strict membind、ASLR disabled、performance 模式，完整 DiffTest/NEMU，冻结 CoreMark，100,000 周期上限，trace 和额外 profile 关闭。保留既有 performance pipeline 的 phase timing、code-page/preload 和 thread pinning。没有外部 CPU 空闲准入检查。

两侧各执行 10k smoke、100k verification、100k warmup，要求 PC、提交指令数、周期数、终止条件及 UART 输出完全一致；随后 8 对 AB/BA。逐样本检查实际 32 个 singleton affinity、NUMA mappings、ASLR personality、codepage PASS 与 binary/dependency 哈希。Host time 和外部 walltime 分别统计均值、中位数、配对 delta，以及固定 seed 20261102、10,000 次 bootstrap 的 95% CI。

[构建与测量入口](../../build/artifacts/repcut-before-seed2-clang23-20261111/run.py) 复用通用 pipeline 的 compile/harness 方法，只调用重编译阶段；每条编译命令单独归档。[驱动日志](../../build/artifacts/repcut-before-seed2-clang23-20261111/driver.log) 保留进度及错误。此段写于编译期间，完成后的结果追加如下。

## 完成后的功能与 placement 门

两侧的 10k smoke、100k DiffTest verification、预热和 8 对 AB/BA 全部通过，共 **22 次有效运行、0 次拒绝**。100k 功能签名相同：PC `0x80000cde`，提交 238,535 条指令，cycle_count 99,996，guest_cycles 100,001，cycle-limit 终止，UART 为 `Running CoreMark for 2 iterations`。

两侧 runtime JSON 相同；实际 32 个线程分别落在 CPU96–127，NUMA1、ASLR disabled、codepage PASS 检查通过。除 emulator binary 外，10 项运行依赖（CoreMark、NEMU、系统动态库和 preload helper）逐字节相同，见 [依赖身份核对](../../build/artifacts/repcut-before-seed2-clang23-20261111/runtime-dependencies.json)。

## 性能结果

负数表示 Clang 23 更快；每组 8 对 AB/BA，固定 seed 20261102 的 10,000 次配对 bootstrap。

| 指标 | Clang 19 均值 / 中位数 | Clang 23 均值 / 中位数 | 配对 delta 均值 / 中位数 | 95% CI | Clang 23 更快 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Host time | 16.369625 / 16.360000 s | 11.405125 / 11.440000 s | **−30.3242% / −30.6772%** | **[−30.6979%, −29.8837%]** | 8/8 |
| 外部 walltime | 16.459784 / 16.450586 s | 11.495891 / 11.535856 s | **−30.1545% / −30.4801%** | **[−30.5241%, −29.7239%]** | 8/8 |

| 阶段耗时中位数 | Clang 19 | Clang 23 |
| --- | ---: | ---: |
| input load | 447.886 ms | 440.562 ms |
| part eval | 14,032.171 ms | 9,077.515 ms |
| global update | 1,518.529 ms | 1,532.894 ms |

收益集中在 part eval，约减少 4.95 秒；输入加载和更新阶段变化很小。阶段统计包含计算、调度与同步，未进一步隔离具体 compiler pass 或机器指令，因此不能把这项改善归到某一个优化选项。

## 结论和产物

**同一 seed2、同一份生成 C++，仅重编译模型及 harness，Clang 23 比 Clang 19 稳定快约 30.3%。** 编译器版本是此前性能差距的一个重要因素，不能只解释为分区随机性。

TNO0027 的重新分区使当前 before 在 Clang 19 下快约 8.5%；本轮再用 Clang 23 后，达到约 11.4 秒 Host time / 11.5 秒外部 walltime，回到历史标准 pipeline 的 11 秒量级。本轮没有重新对测历史 binary；历史与当前源 RTL 仍有 [TNO0026](./TNO0026_historical_before_verilog_content_20261111.md) 记录的差异，不能据此声称两者性能完全相同或微架构完全等价。

| binary | 大小 | SHA256 |
| --- | ---: | --- |
| seed2 Clang 19 | 100,630,944 B | `079da8ac24e10bb16025ce820f3379024a3323d144442f35056e64d7231abc5d` |
| seed2 Clang 23 | 98,878,808 B | `3d2d9ecb5245b4da2bf0c4f701227872e21c3977fb5dc1ae5f59db39404cb463` |

Clang 23 binary 缩小 1.7412%。新旧 binary、所有源码和既有默认配置均分别保留，没有覆盖原实验。

产物入口：

- [Clang 23 emulator](../../build/xs/repcut-before-seed2-clang23-20261111/initial/harness/grhsim-compile/emu)。
- [综合 JSON](../../build/artifacts/repcut-before-seed2-clang23-20261111/report.json)、[summary](../../build/xs/repcut-before-seed2-clang23-20261111/measurements/summary.json)。
- [逐对 CSV](../../build/xs/repcut-before-seed2-clang23-20261111/measurements/pairs.csv)、[逐对 JSON](../../build/xs/repcut-before-seed2-clang23-20261111/measurements/pairs.json)。
- [功能签名](../../build/xs/repcut-before-seed2-clang23-20261111/measurements/functional.json)、[配置及输入 manifest](../../build/xs/repcut-before-seed2-clang23-20261111/measurements/manifest.json)、[原始日志与逐样本放置证据](../../build/xs/repcut-before-seed2-clang23-20261111/measurements/)。

模型/harness 完整构建、编译前后生成源码哈希复核、全部运行门、Python 编译检查、文档相对链接与 `git diff --check` 均通过。此次没有修改通用 pipeline/emitter 源码。
