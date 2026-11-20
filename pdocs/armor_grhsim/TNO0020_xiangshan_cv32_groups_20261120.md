# TNO0020：三组 CV32 开关在 XiangShan 单模型上的性能

在单核 XiangShan 上跑 CoreMark 的前 10 万周期，事件分组、条件 mux、寄存器视图三组全开，平均耗时从 **83.78 s 增至 86.60 s**，同轮平均 **+3.40%**，五轮都更慢。单开事件分组的耗时增加最多，为 **+14.85%**。MicroBench 同样长的窗口里，全开为 +0.66%，四对样本的区间跨零。这三组已接入 XiangShan，可独立开启，默认均关闭。[CV32 上的同组实验](./TNO0019_cv32_xiangshan_slowdown_causes_20261120.md)

## CoreMark

每轮在 node030 CPU 96 串行运行五个模型各一次。下表的秒数是外部 walltime 均值，百分比是候选与同轮默认模型的耗时比减一，再对五轮取均值。区间通过对五个配对比值有放回重采样 10,000 次得到。正数表示更慢。[逐轮秒数](./data/TNO0020_xiangshan_group_times.csv) · [统计结果](../../build/armor-xs-cv32-groups-v1/timing/summary.json)

| 配置 | 平均耗时 | 相对默认 | 95% 配对区间 | 比默认快的轮数 |
| --- | ---: | ---: | ---: | ---: |
| 当前 XiangShan 默认 | 83.78 s | 基准 | — | — |
| 只开事件分组 | 96.13 s | +14.85% | [+6.68%, +20.50%] | 1/5 |
| 只开条件 mux | 85.83 s | +2.47% | [+1.36%, +3.42%] | 0/5 |
| 只开寄存器视图 | 83.58 s | -0.22% | [-1.11%, +0.68%] | 3/5 |
| 三组全开 | 86.60 s | +3.40% | [+2.26%, +4.80%] | 0/5 |

只开事件分组的波动最大。前四轮用了 97.56–101.04 s，第五轮用了 84.60 s，同轮默认是 85.03 s。第五轮的执行终点、CPU 和 NUMA 核查均通过，表中保留了这一轮，较短耗时的来源尚未确定。在这份事件调度上再加条件 mux 和寄存器视图，相对只开事件分组的同轮平均耗时下降 9.52%。这解释了三组全开的回退比单开事件分组小。[第五轮运行记录](../../build/armor-xs-cv32-groups-v1/timing/events/runs/round5.json)

各组先预热一次，交错运行五轮，每个模型在五个顺序位置上各出现一次。整个测量使用同一把 CPU 96 锁，单线程、NUMA 1、ASLR 关闭、seed 0、运行时 NEMU DiffTest 开启。正式样本的 SMT 同胞 CPU 288 最低空闲率为 99.59%。两种负载都按周期上限截止。[测量驱动](../../scripts/armor_xs_cv32_groups/measure.py) · [轮次顺序与输入](../../build/armor-xs-cv32-groups-v1/timing/policy.json)

## MicroBench

同样取前 10 万个周期，默认模型平均 **80.88 s**，全开平均 **81.42 s**。四轮同轮耗时变化均值 **+0.66%**，配对 bootstrap 的 95% 区间 **[−0.21%, +1.53%]**。一轮更快，三轮更慢，这个窗口无法分辨稳定的方向。

两组在 node029 CPU 101、NUMA 1 上分别预热一次，正式计时按 AB、BA、AB、BA 交替，ASLR 关闭。SMT 同胞 CPU 293 在正式样本内最低空闲率为 97.52%。默认和全开均停在 `0x80000446`，提交 138,514 条指令，99,999 条 DiffTest 记录的轨迹文件逐字节匹配同一冻结参考。[四对原始秒数](./data/TNO0020_xiangshan_group_times.csv) · [MicroBench 驱动](../../scripts/armor_xs_cv32_groups/microbench.py) · [MicroBench 统计](../../build/armor-xs-cv32-groups-v1/microbench/summary.json) · [全开轨迹核对](../../build/armor-xs-cv32-groups-v1/microbench/full/trace.json)

## 生成代码的变化

一个计算组是调度器能单独激活和执行的一组组合逻辑。跨组值需要保留给其他组使用。每条激活边表示一个值变化后需要通知一个使用它的组。

| 配置 | 计算组 | 跨组值 | 跨组激活边 | 条件 mux 处数（含输入缓存） | 识别到的寄存器视图 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 默认 | 75,692 | 1,207,694 | 2,387,296 | 0 | 0 |
| 只开事件分组 | 83,211 | 1,126,910 | 2,203,761 | 0 | 0 |
| 只开条件 mux | 75,692 | 1,207,694 | 2,387,296 | 11,297（229） | 0 |
| 只开寄存器视图 | 75,692 | 1,207,694 | 2,387,296 | 0 | 2,191 |
| 三组全开 | 83,211 | 1,126,910 | 2,203,761 | 11,448（190） | 2,644 |

