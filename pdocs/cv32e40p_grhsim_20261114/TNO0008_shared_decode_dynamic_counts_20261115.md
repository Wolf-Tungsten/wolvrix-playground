# TNO0008：共享译码后的动态计数与 Verilator 对照

对 TNO0007 的冻结优化模型补测源代码执行次数。两组 CSR 谓词的逐值 old/new 比较从 **180.705832 降为 1.956776 次/guest cycle，减少 98.9171%**；结果变化仍为 **0.09715749 次/周期**。按 TNO0006 相同的 scalar old/new 比较口径，其占比从 **24.46596% 降为 0.36033%**。

这是一次诊断构建，分别执行一次 smoke 和完整 CoreMark；未重新做性能对测，也未修改优化规则。诊断 binary 的耗时不参与性能结论。

## 相同谓词的前后对照

| 指标 | 优化前 | 共享译码后 |
| --- | ---: | ---: |
| decode CSR：171 个谓词的 old/new 比较/周期 | 143.570533 | 0.956776 |
| execute CSR：171 个谓词的 old/new 比较/周期 | 37.135300 | 1.000000 |
| 两组合计比较/周期 | 180.705832 | 1.956776 |
| 两组合计结果变化/周期 | 0.09715749 | 0.09715749 |
| 全模型 scalar old/new 比较/周期 | 738.601079 | 543.047076 |
| 两组占全模型 scalar old/new 比较的比例 | 24.46596% | 0.36033% |

上述“比较”是生成 C++ 中 `grhsim_changed_* = old != next` 的执行次数，不是全部 C++ 比较运算符数，也不是 Host 退休比较指令数。新增加的缓存 guard 和 switch 分派单独列出，不混入旧分母。全模型的降幅还包含 19 个 opcode 谓词的共享译码。

335/342 个谓词已进入共享译码：decode 覆盖 170/171，execute 覆盖 165/171。**342 个 Boolean 结果槽仍保留**；改变的是更新方式。decode 的 170 个谓词只有实际清旧/置新时执行 old/new 检查，合计 0.09715749 次/周期，且每次结果都确实变化；execute 的 165 个共享谓词在这个 CoreMark 中无需更新。

剩余普通谓词贡献 1.85961852 次/周期。其中 decode 地址 `3282` 的谓词执行 0.85961852 次/周期，execute 地址 `1953` 的谓词执行 1 次/周期；execute 剩余五个谓词所在组在计数区间未执行。所有这些谓词仍保留完整语义，没有基于本次 workload 的常量化或删除。

## 新增的缓存和分派工作

| 两组 CSR 合计，每 guest cycle | 次数 |
| --- | ---: |
| 缓存 valid 检查 | 3.112228 |
| 当前地址与 previous 地址比较 | 3.112228 |
| 地址变化，进入稀疏更新分支 | 2.358845 |
| switch 分派，旧/新地址各一次 | 4.717690 |
| switch 命中清旧项 | 0.048579 |
| switch 命中置新项 | 0.048579 |

这解释了为何不能将“180.71 → 1.96”当成译码总成本降低约 99%：新路径仍有 guard、switch 寻址和变化通知。一个 switch 分派可能被编译为查表或多条比较/分支，不等价于一条 Host 指令。

两个源各有三份局部缓存，对应不同 supernode 内的连续谓词区间。decode 源的三份缓存各观察到 0.78628166 次地址变化/周期，所以合计执行 2.35884499 次更新分支；多数地址不在各自谓词子集中，switch 进入 default。execute 源的活动缓存每周期检查 0.59238196 次，但地址没有变化。跨 supernode 的缓存未合并，以保持现有调度顺序和旧值语义。

计数在镜像装载和复位之后清零，六份 CSR 缓存在该区间内没有冷初始化；冷路径仍存在且已由小用例验证，不能理解为启动成本被消除。

## 与两张 Verilator one-hot 表的差异

这里对应的是**归一化 RTL Verilator**。其两张 4096 项表仍在 `nba_sequent__TOP__0` 中各清旧项、置新项、保存 previous 地址，下游直接读取 `table[K]`。经冻结 binary/source SHA 和总线 trace 核对，复用 TNO0004 的函数计数：该函数在 3,376,065 个 guest cycle 中执行 3,376,064 次，近似每周期每表一次更新，合计四次表项写入和两次 previous 地址写入。更新在函数内无额外条件，不随地址是否相同而跳过。

GrhSIM 已消除了原来两百量级的逐项无效比较，但仍有以下结构差异：

- 同一 decode 源在三个 supernode 分别检查并分派；Verilator 对该源维护一张公共表。
- GrhSIM 稀疏 switch 更新独立 Boolean 槽，并保留逐谓词变化检测、reader 激活；Verilator 下游直接访问表项。
- 七个未覆盖谓词及原有长 OR 消费者仍存在，部分内联比较也不在本次 342 个物化谓词计数中。

因此还存在可继续削减的检查和分派工作。但两种实现的内存、分支及调度成本不同；GrhSIM 共享部分实际写谓词的次数仅 0.09716/周期，少于 Verilator 的表项写入次数，不能把源代码次数换算成该模块的耗时倍率，或据此断言剩余译码必然更慢。

最近一次未插桩对测仍是 [TNO0007](./TNO0007_shared_equality_decode_20261115.md)：整体 GrhSIM / 归一化 Verilator 为 1.4015 倍，GrhSIM / 原始 RTL Verilator 为 2.9932 倍。这些是整机倍率，不能全部归因于这里的残余差异；原始 RTL Verilator 没有这两张 one-hot 表。

## 验证与复现

运行位置为 node030、CPU96、NUMA1、单线程、ASLR disabled。smoke 253 cycles、CoreMark 3,376,065 cycles，UART、退出码、CRC、完成周期、完整总线 trace 均通过；placement 无拒绝。CoreMark 时 CPU288 sibling idle 为 99.8435%，本轮不使用运行时长作性能判断。

优化前后 normalized graph SHA 一致，复用同一 value-ID 归属。新计数覆盖原有全部 990 个 scalar 值；每个共享谓词的冷路径、清旧路径、置新路径共用同一个动态计数 ID，静态验证三个位置各出现一次。全部逐值变化次数在低/高相位分别一致，function/group/round 执行次数也与优化前逐项一致。

新增小用例实际编译执行，验证冷初始化、相同地址、命中/未命中切换时计数准确，防止三个源码位置被误算为三次动态更新。相关 11 项 Python 测试通过，两仓 diff 检查通过。

在 node030 项目目录执行，输出目录必须新建：

```bash
python3 scripts/cv32e40p_decode_counts.py all --output build/cv32e40p/shared-equality-counts-reproduce
PYTHONPATH=scripts python3 -m unittest test_cv32e40p_code_shapes test_cv32e40p_compare
```

- [机器报告](../../build/cv32e40p/shared-equality-counts-v1/report.json)、[原始动态计数](../../build/cv32e40p/shared-equality-counts-v1/counts.json)
- [构建与输入身份](../../build/cv32e40p/shared-equality-counts-v1/build.json)、[计数器清单](../../build/cv32e40p/shared-equality-counts-v1/grhsim-counts/probes.json)
- [Verilator 复用证据](../../build/cv32e40p/shared-equality-counts-v1/verilator-reference.json)、[功能与 placement](../../build/cv32e40p/shared-equality-counts-v1/runs/)
- [诊断脚本](../../scripts/cv32e40p_decode_counts.py)、[计数回归](../../scripts/test_cv32e40p_code_shapes.py)
