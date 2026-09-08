VRT_VERDICT: continue

VRT_PRIMARY_PROGRESS: 已推进至首次完整目标链的最早真实阻塞定位。该步没有技术实现修改或候选提交；目标一确实启动并在 XiangShan RTL 生成阶段失败，方向假设未被检验，必须续接环境修复后的同口径完整链。

VRT_EVIDENCE_CHECK:

- 独立性与现场：在 `/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1` 独立检查，入口 HEAD=`0567b6c7d0261ddd1834daffa8f15327c7f5810a`，入口分支为 `vrt/grhsim-ir-st-opt/c9a4c84b/week_1/r_1` 且无 diff。`wolvrix` HEAD=`cba9c32240f3cd06c5b675968b56046e5b76f818`，嵌套 XiangShan HEAD=`4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`，gsim HEAD=`a3ecb26aa0c18f55c7fbba20e7a9b9d14a25442a`；ready-to-run 分别为 `912f92121570bd28cabbefa7fa56d25b9784c304` 与 `9f476f8b72eb517cb70c1ad1aa92638c419d3034`，均与 baseline.md 一致且 clean。`git ls-tree HEAD` 的父 gitlink 为 wolvrix=`cba9c322...`、XiangShan=`4a6e3da...`、gsim=`a3ecb26...`，无跨方向提交或生成物来源迹象。结果报告中“分支”描述对入口成立；嵌套仓库实际为 detached HEAD，已在此更正记录。
- 原始命令与日志：工程师先以未 source 环境的命令尝试，`make` 退出 2；随后执行 `source ./env.sh` 并把已有 `/home/gaoruihao/wksp/mill` 加入 PATH，再运行：`make -j1 xs_wolf_grhsim_ir XS_GRHSIM_IR_BUILD=$PWD/ptmp/build/w1-r1-s1-a-0567b6c-cba9c32 XS_LOG_DIR=$PWD/ptmp/logs/w1-r1-s1-a-0567b6c-cba9c32 RUN_ID=w1-r1-s1-a-0567b6c-cba9c32 CCACHE_DISABLE=1 VM_BUILD_JOBS=8 XS_VM_BUILD_JOBS=8 GRHSIM_MODEL_BUILD_JOBS=8 CMAKE_BUILD_PARALLEL_LEVEL=8`，退出码 2。原始非空日志为 `ptmp/logs/w1-r1-s1-a-0567b6c-cba9c32/target1-mill.stdout.log`（6470 bytes，SHA256=`7ba0a4f44c8c721d2ee6c019d7f8647f1ae392d9e1d8942fc06f695ce410df6e`），另有 driver、rerun、sim-verilog 日志；只读回执日志亦记录同一错误。失败栈为 `org.objectweb.asm.ClassReader` / `Unsupported class file major version 69`，发生于 Mill `methodCodeHashSignatures`，Makefile:275 的 `sim-verilog`，因此这是最早阻塞。
- 共同起点→本方向修改→测量候选：共同起点为上述入口/wolvrix SHA；本步没有源码修改，测量仅是同一起点的阻塞尝试，没有 A 性能候选或优胜声明。ptmp/build 与 ptmp/logs 均位于方向 1；未发现 mill/emu/verilator 残留进程。

|验收项|独立结论|证据与缺口|
|---|---|---|
|F01|通过|无允许范围外或禁区源码改动。|
|F02|通过|入口、嵌套仓库 HEAD/tree/status、父 gitlink 与 baseline/race 一致。|
|F03|失败（阻塞）|真实 Make 目标已执行；Mill/ASM 与 Java class major 69 不兼容，RTL/IR/模型/emu 指纹未产生。|
|F04|未测|未进入 50,000 周期仿真，无采样、difftest 或终态。|
|F05|失败（未完成）|目标一退出 2，目标二/三未执行；完整单线程链未闭合。|
|F06|未测|未到 emu build，不能给出冷编译 <1800 s 结论。|
|F07|未测|无 A/B、性能样本或稳定性证据。|
|F08|通过（交付）|结果报告、绝对日志及哈希已归档；本审查补充独立核验。|

VRT_NEXT_STEP: 下一 ENGINEER 调用（剩余 5/6）只处理该具体阻塞并接回完整链：在方向 1 worktree 通过项目 Makefile/环境入口核对 XiangShan `.mill-version`=0.12.15 所需 Java/Mill/ASM 兼容组合，优先选择已存在且兼容的 JDK/Mill 启动方式，记录 `java -version`、`mill --version` 和工具路径指纹；不得改 baseline、依赖或测试源码。修复后使用新的 run_id 后缀，按任务书原样串行执行 `xs_wolf_grhsim_ir` → `xs_wolf_grhsim_ir_build_emu` → `run_xs_wolf_grhsim_ir_emu`（CPU2、powersave、50,000 周期、每1000采样、EMU_THREADS=0），保留每条命令完整 stdout/stderr、退出码、生成物哈希和残留进程检查。若环境无法在本调用安全固定，记录失败现场并交 PM/PI 统一环境修复；不要把本次阻塞当作方向 no_value。

按 race_contract，本方向仍为独立候选状态“尚无候选（0/6 已成功工程调用中的技术候选）”；本审查不计工程配额，不能改变共同基线或其他方向状态。未完成实验仅表示证据未闭合，连续无推进规则尚未触发。

## PI v2 勘误（执行编号 week-1-ra-1-plan-step-2-env-v2-c9a4c84b）

以下勘误保留本审查原文及其历史判断，以 PI 公共环境补充 B1-c9a4c84b-v2（档案提交 `719fc9a655034dd104eda63218703e451f8e42bf`）和实际只读证据为准：

- RA1 本周工程调用配额是 **1/6，剩余 5 次**。唯一计费任务是 `week-1-ra-1-step-1-eng-c9a4c84b`，returned/exit_code=0；同一任务内部三次失败尝试不重复计费。原文“0/6 已成功工程调用中的技术候选”把技术候选数和调用用量混淆，不能作为配额结论。
- F02 应收窄为“共同源码起点匹配，但可变环境/产物隔离未通过”。入口仍有 `?? out/`；首轮使用了 `testcase/xiangshan/out`、`r_1/.venv` 和用户共享 Mill/Coursier cache，不能称为按 run 隔离或 clean。证据为 `/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/evidence/pi-env-v2/{roots-before.log,recursive-before.tsv,gitlinks-check.log,fingerprints.log,out-processes.log}`，以及隔离 TSV SHA256 `6149d82c9e892b1fe92ce0682b5f37cabf5500c51fcbd4f35037d90044a343db`。
- F08 仅表示本步结果/审查报告和日志已存在，不代表最终 6/6 工程调用、逐步审查、完整目标和周末验收已经通过。
- 目标首轮实际尝试的是 Mill 0.12.15 / Java 25，因 ASM 报 `Unsupported class file major version 69` 退出 2；RA 的 version 探测另行误启动 Mill 1.1.6 / Azul Java 21，并产生入口 `out/`。两类产物和日志不得混同，也不能把 version 探测当作目标兼容性证明。
- `source ./env.sh` 实际安装了依赖且未经过 Makefile；因此用户共享 cache 与 `r_1/.venv` 都不是合格的按 run 隔离环境。后续不得再次 source 该旧安装入口或重复有副作用探测。

本勘误不改变原始目标、RA1 的通用宽值与边界缓冲 emitter/runtime 方向，也不宣称环境或目标已验证。下一步只解除 F02/F03/F05 阻塞；修复成功后立即回到完整 50k 链。
