# TNO0010：宽常量填充的按需读取，功能通过但不默认启用

实现 TNO0009 的第一步：让 indexed-concat 读取支持宽常量填充，消除两处 2048→32 和一处 1024→32 的完整 concat 临时值。**完整八轮测量显示 walltime 增加 0.7351%，95% 配对 bootstrap CI [+0.2836%, +1.2224%]。** 因此扩展保留为默认关闭的实验选项，原有 indexed-concat 默认行为保持不变。

这次结果修正了 TNO0009 对该方向的收益预期：生成 C++ 更小，但每 guest cycle 的退休指令仅减少约 2 条，不能据宽临时值的源码体积推断它在机器码中仍有同等大小的开销。

## 实现与当前配置

[emitter](../../wolvrix/lib/emit/grhsim_cpp.cpp) 增加 `indexed_concat_wide_constants`，环境变量为 `WOLVRIX_GRHSIM_INDEXED_CONCAT_WIDE_CONSTANTS`，**默认 false**。必须同时开启既有 `indexed_concat_slice`；emit attribute 优先于对应环境变量。功能说明见 [indexed slices](../../wolvrix/docs/emit/grhsim-indexed-concat-slices.md)。

规则允许已知、无 X/Z、无 side effect 的宽 `kConstant` 作为 concat operand。在生成时按源 word 边界和目标 word 边界分段，将常量位片段合并进所选 word；零填充 word 共用 default-zero 分支。非零常量、signed literal 扩展、非对齐字段和跨 word 读取均保持原有 bit 布局。动态宽输入仍回退，未扩大为一般宽值的延迟求值。

同一 scope、唯一完整 IR use、标量结果、源槽 alias/写入检查、effect/event 排除及 local snapshot 约束保留。直接状态视图仍保守排除；没有新增跨状态更新的缓存。早期开发尝试的直接状态快照路径未被测试夹具实际触发，随后移除，最终实现只扩展宽常量支持。

最终默认值检查使用添加实验开关后的 native 工具：

- 不传开关、显式关闭：全部 **26 个 `.cpp/.hpp`** 与 TNO0007 已验证模型 SHA 完全一致。
- 显式开启：全部 **26 个 `.cpp/.hpp`** 与本轮实测候选 SHA 完全一致。
- 三种模式的 normalized graph 与相应冻结参考一致。

因此默认版本继续使用 TNO0007 的生成结果；本轮负收益候选没有成为默认路径。证据见 [default gate](../../build/cv32e40p/indexed-padding-default-gate/report.json)。该 gate 仅重新发射模型，不重复性能测量。

## 实际命中

原有两个寄存器堆 indexed-concat 读取保留，总命中从 2 增到 5。新增均在 [sched_4](../../build/cv32e40p/indexed-padding-final/grhsim_indexed_padding/grhsim_Cv32Bench_sched_4.cpp)：

| 值 | 宽度与消费者 | 生成 word cases |
| --- | --- | ---: |
| `41658 / core$_13859_` | 2048-bit counter concat → 32-bit dynamic slice | 4 |
| `41659 / core$_13860_` | 2048-bit counter concat → 32-bit dynamic slice | 4 |
| `41660 / core$_13861_` | 1024-bit mhpmevent concat → 32-bit dynamic slice | 1 |

两处 counter view 的其他 28 个 word、mhpmevent view 的其他 15 个 word由 default 返回零。每次 slice 最多调用两个 word case，不建立原来的完整 concat 数组。

只一个生成 C++ 文件改变；头文件、runtime、其他 C++ 文件逐字节一致。归一化图、69 个 supernodes、10 个 batch 文件和 1038 个 Boolean 值槽均不变。生成 schedule 源码 1,877,201 → 1,868,805 bytes；完整 ELF `.text` 117,049 → 117,033 bytes，减少仅 16 bytes。batch 4 函数机器码 9,099 → 9,078 bytes。

关闭父选项 `indexed_concat_slice` 后，新旧 emitter 全部生成 `.cpp` 也完全相同。没有改变 RTL、firmware、harness、调度或分区。

