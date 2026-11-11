# TNO0021 GSIM 合并前后补测

## 范围与冻结身份

本轮在 node030 补测单核上游 GSIM。before 为 XiangShan `77ed568fcb70eba6d06195ffaa57a87929dcda6d` 及原 gitlinks；after 为已完成合并的 `defb18e13c2e3a0e272b43b2eaccd1d4b16de9c0`。两侧各自跟踪的 DiffTest 分别是 `26af3a5eebc7fe96a08ff5b600cfefacfff35028` 和 `b17a43ad24ae2d137f263d667787d3968505b771`。本比较包含整个上游版本、DefaultConfig 和 DiffTest 变化，不解释为仿真器后端的独立优化收益。

共用 GSIM commit `a3ecb26aa0c18f55c7fbba20e7a9b9d14a25442a`，用 `/usr/bin/clang++` 19.1.1 构建一次；两侧 C++ emulator 也使用该编译器、`-O3`、无 PGO/BOLT、`GSIM=1`、`DefaultConfig` 和完整 DiffTest。

冻结输入：

| 输入 | SHA256 |
| --- | --- |
| CoreMark 两轮 workload | `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e` |
| NEMU reference | `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e` |
| GSIM 生成器 binary | `6b56c9edc42bf1eb1d2f08402e021b950f49d75424ab6048461e2964a8c9f0ac` |

完整身份见 [初始记录](../../build/artifacts/kunminghu-v3-gsim-followup-20261111/logs/identity-initial.json)，输入保存在 [inputs](../../build/artifacts/kunminghu-v3-gsim-followup-20261111/inputs/)。

## 运行口径

单核固定 CPU96、NUMA node 1 严格 membind，使用 setarch -R 关闭 ASLR。不做 CPU 外部占用准入检查；每次运行实际检查 affinity、线程数、personality 和内存 locality。trace/诊断关闭的正式样本采用 100,000 周期上限、8 对交替 AB/BA；功能阶段先做 10k smoke、每侧独立 100k NEMU 检查和预热。

同版本要求 PC、指令数、周期数、Guest cycles 和 workload 输出稳定。跨版本只要求共同的终止条件、Guest cycles、workload 输出一致；不同 DiffTest schema 的 trace 分别解析并检查覆盖，不做跨 schema 字节比较。每个样本的 Host time 与外部 walltime 都保留；统计使用固定 seed 的 10,000 次配对 bootstrap。未通过门检查的样本留档但不进入统计。

## 构建进度记录

before 使用隔离 worktree 和原始递归 gitlinks。旧版 canonical `make gsim GSIM=1` 先经过 sim-verilog 并保留 CHIRRTL；after canonical gsim 目标使用 sim-chirrtl。两侧都向同一个 GSIM 生成器输入 SimTop.fir。

before 已完成约 2.50 GB CHIRRTL 的 GSIM 转换，总生成耗时约 1,400.383 s，生成 331 个模型 C++ 文件。第一次 harness 编译因旧 DiffTest 把 generated-src 默认为独立 BUILD_DIR 而找不到 difftest-state.h；生成头实际在 NOOP_HOME/build/generated-src。已显式设置 GEN_CSRC_DIR 和 GEN_VSRC_DIR，保留生成结果并重试编译，不改变模型语义或 DiffTest schema。

本节为构建阶段记录，不包含尚未完成的性能结论。后续结果以追加章节记录。

原始记录：[before 构建](../../build/artifacts/kunminghu-v3-gsim-followup-20261111/logs/gsim-before-build.log)、[before C++ 编译](../../build/artifacts/kunminghu-v3-gsim-followup-20261111/logs/gsim-before-compile.log)、[冻结执行脚本](../../build/artifacts/kunminghu-v3-gsim-followup-20261111/run-followup.py)。

## 增量：编译与计时阶段调度

before binary 已链接完成，并通过一次独立 10k NEMU 功能探测；该探测发生在构建阶段，不作为性能样本。after GSIM 已完成生成，生成器总耗时 1,689.227 s，写出 410 个 C++ 文件。

after 最后一个翻译单元 SimTop3.cpp 包含一个约 46,475 行的生成函数。一次 3 秒编译器采样显示主要开销在 LLVM GVN / TypeBasedAA 调用链。保留相同 Clang 19.1.1 和 -O3 参数；未通过降低优化等级或修改生成代码来改变比较条件。

