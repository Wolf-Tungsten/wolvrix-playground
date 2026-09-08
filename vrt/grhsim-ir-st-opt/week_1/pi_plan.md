# PI_PLAN：grhsim-ir-st-opt 第 1 虚拟周

`week-1-pi-plan-baseline-isolation-c9a4c84b` 于 2026-09-08 执行。R=3，W=6；RA 1/2/3 当前均 0/6。PI/RA 调用不计费，虚拟调用次数不等于物理时间。原始需求逐字保留于 [requirements.md](../requirements.md)，共同版本/输入/工具见 [baseline.md](baseline.md)，实际 worktree 与赛马约束见 [race.md](race.md)。三文件相互引用；本周只完成规划与隔离，不实施优化或运行替代工程实验。

## 共同边界和目标

目标是优化 grhsim-ir 路线的**单线程** XiangShan CoreMark 50k 仿真，用户参照 gsim 约 40s，编译时间 `<30min` 是独立性能指标。允许扩展 grhsim-ir 语义、通用高性能 op/emit、分区调度、行为等价通用子图替换；禁止修改冻结 GRH IR 及 GRH 上的 pass、修改 XiangShan 和测试相关源码、多线程仿真加速、按特定模块名匹配优化。每个方向必须报告优化候选的完整 50k 实测单线程性能。gsim 约 40s 只是用户参照，不能写成实测成绩或替换主目标。

共同 A 起点是 baseline.md B1-c9a4c84b-v1：入口 `0567b6c7d0261ddd1834daffa8f15327c7f5810a`，wolvrix `cba9c32240f3cd06c5b675968b56046e5b76f818`，XiangShan `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`，gsim `a3ecb26aa0c18f55c7fbba20e7a9b9d14a25442a`；输入和 Makefile 指纹、递归依赖见清单。入口当前档案提交推进与代码基线严格分开。所有方向从 race.md 新会话后缀 worktree 起步，后续只续接本方向提交；不得 merge/cherry-pick/copy 其他方向代码或生成物。

## 三个独立方向

### 方向 1：通用宽值与边界缓冲 emitter

**目标与联系：**在 GrhSIM CPU emitter/runtime 的通用 wide-value、partition boundary、helper 调用路径减少临时复制和重复转换，遵守 pointer/caller-provided output buffer 的 legacy 性能路线；不改变 GRH IR、pass 或 XiangShan。它直接针对用户鼓励的高性能 op/emit，并以单线程模型降低仿真时间。

**假设：**目标 coremark 模型的宽值边界搬运和 helper 临时对象占用足够大；保持 compute/commit、history、mask 和多写口顺序可把搬运减少而不改变观察行为。

**证明/证伪：**完整 50k 对拍所有有序采样、终态和退出状态与 A 相同，冷编译 `<30min` 且至少一次完整运行比 A 的配对中位数更快（同时满足 F07 的资格阈值）；若结构/功能失败，或 profile/源码核查显示边界搬运不是主成本且完整 A/B 无可重复改善，则假设在本方向证伪。局部 helper 快、不等价或未完成目标不算证伪/通过。

**目标测试与证据：**首个 ENGINEER 调用必须在 r_1 从空独立输出目录实际执行完整 `make xs_wolf_grhsim_ir ...` → `make xs_wolf_grhsim_ir_build_emu ...` → `make run_xs_wolf_grhsim_ir_emu ... XS_SIM_MAX_CYCLE=50000`，到完成或第一个真实阻塞；之后每步围绕该阻塞。提交的 emitter/runtime diff、模型/emu SHA、编译起止、三次以上 taskset 运行日志、终点对拍和结构/回归报告写入方向报告。

### 方向 2：通用活动度与分区调度成本模型

**目标与联系：**只在允许的 CPU GrhSIM 后端调整通用 `cpu.st.*` partition/schedule 参数或算法（例如 active-word/function 边界、任务批量成本），不按模块名特化、不改冻结 GRH/pass、不启用仿真多线程。它针对用户鼓励的分区调度并同时观察编译时间。

**假设：**现有固定容量/目标批量在 XiangShan 的真实 DAG 上产生过多 task、函数或冗余 activity scan；用 IR 形状和估算成本决定边界能同时减少运行时开销而保持 schedule 不变量。

