# TNO0001：CV32E40P CoreMark 复现与 compute 成本定位

## 结果

复现了明显慢速，但未严格复现“约十倍”。在同一份转换后 RTL、同一 firmware 和共用 harness 上，8 对 AB/BA 的 **GrhSIM / Verilator walltime 为 2.860 倍，95% paired bootstrap CI [2.856, 2.865]**。相对原始 RTL Verilator 的单组诊断参照，GrhSIM 约慢 **6.15 倍**；后者没有配对 CI，不与前者混为一种统计结论。

| 口径 | Verilator | GrhSIM | GrhSIM / Verilator |
| --- | ---: | ---: | ---: |
| 相同转换后 RTL，进程 walltime，8 对均值 | 3.227211 s | 9.229842 s | 2.860022，CI [2.855537, 2.864967] |
| 同上，仅仿真循环 | 3.190081 s | 9.195199 s | 2.882454，CI [2.877484, 2.887810] |
| 同上，初始化与复位 | 0.011049 s | 0.007833 s | 0.708911 |
| 原始 RTL Verilator，单组 ABA 诊断 | 1.500075 s | 9.229842 s（主对测均值） | 约 6.152919，无 CI |

主对测每次完整执行 CoreMark 十迭代，共 3,376,065 个模拟周期；Verilator 约 1.0583 Mcycle/s，GrhSIM 约 0.3672 Mcycle/s。八对均为 GrhSIM 更慢，无样本剔除、无 placement 重试。CPU288 在这组样本的 `/proc/stat` 记录中均为 100% idle；测量没有使用外部空闲准入，也没有干预其它进程。

## 输入与验证边界

