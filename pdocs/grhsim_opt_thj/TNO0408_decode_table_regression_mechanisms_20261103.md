# TNO0408：两张退化译码表的差异与 CSR 字节读取对照

日期：2026-11-03。范围：解释上一轮局部退化；生产代码、默认选项和整机样本未修改。

## 从完整数据重新分类

检查 24 张表的所有分布后，明显、反复退化的仍是 `03_indexedLSUopTable` 和 `16_PrivilegePermitModule`。随机输入下完整局部 eval 分别为 3.044→4.764 ns（+56.56%）、5.941→8.885 ns（+49.52%）。不能仅按输入位数或表行数筛除：同样 4 位、16 行的另外七张索引表均改善；3 位的 VCVT 也改善约 30%，同为 11 行的 I2F 改善约 59%。

## 一：索引表在参数固化后为常量

源码 `backend/decode/DecodeUnitComp.scala:39` 的 indexedLSUopTable 参数 uopIdx 在此实例为 0。16 个输入组合的两个偏移都为 0，默认值也为 0，全部输出位受约束，和 DontCare 填值选择无关。其他七张表的输出记录不止一种。

原硬件路线在生成／优化过程中已化为常量，A 的 eval 没有输入变化触发，只需初始化和输出刷新。B 的 GRH 仍把整表视作依赖输入的组合运算；即使 Clang 把表函数折叠为写零，输入比较、活动置位、batch 调用和写回仍存在。kernel 两侧均约 1.39 ns，完整 eval 才出现显著差距。99% 输入保持时，差距缩到约 1%。

这不是 C++ 无法算出常量，而是常量信息被发现得晚，调度已按动态依赖生成。适合的后续工作是表语义层识别恒定函数并消除输入依赖；无需按 uopIdx 或实测速度硬编码例外。

## 二：CSR 表的一位结果触发了特殊机器码形态

源码 `backend/fu/NewCSR/CSRPermitModule.scala:355` 的表输入为 V、PRVM、CSR 地址权限位，共 5 位；11 个允许组合输出 1，其他组合为 0，完全没有输出 DontCare。它是 32 位真值位图 `0x31f071`。

原 A 被最小化为较小的布尔组合。intrinsic B 的 48 字节 LUT 在 Clang 编译后已经消失，变为常量位测试；所以不能把此例慢直接解释成 LUT 访存或 cache miss。原二进制实际为：

```asm
mov    (%rdi), %eax       # 4 字节读取，实际输入 in 是 uint8_t
mov    $0x31f071, %ecx
bt     %eax, %ecx
setb   0x1b(%rdi)
```

局部模型的 in 在偏移 0，public out 在偏移 1，first_eval_ 和 event_baseline_initialized_ 在偏移 2、3。4 字节 load 覆盖了相邻字段；输入和 out 是逐次字节写，完整 eval 还写相邻标志。bit-test 只使用索引的低 5 位，因此这是语义合法的扩宽读取，不是已证实的 Clang 功能错误。

这与窄 store 后重叠宽 load 导致存储转发困难的机制吻合。该微架构归因尚未用性能计数器单独核验；下面的干预可直接验证读取宽度是重要原因。

## 局部干预：只限制输入读为字节

从先前 intrinsic B 的生成代码另建诊断模型，把两个函数中的输入表达式改为 `static_cast<const volatile std::uint8_t&>(in)`；类型、位图、bit-test、调度和输出路径保持。volatile 仅用来约束这次实验的读取宽度，不作为生产 API 或正式修复。汇编核实主要指令变为 `movzbl (%rdi), %eax`，后面仍是同一个常量和 bt/setb。

两组各 32 个输入穷举和 kernel/eval 完整输出检查通过。node030 CPU96 上，5 种输入分布、kernel/full 各 8 对，共 80 对／160 次；运行中单线程、NUMA、SMT sibling 检查均通过。这里诊断 A 是上一轮的 intrinsic B，诊断 B 是字节读取版本。

| 分布 | 范围 | 原 intrinsic 中位 ns | 字节读取中位 ns | 配对变化中位数 | 更快对数 |
|---|---|---:|---:|---:|---:|
| random | kernel | 9.0997 | 1.5375 | -83.12% | 8/8 |
| random | full | 8.8505 | 4.5924 | -48.12% | 8/8 |
| matched | kernel | 9.0915 | 1.5375 | -83.08% | 8/8 |
| matched | full | 8.3864 | 4.9779 | -40.68% | 8/8 |
| dense | kernel | 9.0970 | 1.5350 | -83.12% | 8/8 |
| dense | full | 7.6151 | 5.7260 | -24.83% | 8/8 |
| toggle1 | kernel | 9.0887 | 1.5365 | -83.08% | 8/8 |
| toggle1 | full | 9.0881 | 4.1144 | -54.73% | 8/8 |
| hold99 | kernel | 9.0952 | 1.5388 | -83.08% | 8/8 |
| hold99 | full | 3.0596 | 3.0583 | -0.09% | 5/8 |

随机 kernel 从 9.100 ns 降至 1.537 ns，完整 eval 从 8.851 ns 降至 4.592 ns。由此应把前序“这个小 CSR 表替换不划算”的经验性判断细化为“当前生成机器码的宽读取造成严重局部代价”。单纯禁止这一类小表会掩盖可修复的实现问题。99% 保持时两边完整 eval 都约 3.06 ns，也符合只有重新执行运算时才付出主要差距。

这个数字来自独立局部对照，不能当作已经修复整机或证明整机进一步加速。原 8 对整机 2.04% 结果及原 24 张表数据全部不变。

## 对后续选择策略的含义

- 先检查函数是否已经退化为常量、直连或简单关系，再决定保留表操作；常量化应尽早影响活动依赖。
- 输入位数小、行数少、输出不同值少都只能作为特征，不能独立决定拒绝：单比特布尔表可能非常适合 bitset。
- 同时检查生成机器码的数据访问宽度和调度成本；本例 CSR 的代码更短却更慢。
- 高保持率本身常使两个版本都跳过计算，局部运算倍率不能代表完整 eval 或整机收益。

## 证据

- 原结果：[TNO0407](./TNO0407_decode_table_local_results_and_delivery_20261103.md)。
- 诊断目录：`wolvrix/build/artifacts/decode-table-study/regression-diagnosis-v1`，含原 A/B 汇编摘录、24 表特征及原测量引用。
- 新对照：[summary.json](../../wolvrix/build/artifacts/decode-table-study/regression-diagnosis-v1/csr-byte-load-measure/summary.json)、[pairs.csv](../../wolvrix/build/artifacts/decode-table-study/regression-diagnosis-v1/csr-byte-load-measure/pairs.csv)。
- 字节读取模型的 C++、机器码、穷举验证及编译命令在 `csr-byte-load`；所有运行环境证据在 `csr-byte-load-measure`。
