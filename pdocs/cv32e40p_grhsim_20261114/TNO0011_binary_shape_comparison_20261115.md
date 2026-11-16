# TNO0011：冻结 binary 形态与热点机器码对照

当前默认 GrhSIM / 归一化 RTL Verilator 的 CoreMark walltime 差距为 **1.4015 倍**；对原始 RTL Verilator 为 **2.9932 倍**。离线反汇编显示，在相同归一化 RTL 上，GrhSIM 的选定模型函数有更多静态指令、条件和比较操作；原始 RTL Verilator 与归一化 Verilator 之间另有显著代码形态差异。因此 2.99 倍不能全归因于 Wolvrix emitter。

本轮只分析冻结的 ELF 与已有 perf 样本；没有运行新的 workload、采样或性能对测，没有更改生产规则，也没有从结果中选优化候选。

## 输入身份与运行口径

三份 binary 来自同一 CV32E40P/CoreMark 构建集，使用 Clang 23.1.2 和相同 flags：`-std=c++20 -O3 -march=native -DNDEBUG -gline-tables-only`。各自原有功能记录均为 3,376,065 个 guest cycles、相同 CoreMark trace SHA256；既有 perf 样本都固定 node030 CPU96、单线程、ASLR disabled。上游 commit、30 个 RTL 输入、sv2v 输出、当前 GrhSIM graph、binary、采样、生成源文件及分析器 SHA 记录在 [inputs.json](../../build/cv32e40p/binary-shape-v9/inputs.json)。

这里固定的是同一份 CV32E40P 源 RTL 与 Verilator 所用的 sv2v 归一化 RTL（SHA256 `6513cc0a2984c6f74b589e06a33564a854b9cd8272cbdcedd73bd7912b684292`），不是相同的 Wolvrix post-frontend graph。当前 GrhSIM graph SHA256 为 `e1ccc2928b055e022eb5a7a6637265af19a762e8fdf964ad26ee5833b5f9191b`，其中包含已经采用的图变换。因此当前 GrhSIM / 归一化 Verilator 比值代表已配置 GrhSIM pipeline 与 Verilator pipeline 的差距，不能解释为严格隔离的 emitter-only 效应。

| 后端 | binary SHA256 | binary 大小 |
| --- | --- | ---: |
| 当前默认 GrhSIM | `9642e07f8a0add9eaf1b0962005f60aadc5e4d6ce8382622de99489cb8860037` | 33,864,768 B |
| 归一化 RTL Verilator | `5396106991546a7aa0da975a44e9b92c21988bf6a4d60d4755bdafa370be7614` | 1,327,688 B |
| 原始 RTL Verilator | `6b90343c3a7ff6fe9da056cb56decf995ea9757e22b4bf3b3846e3c8f53c1661` | 1,121,928 B |

三组 perf 数据是不同时间采集的；它们只用于各自 binary 内的热点排序和机器指令归属，不能把函数采样百分比当作跨 binary 的同步因果比较。性能比值与 PMU 汇总均复用既有结果，没有把 annotate 样本用于新 walltime 结论。

## 函数与 ELF 形态

| 后端 | ELF `.text` | ELF `.rodata` | 模型函数符号字节数 |
| --- | ---: | ---: | ---: |
| 当前默认 GrhSIM | 117,049 B | 33,572,034 B | 103,491 B |
| 归一化 RTL Verilator | 349,392 B | 52,967 B | 65,387 B |
| 原始 RTL Verilator | 281,936 B | 5,959 B | 44,932 B |

GrhSIM ELF 大，主要体现在 `.rodata`，不等于其热指令更多。`nm` 找到只读符号 `k_mem_init_ram_rows`，大小为 **33,554,432 B（32 MiB）**，是 RAM 初始化映像；它约占 `.rodata` 的 99.95%。即使只看相关模型函数，GrhSIM 机器码仍比归一化 Verilator 多 **58.2%**，比原始 RTL Verilator 多 **130.3%**。整体 `.text` 与模型函数字节数方向不同，说明不能用 ELF 总大小代替热代码大小。