## 一组八轮结果

node030、CPU96、NUMA1、单线程、ASLR disabled；Clang 23.1.2、`-O3 -march=native`，无波形或性能插桩。四侧各预热一次，再按“旧 GrhSIM、宽常量候选、归一化 Verilator、原始 Verilator”与反序交替八轮。32 个正式样本全部通过功能和 placement，零重试、零剔除；CPU288 sibling 全部记录为 100% idle。

| 后端 | walltime 均值 | 仿真循环均值 |
| --- | ---: | ---: |
| 已验证的共享译码 GrhSIM | 4.138840 s | 4.106627 s |
| 宽常量按需读取候选 | 4.169202 s | 4.136427 s |
| 归一化 RTL Verilator | 2.948334 s | 2.912713 s |
| 原始 RTL Verilator | 1.378627 s | 1.342590 s |

候选 / 旧 GrhSIM walltime 为 **1.007351**，CI **[1.002836, 1.012224]**；仿真循环为 **1.007271**，CI **[1.002839, 1.012063]**。八轮 walltime 中六轮更慢，两轮略快。

候选 / 归一化 Verilator 为 **1.414089**，CI **[1.407663, 1.421100]**；候选 / 原始 Verilator 为 **3.024190**，CI **[3.007611, 3.039715]**。这些是未采纳候选的倍率，不替换 TNO0007 的默认版本结论。

同轮数据中的保留基线 / 归一化 Verilator 为 **1.403796**，CI **[1.398059, 1.409860]**；保留基线 / 原始 Verilator 为 **3.002154**，CI **[2.990637, 3.015300]**。对应 summary 和未采纳决定见 [decision.json](../../build/cv32e40p/indexed-padding-final/decision.json)。

正式输出仅在 `indexed-padding-final`。`indexed-padding-v1` 用于早期功能开发，没有配对计时；没有依据多个性能候选选优，也没有重测到显著结果为止。

## 为什么源码变化没有形成收益

正式测量之后，两份生产 binary 各一次 `perf stat` 和采样：

| 每 guest cycle | 旧 GrhSIM | 候选 |
| --- | ---: | ---: |
| Host instructions | 13,104.51615 | 13,102.51644 |
| Host cycles | 4,114.86845 | 4,153.63501 |
| Branches | 599.60495 | 599.60502 |
| Branch misses | 1.58198 | 2.25149 |

退休指令只下降 **0.01526%**，分支总数基本一致，branch misses 增加约 **42.32%**。这与 walltime 退化方向一致，但单次 aggregate PMU 不能证明哪一条分支造成退化；代码布局及分支预测别名仍可能参与。

batch 4 反汇编中，静态指令数 1,893 → 1,931，带 `%rsp` 的指令数 188 → 191。按需 lambda 的源码更短，并没有自动成为更少的机器操作或更少的栈访问。Clang 已消除原路径的大量宽值工作，新的选择表达式也有自己的编译代价。

因此 TNO0009 所引用的宽临时值源码行采样不能作为可回收收益，也不能只看声明了多少字节的数组。后续 1024→16 的 shift/mux 路径仍值得检查，但应先从实际机器码和动态工作确认可消除的部分，再进行独立改写；本轮不继续做其他参数或实现的搜索。

## 验证

四侧 smoke 均为 253 cycles，CoreMark 均为 3,376,065 cycles，退出码 0，CRC、UART 和完成周期一致。完整有效总线事务 trace SHA：

- smoke：`84e48e4a17e723b73c167a256a44ded549bd8f82d36cc5be4070554f40763fc0`
- CoreMark：`ed2b490886767aa74524a6dd15e708e8f2b231bc3886814af0ba4d1919b3e098`

新增 focused 覆盖宽零/非零常量、符号扩展、部分 word、跨常量/标量边界、129-bit index、越界、固定地址下数据变化和 padded clocked bank。动态宽 operand、未知 padding、跨 scope、effect、多用户等保持回退。

