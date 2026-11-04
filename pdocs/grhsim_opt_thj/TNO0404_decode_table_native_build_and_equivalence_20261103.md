# TNO0404：译码表单线程构建与整机等价检查

日期：2026-11-03。A/B 原生单模型构建完成；正式 walltime 采样进行中。

## 冻结构建

本轮目录 `build/xs/decode_table_20261103_v3`，两侧均完整从 Chisel 生成。
A 为 none，B 为 decode-table。两侧工具共享冻结的 Python binding 与 libwolvrix-lib.so；
使用 Clang 23.1.2，模型参数 `-std=c++20 -O3 -march=native`，保留 SLP。
RTL／模型／编译／运行 DiffTest 全部为 on，不引用关闭 DiffTest 的历史数字。

| 指标 | A | B |
|---|---:|---:|
| emu 文件字节 | 79,092,832 | 78,103,768 |
| ELF .text 字节 | 71,519,112 | 70,407,072 |
| ELF .rodata 字节 | 6,684,504 | 6,806,008 |
| 生成 C++ 文件数 | 132 | 129 |
| 生成 C++ 字节 | 1,264,654,275 | 1,248,682,597 |
| 扁平图 kDecodeTable | 0 | 62 |
| C++ 软件译码调用 | 0 | 62 |

全部生成 C++ 均没有 `wolvrix_decode_table_` DPI transport 残留。
23 张表在完整模型中保留；ROB 的 6→5 位退休计数表虽然 elaboration 8 次，
优化后的扁平图已没有对应操作，不能将其局部收益算成整机收益。24 张表仍全部保留在
局部调查中，未按性能选择有利调用。

`source_chain.json`／CSV 对齐每张原表的 Chisel SourceInfo、RTL 行、扁平 GRH
操作符号／输入输出以及 C++ 函数和调用行。静态字节变化不能直接证明 walltime 改善。

## 整机功能 gate

CPU96、NUMA node1、专用单模型单线程。两侧 smoke 通过；种子 0 和 1 各运行
`-C 100000`，NEMU/Difftest 均通过，每组 A/B 的 100,000 条 DiffTestState 记录逐条一致。
比较包括有效字段、提交数据、周期字段、记录数量和顺序，忽略 C padding 和无效负载。

四次诊断均达到相同最终签名：PC `0x80000c0c`、instr_count 240349、cycle_count 99996、
Guest cycle spent 100001。最后两个计数分别是原有 Difftest 延迟及 emu 停机计数口径；
实际命令两侧都为 `-C 100000`。两组使用相同 CoreMark 负载、不同固定种子，
不宣称代表两种不同程序负载。

诊断时开启 dump-difftrace，因此不把其耗时作为正式 walltime 样本。
四次运行的 native binary、依赖库和匿名页归属检查均通过；测量保持 CPU96，SMT sibling
288 空闲检查通过。系统 ELF loader 单独记录，未冒充用户代码页。

## 后续测量

预热后进行 8 对 AB/BA，共 16 次 C100000 正式运行，关闭诊断／trace。
局部测量在整机配对完成后串行运行；两种计时不重叠，测量期间不构建。
局部编译在 node029 完成，已验证它和 node030 的 Clang `-march=native` 都为 znver4，
115 项 feature 参数完全一致；局部运行也在 node030 CPU96，文件和匿名页单独核验。

## 原始证据

- `build/xs/decode_table_20261103_v3/binary_structure.json`、`source_chain.json`、`source_chain.csv`。
- `build/xs/decode_table_20261103_v3/comparison-v1/trace-s0.json`、`trace-s1.json`。
- `comparison-v1/{A,B}/runs/verify-s{0,1}.json`、`.locality.json` 和 `.numa/`。
- `wolvrix/build/artifacts/decode-table-study/compiler-target-match.json`。
- [TNO0403 完整覆盖及 36 次未知宽度回退来源](./TNO0403_decode_table_full_coverage_20261103.md)。
