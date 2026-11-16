# TNO0005：调度前合并 concat 中的同源连续 slice

本轮完成 TNO0004 的第一项优化。**GrhSIM walltime 降低 35.6065%，95% 配对 bootstrap CI [35.5013%, 35.7227%]，8/8 轮均更快。** 同一轮的 Verilator 对照表明，剩余 walltime 倍率为归一化 RTL Verilator 的 **1.5173 倍**、原始 RTL Verilator 的 **3.2442 倍**。

## 固定对照与结果

| 后端 | 进程 walltime 均值 | 仿真循环均值 |
| --- | ---: | ---: |
| 上一版 GrhSIM，含 indexed-concat 和 packed-scalar-slices | 7.473105 s | 7.439790 s |
| 新 GrhSIM，增加调度前 concat-slice 合并 | 4.812177 s | 4.779435 s |
| 归一化 RTL Verilator | 3.171653 s | 3.135461 s |
| 原始 RTL Verilator | 1.483320 s | 1.445465 s |

| 配对倍率，分子 / 分母 | walltime 均值 | 95% CI |
| --- | ---: | ---: |
| 新 GrhSIM / 上一版 GrhSIM | 0.643935 | [0.642773, 0.644987] |
| 新 GrhSIM / 归一化 Verilator | 1.517265 | [1.512762, 1.521102] |
| 新 GrhSIM / 原始 Verilator | 3.244243 | [3.235530, 3.252061] |

仅仿真循环降低 35.7582%，CI [35.6504%, 35.8767%]。全部数据来自本轮同一组八轮；不把历史均值混入 CI。此前 TNO0003 的 2.35/5.05 倍用于描述优化前的量级，本轮的剩余差距使用本轮 Verilator 样本计算。

node030、CPU96、NUMA1、ASLR disabled、单线程。四侧各预热一次，顺序按“旧 GrhSIM、新 GrhSIM、归一化 Verilator、原始 Verilator”与反序交替，固定八轮。每样本完整运行 CoreMark 十次迭代，重复数为 1；原始 Verilator 单次仍超过一秒。32 个正式样本均通过功能/placement，零重试、零剔除，CPU288 sibling 均记录为 100% idle。编译和 CTest 在正式计时前完成，perf 在计时结束后单独执行。

两种 GrhSIM 及归一化 Verilator 的源 RTL 相同；原始 Verilator 保留原 SV 数组结构，因此 3.24 倍同时包含前端路径与后端差异，不能全算作 GrhSIM 后端差距。

## 实现与语义边界

在 [redundant_elim.cpp](../../wolvrix/lib/transform/redundant_elim.cpp) 中扩展 concat 规则，随已有 `simplify` 默认执行。通用说明见 [redundant-elim 文档](../../wolvrix/docs/transform/redundant-elim.md)。规则不使用 CV32 型号、信号名、热点或运行结果来筛选。

`kConcat` 的输入按高位到低位排列。`kSliceStatic` 的唯一输入是源值，`sliceStart`/`sliceEnd` 是含端点的低/高位。对同一 SSA source 的相邻、连续片段：

```text
concat(x[31:24], x[23:16], x[15:8], x[7:0]) -> concat(x)  // x 宽度为 32
concat(prefix, x[23:16], x[15:8], suffix) -> concat(prefix, x[23:8], suffix)
```

完整源片段复用 source；部分片段生成一个 unsigned static slice。检查源和结果类型、slice 范围/位宽、concat 总宽度与循环依赖。不同源、间隙、重叠、重复位、反序或不合法区间不合并。concat 的输出 value、位宽、signedness、名称、端口均保留；旧 slice 不在该 rewrite 中删除，其他用户和可观测值继续读取原 slice。后续已有 DCE/CSE 决定是否能清理。

规则只处理纯位模式，不重算或移动 source 的寄存器/内存/effect 读取，也不解释 X/Z。保留 concat 输出类型使 signed source 不会改变后续扩展语义。它不修改 activity schedule 的事件传播算法、时钟门控、固定点收敛条件或 RAM 模型。

## 严格隔离这条规则

新增 [重放工具](../../testcase/cv32e40p-bench/simplify.cpp) 和 [比较脚本](../../scripts/cv32e40p_concat_compare.py)。流程是：

1. 读取 TNO0003 的冻结模型及更早冻结的 `run2/graph.json`。
2. 同一个 `cv32e40p_simplify` 可执行文件，分别通过 `LD_LIBRARY_PATH` 使用旧、新 Wolvrix 库，对同一图执行相同的 two-state SimplifyPass。
3. **两份图都使用 TNO0003 冻结的同一份 emitter 可执行文件和同一份旧库**生成。新库只用于简化阶段。
4. 控制图生成的所有 `.cpp` 与 TNO0003 逐文件 SHA 相同，因而基线直接复用该已冻结 binary。候选只重新编译新的图，Clang 23.1.2、`-O3 -march=native`、harness/固件/RTL/placement 保持一致。

