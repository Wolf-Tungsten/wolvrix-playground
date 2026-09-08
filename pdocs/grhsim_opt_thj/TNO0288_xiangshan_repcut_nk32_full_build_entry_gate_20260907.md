# TNO0288: XiangShan RepCut N=K=32 full build entry gate

日期：2026-09-07

状态：`13 TESTS AND REAL-PACKAGE DRY RUN PASS; NO NEW MODEL BUILD OR PERFORMANCE RUN`。

前置：[TNO0287](./TNO0287_xiangshan_repcut_nk32_full_control_reproduction_20260907.md)。

## 1. 独立完整构建入口

`build/repcut_nk32_opt_20260907/stage4_build/build_full.py` 接收原生 package、flat SimTop.sv、
work、assignment 及 fresh output 路径，默认只 dry-run；显式 `--execute` 才编译。
完整构建必须在空 `package.runtime/build` 生成并重编全部 32 个模型，不能套用前三项
只重编 wrapper/复用 1422 对象的方法，因为新的 assignment 会改变模型本身。

保持旧 build_clean_arm.sh 的 make/Clang21.1.5/Verilator5.048 选项、C++17 和 wrapper
无 `-O`，支持套用已冻结 runtime-v1 和 push/pull。原包必须恰有 32 个 unit、正确函数
注册、空 early phase、符合既有 header/constructor 形态；filelist 按 token 解析并核对
路径归属与完整性，拒绝符号链接和旧模型对象混入。

构建前后复核原包、assignment、flat-SV、generated macros/headers、difftest make/C++
输入、runtime helpers、工具和 staged sources 身份；编译后核验每个模型端口实际存储、
全部对象 compiler marker 与四个 wrapper 的完整 argv。

review 修正：manifest 的 `toolchain` 必须与冻结 reference 字典完全一致，新增工具
SHA 另放 `tool_identities`，否则测量器会拒绝同工具链配对。构建 PATH 明确 LLVM/bin
优先并检查实际 ld.lld 身份；原脚本依赖启动环境 PATH，不新加链接优化选项。

入口 SHA：`7f4aec974c3daae7d80afde026b41274f31a5ae204fd7504e49e4514bdf3ec36`。
13 项单元测试通过，包括默认 dry-run 不调用编译、源身份变化、ABI/布局与路径拒绝。

## 2. 真实 package dry-run

使用 TNO0287 完整重建且逐字节验证的 control package，实际执行独立 staging、所有
结构门和构建 plan 生成；模式为 legacy/push，输出 `stage4_build/control-dryrun-v1/`。

`build-plan.json` SHA：`bc4a749ed241fb4c1fe3af14041d37aed029090e1510c6da498bbaac335f059c`。
staged common 与前三项的 `runtime/generated-v1` common 逐字节一致，SHA 均为
`f3cd97adafe3670c3fc89e12cb27b2a3643221f8f27c537e575acef0518e5909`。

本次未执行 make，没有生成新模型对象或 emu，不把 dry-run 记作完整 build pass。
后续真正构建必须指定另一个 fresh output，不能复用已存在的 dry-run 目录。

## 3. 本轮交接

四项准备均有独立实现/验证证据，但四项实际性能比较都未完成：调度器、CCD 映射、pull
的真实模型功能 canary 也尚未启动；校准没有选定 runtime 数据，所以没有生成新 assignment。
性能阻断见 [TNO0286](./TNO0286_xiangshan_repcut_nk32_resource_blocker_20260907.md)。
生产源码、安装库、冻结 ELF/assignment 和默认值未修改。需取得同 NUMA 四个 CCD 的
持续空闲窗口后，从 stage1 C100 和 C10000 AB/BA 继续，不能直接跳到后续组合结论。
