# TNO0015：成排累加默认开启后的 XiangShan 性能回归

**默认开启后，CoreMark 10 万周期的平均 walltime 从 113.71 秒降至 102.42 秒，每次省 11.29 秒。八轮同轮配对平均下降 9.93%，95% 区间 [−10.49%, −9.35%]，8/8 轮更快。**

| 配置 | 累加槽数 | 平均 walltime | 平均 Host time | walltime 相对关闭 |
| --- | ---: | ---: | ---: | ---: |
| 显式关闭 | 0 | 113.71 s | 113.65 s | 基准 |
| 默认开启 | 32,454 | 102.42 s | 102.36 s | −9.93% |

仿真器上报的 Host time 配对变化为 −9.94%，95% 区间 [−10.50%, −9.36%]。两种计时口径的平均降幅相差约 0.01 个百分点。[逐轮原始秒数](./data/TNO0015_default_bank_pairs.csv) · [统计复算](../../build/armor-acc-default-v1/perf-regression/verified-stats.json) · [复算脚本](../../scripts/armor_acc_default_results.py)

| 轮次 | 顺序 | 关闭（s） | 默认（s） | 同轮变化 |
| ---: | --- | ---: | ---: | ---: |
| 1 | 关→开 | 110.78 | 98.39 | −11.18% |
| 2 | 开→关 | 112.83 | 102.55 | −9.11% |
| 3 | 关→开 | 113.80 | 104.15 | −8.48% |
| 4 | 开→关 | 113.57 | 102.64 | −9.62% |
| 5 | 关→开 | 115.00 | 102.86 | −10.56% |
| 6 | 开→关 | 115.04 | 102.76 | −10.68% |
| 7 | 关→开 | 114.78 | 103.17 | −10.11% |
| 8 | 开→关 | 113.84 | 102.84 | −9.67% |

关闭先跑的四轮平均下降 10.08%，默认先跑的四轮平均下降 9.77%。TNO0014 的默认可执行文件在轮前和轮后分别耗时 99.89 秒和 102.64 秒，这两次单次测量只用于观察本机时间波动。[完整记录](../../build/armor-acc-default-v1/perf-regression/timing/summary.json)

## 对照与测量口径

本轮用正式单模型生成入口比较两个配置。A 设置 `WOLVRIX_XS_GRHSIM_ACCUMULATE_BANK=0`，B 使用默认值。每种配置从自己的 pre-reg-to-mem 检查点继续调度、生成 C++。两份检查点由同一批 2,146 个 RTL 输入生成，A 按普通规则打包，B 在打包时保留候选计数器。两组均关闭提交分组。[默认变更](./TNO0014_accumulate_bank_default_20261120.md) · [输入校验](../../build/armor-acc-default-v1/perf-regression/build-inputs.json)

重新生成 B 后，140 个 C++、头文件和 Makefile 中有 4 个调度文件与 TNO0014 的已验证模型有差异，涉及少量值变化检测和读者通知。新旧 B 的代码段分别为 88,848,066 和 88,848,114 字节。主比较使用本轮 B。TNO0014 的可执行文件在八轮开始前和结束后各运行一次，单独记录。[默认组重新生成](../../build/armor-acc-default-v1/perf-regression/default-emit.log) · [源码与可执行文件身份](../../build/armor-acc-default-v1/perf-regression/default-identity.json)

A 的检查点与 TNO0013 的全关检查点 SHA-256 相同。从检查点往后，两轮采用各自的生成入口，例如本轮两组都开启了 `split_oversize_compute_nodes`，TNO0013 的实验驱动将其关闭。此前的 −9.09% 是历史配对结果，本轮节省量按当前 A、B 的同轮耗时计算。[检查点哈希](../../build/armor-acc-default-v1/perf-regression/matched-checkpoints.json) · [TNO0013](./TNO0013_commit_group_and_accumulate_bank_20261120.md) · [此前的生成驱动](../../scripts/armor_acc_emit.cpp)

固定负载为单核 XiangShan DefaultConfig 的 CoreMark 10 万周期窗口，DiffTest 开启。性能进程单线程绑定 node030 的逻辑 CPU 96，内存绑定 NUMA 1，关闭 ASLR。每组预热一次，正式计时八轮，每轮两组相邻运行，奇数轮 A→B，偶数轮 B→A。主指标是从启动到进程退出的 walltime，包含 harness 和 NEMU。表内秒数取算术平均，相对变化取八个同轮 `100 × (B/A − 1)` 的均值。95% 区间来自固定种子 20261102 的 10,000 次配对 bootstrap。[测量入口](../../scripts/grhsim_single_compare.py) · [实验脚本](../../scripts/armor_acc_default_regression.py)

## 功能与放置核对

- 两组的生成脚本使用 TNO0014 的工具构建、RTL 清单和冻结检查点。功能核对脚本复用 TNO0013 的 DiffTest 轨迹与计数器参考输出。[生成关闭组](../../scripts/armor_acc_default_build_off.sh) · [重新生成默认组](../../scripts/armor_acc_default_reemit.sh) · [编译与核对](../../scripts/armor_acc_default_verify.py)
- node030 上 seed 0 和 1 的 DiffTest 比较各覆盖 99,999 条记录。16 个正式样本均在相同 PC `0x80000c1a` 停止，提交 250,838 条指令，通过 CPU、线程数和 NUMA 检查。SMT 同胞 CPU 288 的样本内空闲率最低为 99.64%。[seed 0](../../build/armor-acc-default-v1/perf-regression/timing/trace-s0.json) · [seed 1](../../build/armor-acc-default-v1/perf-regression/timing/trace-s1.json) · [测量策略与模型哈希](../../build/armor-acc-default-v1/perf-regression/policy.json)
- 两组在 node029 的独立功能运行均与同一份参考轨迹和期末 dump 匹配。计数器输出各有 35,063 行，其中 10,045 行非零，按包含重复次数的行内容比较。正式计时未开启轨迹和强制 dump。[显式关闭核对](../../build/armor-acc-default-v1/perf-regression/off/verify/result.json) · [默认开启核对](../../build/armor-acc-default-v1/perf-regression/default-reemit/verify/result.json)