- 工作区：`wolvrix-playground-cv32e40p`。父仓基点 `eade363`，Wolvrix `74d80cf`，均在分支 `thj/cv32e40p-grhsim-investigation-20261114`；Wolvrix 核心及默认优化没有修改。
- CV32E40P：[`b353438ff469c030c89f6804f3b24a2852880e8b`](https://github.com/openhwfoundation/cv32e40p/tree/b353438ff469c030c89f6804f3b24a2852880e8b)。关闭 FPU、CORE-V 扩展和外部中断，保留原始模拟时钟门。
- CoreMark：[`core-v-verif fc3a7a3ea9d793ffe5cf0772f87d939b4bcde50c`](https://github.com/openhwgroup/core-v-verif/tree/fc3a7a3ea9d793ffe5cf0772f87d939b4bcde50c/cv32e40p/tests/programs/custom/coremark)。算法源码未改；RV32IM/ILP32、performance seeds、总数据 2 KB、10 次迭代；本地仅提供启动、链接和最小整数 libc。GCC 15.2.0 编译出的同一镜像供全部后端使用。
- Host 模型：Clang 23.1.2，`-O3 -march=native -DNDEBUG -gline-tables-only`；Verilator 5.052，`--threads 1`，fast/slow C++ 均显式 O3。GrhSIM 使用当前通用 frontend、activity schedule、emitter 默认值，不套用 XiangShan preset。
- 测量：node030、CPU96、NUMA1、ASLR disabled。两侧私有 binary/library/image 副本先在目标 NUMA fault-in；每个样本在开始和结束处验证线程数、affinity、ASLR、模型/堆/栈和 executable/library 页 locality。
- Testbench：共用 4 MiB RTL byte RAM、一周期响应、字节使能写入、UART/退出 MMIO、周期计数器。RAM 初始零值；共用 harness 在复位期间经 RTL 端口装载镜像。装载与复位计入 `init_s`，运行中 loader 禁用。进程 walltime 还包含启动、审计与销毁。

三侧模型（原始 Verilator、转换后 Verilator、转换后 GrhSIM）均通过 smoke 和完整 CoreMark：

- smoke：253 cycles，`SMOKE PASS`，覆盖字节/半字写入、连续相关读写、UART 和正常退出。
- CoreMark：3,376,065 cycles，exit 0，UART 完全相同；seed/list/matrix/state/final CRC 分别为 `e9f5/e714/1fd7/8e3a/fcaf`。
- 每周期有效 instruction/data request 的 trace 完全相同，CoreMark trace SHA256：`ed2b490886767aa74524a6dd15e708e8f2b231bc3886814af0ba4d1919b3e098`。
- 这验证本负载的执行一致性，不是对全部 RV32 指令和配置的形式等价证明。上游 port 打印的 “Total time (secs)” 实际返回 ticks，本记录不将其作为 CoreMark 分数或 Host 秒数。

## 直接导入限制与统一转换

原始 SV 无法由当前 importer 直接生成运行模型，遇到枚举常量、packed struct 成员读取、generate 局部符号、混合常量/寄存器驱动等限制。只靠 sv2v 也不足以绕过全部问题。原始失败日志保存在 [original-frontend-rejection.log](../../build/cv32e40p/logs/original-frontend-rejection.log)，混合驱动失败在 [mixed-driver-frontend-rejection.log](../../build/cv32e40p/logs/mixed-driver-frontend-rejection.log)。这些是构建兼容性问题，不是性能样本。

最终固定转换为 sv2v 0.0.13 + Yosys 0.33：参数特化后 `proc; pmuxtree; flatten; opt -full; splitnets; opt_clean`，没有技术映射。两主对照读取同一个转换结果；testbench RAM 不经过 Yosys。脚本和各阶段文本均有 hash。转换后的 netlist 展开了 CPU 的 packed 数据结构，改变了仿真代码形态，因此本轮结论必须带这个边界。

此外，GrhSIM 把 `$readmemh` 内容固化到生成代码，而 Verilator 通常在运行时加载。最终统一使用 RTL loader 和 RAM 零初始化，使两个 workload 能共用同一个模型，避免镜像加载方式混杂仿真性能。

唯一补充隔离实验提前记录了假设，固定原始/转换后/原始 Verilator 的 ABA 顺序，关闭 trace，三次均通过功能与 placement。原始两次 wall 为 1.493923 / 1.506227 s，中间转换后为 3.236474 s；仅仿真循环转换后/原始为 **2.18845 倍**。这支持转换本身也损害了 Verilator 性能的判断。该短诊断期间节点上另有源映射工具构建，因此不将其升级为独立稳定性能验收。它没有解释掉相同转换后输入上的 2.86 倍差距，也不能据此反推反馈者的原始配置。

## 原因定位

**主要差距在 compute 生成代码的执行指令量；当前证据不支持将初始化、4 MiB RAM 整体复制或主 dispatch 函数作为主因。**

| PMU 指标（约值，每模拟周期） | 转换后 Verilator | GrhSIM |
| --- | ---: | ---: |
| Host cycles | 2,943.85 | 8,413.79 |
| Instructions | 9,800.58 | 24,925.47 |
| Branches | 569.14 | 855.62 |
| Branch misses | 0.901 | 1.608 |
| IPC | 3.329 | 2.962 |

指令量约 2.54 倍，IPC 较低进一步扩大耗时差。两侧 branch miss rate 约 0.16% / 0.19%；不能用“严重分支误预测”解释结果。Verilator PMU 的 running fraction 为 89%，GrhSIM 为 100%；上表使用 perf 缩放计数，属于估计。PMU 和采样独立运行，没有计入八对统计。

`perf record cycles:u` 无 lost samples。GrhSIM compute batches 合计约 **93.82%**，commit **4.36%**，`eval()` 自身 **1.57%**，初始化约 **0.02%**。最热 batch 5 为 **15.42%**，batch 21 为 **8.02%**，batch 0 为 **7.80%**。RAM load/store 仍是生成代码中的索引访问；没有看到按每周期复制 4 MiB 的热点。

源映射使用与性能模型相同的冻结 Wolvrix library 和 emitter execution planner，导出 [sources.csv](../../build/cv32e40p/run2/sources.csv)：

1. 原始 [register file RTL](../../build/cv32e40p/run2/inputs/cv32e40p/rtl/cv32e40p_register_file_ff.sv) 的第 89/90 行是 `mem[raddr]`。原始 [Verilator C++](../../build/cv32e40p/run2/verilator-original/VCv32Bench___024root__0.cpp) 的对应读取是直接 `mem[index]`。
2. 转换后 [RTL](../../build/cv32e40p/run2/Cv32Bench.v) 第 44152/44154 行，将 32 × 32-bit 的整数寄存器堆拼接为 1024-bit 临时值，再动态切出 32 位。
3. 对应 IR 为 `_op_44694` / `_op_44800`：每个 concat 有 **993 个 operand**（992 个独立 bit，加 x0 的常量段），唯一使用者是 32-bit `kSliceDynamic`。
4. GrhSIM [batch 5](../../build/cv32e40p/run2/grhsim/grhsim_Cv32Bench_sched_5.cpp) / [batch 21](../../build/cv32e40p/run2/grhsim/grhsim_Cv32Bench_sched_21.cpp) 先逐位装配 16 个 uint64 word，再做动态切片。采样命中这些 pack/OR/存储表达式；例如 batch 5 第 3347 行与 batch 21 第 284 行。batch 5 还包含变化检测后的 reader 激活（第 730 行），不能把这两个 batch 的全部 23.44% 都归因于寄存器堆 pack。
5. 当前模型有 3,142 个持久 bool slot。类似的逐位读写、变化比较和激活传播散布在 compute batches；CSR bank 还有 1024/2048-bit concat 后动态读取。这是具体、可追踪的生成形态成本，而不是根据文件大小猜测。

计数版记录 6,767,786 次 `eval`、10,151,543 轮、233,485,489 次 compute-batch 调用、10,151,543 次 commit-batch 调用。包括少量镜像装载/复位后，约为每 guest cycle **2 eval、3 rounds、69 compute-batch calls**。这说明 fixed-point 重评估会放大 compute 成本，但 dispatch 的独占采样只有 1.57%，不能把全部差距描述成“调度函数开销”。计数版不是性能候选，没有用其 walltime替换正式结果。

GrhSIM binary 约 34.0 MB，但 `.text` 只有 207,991 bytes，约 33.58 MB 属于 `.rodata`，主要来自 RAM 初始值表。生成 C++ 约 226 MB 也主要受初始化表示影响。这个大小问题值得单独记录，但当前初始化只有约 8 ms，不能把 binary 大小直接当成本次 9.2 s runtime 的原因。

## 交付、验证与后续边界

新增 [runner](../../scripts/cv32e40p_compare.py)、[共用 fixture/说明](../../testcase/cv32e40p-bench/README.md)、[runner 回归](../../scripts/test_cv32e40p_compare.py)，并给通用 frontend 的错误日志补充源码位置。Wolvrix 核心未改。三项 Python 回归覆盖倍率方向、CRC 门和输出解析；实际三模型构建、六次完整功能验证、16 个主性能样本和全部诊断样本通过。

构建耗时单独归档：共用 sv2v/Yosys 约 2.76/13.47 s；GrhSIM frontend/emit/compile/link 约 20.31/8.06/31.54/1.51 s；转换后/原始 Verilator 构建约 55.85/43.02 s。工具首次构建不混入运行时间。

下一步若要优化，应先改善直接 SV 导入、保留寄存器堆数组语义，或针对有证明约束的 concat + dynamic slice 消除整组物化；其次才评估变化检测和活动传播的细粒度成本。本轮未实现这些优化，未做分区、参数搜索或运行后选优。尚无反馈者的版本/命令，因此不能断言本次路径就是其“约十倍”的唯一原因。

关键产物：

- [完整机器报告](../../build/cv32e40p/run2/report.json)、[逐对 CSV](../../build/cv32e40p/run2/pairs.csv)、[summary](../../build/cv32e40p/run2/summary.json)
- [构建身份](../../build/cv32e40p/run2/build.json)、[输入清单](../../build/cv32e40p/run2/inputs.json)、[转换过程](../../build/cv32e40p/run2/normalization.json)、[测量策略](../../build/cv32e40p/run2/measurement-policy.json)
- [三模型功能验证](../../build/cv32e40p/run2/verification.json)、[转换隔离实验](../../build/cv32e40p/run2/normalization-control.json)、[实验事前假设](../../build/cv32e40p/run2/normalization-control-policy.json)
- [GrhSIM perf](../../build/cv32e40p/run2/grhsim-perf-report.txt)、[Verilator perf](../../build/cv32e40p/run2/verilator-perf-report.txt)、[源码行采样](../../build/cv32e40p/run2/grhsim-perf-lines.txt)、[batch 5 汇编](../../build/cv32e40p/run2/grhsim-batch5-annotate.txt)
- [调度计数与抽样 trace](../../build/cv32e40p/run2/runs/diagnostic/diagnostic/run.log)、[源映射身份](../../build/cv32e40p/run2/mapping-identity.json)