`build.json` 记录两套 native 工具/库、输入图、控制图、新图、结构报告、编译器、binary、harness、Wolvrix patch 与 SHA。每次后续阶段重新验证身份。只构建并测试这一项结构规则，没有参数搜索、手工选图或根据计时结果更换候选。

## 生成代码的实际变化

| 结构 | 之前 | 之后 |
| --- | ---: | ---: |
| 两个 register bank concat，各自 operand 数 | 993 | 32 |
| 两个 CSR concat，各自 operand 数 | 194 | 8 |
| 第三个 CSR concat operand 数 | 18 | 3 |
| 持久 Boolean value slots | 3,142 | 1,038 |
| 持久 uint32 value slots | 207 | 128 |
| 持久 wide value slots | 8 | 0 |
| supernodes，含 compute/commit | 183 | 69 |
| compute/commit C++ 文件数 | 24 | 10 |
| scalar 比较源码位置 | 1,494 | 990 |
| packed 八项比较源码位置 | 212 | 0 |
| 显式 activity OR 源码位置 | 896 | 556 |
| compute/commit 源码 bytes | 4,206,342 | 1,596,518 |
| ELF `.text` bytes | 192,295 | 102,249 |

寄存器 bank 的选中区间已从数十个 bool slot 的逐 bit OR，变成两个 32-bit 值的组合。例如 [新 sched_0](../../build/cv32e40p/concat-slices-v1/grhsim_concat_slices/grhsim_Cv32Bench_sched_0.cpp) 1490 行起，以及 [新 sched_7](../../build/cv32e40p/concat-slices-v1/grhsim_concat_slices/grhsim_Cv32Bench_sched_7.cpp) 858 行起，简化为：

```cpp
case 1u:
    return (word_a & UINT64_C(0xffffffff)) |
           ((word_b & UINT64_C(0xffffffff)) << 32u);
```

这里仍使用原有 indexed-concat helper，变化来自其输入图；没有为该 register bank 新写专用 emitter。packed-slices 的命中数降为零也是图和调度变化后的结果，并非关闭该选项。

IR 总量与实际生成成本需要分开看。调度前 concat 从 1,168 降为 631，operations 从 44,615 降为 44,296，但 static slices 从 14,978 增为 15,196。默认 `keepDeclaredSymbols=true` 保留许多原来的命名 slice，同时部分片段合并会创建新宽 slice；后续实际使用、内联和调度形态才决定持久槽位。调度后的 register-read operations 也由 3,021 增至 3,438，许多会被内联。这些 IR 数量不能直接当作动态加载次数，更不能只凭总 operations 判定性能。

结构报告：[structure.json](../../build/cv32e40p/concat-slices-v1/structure.json)。两份图继续使用 153 个寄存器读源，保留完整 RTL RAM 和时钟门。

## PMU 与剩余热点

正式计时后，两个 GrhSIM binary 分别做一次 `perf stat` 和一次 `cycles:u` 采样。PMU running fraction 均 100%，199 Hz 采样 lost samples 均为 0；统计包含初始化/退出，按完整 guest cycles 归一化。

| 每模拟周期 | 旧 GrhSIM | 新 GrhSIM |
| --- | ---: | ---: |
| Host instructions | 20,846.64 | 14,294.09 |
| Host cycles | 6,911.20 | 4,465.75 |
| Branches | 848.23 | 567.80 |
| Branch misses | 2.1440 | 1.4511 |

指令量减少约 **31.43%**，IPC 从约 3.0164 提升到 3.2008，与仿真循环下降约 35.76% 的方向一致。这支持“减少物化 bit、拼装和通知”的结构解释；本轮没有逐类关闭这些操作，不能把收益精确拆成各类代码的百分比。

新版采样主要仍在 compute batch 0/1/5/3/7，占比约 16.33%/12.81%/11.79%/11.10%/10.76%；commit batch 9 约 7.34%。本次调度重新分组，batch 编号与旧版不同，不能按相同编号直接比较热点。初始化从约 7.74 ms 到 7.20 ms，主要收益发生在持续仿真。

新图简化约 1.03 s，旧库控制约 1.04 s；候选 emit/compile/link 为 2.24/19.73/1.25 s。只报告本次构建成本，不与不同缓存条件的历史构建速度比较。

这一步已经缩小差距，但同 RTL 的 1.52 倍仍值得继续定位。下一项仍是研究中间值和活动传播粒度；应先针对新模型重看实际读写/比较热点，再定义一个通用、语义可证明的改动。原始 RTL ingest/数组保留是另一个独立方向，本轮未混入。

## XiangShan 的适用范围