`emit-grhsim-cpp-indexed-concat-slice` 和 `emit-grhsim-execution-plan` 通过；focused 的开启、关闭、split、profile 四种生成模式各通过 Clang 23 O0/O3、ASan/UBSan。加入默认关闭开关后，再检查默认、显式与环境优先级及 planner/emitter 命中一致性。相关 11 项 Python 测试通过。

该扩展对 XiangShan 的 padding/Vec 读取仍有结构适用性，但 CV32 的负收益不能用于推断 XiangShan 的收益或退化。本轮未重建 XiangShan；新选项全局默认关闭。

## 复现与产物

在 node030 项目目录，使用新输出目录：

```bash
cmake --build build/cv32e40p/tools --target cv32e40p_emit emit-grhsim-cpp emit-grhsim-execution-plan -j16
PATH=/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin:$PATH \
ctest --test-dir build/cv32e40p/tools/grhsim32/wolvrix --output-on-failure \
  -R '^(emit-grhsim-cpp-indexed-concat-slice|emit-grhsim-execution-plan)$'
python3 scripts/cv32e40p_indexed_padding_compare.py build --output build/cv32e40p/padding-reproduce
python3 scripts/cv32e40p_indexed_padding_compare.py attach-verilator --output build/cv32e40p/padding-reproduce
python3 scripts/cv32e40p_indexed_padding_compare.py verify --output build/cv32e40p/padding-reproduce
python3 scripts/cv32e40p_indexed_padding_compare.py measure --output build/cv32e40p/padding-reproduce
python3 scripts/cv32e40p_indexed_padding_compare.py profile --output build/cv32e40p/padding-reproduce
python3 scripts/cv32e40p_indexed_padding_compare.py report --output build/cv32e40p/padding-reproduce
```

runner 为候选显式设置 `WOLVRIX_GRHSIM_INDEXED_CONCAT_WIDE_CONSTANTS=1`。实测 binary SHA 为 `20d970d5b9bb2e846167dc20d91cde793831d17b067a6c44c1e9b9de020987b4`，基线为 `9642e07f8a0add9eaf1b0962005f60aadc5e4d6ce8382622de99489cb8860037`。测量时 patch 与添加默认关闭开关后的 patch 分别保留；后者显式开启的全部生成源与实测候选一致。

- [正式报告](../../build/cv32e40p/indexed-padding-final/report.json)、[逐轮 CSV](../../build/cv32e40p/indexed-padding-final/pairs.csv)、[测量策略](../../build/cv32e40p/indexed-padding-final/measurement-policy.json)
- [冻结构建](../../build/cv32e40p/indexed-padding-final/build.json)、[结构](../../build/cv32e40p/indexed-padding-final/structure.json)、[源码变化检查](../../build/cv32e40p/indexed-padding-final/validation/structure-checks.json)
- [功能与 trace](../../build/cv32e40p/indexed-padding-final/functional.json)、[生产 PMU 与采样](../../build/cv32e40p/indexed-padding-final/)
- [机器码统计](../../build/cv32e40p/indexed-padding-final/validation/machine-code-shape.json)、[旧机器码](../../build/cv32e40p/indexed-padding-final/validation/batch4-before-annotate.txt)、[候选机器码](../../build/cv32e40p/indexed-padding-final/validation/batch4-after-annotate.txt)
- [实测版 CTest](../../build/cv32e40p/indexed-padding-final/validation/ctest.log)、[最终默认值 gate](../../build/cv32e40p/indexed-padding-default-gate/report.json)
- [最终开关 CTest](../../build/cv32e40p/indexed-padding-default-gate/ctest.log)、[验证清单](../../build/cv32e40p/indexed-padding-default-gate/validation.json)
- [比较 runner](../../scripts/cv32e40p_indexed_padding_compare.py)、[功能文档](../../wolvrix/docs/emit/grhsim-indexed-concat-slices.md)

本轮代码及文档仍在现有调查分支的工作树，未新增提交。
