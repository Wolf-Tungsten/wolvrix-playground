# Chisel／Verilog 仿真表达研究

本工具用于广泛调查库与设计代码中的仿真表达机会，并复用真实 Chisel、RTL frontend
和 GrhSIM emitter 生成独立实例。它不会改写香山 RTL 或生产仿真配置。

研究记录从 [TNO0375](../pdocs/grhsim_opt_thj/TNO0375_chisel_simulation_pattern_survey_progress_20261029.md)
开始；第一批校准和反例见 [TNO0376](../pdocs/grhsim_opt_thj/TNO0376_chisel_pattern_first_microbench_20261029.md)。

## 工具与产物

- `scripts/chisel_pattern_catalog.py`：开放候选、源码检索入口、软件表达和语义边界。
- `scripts/chisel_pattern_findings.py`：逐候选的硬件目的、已有优化、实证结论和继续条件。
- `scripts/chisel_pattern_study.py`：源码覆盖、冻结生成包扫描、中文 Markdown／HTML 报告。
- `scripts/chisel_pattern_bench.py`：真实库编译、elaboration、GRH/C++ 发射和逐对实验。
- `scripts/chisel_pattern_results.py`：输入／二进制哈希校验、完整采样校验、机器码与 CSV 汇总。
- `scripts/chisel_pattern_frozen.py`：直接抽取冻结香山 MSHR count 表达式，保留分散槽位。
- `scripts/chisel_pattern_crc_control.py`：同一 binary、共同调用循环的 CRC 复核。
- `testcase/chisel-pattern-study/`：Scala wrapper、C++ 软件模型及差分/计时 harness。
- `grhsim32_pattern_emit`：可选构建目标，使用标准 GRH 和 emitter，无新的生产 IR 操作。

默认 artifact 约定为 `wolvrix/build/artifacts/chisel-pattern-study/`。每轮使用新的子目录，
保存 `scala_manifest.json`、原始 RTL、frontend GRH、归一化 GRH、C++、反汇编、
构建命令与哈希、逐对计时、验证结果和环境。已有研究轮次应保留，避免覆盖失败或反例。

## 复现

先具备当前 XiangShan Mill 依赖和已编译的 classpath。研究驱动从
`testcase/xiangshan/out/xiangshan/` 读取现有 Mill classpath，不改写其构建文件；实际调用的
utility 源码会与 wrapper 一起重新编译，Chisel jar 和源文件身份保存到 manifest。

```bash
cmake -S tools/grhsim32 -B build/grhsim32-tools
cmake --build build/grhsim32-tools --target grhsim32_frontend grhsim32_pattern_emit -j16

python3 scripts/chisel_pattern_bench.py all \
  --output wolvrix/build/artifacts/chisel-pattern-study/new-run \
  --jobs 4 --cpu 96 --loops 16

python3 scripts/chisel_pattern_frozen.py \
  --output wolvrix/build/artifacts/chisel-pattern-study/new-frozen-count --cpu 96

python3 scripts/chisel_pattern_crc_control.py \
  --case wolvrix/build/artifacts/chisel-pattern-study/new-run/cases/crc16 \
  --output wolvrix/build/artifacts/chisel-pattern-study/new-crc-control --cpu 96

python3 scripts/chisel_pattern_study.py all \
  --output wolvrix/build/artifacts/chisel-pattern-study/new-survey \
  --bench wolvrix/build/artifacts/chisel-pattern-study/new-run \
  --frozen wolvrix/build/artifacts/chisel-pattern-study/new-frozen-count \
  --crc-control wolvrix/build/artifacts/chisel-pattern-study/new-crc-control
```

`--compiler`、`--build`、`--chisel-sources` 可覆盖本工作区默认值。编译使用 `-march=native`，
因此编译和测量应在同一型号 CPU 上进行。本次正式实验在 node030、CPU96；计时串行，
同一轮所有编译先结束。不要同时在同一 CPU 上运行其他研究基准。