规则位于通用简化器，支持任意合法宽度、多个源、部分片段、signed source 和 X/Z；没有 CV32 特例。XiangShan 的字段拼接、Chisel Vec 或拆分后重组若保留同一 SSA 源，可直接满足同一规则；如果源已经被 clone、改写为 memory 或被其他 canonicalization 消除，实际命中会不同。

本轮没有重建 XiangShan，也没有改它的工作区、preset 或 assignment。TNO0003/TNO0004 的结构线索仍成立，但 CV32 的 35.61% 不能外推为 XiangShan 收益。

## 功能与测试

四侧 smoke 为 253 cycles；完整 CoreMark 为 3,376,065 cycles、exit 0。UART、所有预期 CRC、完成周期、有效总线事务完全一致。八份完整 trace 的各 workload SHA256 一致：

- smoke：`84e48e4a17e723b73c167a256a44ded549bd8f82d36cc5be4070554f40763fc0`
- CoreMark：`ed2b490886767aa74524a6dd15e708e8f2b231bc3886814af0ba4d1919b3e098`

四项 CTest 通过：`transform-concat-slices`、`transform-redundant-elim`、`transform-simplify`、`transform-dead-code-elim`。

新增 [concat-slices 回归](../../wolvrix/tests/transform/test_concat_slice_coalescing.cpp) 对九类图各测 signed/unsigned，每类 256 个确定性输入，其中一半包含 X/Z。用 SVInt 解释原图和简化后的图，核对 concat 输出、另一个 slice 用户和后续扩展；覆盖 32-bit 完整 bit 序列、129-bit 完整源、跨 64-bit 的部分片段、多个源、间隙、反序、重叠和重复位。额外五个不合法范围/宽度用例检查不发生合并。还检查 declared/output 元数据、多用户以及 simplify 收敛。

九项相关 Python 回归通过，包含后端倍率方向和功能门；`py_compile`、两仓 diff 检查和本记录相对链接检查通过。测试日志与源码身份见 [validation](../../build/cv32e40p/concat-slices-v1/validation/)。

## 复现

保留前几轮冻结目录，在 node030 本项目目录运行，输出目录必须是新目录：

```bash
cmake -S testcase/cv32e40p-bench -B build/cv32e40p/tools -DCMAKE_BUILD_TYPE=Release
cmake --build build/cv32e40p/tools --target cv32e40p_simplify \
  transform-concat-slices transform-redundant-elim transform-simplify transform-dead-code-elim -j16
ctest --test-dir build/cv32e40p/tools/grhsim32/wolvrix --output-on-failure \
  -R '^transform-(concat-slices|redundant-elim|simplify|dead-code-elim)$'
python3 scripts/cv32e40p_concat_compare.py build --output build/cv32e40p/concat-reproduce
python3 scripts/cv32e40p_concat_compare.py attach-verilator --output build/cv32e40p/concat-reproduce
python3 scripts/cv32e40p_concat_compare.py verify --output build/cv32e40p/concat-reproduce
python3 scripts/cv32e40p_concat_compare.py measure --output build/cv32e40p/concat-reproduce
python3 scripts/cv32e40p_concat_compare.py profile --output build/cv32e40p/concat-reproduce
python3 scripts/cv32e40p_concat_compare.py report --output build/cv32e40p/concat-reproduce
```

结果在 `build/cv32e40p/concat-slices-v1`。本轮仍使用 `thj/cv32e40p-grhsim-investigation-20261114` 分支，未新增提交。

## 产物索引

- [完整报告](../../build/cv32e40p/concat-slices-v1/report.json)、[逐轮 CSV](../../build/cv32e40p/concat-slices-v1/pairs.csv)、[测量策略](../../build/cv32e40p/concat-slices-v1/measurement-policy.json)
- [构建身份](../../build/cv32e40p/concat-slices-v1/build.json)、[源码 patch](../../build/cv32e40p/concat-slices-v1/wolvrix.patch)、[控制图](../../build/cv32e40p/concat-slices-v1/control.json)、[新图](../../build/cv32e40p/concat-slices-v1/candidate.json)
- [功能与 trace](../../build/cv32e40p/concat-slices-v1/functional.json)、[逐次样本及 placement](../../build/cv32e40p/concat-slices-v1/runs/)
- [相同 RTL Verilator summary](../../build/cv32e40p/concat-slices-v1/verilator-summary.json)、[原始 Verilator summary](../../build/cv32e40p/concat-slices-v1/verilator-original-summary.json)
- [旧 GrhSIM PMU](../../build/cv32e40p/concat-slices-v1/grhsim_baseline-stat.csv)、[新 GrhSIM PMU](../../build/cv32e40p/concat-slices-v1/grhsim_concat_slices-stat.csv)、[新 GrhSIM 热点](../../build/cv32e40p/concat-slices-v1/grhsim_concat_slices-perf.txt)
