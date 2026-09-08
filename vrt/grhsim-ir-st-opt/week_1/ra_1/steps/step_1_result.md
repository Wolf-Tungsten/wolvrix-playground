# RA1 Step 1 ENGINEER result

VRT_PRIMARY_PROGRESS: narrowed
VRT_EVIDENCE: 首次完整目标链已真实尝试。入口 worktree `/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1` HEAD `0567b6c7d0261ddd1834daffa8f15327c7f5810a`，分支 `vrt/grhsim-ir-st-opt/c9a4c84b/week_1/r_1`，干净；子仓库 wolvrix `cba9c32240f3cd06c5b675968b56046e5b76f818`，XiangShan ready-to-run `912f92121570bd28cabbefa7fa56d25b9784c304`，gsim ready-to-run `9f476f8b72eb517cb70c1ad1aa92638c419d3034`，均无差异。父 gitlink 与共同基线一致。首试未 source env.sh，Make 退出 2；按合法环境入口 source 后重试，发现 PATH 缺少已有 `/home/gaoruihao/wksp/mill`，加入 PATH 后再次重试。实际命令及全部参数记录于 `ptmp/logs/w1-r1-s1-a-0567b6c-cba9c32/driver.log`。目标一命令退出 2，最早错误为 `org.objectweb.asm.ClassReader... Unsupported class file major version 69`，位置 XiangShan `sim-verilog` Make 目标（Makefile:275），原始输出 `target1-mill.stdout.log` 非空。输出仅在本方向 `ptmp` 下；无源码优化修改。
VRT_REMAINING_GAP: Mill/Java 版本兼容性阻塞尚未解除；IR 生成、emu 构建、50,000 周期仿真、正确性终点和性能均未测。下一步应核对 XiangShan 要求的 Java/Mill 版本与当前环境，在本方向通过合法 Makefile/环境入口修复后重接同一 RUN_ID 后缀的新完整链；不得据此宣称方向假设证伪。
VRT_TARGET_RUN: attempted
VRT_TARGET_COMMAND: `make -j1 xs_wolf_grhsim_ir XS_GRHSIM_IR_BUILD=$PWD/ptmp/build/w1-r1-s1-a-0567b6c-cba9c32 XS_LOG_DIR=$PWD/ptmp/logs/w1-r1-s1-a-0567b6c-cba9c32 RUN_ID=w1-r1-s1-a-0567b6c-cba9c32 CCACHE_DISABLE=1 VM_BUILD_JOBS=8 XS_VM_BUILD_JOBS=8 GRHSIM_MODEL_BUILD_JOBS=8 CMAKE_BUILD_PARALLEL_LEVEL=8` (after `source ./env.sh; export PATH=/home/gaoruihao/wksp:$PATH`)
VRT_TARGET_EXIT: 2
VRT_TARGET_LOG: `ptmp/logs/w1-r1-s1-a-0567b6c-cba9c32/target1-mill.stdout.log` (absolute: `/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1/ptmp/logs/w1-r1-s1-a-0567b6c-cba9c32/target1-mill.stdout.log`, SHA256 `7ba0a4f44c8c721d2ee6c019d7f8647f1ae392d9e1d8942fc06f695ce410df6e`)

## F01-F08

| 项 | 状态 | 证据/缺口 |
|---|---|---|
| F01 | 通过 | 无技术源码改动；仅运行环境与日志。|
| F02 | 通过 | 起点、子仓库 HEAD/tree/status、父 gitlink 已核对。|
| F03 | 失败 | Make 命令已记录；Mill 版本兼容阻塞，模型/RTL/emu 指纹未生成。|
| F04 | 未测 | 未进入仿真。|
| F05 | 失败 | 第一目标真实尝试退出 2，后两目标未执行。|
| F06 | 未测 | 未到模型生成/emu build 完成。|
| F07 | 未测 | 无 A 性能样本。|
| F08 | 通过 | 本报告及非空原始日志已写档案；待 RA 独立复核。|

编译计时：重试 2026-09-08 20:44:27 至 20:44:33 (+08:00)，约 6 s；冷/热缓存状态：本方向首次生成，Mill 缓存部分已有。仿真未启动，CPU2 governor 核查为 `powersave`。未发现残留 mill/emu/verilator 进程。共同起点→本方向修改→测量版本关系：共同起点 `0567b6c`/`cba9c32`，本步无修改，测量候选同一起点；无候选优胜声明。

本步完成的是目标链的首次真实尝试并定位最早阻塞，不等于原始 50k 性能优化目标完成。
