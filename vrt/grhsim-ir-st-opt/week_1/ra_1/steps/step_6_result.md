# 第 6 步结果：冻结输入来源检索与准入结论

## 决策

**`blocked_missing_provenance`**。本次完成了限定范围的只读检索，没有生成、build-only、CoreMark、gsim 或性能运行。现有材料不能把任务指定的冻结 flat GRH 与生成 C++、当前 emit 提交及 emu 建立可核实的完整身份链，因此停止继续追溯。

## 检索与复核

检索命令、退出状态、命中清单、文件清单和独立 SHA-256 复核保存在本步临时审计材料中。命令覆盖：根仓库近 400 条历史、2026-09-01 后的相关路径历史、Wolvrix 子模块历史、版本化 manifest/日志索引、既有 step 1–4 材料、候选 IR 构建目录、生成 C++ 目录和构建日志。各审计命令均在 90 秒边界内结束；历史/材料检索命中返回 0，精确哈希反查无命中返回 1，缺失目录清单返回 1，独立哈希校验返回 0。

根仓库 HEAD 为本次提交的父提交，分支为 `vrt/grhsim-ir-st-opt/week_1/r_1`。五个直接子模块均在同名分支、工作树干净；gitlink 与 `grh/grhsim-ir` 基点一致：reference/gsim、testcase/hdlbits、testcase/openc910、testcase/xiangshan、wolvrix。未修改子模块。

## 证据清单

| 项目 | 状态 | 证据与关键数据 |
| --- | --- | --- |
| 候选 GrhSIM JSON | `verified_file`；来源 `unknown` | 464,968,979 bytes，SHA-256 `5b2494766fbc12030cd919452835bcfd7443a81b7e1f5314499d61dd0e27075c`；实现进展文档第 40–43 行记录同一哈希、4,981,305 ops、4,677,017 values、695,052 states、mappings=0 的阶段性 checkpoint。 |
| round-trip JSON | `verified_file`；来源 `unknown` | 同大小、同 SHA-256；字节相等只证明 round-trip 稳定，不证明生成来源。 |
| 冻结 flat GRH | `missing` | 候选目录中不存在任务指定的 flat 文件；既有 manifest 明确记录缺失。不能用 mappings=0 的 GrhSIM JSON 或其他方向/legacy checkpoint 替代。 |
| flat GRH→生成参数 | `missing/unknown` | 脚本 [scripts/wolvrix_xs_grhsim_ir.py](../../../../../scripts/wolvrix_xs_grhsim_ir.py) 和 Makefile 行 696–727 证明当前入口支持 resume、reg-to-mem、batch、keep-origins 等参数，但没有历史 manifest 将它们绑定到候选文件。 |
| mapping / batch / SimTop | `unknown` | 当前源码默认 reg-to-mem=1、SimTop、batch 参数可显式传入；候选 JSON 的 mappings=0 与 CPU mapping 要求不匹配，不能推断历史值。 |
| 生成 C++ 目录与提交 | `unknown` | 现有候选 emu 目录没有可关联的 C++ 源清单或生成 Makefile。版本化 NO0591/NO0670 记载过 gate57/gate67 的独立临时生成目录和命令，但没有候选 JSON 哈希或当前 emit 提交绑定。 |
| 编译器与 flags | `unknown` | 旁证显示 clang++、`-std=c++20 -O3` 的实际 gate 日志；候选 ELF `.comment` 同时含 GCC 13.3.0 与 clang 22.1.2，无法恢复各 TU 的完整命令、链接输入和对应生成提交。 |
| emu | `verified_file`；C++→emu `unknown` | 167,671,192 bytes，SHA-256 `58710fd69e873b4b6c7d49796a7399d79c29909572b6c9f41e0c9959f6cd8da2`；符号链接目标存在，模型选择头指向 `GrhSIM_SimTop`，但没有来源 manifest。 |
| CoreMark 负载 | `verified_file`；历史绑定 `unknown` | 16,712 bytes，SHA-256 `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`。 |
| NEMU | `verified_file`；历史绑定 `unknown` | 567,504 bytes，SHA-256 `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`。 |
| 初始化 / seed | `unknown` | 当前 args 头默认 seed=0，版本化 gate57/gate67 文档记录 seed=0；这只能证明那些 gate 的运行口径，不能证明候选 emu 的初始化和 seed。 |
| 单线程 / 50k 配置 | `unknown` | Makefile 记录 `XS_NUM_CORES=1`、可显式设置 50,000 周期和关闭波形；历史 gate 文档记录 50k 功能结果，但候选身份链未闭合。 |
| CoreMark/NEMU 正确性与性能 | `mismatch`（相对于本步准入要求） | 历史 gate57/gate67 有 50k、50 个采样和 NEMU 记录，但其输入、生成目录和 emu 与候选 checkpoint 的关系无法核实，不能作为本任务窄 MUX 基线。 |

## 历史旁证结论

提交历史确认了独立 GrhSIM IR 路线、CPU mapping/emitter 阶段和 reg-to-mem 默认值变更；实现进展文档明确早期阶段只保证 flat GRH lowering、verify、store/load、round-trip，CPU mapping/emit 尚属后续增量。NO0591、NO0594、NO0595、NO0670 等文档记录了 gate57/gate67 的生成命令、clang++/O3、SimTop、batch=0、seed=0 和 50k 运行，但这些记录引用的是独立临时输入与输出，未记录候选 464,968,979-byte JSON 的来源哈希，也未记录当前候选 emu 的哈希。因此只能标为旁证，不能升级为 verified 关联。

## 停止条件与最小恢复项

继续追溯已无新增来源证据，按任务书停止。后续若要恢复，外部必须提供：

1. 冻结 flat GRH 文件及 SHA-256；
2. 同一文件的生成提交、filelist、read-args、mapping（含 reg-to-mem 与 batch）、SimTop、keep-origins、初始化和 seed manifest；
3. 由该输入生成的 C++ 目录完整清单及生成提交；
4. build-only 的实际编译器、flags、链接输入和 emu SHA-256；
5. emu 与 CoreMark/NEMU、单线程、50k 运行配置的关联日志。

在上述材料到齐前，不得宣称 `ready_for_rebuild`，不得以现有 checkpoint/emu、静态代码体积、414,218 条静态命中或 gsim 40 秒规划参照替代性能基线。没有修改生产代码、Makefile、XiangShan、负载、测试方法或调度 JSON。

## 遗留问题

冻结 flat GRH 及其来源、候选生成 C++ 身份、当前 emu 的生成链、完整编译参数和初始化/seed 仍待外部恢复；恢复后才能进入三阶段 Makefile 重建和受控窄 MUX 正确性/性能比较。