当前 GrhSIM 的 profile 样本分布在 `eval_compute_batch_0..8` 和 `eval_commit_batch_9`：compute 函数各占其自身 profile 的 **4.55–12.96%**，commit 占 7.66%，`eval()` 占 4.38%。归一化 Verilator 的样本则集中于 `nba_sequent__TOP__0`（57.83%）和 `nba_comb__TOP__0`（24.49%）。原始 Verilator 的 `nba_sequent__TOP__0` 占 48.08%，其余落在多个组合、活动和 eval 函数。这些百分比只说明各 profile 内部的热点集中程度。

## 静态机器指令统计

GrhSIM 统计 `eval()`、全部 9 个 compute batch 和 commit；每份 Verilator 统计 profile 排名前 10 的函数。表中是这些符号反汇编出的静态指令，不是每个 guest cycle 实际执行的动态指令数。

| 选定函数合计 | GrhSIM | 归一化 Verilator | 原始 RTL Verilator |
| --- | ---: | ---: | ---: |
| 函数数 / 静态指令 | 11 / 20,614 | 10 / 13,657 | 10 / 10,662 |
| 条件分支 | 749 | 487 | 919 |
| 全部分支 | 1,655 | 730 | 1,432 |
| compare/test | 2,146 | 919 | 1,343 |
| cmov/setcc | 1,760 | 577 | 532 |
| memory operand 指令 | 8,842 | 5,237 | 2,868 |
| stack operand 指令 | 2,194 | 2,164 | 868 |
| vector/mask 指令 | 2,178 | 1,386 | 428 |

在该静态函数集合中，GrhSIM 相对归一化 Verilator 有 **1.51 倍**指令、**2.33 倍** compare/test、**3.05 倍** cmov/setcc 指令。计数器按 mnemonic 和 operand 格式分类；memory 项包含 stack 与 RIP-relative operand，vector/mask 包括 AVX 和 predicate-mask mnemonic。函数集合和类别定义并不等价于动态工作量，只适合描述产出的代码结构。

已有 PMU 样本给出的 Host instructions / guest cycle 为：GrhSIM **13,104.52**，归一化 Verilator **9,799.12**，原始 RTL Verilator **5,355.18**。对应比值是 **1.337 倍**和 **2.447 倍**。这是与上述静态形态方向一致的独立证据；样本不在同一时刻采集，不能据此精确分解 walltime。

## 热点指令与源码映射

`llvm-addr2line` 将最高 annotate 指令映射回带有 IR operation/value 注释的生成 C++。归档的每条热点记录包含指令地址、函数内 annotate 百分比、符号和源文件行。

- GrhSIM batch 1 的热点包含 `test`/`setne`，分别映射到 [sched_1.cpp:1613](../../build/cv32e40p/shared-equality-validated/grhsim_shared_equality/grhsim_Cv32Bench_sched_1.cpp:1613) 的 `kLogicNot` 运算和 [sched_1.cpp:1128](../../build/cv32e40p/shared-equality-validated/grhsim_shared_equality/grhsim_Cv32Bench_sched_1.cpp:1128) 的结果变化检查；[sched_1.cpp:1988](../../build/cv32e40p/shared-equality-validated/grhsim_shared_equality/grhsim_Cv32Bench_sched_1.cpp:1988) 的寄存器写使能 decode 也映射到 predicate-mask 移位指令。这与前面共享译码后仍保留逐值变化检查和活动通知的结构相符。
- GrhSIM batch 5 的最高单条样本指令为 `vmovdqu64` 到 stack，占该函数 annotate 的 31.69%，映射到 [sched_5.cpp:977](../../build/cv32e40p/shared-equality-validated/grhsim_shared_equality/grhsim_Cv32Bench_sched_5.cpp:977) 的 16-word 常量数组。它提示宽临时值/栈物化仍存在；该百分比只在 batch 5 函数内，不能解释为 31.69% 总运行时间。
- 归一化 Verilator 的主要 NBA 函数热点指令也有 `vmovdqu64` stack store，映射到 [root_0.cpp:9656](../../build/cv32e40p/run2/verilator/VCv32Bench___024root__0.cpp:9656) 的宽零填充。AVX-512/vector code 在两侧都存在，不是“GrhSIM 没有使用 SIMD”。
- 原始 Verilator 的热点分别落在 [root_0.cpp:2714](../../build/cv32e40p/run2/verilator-original/VCv32Bench___024root__0.cpp:2714) 的 sequential 函数和 [root_1.cpp:912](../../build/cv32e40p/run2/verilator-original/VCv32Bench___024root__1.cpp:912) 的组合控制表达式。

