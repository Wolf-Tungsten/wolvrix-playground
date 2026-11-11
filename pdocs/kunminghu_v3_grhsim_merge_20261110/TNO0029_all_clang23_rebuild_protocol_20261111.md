# TNO0029 三种模拟器统一 Clang 23 的重编译与对测口径

## 目的与版本

接续 [TNO0028](./TNO0028_seed2_clang23_recompile_20261111.md) 的编译器实验，回到 kunminghu-v3 merge 前后对照：单核 GSIM、单核 native GrhSIM、32 线程 RepCut GrhSIM，六份 emulator 的模型与 DiffTest harness 均用 **Clang 23.1.2** 重编译。

before 为 XiangShan `77ed568fc` / DiffTest `26af3a5e`，after 为 merge 后的 XiangShan `defb18e13` / 本地适配 DiffTest `b17a43a`。保持各自 DefaultConfig 和完整 DiffTest/NEMU。单核 GrhSIM 的历史两侧已使用 Clang 23，本次仍重新编译并在新窗口复测；历史 GSIM 与 RepCut 使用的是 Clang 19。

## 固定模型与构建方法

复用各自归档的生成 C++ 和 generated DiffTest headers，复制前后与编译后核对逐文件 SHA256。没有重做 Chisel、RTL frontend、GSIM 模型生成、分区或 C++ 发射。GSIM 生成器仍是此前 `reference/gsim` revision 的产物，它不参与 emulator 运行；本次更换的是全部运行代码的 C/C++ 编译器。

| 模式 | before 模型 | after 模型 | 模型编译口径 |
| --- | --- | --- | --- |
| GSIM 单核 | 原 before CHIRRTL 生成的 331 个 C++ 文件 | 原 after 的 410 个 C++ 文件 | 原 DiffTest GSIM 规则，`-O3`，无 PGO/BOLT |
| GrhSIM 单核 | 原 native before model | 原 native after model | `-std=c++20 -O3 -march=native`，保留 PCH 和生成 Makefile |
| RepCut 32 线程 | TNO0027 新 seed2 initial | 原 after retained seed7 initial | `-std=c++20 -O3 -march=native -pthread`，64-byte 对象代码节对齐 |

RepCut 使用已经选定的两份分区。before 此前多做过一轮 8-seed 搜索，after 仍沿用原选择，因此它代表当前两份冻结模型在统一编译器下的比较，不能解释为对两边重复相同次数随机分区得到的统计分布。没有在本轮自动 migration 或重新选分区。

GSIM 调用 `gsim-build-emu` 并禁止触发模型生成；native 和 RepCut 复用现有 compile/harness 规则。六次构建分阶段串行进行，单个构建内部正常并行。所有构建完成后才启动性能测量，避免本实验的编译进程与计时重叠。

## 验证与计时

统一 node030，单核 CPU96，RepCut CPU96–127，NUMA1 strict membind，关闭 ASLR；固定 CoreMark、100,000 周期、完整 NEMU DiffTest、8 对 AB/BA。不做外部 CPU 空闲准入检查，保留真实线程 affinity、NUMA 页、ASLR personality 与冻结输入验证。

单核复用现有 `grhsim_single_compare.py`：10k smoke、两组 100k DiffTest trace 覆盖验证、预热、8 对计时；跨 schema 使用各版本独立 NEMU 检查，共同比较终止条件、Guest cycles 与 workload 输出。各版本内部要求 PC/提交进度等功能签名稳定。正式 walltime 关闭 trace 和诊断计数。

RepCut 复用严格 performance Runner：10k smoke、100k DiffTest、预热、8 对计时，保持 code-page/preload、thread pinning、原 phase timing；逐次验证 32 个 singleton affinity 和 NUMA1 locality。前后 runtime 配置须相同，各版本内部签名稳定。

三组串行测量，分别报告 Host time 与外部 walltime、均值/中位数、逐对 delta、固定 seed 20261102 的 10,000 次配对 bootstrap 95% CI。不把不同测量组的时间混合成一个分布，也不把整版 merge 差异解释为单独的后端优化收益。

## 产物与执行入口

- [构建和测量脚本](../../build/artifacts/kunminghu-v3-clang23-retest-20261111/run.py)、[驱动日志](../../build/artifacts/kunminghu-v3-clang23-retest-20261111/driver.log)。
- [固定身份](../../build/xs/kunminghu-v3-clang23-retest-20261111/identity.json)、[构建与运行目录](../../build/xs/kunminghu-v3-clang23-retest-20261111/)。
- 每份 build 下的 `model-sources.json` / `generated-sources.json` 记录原件和副本 SHA；`compile-dry-run.log` 与 `compile.command.json` 记录单核编译规则；RepCut 的每个对象另有编译命令记录。

本记录形成于构建期间。三类完成后的功能和性能结果按独立文档追加，不覆盖原有 Clang 19 或先前 Clang 23 的实验结论。