为先完成已冻结的 GrhSIM 对测，在确认该编译进程身份后将其 SIGSTOP，串行运行单核和 RepCut GrhSIM，再通过 finally 恢复编译，随后运行 GSIM 对测。计时前后检查编译进程保持 stopped 状态。因此没有本次编译 CPU 负载与正式样本重叠；after 构建的外部 elapsed time 包含暂停，不能拿来比较构建速度。

证据：[阶段调度](../../build/artifacts/kunminghu-v3-gsim-followup-20261111/phase-scheduling.json)、[串行调度脚本](../../build/artifacts/kunminghu-v3-gsim-followup-20261111/run-ready-measurements.py)、[编译器采样](../../build/artifacts/kunminghu-v3-gsim-followup-20261111/logs/after-compile-perf-report.txt)。两侧 DiffTest 生成接口已复制到 [冻结接口目录](../../build/artifacts/kunminghu-v3-gsim-followup-20261111/difftest-generated/manifest.json)，node030 工具链文件哈希见 [toolchain-node030.json](../../build/artifacts/kunminghu-v3-gsim-followup-20261111/toolchain-node030.json)。

## 增量：功能门与 8 对正式计时结果

after GSIM binary 已成功链接，大小 67 MiB；before/after 两侧各完成 10k smoke、seed 0/1 的 100k 独立 NEMU DiffTest 和 trace 覆盖检查。每侧两个 seed 的签名稳定，跨版本共同签名为 Guest cycles=100001、stop_reason=cycle-limit、UART Running CoreMark for 2 iterations。before 的典型提交为 pc=0x80000b40、instrCnt=238550、cycleCnt=99998，after 为 pc=0x80000c10、instrCnt=250845、cycleCnt=99997；这些 revision-specific 进度差异不参与跨版本等价判断。两侧 CPU96、单线程、NUMA1 locality 和 ASLR 检查均通过。

8 对 AB/BA、16 个正式样本全部通过功能与放置门。正式样本关闭 trace/诊断，仍使用完整 DiffTest/NEMU；构建、smoke、trace 和预热时间不进入统计。正数表示 after 更慢。

| 指标 | before 均值 / 中位数 (s) | after 均值 / 中位数 (s) | 配对 delta 均值 / 中位数 | bootstrap 95% CI |
| --- | ---: | ---: | ---: | ---: |
| Host time | 80.252 / 80.111 | 108.151 / 108.247 | +34.774% / +34.850% | [+33.872%, +35.624%] |
| 外部 walltime | 80.303 / 80.166 | 108.188 / 108.284 | +34.777% / +34.850% | [+33.874%, +35.626%] |

after 更快 0/8 对。本轮 Host time 区间完全高于零，合并后 GSIM 单核更慢。这是包含上游微架构、DefaultConfig 和 DiffTest 版本的整版比较，不能解释为 GSIM 后端的隔离优化收益。

逐对数据：

| 对（原始索引 + 1） | 顺序 | before Host (s) | after Host (s) | Host delta | before 外部 (s) | after 外部 (s) |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | AB | 79.629 | 106.813 | +34.14% | 79.653 | 106.844 |
| 2 | BA | 106.721 | 79.326 | -25.69% | 106.752 | 79.351 |
| 3 | AB | 79.227 | 107.857 | +36.14% | 79.251 | 107.891 |
| 4 | BA | 108.636 | 81.950 | -24.56% | 108.667 | 81.975 |
| 5 | AB | 81.587 | 108.855 | +33.42% | 81.613 | 108.888 |
| 6 | BA | 110.028 | 80.646 | -26.70% | 110.061 | 80.671 |
| 7 | AB | 80.592 | 108.932 | +35.16% | 80.617 | 108.964 |
| 8 | BA | 107.364 | 79.060 | -26.34% | 107.400 | 79.086 |

AB/BA 的逐对 delta 按执行顺序直接计算；汇总 delta 使用每对的 A/B 标签，因此结论不受交替顺序影响。证据：[summary](../../build/xs/kunminghu-v3-gsim-followup-20261111/gsim-single/summary.json)、[逐对 JSON](../../build/xs/kunminghu-v3-gsim-followup-20261111/gsim-single/pairs.json)、[逐对 CSV](../../build/xs/kunminghu-v3-gsim-followup-20261111/gsim-single/pairs.csv)、[trace seed 0](../../build/xs/kunminghu-v3-gsim-followup-20261111/gsim-single/trace-s0.json)、[trace seed 1](../../build/xs/kunminghu-v3-gsim-followup-20261111/gsim-single/trace-s1.json)、[运行 manifest](../../build/xs/kunminghu-v3-gsim-followup-20261111/gsim-single/manifest.json)。