只运行部分实验可以使用 `--cases popcount16 popcount64`。完整报告校验默认要求全部
注册实例完成；部分研究可以直接查看对应 case 的结果，不冒充完整报告。

默认 `--normalization postpartition` 执行当前生产分区后的 memory-write-coalesce 和
reg-to-mem，后者使用 VerilatorV1 profitability 策略、禁用 intent。`--normalization raw`
保留早期 frontend→activity→emitter 对照。两者都没有复现整个 32 分区的连接和通信。

## 怎样解读结果

1. **源码覆盖**是带哈希的词法扫描。字符串和嵌套注释被排除，未分类文件保留；它不是
   全设计 elaboration 调用图，也不证明每个文件已被人工逐行审阅。
2. **完整 eval**包含输入变化检测、调度、状态提交和输出物化。直连也有这类成本。
3. **组合计算体**从实际发射的 group 中逐字保留算式，去掉外层派发；仍包含 slot
   物化。所有输入验证它与原 eval 一致。两侧采用同一次函数调用 ABI。
4. **软件状态组件**维护自己的内部状态，每拍比较沿前/沿后输出。它不包含香山其他
   模块的传播和分区通信，也未证明所有内部波形都可被重建。
5. **冻结香山 count 子锥**保留真实 bool slot 索引。`packed_lower_bound` 不含打包成本，
   只能说明预先打包的潜力，不能当作直接替换收益。

每个一般实例两组种子、random/sparse/dense/toggle1/hold99 五种分布，每种 100,000
个向量或周期；有限输入空间另做穷举。状态例子还包含复位、满空、同拍入出队、索引
读写、CAM 重复键和直方图边界的定向序列。每种分布 8 对 AB/BA；输入生成在计时外，
输出 checksum 防止计算消失。变动范围和 IQR 与中位数一起保存。

分布名称描述主要输入形态，定向边界/协议序列会插入其中；histogram 的随机输入主要
取 0..55，使内部桶、underflow 和 overflow 都被覆盖。详细序列以 harness 为准。

这些是有限二态差分与特定参数的实验，不是四态形式证明、硬件 PPA 或整机 walltime。
尤其不能把某个 batch 的总时间按源码操作数量分配到 utility。

反汇编统计包含对齐 nop，不是运行时指令计数。不同 case 的绝对纳秒也不能直接相减：
CRC 复核中，保留相同生成计算体但改变调用上下文，查表收益就改变了。当前报告保留
这一反证，`findings.csv` 给每项记录明确处置；不能只挑最快的一轮作为优化结论。

三种粒度的接口、稳定绑定、状态事件、回退以及局部/完整前端工作边界，见
[双实现与自定义 IR 设计](../wolvrix/docs/emit/chisel-semantic-simulation.md)。

## 新增模式

目录不设置固定模式数量。新发现应增加源文件/符号入口、成本机制、已知优化和语义
边界。需要实验时，添加 Scala 参数实例和独立 C++ 参考实现，并说明是直接库调用、
结构缩小例子还是冻结生成代码。状态模型必须加入沿前与沿后验证，不可只匹配最终值。

报告会拒绝失败轮次、缺失/重复采样、错误的交替次序、非有限时间和被修改的实验输入
或二进制。测试：

```bash
PYTHONPATH=scripts python3 -m unittest -v scripts/test_chisel_pattern_study.py
python3 scripts/chisel_pattern_results.py <完整实验目录>
node scripts/test_chisel_pattern_report.mjs <report.html> <chromium> <浏览器产物目录>
```


## 2026-10-30：整机单线程基线的比较口径补充

