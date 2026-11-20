# TNO0018：CV32E40P 使用 XiangShan 单模型默认配置的性能

CV32E40P 的同一份 CoreMark 固件在 XiangShan 默认入口下平均耗时 **3.663 s**，在 CV32 基线入口下为 **2.470 s**。八轮同轮配对的 walltime 平均增加 **48.31%**，95% bootstrap 区间为 [+47.36%, +49.13%]，8/8 轮均慢。[逐轮原始秒数](./data/TNO0018_cv32_xs_defaults.csv)

| 入口 | eager 阈值 | x86 内存 cmov 开关 | 平均 walltime | 平均仿真循环时间 | 仿真吞吐（百万 guest cycle/s） |
| --- | ---: | --- | ---: | ---: | ---: |
| CV32 基线 | 0 | 关 | 2.470 s | 2.438 s | 1.385 |
| CV32 | 4096 | 开 | 2.530 s | 2.497 s | 1.352 |
| XiangShan | 0 | 关 | 3.742 s | 3.708 s | 0.910 |
| XiangShan 默认 | 4096 | 开 | 3.663 s | 3.629 s | 0.930 |

吞吐按 3,376,065 个 guest cycle 除以 harness 的平均仿真循环时间计算。walltime 包含进程启动和初始化。各行的模型与 harness 均使用同一版本的 Clang 和基础编译参数。[八轮统计](../../build/armor-cv32-xs-defaults-v1/summary.json)

## 两项表达式优化的作用

| 同轮比较 | 配对 walltime 变化 | 95% 区间 | 方向一致的轮数 |
| --- | ---: | ---: | --- |
| XiangShan 入口，开相对关 | −2.09% | [−2.25%, −1.89%] | 8/8 快 |
| CV32 入口，开相对关 | +2.41% | [+1.72%, +2.96%] | 8/8 慢 |
| 两项都关，XiangShan 相对 CV32 | +51.48% | [+50.60%, +52.25%] | 8/8 慢 |
| 两项都开，XiangShan 相对 CV32 | +44.82% | [+44.35%, +45.19%] | 8/8 慢 |

两项都关闭时，两套入口的耗时差距已经存在。生成结果中，CV32 有 25 个 supernode、4 个调度源文件，XiangShan 有 80 个 supernode、6 个调度源文件。两个入口还使用了不同的前置变换和 event-region 设置。本轮只在各入口内部独立改变了 eager 和 cmov 的组合，无法量化每个调度参数对入口间差距的贡献。[入口配置差异](./TNO0017_single_model_expression_defaults_20261120.md) · [XiangShan 生成日志](../../build/armor-cv32-xs-defaults-v1/xs-default/emit.log)

## 输入与测量

- 使用 CV32 基准已冻结的规范化 `Cv32Bench.v`、harness 和 CoreMark 10 次迭代固件。CV32 两组复用 TNO0017 在该 RTL 对应图上生成的模型源码。XiangShan 两组从这份 RTL 运行正式的 `wolvrix_xs_grhsim.py`，默认组未设置两个表达式选项，关闭组只将其设为 0。四份模型在 node030 重新编译，基础参数统一为 Clang 23.1.2 的 `-std=c++20 -O3 -march=native`。cmov 参数仅用于两组开启配置的模型编译。[输入与编译器身份](../../build/armor-cv32-xs-defaults-v1/policy.json) · [复现脚本](../../scripts/armor_cv32_xs_defaults.py)
- 四组都通过 smoke 和 CoreMark，退出码、UART、CRC、周期数均与 Verilator 参考匹配。smoke 的 253 周期及 CoreMark 的 3,376,065 周期都逐周期记录总线，全程轨迹 SHA-256 各自与参考一致。正式计时关闭轨迹采集。[功能核对](../../build/armor-cv32-xs-defaults-v1/traces.json)
- 单线程绑定 node030 CPU 96、NUMA 1，关闭 ASLR，使用共享测量锁。各组预热一次，八轮中每组在每个顺序位置各出现两次。32 个正式样本均通过启动和结束时的放置检查。第一轮 CV32 基线的 SMT 同胞空闲率为 93.65%，其余 31 个样本为 100%，统计保留全部样本。配对百分比取八个同轮耗时比的均值，区间按轮重采样 10,000 次。[顺序与放置记录](../../build/armor-cv32-xs-defaults-v1/rounds.json)