**证明/证伪：**mapping 的 phase/event/domain、DAG 顺序、E/roundSeeds、fanout、history 和 task coverage 结构检查通过；完整 50k 终点与 A 一致，编译 `<30min`，且 F07 规定的成对中位数和重复稳定性优于 A。若 schedule invariant/功能失败，或完整 A/B 无达到阈值的改善，则证伪；小图统计、函数数减少或单次微基准不能单独判定。

**目标测试与证据：**首步在 r_2 尝试同一完整目标流程，不因预计耗时长跳过；辅助分析只能解释一个具体阻塞并在下一步重新运行完整目标。记录 mapping JSON 的结构指纹/统计、既有 Makefile 回归、冷编译时段、单线程运行日志、候选 commit 与对 A 的 diff。

### 方向 3：通用语义等价子图/状态访问替换

**目标与联系：**在 grhsim-ir/CPU lowering 或 emit 允许的通用语义层实现可证明等价的状态 read/commit、内存 cell/写合并或 event/history 快路径；覆盖任意满足不变量的子图，不匹配 XiangShan 模块名，不碰 GRH IR/pass、输入或测试源码。它对应用户鼓励的行为等价通用子图替换。

**假设：**常见通用 read-before-write、重复 fanout 或同轮有序 memory 写可在 GrhSIM IR 后端中合并，若保留 deferred publication、mask、history 和 call/event guard，可减少 per-eval 工作。

**证明/证伪：**对现有 CPU emit/reg-to-mem/dual-RAM/多时钟等回归均通过，完整 XiangShan 50k 的每个采样/终态/对拍与 A 一致，冷编译 `<30min`，F07 的重复 A/B 性能达到资格阈值；任一语义差异、非通用匹配、性能无改善或编译超时均排除该候选。辅助反例不能替代完整目标。

**目标测试与证据：**首步在 r_3 实际尝试全流程；随后每次调用都必须是区别明确的反例、边界、修复或独立复核，并最终回到完整 50k。记录 pass/emit diff、输入/模型/二进制指纹、对拍终点、编译墙钟、单线程进程证据和每次原始日志。

## 固定最终验收表（RA 无权缩减或改写）

|编号|固定验收项|通过所需证据；缺失即未通过|
|---|---|---|
|F01 需求与边界|候选只改允许的入口/wolvrix 代码；无冻结 GRH IR/pass、XiangShan/测试源码、多线程、模块名特化；精确 Git diff、依赖清单、候选 commit|
|F02 共同基线/独立性|与 baseline.md SHA/tree/gitlink 一致；race.md 方向 worktree clean 起点；无跨方向 merge/copy/生成物；每步 status、HEAD、父 gitlink、产物来源|
|F03 输入与流程|XiangShan HEAD/ready-to-run 两文件 SHA 与 B1 一致；真实 Makefile 目标链和完整命令；模型/RTL/filelist/emu SHA|
|F04 行为正确性|现有 CPU mapping/schedule/emit、GrhSIM IR/必要 HDLBits 回归按 Makefile 通过；50k 每 1000 周期有序采样、NEMU difftest、终点 PC/trap/instruction/状态与 A 一致；无 mismatch/ABORT/BAD TRAP|
|F05 完整单线程目标|`make run_xs_wolf_grhsim_ir_emu XS_GRHSIM_IR_BUILD=<fresh> XS_SIM_MAX_CYCLE=50000 XS_WAVEFORM=0 XS_WAVEFORM_PATH= XS_PROGRESS_EVERY_CYCLES=1000 XS_NUM_CORES=1 XS_EMU_THREADS=1 EMU_THREADS=0 XS_LOG_DIR=<direction>/ptmp/logs RUN_ID=<unique>` 的真实成功日志；进程树/flags 证明无线程并行仿真，不能以局部 benchmark/旧日志替代|
|F06 编译时限|从清空且方向私有的模型/emu/build 输出开始，记录 `make xs_wolf_grhsim_ir` 到 `make xs_wolf_grhsim_ir_build_emu` 完成的 wall-clock 起止、退出码、编译器和 `VM_BUILD_JOBS=8`；每个候选至少一次冷编译 `<1800s`，缓存命中另报，不把环境安装或仿真时间混入编译成绩|
|F07 可比性能与稳定性|同 A/B 输入、CPU 2、powersave、串行其它负载、同 flags；候选与 A 各至少三次完整 50k，交错顺序、各自新 RUN_ID/日志，报告 emu `Host time spent` 中位数与每次值。候选资格要求 F01–F06 全部通过且 median(candidate) < median(A)×0.99，三次方向内运行最大/最小比不超过 1.05；超过噪声阈值或少于三次则不可排名。运行时计时只取 emu 进程启动至退出，排除构建、日志准备和 gsim|
|F08 交付与复核|RA 独立复核源码、原始日志、指纹、编译/仿真计时；方向 6/6 工程调用、步骤审查和周报齐全；候选精确 commit 可从共同起点复现|

