# SimpleTES B native landing

## 实现与验证计划

根据 [TNO0295](./TNO0295_simpletes_b_to_ab_valid_retest_20260909.md) 的直接 B→AB
复测，用户要求将 B 落地到 Wolvrix，然后对当前默认 base 与 base+B 复测。
本阶段只落地 B（selected hot-input compute dispatch branch weighting），
不包含 A 的激活位图合并写入或 C 的 commit clear 省略。

实现直接放在通用 `wolvrix/lib/emit/grhsim_cpp.cpp`，C++ 和 Python emit 路径
默认共享这段逻辑，无 SimTop 配置覆盖，无变量名/模块名匹配，也不借用
`targeted-direct` 开关。已有结构分析选出热输入后，仅在非 fullpass、compute
phase、clearMask 等于 dispatchMask 的 eligible word 内，将该输入直接激活的
supernode guard 从 `unlikely` 改为 `GRHSIM_LIKELY`。其他分支仍使用原提示。
该改变不删除运行时条件，也不绕过 supernode 执行语义。

开始时 parent HEAD 为 `4d59a0e15c7d47d7dfb7abeea4624530393db895`，
Wolvrix HEAD 为 `6a895c9375b029e0a65e7512dfcf0fbbc2c0007a`。
当前 emitter 在落地前与消融基线 `054c6a7` 相同，但当前仓库另含 RepCut 更新，
因此会从当前源码分别建立独立的 base/base+B 构建，并使用相同冻结 RTL/输入、
编译器和默认生成选项。不能将消融时期的 ELF 直接标为本轮 fresh 落地产物。

B 的三个研究 patch hunks 已应用到生产源码；应用后实际读取的 emitter SHA-256 为
`4d1aaff4b647ed3e064335d80762253666572fef2e0c1bebc574c1035768d051`，
与已消融的 B source 一致。该 SHA 是应用后计算的文件身份。
测试将覆盖结构门槛、选中/未选中的 compute guard、commit guard 以及输入变化下
的生成模型功能。生产默认代码与测试完成验证后按任务阶段提交；实际 commit
身份、build/function 结果和性能数字在产生后记录，不预填。

性能继续以 SimTop 50k 的 `Host time spent` walltime 为准，关闭 ASLR，
ABBA+BAAB 在相同 CPU/CCD/NUMA 上执行，fresh inode staging、空闲 CCD、
持续监测、NUMA、PMU、功能和完整八项稳定性门禁均保持原标准。
order gap 要求 `<0.25 pp`，无效组不用于默认性能结论。

SimpleTES 后续研究应以实际提交后的 native-B 基线和新的空 patch seed 开始，
旧 checkpoint 的 pin/control 保持其历史含义，不自动启动研究。本阶段更新
必要的 pin、说明和离线回归入口，确保新的 control 随实际 baseline 重新构建。

## 测试覆盖范围说明

新增定向 fixture 实际覆盖选中/未选中输入的 compute guard、端口重排、
结构门槛边界，以及生成模型在冷热输入变化和重复 eval 下的输出。
commit/fullpass 不应用本提示由 emitter 的显式 phase/fullpass 条件保证，
本次没有新增专门的 commit/fullpass 负向 fixture；现有相关回归仍一并执行。

## 实现提交与 C++ 回归

实际 Wolvrix 提交为 `94109bc68e0f0ea76d6083b3c193750be9a7bfae`，
只包含 emitter 与对应测试两个文件，B emitter SHA 保持上述实际值。
在 node032 的独立 `wolvrix/build/b_landing_20260909` 目录以 clang 19.1.1、
Release、新 CMake 配置构建，关闭无关的 MtKaHyPar/libfst 可选库；
未修改工作区已有 mt-kahypar 构建产物。构建目标为 `emit-grhsim-cpp`、
`emit-grhsim-cpp-memory-fill`、`transform-activity-schedule`，313 个构建步骤成功。

随后执行 `ctest --test-dir wolvrix/build/b_landing_20260909 --output-on-failure
-j1 -R '^(emit-grhsim-cpp.*|transform-activity-schedule)$'`，8/8 通过，
总计 497.47 秒；包括完整 emitter、direct-hot-input-event、commit-exact-event、
assertion-outer-guard、deferred-activation-forward、same-batch-activation-cohort、
memory-fill 与 activity-schedule。原始报告保存在该构建目录的
`Testing/Temporary/LastTest.log`。

SimTop fresh 构建已在提交前冻结 base/base+B 源码、测试、RTL、evaluator/runtime；
其 provenance 如实标记旧 commit 加实际 B 文件修改，之后的提交不改变输入。
本记录提交时 fresh SimTop 构建与 50k 配对复测仍在执行，结果另行归档。
