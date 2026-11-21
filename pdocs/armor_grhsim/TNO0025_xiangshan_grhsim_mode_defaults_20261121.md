# TNO0025　XiangShan 单模型 GrhSIM 的普通与 PGO 默认配置

`make xs_wolf_grhsim_emu` 从 `PGO_WORKLOAD` 选择生成与编译配置。普通版采用 TNO0023 中 CoreMark 四轮均更快的四寄存器块，PGO 版采用 TNO0024 两个负载复测过的联合配置。[入口及覆盖方法](../../README.md#xiangshan-single-model-grhsim) · [普通版选型](./TNO0023_grhsim_commit_pgo_partition_mux_20261121.md) · [PGO 复测](./TNO0024_xiangshan_gsim_grhsim_pgo_threeway_20261121.md)

| `PGO_WORKLOAD` | 计算超节点上限 | 每个数据比较块最多寄存器数 | 事件区域、条件 mux、covered state views |
| --- | ---: | ---: | --- |
| 未设置或空 | 108 个操作 | 4 | 三组关闭 |
| 训练镜像路径 | 160 个操作 | 16 | 三组开启，mux 门槛 16 个操作 |

两种配置的计算节点及拆分上限都是 108 个操作，每个数据比较块最多 16 字节。模型和 DiffTest harness 都以 `-O3 -march=native` 编译。设置训练镜像后再加 `WOLVRIX_XS_GRHSIM_PGO_GROUPS=0`，可复现原 PGO 的 108 上限、三组关闭、逐项提交。也可单独指定分组开关、容量、块宽和编译参数。

从同一份 TNO0017 XiangShan 检查点分别运行普通与 PGO 的 Make 入口，均使用 Clang 23.1.2。每套比对了 140 个模型构建输入和调度统计。PGO 与计时所用的 `joint` 逐字节一致。普通版与 `blocks` 的差异是 5,307 处连续写使能比较从临时零数组改为引用同一个静态零数组，数据比较块划分一致。[普通版生成物对照](../../build/armor-xs-mode-defaults-v1/ordinary/source-comparison.json) · [PGO 版生成物对照](../../build/armor-xs-mode-defaults-v1/pgo/source-comparison.json)

两套入口均完成构建。PGO 使用 CoreMark 训练 100,000 周期，合并后的 profile 含 1,077 个函数。用两个最终 `emu` 分别运行以下 100,000 周期窗口，四次的 99,999 条 DiffTest 记录逐条匹配冻结参考。CoreMark 的 35,063 行期末性能计数也完全匹配。40 项入口和选项测试均通过，包括 Make 命令行及环境变量对模型与 harness 编译参数的覆盖。[测试日志](../../build/armor-xs-mode-defaults-v1/options.log)

| 负载 | 终点退休指令数 | 普通版核对结果 | PGO 版核对结果 |
| --- | ---: | --- | --- |
| CoreMark | 250,838 | [通过](../../build/armor-xs-mode-defaults-v1/verify/ordinary/coremark/result.json) | [通过](../../build/armor-xs-mode-defaults-v1/verify/pgo/coremark/result.json) |
| MicroBench | 138,514 | [通过](../../build/armor-xs-mode-defaults-v1/verify/ordinary/microbench/result.json) | [通过](../../build/armor-xs-mode-defaults-v1/verify/pgo/microbench/result.json) |