## 增量：8 对正式计时结果

8 对 AB/BA、16 个正式样本全部通过功能与放置门。所有通过门的慢样本均保留；诊断、预热和构建时间不进入统计。正数表示 after 更慢。

| 指标 | before 均值 / 中位数 (s) | after 均值 / 中位数 (s) | 配对 delta 均值 / 中位数 | bootstrap 95% CI |
| --- | ---: | ---: | ---: | ---: |
| Host time | 80.252 / 80.111 | 108.151 / 108.246 | +34.774% / +34.850% | [+33.872%, +35.624%] |
| 外部 walltime | 80.277 / 80.135 | 108.183 / 108.279 | +34.773% / +34.847% | [+33.869%, +35.624%] |

after 更快 0/8 对。本轮 Host time 区间完全高于零，合并后更慢。
这是各 revision 的 DefaultConfig 和所跟踪 DiffTest 的整体比较，不能解释为仿真器后端的隔离优化收益。

| 对（原始索引 + 1） | 顺序 | before Host (s) | after Host (s) | Host delta | before 外部 (s) | after 外部 (s) |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | AB | 79.629 | 106.813 | +34.138% | 79.653 | 106.844 |
| 2 | BA | 79.326 | 106.721 | +34.535% | 79.351 | 106.752 |
| 3 | AB | 79.227 | 107.857 | +36.137% | 79.251 | 107.891 |
| 4 | BA | 81.950 | 108.636 | +32.564% | 81.975 | 108.667 |
| 5 | AB | 81.587 | 108.855 | +33.422% | 81.613 | 108.888 |
| 6 | BA | 80.646 | 110.028 | +36.433% | 80.671 | 110.061 |
| 7 | AB | 80.592 | 108.932 | +35.165% | 80.617 | 108.964 |
| 8 | BA | 79.060 | 107.364 | +35.801% | 79.086 | 107.400 |

证据：[summary](../../build/xs/kunminghu-v3-gsim-followup-20261111/gsim-single/summary.json)、[逐对 JSON](../../build/xs/kunminghu-v3-gsim-followup-20261111/gsim-single/pairs.json)、[逐对 CSV](../../build/xs/kunminghu-v3-gsim-followup-20261111/gsim-single/pairs.csv)、[运行 manifest](../../build/xs/kunminghu-v3-gsim-followup-20261111/gsim-single/manifest.json)。

## 勘误：BA 列归属与外部 walltime（2026-11-11）

“增量：功能门与 8 对正式计时结果”一节中的手工表存在记录错误：BA 行把执行顺序当成了 before/after 的列归属，且外部 walltime 汇总抄写不准确。该节的逐对表、外部 walltime 行，以及“逐对 delta 按执行顺序直接计算”的说明作废。原始日志、pairs.csv、pairs.json、summary.json 和 report.json 不受影响；其后的“增量：8 对正式计时结果”由脚本按 A=before、B=after 标签生成，数值正确。

统一口径是每对均计算 100 × (B/A − 1)，AB/BA 仅决定执行先后。BA 四对的 Host delta 依次为 +34.535%、+32.564%、+36.433%、+35.801%，都表示 after 更慢。

正确的外部 walltime 均值为 before 80.277228 s、after 108.183336 s；配对平均 +34.772737%，95% CI [+33.869017%, +35.623554%]。Host time 配对平均 +34.774273%，95% CI [+33.871760%, +35.624002%]，结论保持不变。

本轮最终校验：88 项相关 Python 测试通过，三组分别完成 8 对有效样本，未有被功能或放置门拒绝的正式样本；node030 本任务进程均已退出。各 binary、CHIRRTL、生成 C++、schema 和递归子模块身份见 [GSIM before manifest](../../build/artifacts/kunminghu-v3-gsim-followup-20261111/model-manifests/gsim-before.json)、[GSIM after manifest](../../build/artifacts/kunminghu-v3-gsim-followup-20261111/model-manifests/gsim-after.json)，最终检查见 [final-verification.json](../../build/artifacts/kunminghu-v3-gsim-followup-20261111/final-verification.json)。