前两处与 TNO0008 的共享等值译码计数、TNO0009 的宽临时值分析互相印证，但 annotate 的单条指令采样会受 skid 影响，不能精确标出一条源码语句的成本。

## 区分后端与 RTL 归一化

当前配对 walltime 报告中，GrhSIM 相对归一化 Verilator 为 **1.4015 倍**（95% CI `[1.3995, 1.4033]`）；模拟循环时间比为 **1.4078 倍**。相对原始 RTL Verilator，walltime 为 **2.9932 倍**（95% CI `[2.9871, 2.9981]`），模拟循环时间为 **3.0528 倍**。GrhSIM initialization 均值约 6.89 ms，低于两份 Verilator 的约 9.97/10.56 ms；可见主要差距发生在模拟循环，不是 ELF 初始化。细节见既有 [shared-equality report](../../build/cv32e40p/shared-equality-validated/report.json)。

归一化 Verilator 本身的模型函数代码为 65,387 B，原始 RTL Verilator 为 44,932 B，增加 **45.5%**；整个 `.text` 也由 281,936 B 增至 349,392 B。两种 Verilator 使用相同编译器、参数和 harness，输入分别为归一化 RTL 与原始 RTL，因此这项差异属于 RTL 转换后产生的代码形态差异，不能归因于 Wolvrix。既有 Host instructions / guest cycle 也从 5,355 增至 9,799。该组程序的既有运行均值约为归一化 2.968 s、原始 1.390 s，但它不是本轮新建的第三组配对对测。

综合证据强弱：

1. **强证据：** 同一归一化图、相同工具链下，GrhSIM 每 guest cycle 的 Host 指令更多，模拟循环确实更慢；热点机器码映射到 GrhSIM 的 scalar change/notify、宽常量临时值和 Verilator 的宽表/组合函数。
2. **结构证据：** 所选 GrhSIM 函数有更多静态比较、条件选择和内存 operand，且模型函数字节数更大。这些特征与增加的指令量相符，但静态代码量本身不能证明执行频率。
3. **尚未证明：** 本轮没有同一时段 perf sample 的逐周期分布，也没有把某一类机器指令的退休数量和延迟隔离出来。因此不能说 `setcc`、vector spill 或任一 CSR/ALU 表达式单独造成 1.40 倍差距。原始 Verilator 的 2.99 倍差距还包含明显的 RTL 归一化影响。

## 复现与产物

重新运行时须指定一个尚不存在的输出目录；脚本会校验 manifest、源 RTL、归一化 RTL、当前 graph、binary SHA、功能 trace 和原有 profile 样本身份，随后只调用 `nm`、`llvm-objdump`、`perf annotate` 与 `llvm-addr2line` 做离线分析：

```bash
python3 scripts/cv32e40p_binary_shape.py \
  --output build/cv32e40p/binary-shape-recheck
PYTHONPATH=scripts python3 -m unittest -v test_cv32e40p_binary_shape
```

- [最终机器汇总](../../build/cv32e40p/binary-shape-v9/report.json)、[输入、工具、源 SHA](../../build/cv32e40p/binary-shape-v9/inputs.json)
- [三份反汇编](../../build/cv32e40p/binary-shape-v9/disassembly)、[既有 profile 的 annotate](../../build/cv32e40p/binary-shape-v9/annotations)
- [分析器](../../scripts/cv32e40p_binary_shape.py)、[解析回归](../../scripts/test_cv32e40p_binary_shape.py)

相关 4 项 parser/统计测试通过，`py_compile` 和 `git diff --check` 通过。此次没有重新执行性能测试。