后续整机实验采用 Wolvrix 专用完整 SimTop 单线程流程，运行固定 node030 CPU96。
[历史对照 TNO0384](../pdocs/grhsim_opt_thj/TNO0384_native_single_thread_historical_comparison_20261030.md)
发现两个必须随基线记录的条件：生成 Makefile 会给 Clang 23 自动加入
`-fno-slp-vectorize`；`membind=1` 没有迁移已有文件缓存中的远端代码页。
不能只保存调用者提供的 CXXFLAGS，也不能从 NUMA 命令行推断实际代码页位置。
[同字节代码页控制 TNO0385](../pdocs/grhsim_opt_thj/TNO0385_native_single_thread_code_page_locality_control_20261030.md)
保留原二进制，单独量化这个页面布局因素。

当前 `chisel_pattern_bench.py` 的微基准直接使用 `-O3 -march=native` 编译，
没有经由整机生成 Makefile 自动追加该 no-SLP 保护。已有微基准结果继续保留为其实际
编译条件下的实验；不能将其与带 no-SLP 的整机基线混称为相同生产编译条件。
后续生产口径的模式复测应冻结并记录**有效完整编译命令**、兼容 fixture 验证、
二进制身份和运行页面布局；需要比较编译策略时，另列实验，不与 Chisel 改写收益混合。


### 同日更新：按用户决定恢复默认 SLP

[TNO0386](../pdocs/grhsim_opt_thj/TNO0386_grhsim_generated_makefile_default_slp_20261030.md)
从 Makefile 生成器源头删除自动 no-SLP 规则。以后重新生成并编译的模型保留编译器
默认优化；上述 no-SLP 基线仍作为历史条件记录。Clang 的独立错误复现保留，后续
在编译器层修复，不用脚本覆盖或自动关闭优化来规避。性能实验仍须检查实际编译命令
和代码页位置，不能将旧 binary 的属性当作新构建属性。


### 单线程测量的 NUMA 验收入口

重测冻结 binary 使用 `scripts/grhsim_single_baseline.py measure --binary <emu> --output <新目录>`。
运行固定 CPU96，并从 sysfs 获取对应 NUMA 节点。测量阶段会把 emu、NEMU、输入和
动态依赖库复制为该节点上的独立文件缓存实例，校验哈希、prefault，并在仿真期间
每约 5 秒核对实际 maps/numa_maps。文件页、匿名状态页、必需库和 CPU/线程检查
有任一失败就停止，不把该样本纳入正式结果。

该入口可独立复用，完整 `all` 流程的测量阶段也采用相同验收。旧基线不能只靠补一个
`numactl --membind` 参数继续当作本地代码页运行；必须检查实际页面位置。
原生 ELF 系统装载器保留并单独统计。详细口径及复现命令见
[TNO0387](../pdocs/grhsim_opt_thj/TNO0387_native_single_thread_slp_local_numa_measurement_20261030.md)。


当前已完成的默认 SLP、本地 NUMA 单线程基线见
[TNO0388](../pdocs/grhsim_opt_thj/TNO0388_native_single_thread_slp_local_baseline_results_20261030.md)：
node030 CPU96、C100000 × 8，Host 均值 98.57875 秒，CV 1.04%，全部功能和页面检查通过。
后续比较复用该冻结 binary 与准备协议，并在当次环境配对重跑。


### IntrinsicExpr 的首次生成实验

[TNO0389](../pdocs/grhsim_opt_thj/TNO0389_intrinsic_expr_priority_encoder_verilog_20261030.md)
用独立 PriorityEncoder64 和 Scala Boolean 开关比较了常规 RTL 与
`IntrinsicExpr("circt_dpi_call", ...)` 的 Verilog 输出。前者为 63 条条件选择，后者为
组合 DPI 调用；顶层端口相同。直接使用自定义 intrinsic 名称被默认 firtool 拒绝。
7 位 DPI 标量返回也被拒绝，使用 32 位通道并取低 7 位后生成成功。
本轮严格停在 Verilog，没有实现函数或做新的仿真/性能结论。入口和源码见
[实验说明](../testcase/chisel-intrinsic/README.md)。