事件分组收进了 13 个单终点区域和 9,763 个共享区域。在重新分组时，调度器还细分了 1,850 个原有组来消除依赖环。最终跨组值减少 6.69%，激活边减少 7.69%，计算组增加 9.93%。五种配置的提交组都是 347 个。XiangShan 的计算 node 和 supernode 上限均为 108，超大 node 拆分开关开启，实际拆分数为 0。[原始结构统计](../../build/armor-xs-cv32-groups-v1/models.json) · [全开调度日志](../../build/armor-xs-cv32-groups-v1/full/emit.log) · [共享分组规则](../../wolvrix/docs/transform/activity-shared-event-regions.md)

## 每个仿真周期的宿主机工作量

另在 node029 固定一个核心，对相同可执行文件各跑一次 CoreMark，以 `perf stat` 记录整个进程的用户态事件，除以模拟器报告的 100,001 个 guest cycles。最后一列表示 L2 向指令缓存提供的 64 字节缓存行数。计时样本均单独运行。[原始 PMU 数据](../../build/armor-xs-cv32-groups-v1/full/pmu/stat.csv) · [采集脚本](../../scripts/armor_xs_cv32_groups/count.py)

| 配置 | 退休指令 | 退休分支 | 分支预测失败 | 从 L2 填入指令缓存的行数 |
| --- | ---: | ---: | ---: | ---: |
| 默认 | 3,569,908 | 278,914 | 22,593 | 19,835 |
| 只开事件分组 | 3,534,209 | 286,188 | 22,865 | 18,691 |
| 只开条件 mux | 3,508,809 | 281,740 | 24,105 | 25,402 |
| 只开寄存器视图 | 3,567,338 | 278,897 | 22,555 | 20,648 |
| 三组全开 | 3,457,393 | 288,944 | 24,707 | 26,119 |

单开寄存器视图时，匹配到 2,191 个值，每周期退休指令仅少 0.07%。单开条件 mux 时，退休指令少 1.71%，预测失败多 6.70%，从 L2 填入指令缓存的行数多 28.07%。三组全开后，这三项分别为 −3.15%、+9.36%、+31.68%。这些变化在同一个窗口内同时发生。

## 三组开关

可用下面的命令对 XiangShan 单模型启用全部三组。每组都可以单独设为 `1` 或 `0`。省略组开关时，调度与生成沿用原先的配置。显式设置某个生成组会覆盖该组内的底层环境变量。[XiangShan 生成入口](../../scripts/wolvrix_xs_grhsim.py)

```sh
make xs_wolf_grhsim_emu \
  WOLVRIX_XS_GRHSIM_EVENT_REGIONS=1 \
  WOLVRIX_XS_GRHSIM_CONDITIONAL_MUX=1 \
  WOLVRIX_XS_GRHSIM_COVERED_STATE_VIEWS=1
```

基准脚本在 `build` 或 `emit` 时接受 `--event-regions --conditional-mux --covered-state-views`。三项均支持 `--no-` 前缀。[基准入口](../../scripts/grhsim_single_baseline.py)

| 组 | 实际启用的规则 |
| --- | --- |
| 事件分组 | `event_regions`、`event_regions_shared`、`event_regions_shared_connected` |
| 条件 mux | `conditional_mux_cones`、`conditional_mux_input_cache`、`conditional_mux_shared_arm` |
| 寄存器视图 | `covered_state_view_notifications`、`covered_state_view_inline`、`covered_state_view_composition`、`covered_state_view_composition_inline` |

## 构建与正确性

五个模型从同一个单核 `DefaultConfig`、`SimTop` 的 pre-reg-to-mem 检查点生成。全部采用成排累加、eager 阈值 4096 和 x86 内存 cmov，使用 Clang 23.1.2、模型 `-O3 -march=native` 和相同的 DiffTest harness。显式关闭三组时，139 个生成的 C++ 源文件和头文件，以及模型 Makefile，均与 ARMOR 系列 TNO0017 的默认产物逐字节相同，计时对照复用该可执行文件。[输入身份](../../build/armor-xs-cv32-groups-v1/inputs.json) · [对照核验](../../build/armor-xs-cv32-groups-v1/base/control.json) · [生成与编译](../../scripts/armor_xs_cv32_groups/build_models.py)

功能检查单独运行。五个版本在 CoreMark 的 10 万周期窗口均停在 `0x80000c1a`，提交 250,838 条指令。完整窗口的 99,999 条 DiffTest 记录按顺序比较有效字段，五份原始轨迹的 SHA-256 也与参考一致。结束时的 35,063 行性能计数器按内容和出现次数核对，五组均与参考相同。[逐模型核验](../../build/armor-xs-cv32-groups-v1/correctness/) · [核验脚本](../../scripts/armor_xs_cv32_groups/verify_model.py)

XiangShan 选项测试 36 项和基准入口测试 27 项均通过，覆盖每组独立开启、显式关闭和检查点恢复时的参数传递。[选项测试](../../build/armor-xs-cv32-groups-v1/test-options.log) · [基准测试](../../build/armor-xs-cv32-groups-v1/test-baseline.log)
