# TNO0039 编译器敏感度的函数采样与前后热点变化

## 目的与采样口径

接续 [TNO0038](./TNO0038_after_seed7_compiler_sensitivity_20261111.md)，定位 before seed2 的 Clang 23 收益，以及 after seed7 未获得类似收益的具体原因。该文记录采样和代码形态，因果控制另见 [TNO0040](./TNO0040_priority_mux_sinking_cause_20261111.md)。

复用此前四份冻结 emulator 及其 private runtime：before seed2 的 Clang 19/23、after seed7 的 Clang 19/23。保持 node030、CPU96–127、NUMA1、ASLR disabled、标准 code-page/preload、完整 DiffTest/NEMU、CoreMark 100k。执行 process-scoped `perf record -e cycles:u -F 997 --sample-cpu`，没有做全机采样或外部 CPU 空闲检查。采样运行仅用于诊断，不作为正式 walltime 数据。

四次运行均达到 100,001 Guest cycles，完整 DiffTest 通过，签名与各自冻结参考一致。perf 报告 lost samples=0。IP 使用各 binary 的 ELF 符号表和实际 `/proc/maps` load base 重新解析，包括原地址 remap 的匿名大页代码区域。仅统计 CPU96–127 的进程样本；其他启动辅助进程地址排除。

| 模型 | CPU96–127 样本数 |
| --- | ---: |
| before / Clang 19 | 520,301 |
| before / Clang 23 | 353,582 |
| after / Clang 19 | 529,491 |
| after / Clang 23 | 540,382 |

全局样本中大量时间落在 worker 自旋等待函数，因此按对应 worker CPU 分别分析模型函数。下述百分比为指定线程采样周期占比，不是整个 emulator walltime 占比，也不用于把线程累计时间相加。

before23 的原始日志包含一条 `[codepage-retry]` host 消息，通用 UART 提取将其误计入 workload 输出，最初脚本因此暂停。修正仅限诊断解析：原日志完整保留，明确剔除该 host 前缀后核对 Guest UART、PC、提交数和周期数；没有忽略 DiffTest 错误，也未修改正式 runner。

## before：收益集中于长 priority mux batch

| before 函数 | worker CPU | Clang 19 采样周期 | Clang 23 采样周期 |
| --- | ---: | ---: | ---: |
| part_6 / compute batch 93 | 102 | 4.334 G | 0.285 G |
| part_8 / compute batch 182 | 104 | 5.095 G | 0.331 G |
| part_20 / compute batch 185 | 116 | 5.015 G | 0.366 G |

表中的采样周期由 perf sample period 加权估计，不是函数精确计数器。同一 workload、周期数及功能签名下，变化集中在少量 compute batch。生成源码清查发现 **28 个对象中有 96 条长 priority mux：64 条长度 511、32 条长度 520**，分布于 part_5、6、8、19、20、22、24。

例如 part_6/batch_93 的 `priority_mux_80800` 从 ROB 的 `diffCommits.info[*].pdest` 选择物理寄存器编号，结果写入 `rat.fpRat.difftest_table_5`。这是 DiffTest RAT 更新路径。旧 [RenameTable.scala](../../testcase/xiangshan/build/xs/kunminghu-v3-gsim-followup-20261111/source-before/src/main/scala/xiangshan/backend/rename/RenameTable.scala) 遍历 `diffWritePorts`、按逻辑地址更新 `difftest_table_next`，展开后形成这类长选择链。

Clang 19/23 对第一条 511 级链的生成方式不同：

```text
Clang 19：检查条件；未命中则跳到下一段；命中则读数据并跳到公共出口。
Clang 23：检查条件并设置数据偏移；未命中顺序继续；命中跳到公共数据读取。
```

Clang 23 的优化 IR 将各分支独立的 `load` 合并为“选择偏移 + 公共 load”，相应地改变了常见未命中路径。这里只是源码/汇编观察，因果证明和动态深度计数见 TNO0040。

## after：旧长链消失，热点转向向量译码

在 after seed7 全部生成 sched 文件中，**没有长度 ≥500 的 priority mux**；只有两条长度 140 的链。新的 [RenameTable.scala](../../testcase/xiangshan/src/main/scala/xiangshan/backend/rename/RenameTable.scala) 将 DiffTest RAT 接到 [DiffRatStateBuffer](../../testcase/xiangshan/src/main/scala/xiangshan/backend/rob/DiffRatStateBuffer.scala)，其实现按 rename 更新构造状态并保存到分 bank 的存储中。不能继续假设旧 RAT 长链仍是 after 的主要工作。

after 的 CPU104/part_8 热点为 compute batch 53、39、54、51、59，Clang 23 没有明显降低其采样周期。以 batch 53 为例：

| 指标 | Clang 19 | Clang 23 |
| --- | ---: | ---: |
| 函数机器码大小 | 175,800 B | 174,099 B |
| 静态指令数 | 33,390 | 29,545 |
| 栈帧分配 | 4,424 B | 6,536 B |
| 引用 `%rsp` 的静态指令行数 | 12,783 | 13,598 |
| 采样周期 | 3.894 G | 4.561 G |

这份生成 C++ 约 5.9 MB，主体是向量译码生成的布尔表达式。热点指令包含大量 `mov`、`or`、条件选择及栈读写。Clang 23 虽减少静态指令数量，却没有消除其主要动态成本。栈访问计数是静态特征，不等于硬件 cache miss 或已量化的 spill 周期贡献；目前不能把 after 的小幅回退全部归因于寄存器分配。

[VectorDecodeChannel.scala](../../testcase/xiangshan/src/main/scala/xiangshan/backend/vector/Decoder/DecodeChannel/VectorDecodeChannel.scala) 根据 `rawInst`、`sew`、`lmul`、`nf` 直接产生三组 decode 表；[DecodeChannels.scala](../../testcase/xiangshan/src/main/scala/xiangshan/backend/vector/Decoder/DecodeChannels.scala) 将各条输入指令接到向量 decoder。该输入连接没有先按“指令是否为向量”门控，因此标量 CoreMark 也可能激活相关组合计算。实际采样已经证实这些生成函数确实在本 workload 中占用时间，不能以“CoreMark 不执行向量指令”推断向量译码没有仿真成本。

batch 中还包含断言条件和少量 DPI/system task；不能把整个 batch 的采样都称为断言开销。建议下一步围绕这些具体译码函数检查表达式共享、临时值生存期及依赖/激活范围，并保留断言和完整 DiffTest。

## 产物

- [采样入口](../../build/artifacts/repcut-compiler-hotspots-20261111/profile.py)、[IP 解析脚本](../../build/artifacts/repcut-compiler-hotspots-20261111/analyze_samples.py)、[采样 manifest](../../build/xs/repcut-compiler-hotspots-20261111/manifest.json)。
- [before19 样本解析](../../build/xs/repcut-compiler-hotspots-20261111/before19/resolved.json)、[before23](../../build/xs/repcut-compiler-hotspots-20261111/before23/resolved.json)、[after19](../../build/xs/repcut-compiler-hotspots-20261111/after19/resolved.json)、[after23](../../build/xs/repcut-compiler-hotspots-20261111/after23/resolved.json)。各目录同时保留 perf.data、原始 IP、符号表、maps、命令、日志和功能结果。
- [before 长 mux 清单](../../build/artifacts/repcut-compiler-hotspots-20261111/before-long-mux-files.json)、[after 清单](../../build/artifacts/repcut-compiler-hotspots-20261111/after-long-mux-files.json)、[热点汇编](../../build/xs/repcut-compiler-hotspots-20261111/assembly/)。