gsim 参照可按相同输入和单线程口径另测并报告，但约 40s 不进入 F07 的替代主目标；无 gsim 实测也不能阻止 grhsim-ir A/B 验收。`F07` 的 1% 门槛只是抗噪声的候选资格规则，不是对用户需求的放宽；即使所有方向快于 A 但未达到门槛，也写“无合格方向”。编译 `<30min` 是 F06 独立硬门槛，不能用快仿真抵销。

## 测量协议与调用交接

每方向输出根分别为 `ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_<i>/ptmp`，构建 `XS_GRHSIM_IR_BUILD`, `XS_LOG_DIR`, `XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR`, temporary/pip/ccache/XDG/Mill/Ivy/Coursier caches 全部方向私有且带候选 SHA；绝不引用入口主检出或别的方向。共享只读 ready-to-run 必须先核 SHA。候选输出目录为空/新建；旧 checkpoint、旧 emu、旧日志不能混入。

首个 ENGINEER 调用动作类型必须为 `target`，真实执行完整流程到最早阻塞；不能以预计耗时跳过。辅助调用只能是 `blocker`/`support`/`verification` 并引用 F01–F08 的具体阻塞、决定规则和接回命令。连续两步 `none` 时，RA 第二次审查必须记录失败代码位置、不同修复假设和验证命令；未完成不是证伪。每位 RA 必须成功使用满 6 次 ENGINEER 调用：done/no_value 也须用剩余调用做区别明确的反例、边界或独立复核，不能重复报告充数。RA/ENGINEER 不得改 baseline.md、requirements.md 或本规划。

发现遗漏依赖、公共修复、污染或目标漂移时，立即停止该方向候选声明，报告 PM；PI 追加带版本的 baseline/race/验收口径，全部受影响方向从共同起点重新测量。周末仅在 3×6 次成功调用、逐次 RA 审查/周报齐备后，由 PI 选至多一个满足 F01–F08 的方向，记录每个仓库精确候选 SHA；并列按 median 仿真时间较小者、再按编译时间较小者，仍并列则记录无可区分优胜者而不集成。PM 再派 Agent 只集成一个方向，集成后在目标引用复验；部分多仓库成功、冲突修复或集成版本变化均须重新验收。无合格方向则不集成，保留三个方向分支和报告。

## 本动作状态与缺口

本动作没有运行构建、安装、测试或优化实验，没有伪造成绩。已建立三组入口/wolvrix worktree 和递归依赖私有检出，见 race.md 与 `ptmp/.../evidence/isolation-verified.tsv`（489 行、SHA-256 `6149d82c9e892b1fe92ce0682b5f37cabf5500c51fcbd4f35037d90044a343db`）；该证据逐方向核了 HEAD/tree/clean。待工程阶段补齐：Mill/Python 环境合法入口、每方向首个完整目标尝试、六次成功 ENGINEER 调用及 RA 审查、完整编译/运行证据、周末 F01–F08 验收和单一方向集成。当前不声称“目标已可实施”或性能已改善；隔离本身已实际完成，技术实验尚未开始。

VRT_PRIMARY_GOAL: 完整单线程 XiangShan CoreMark 50k grhsim-ir 性能与 <30min 编译目标，按 F01-F08 验收
VRT_SUCCESS_CRITERIA: 本 PI_PLAN 固定三方向假设、完整目标命令、共同基线、正确性、编译和排名规则；不产生优化成绩
VRT_TARGET_PATH: 三个方向均已从 B1 共同起点隔离；下一步首个 ENGINEER 必须在各自私有 worktree 运行 F05 完整流程至真实完成或最早阻塞
VRT_TASK_KIND: target
VRT_NEXT_TARGET: 在 r_1/r_2/r_3 分别以独立 XS_GRHSIM_IR_BUILD 和日志目录执行 F05 命令；若失败，按原始退出码和日志转为 blocker 后回到同一命令
