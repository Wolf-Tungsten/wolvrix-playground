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

## 第 1 周环境补充与 RA/ENGINEER 交接（B1-c9a4c84b-v2）

执行编号 `week-1-pi-common-environment-amendment-c9a4c84b`，2026-09-08。本段追加于既有周规划，原三方向、原始需求、F01–F08、编译 <1800s、F07 的 1%/5% 门槛和最终选择规则全部保留。环境及历史状态按 [baseline.md §6](baseline.md#6-公共环境补充-b1-c9a4c84b-v22026-09-08)、[race.md 当前补充](race.md) 更新。当前仍没有有效 A 或优化候选的完整 50k 成绩，不能提前选优或结束本周。

### 配额与审查纠正

只读 state.json 确认唯一成功 ENGINEER 是 `week-1-ra-1-step-1-eng-c9a4c84b`，returned/exit_code=0。因此 **RA1=1/6、剩余5；RA2=0/6；RA3=0/6**。成功返回和技术通过分开计数，首轮目标退出2也占用此次工程机会。RA 审查末尾“0/6 已成功工程调用中的技术候选”混淆配额与成绩，现明确纠正；下一 RA 应在自己的 step_1_review.md 追加勘误，保留原文，不修改 .runner。本次 PI 不计工程配额。

本 PI 读取时 pending 已是本次 PI task，running 仅本次 PI；派发说明中的 pending=null/running PM 是派发前快照，不能照抄成当前状态。没有未知 ENGINEER 调用需要重放。RA1 首次真实目标尝试要求已履行，RA2/3 首 ENGINEER 仍必须运行完整目标链至完成或最早实际阻塞，不能仅引用 RA1 失败结束调用。

审查还应追加事实：RA 20:50 的 version 探测启动的是 Mill1.1.6/Azul21 并产生入口 out；目标 20:44 使用 Mill0.12.15/Java25；首轮 source env.sh 安装依赖未经过 Makefile，使用了 r_1/.venv、XiangShan/out 及用户共享 cache。因此原 F02 的全通过仅可保留为“源码起点匹配”，环境/产物隔离尚未通过；F08 本步报告存在不等于最终6/6交付通过。没有源码 diff 不等于包含未跟踪/忽略产物的现场 clean。

### 下一 RA1 第 2 步任务书的必需内容

由后续 RA 写唯一档案目录中的 `week_1/ra_1/steps/step_2_task.md`，PI 本次不代写任务书、不执行工程。任务类型 blocker，直接解除 F02/F03/F05 的 Java/Mill 与环境入口阻塞，成功后立即返回完整目标；不得借公共修复加入其他两个方向或宽值优化实现。

1. 输入必须列 requirements、v2 全节、原三方向/F01–F08、race、step_1 task/result/review、两个指定回执和 `L` 五份原始日志、隔离 TSV 原 hash；技术 cwd 固定 r_1，起点仍入口 `0567b6c7d0261ddd1834daffa8f15327c7f5810a` / wolvrix `cba9c32240f3cd06c5b675968b56046e5b76f818`，依赖逐项同 v1。档案主检出从 `12ed381becc6fbafebe4a52a71e57301ac28e090` 仅推进本次三文档提交；不得合入 r_1 作为新代码起点。
2. 采用唯一核定 Java17.0.20 Ubuntu + Mill0.12.15 JVM / `-i` 组合，Java25、Mill1.x、自动获取的 Azul21 均排除。将 baseline 中路径/hash/精确 Python 四版本写进任务；区分“PI 核定允许”与“工程已验证”。禁止凭 --version 成功认定 RTL 生成可用。
3. 开工按 HEAD/tree/gitdir/父 gitlink/status 和忽略输出检查；保留 r_1/out、testcase/xiangshan/out、.venv、build/xs 及原日志。私有新根用 `r_1/ptmp/B1-c9a4c84b-v2/<candidate-sha>/<unique-run>`。不要清理旧现场或复用其中 classes、模型、emu、锁或 cache。记录旧 PID1605023 无进程的当前复核，若 PID 已被复用按真实命令/启动时间判断，不能直接 kill。
4. 所有安装/构建/测试通过 Makefile。现有 py_install 只能安装 wolvrix，缺 venv/固定 backend/工具验证入口；ENGINEER 可在 r_1 入口 Makefile 先补目标及必要入口辅助脚本，至少覆盖 `vrt_common_env_prepare`、`vrt_common_env_verify`（此处为建议的待实现接口，当前不存在，RA 应核对最终名称后给出命令）。前者创建新私有 venv、固定依赖/工具、输出无安装副作用的 env 文件；后者记录版本、hash、完整 Python 依赖/安装检查及路径隔离。只能引导这些目标跳过旧 env 检查，不允许跳过依赖成功检查。source 原 env.sh 会直接安装，不能重复；不得直接 Python/pip/cmake/ctest/compiler 作为替代命令。
5. 公共 Makefile 修复独立提交和记录 patch hash，限定 baseline §6.3–6.5 的环境/路径编排；方向技术代码和测试/依赖源码不改。修复后同调用继续执行原目标链，不等待优化、不止步于版本探测。工程结果交 RA 独立审查，再交 PM/PI 冻结公共修复 commit、工具/wheel 完整指纹及三方向采用方式；冻结前实验是目标推进证据，不能标作最终可比成绩。其他方向不得自行抄取尚未核定的 r_1 修改。

### 工程命令和隔离核验要求

下一 RA 必须给可执行命令（包括真实 run id、环境目标最终接口、完整日志/退出码捕获）；下面是经当前 Makefile 静态核对的交接骨架，不表示 PI 已执行或新目标已存在。RA 应在派发中要求 ENGINEER 先实现缺失目标，再调用。不能只给调查列表。

```bash
cd /home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1
VRT_RUN=w1-r1-s2-a-0567b6c-cba9c32-v2-01
VRT_RUN_ROOT="$PWD/ptmp/B1-c9a4c84b-v2/0567b6c-cba9c32/$VRT_RUN"
# 若目录已有，保留并选择新 run id；不能覆盖。以下两个新目标须先实施。
make -j1 vrt_common_env_prepare SKIP_WOLF_ENV_CHECK=1 VRT_ENV_ROOT="$VRT_RUN_ROOT"
make -j1 vrt_common_env_verify SKIP_WOLF_ENV_CHECK=1 VRT_ENV_ROOT="$VRT_RUN_ROOT"
# 仅加载上述成功目标生成、经检查无安装副作用的环境文件。
source "$VRT_RUN_ROOT/env.sh"
```

环境文件应固定 JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64、MILL_VERSION=0.12.15，PATH 先取该 JDK/bin 和指纹核定的私有 mill 入口，再取 venv/LLVM22.1.2。显式隔离 MILL_OUTPUT_DIR、MILL_FINAL_DOWNLOAD_FOLDER、XDG_CACHE_HOME/CONFIG_HOME/DATA_HOME、COURSIER_CACHE、Ivy、TMPDIR/TMP/TEMP、PIP_CACHE_DIR、Java user.home/java.io.tmpdir 等，不改 HOME。JAVA_OPTS/继承的 JAVA_TOOL_OPTIONS、JDK_JAVA_OPTIONS、CLASSPATH、PYTHONPATH、PIP 配置须核查并排除未记录注入；记录允许值，不输出凭证。工程验证须用实际写入位置/子 JVM 证据证明设置生效；不支持的变量不能默认为已隔离。

输出映射须覆盖 RTL、filelist、emit C++、emu、skbuild 和 difftest generated-src。尤其原任务未设 XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR，会导致 build_emu 的 Makefile guard 失败；本次明确要求设置它，是把原完整链具体化，不改变研究算法/参数。generated-src 生产者硬编码 NOOP_HOME/build/generated-src，必须由入口编排按 baseline §6.4 保留旧输出后建立本 run 的物理映射；不能只改消费路径或修改测试 Scala。输出链接只能指向本方向 ptmp/run；每次切换先核无进程、保存前一指向/指纹。

在新环境准备成功、依赖 wheel 下载耗时单列后，以新空源码编译输出开始 F06；py_install 的 native 编译必须纳入编译证据，不能预热后伪报冷编译。实际完整三目标使用同一参数集合，静态骨架如下（RA 须补上逐命令 tee/PIPESTATUS、计时、生成物/进程记录；前一失败时不执行后一）：

```bash
VRT_ARGS=(
  "RUN_ID=$VRT_RUN" "PYTHON=$VRT_RUN_ROOT/venv/bin/python"
  "PIP_CONFIG_SETTINGS=--config-settings=build-dir=$VRT_RUN_ROOT/skbuild --config-settings=cmake.build-type=Release"
  "BUILD_DIR=$VRT_RUN_ROOT/build" "WOLVRIX_BUILD_DIR=$VRT_RUN_ROOT/wolvrix-build"
  "XS_WORK_BASE=$VRT_RUN_ROOT/xs" "XS_RTL_BUILD=$VRT_RUN_ROOT/xs/rtl"
  "XS_WOLF_FILELIST=$VRT_RUN_ROOT/xs/filelist/xs_wolf.f"
  "XS_DIFFTEST_GEN_DIR=$VRT_RUN_ROOT/xs/generated-src"
  "XS_GRHSIM_IR_BUILD=$VRT_RUN_ROOT/grhsim-ir"
  "XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=$VRT_RUN_ROOT/grhsim-ir/model"
  "XS_LOG_DIR=$VRT_RUN_ROOT/logs"
  CC=/home/gaoruihao/wksp/LLVM-22.1.2-Linux-X64/bin/clang
  CXX=/home/gaoruihao/wksp/LLVM-22.1.2-Linux-X64/bin/clang++
  CCACHE_DISABLE=1 VM_BUILD_JOBS=8 XS_VM_BUILD_JOBS=8
  GRHSIM_MODEL_BUILD_JOBS=8 CMAKE_BUILD_PARALLEL_LEVEL=8
  XS_SIM_MAX_CYCLE=50000 XS_PROGRESS_EVERY_CYCLES=1000
  XS_NUM_CORES=1 XS_EMU_THREADS=1 EMU_THREADS=0
  XS_SIM_TOP=SimTop XS_ZERO_INIT=0 XS_SIM_DEFINES=DIFFTEST
  XS_SIM_VFLAGS=+define+DIFFTEST XS_WITH_CHISELDB=0 XS_WITH_CONSTANTIN=0
  XS_WOLF_GRHSIM_IR_REG_TO_MEM=1 XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0
  XS_WOLF_GRHSIM_IR_KEEP_ORIGINS=0 XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=64
  XS_WAVEFORM=0 XS_WAVEFORM_PATH= XS_COMMIT_TRACE=0 XS_RAM_TRACE=0
  WOLVRIX_GRHSIM_WAVEFORM=0 WOLVRIX_GRHSIM_PERF=0
)
make -j1 xs_wolf_grhsim_ir "${VRT_ARGS[@]}"
make -j1 xs_wolf_grhsim_ir_build_emu "${VRT_ARGS[@]}"
taskset -c 2 make -j1 run_xs_wolf_grhsim_ir_emu "${VRT_ARGS[@]}"
```

仍须保持 §4 其余固定值（two-state、Release、模型/emu -O3、无 PGO/LTO、seed=0、reset_cycles=50、phase timing 关闭）。CPU2 governor powersave、sibling18 无研究负载；不能将上述 taskset 代替运行线程/affinity 证明。首次成功仅建立单次 A；最终每方向候选仍须完整回归、A/B 各至少三次交错 50k、所有采样/终态/NEMU 对拍、Host time spent 中位数和 F06 冷编译 <1800s。改变任何起点/环境口径后全部受影响 A/B 重测，无法补齐不可排名。

### 返回目标、失败策略与剩余流程

工程回报须列：每条真实完整命令及 cwd/时间/整数退出码，非空 stdout/stderr 和原始日志绝对路径，版本与输入/工具/wheel/RTL/filelist/IR/model/emu 指纹，编译起止与环境安装分段时间，CPU/进程/线程证据，全部仓库前后 HEAD/tree/gitlink/status、未跟踪/忽略产物及公共补丁提交。成功到 50k 后记录每1000周期有序采样、终点 PC/trap/instruction/state、cycle limit/退出状态及 difftest；失败则明确最后完成阶段、最早新故障、残留进程、保留目录、进一步假设和重接同一目标命令。

若仍 major69：核实际 launcher/fork JVM 与 class 来源，检查是否落回 Java25 或旧 cache；在既定组合内纠正路径后重新尝试。若依赖要求更高 JVM 或 0.12.15 本身不支持所需能力：保留最小原始报错、源码/依赖版本依据和可比较方案交 PI，不升级 Mill/JDK/ASM。若转为下载/Scala/firtool/Python/native/运行错误：这表示阻塞位置变化，RA 基于新故障给下一具体修复；未测不是证伪。单纯版本检查/缓存盘点不能替代目标尝试。

各方向必须用满6次成功 ENGINEER，并逐次独立 RA 审查；done/no_value 不提前终止。连续两步无目标推进、无阻塞缩小、无独立新证据，则 RA 重核现场、定位故障并改变策略。全部配额、审查与周报齐备后 PI 才按 F01–F08 选择至多一个方向，精确列多仓库候选交 PM 派 Agent 集成/复验；无合格方向不集成、不拼接技术方案，三个方向成果保留。本次仅完成公共口径交接。

## 第1周公共返工与 RA1 step3 交接（B1-c9a4c84b-v3）

执行编号 `week-1-pi-environment-reconcile-and-race-handoff-c9a4c84b`。本段为已有周中补充，技术规范以 [baseline.md §7](baseline.md#7-公共环境返工规范-b1-c9a4c84b-v32026-09-08) 为准，原三方向/F01–F08/完整50k/编译<1800s/排名不缩减。本次PI不实施、不选优、不集成。实时成功ENGINEER仍为step1与step2两个任务，RA1=2/6余4，RA2/3各0/6余6；pending是本次PI而非派发前null，无未知工程调用、recovery_required=false。

### RA 下一任务书应固定的起点和交付

RA应在唯一正式档案根 `/home/gaoruihao/wksp/wolvrix-playground/vrt/grhsim-ir-st-opt/week_1/ra_1/steps/step_3_task.md` 拆出一个 **blocker** 工程任务；不是新周规划或提前优化任务。本PI没有创建或消费该工程调用。其输入包含baseline全部v1/v2/v3、本文全部原方向与F01–F08、race最新段、step1/step2全部task/result/review及其原始证据，审查提交1127d47acc91729789a6cb32c70847301901aec7、6bfd6a55f828d2636dba6c16fac0b44ee1eb16cf和本次档案提交。工程开始仍读实时回执，不能预记第三次成功。

|身份|下一 ENGINEER 精确续接/操作边界|
|---|---|
|启动入口|`/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1`；分支 `vrt/grhsim-ir-st-opt/c9a4c84b/week_1/r_1`；HEAD `3eea16676f73cba5f87364e8959049437de40308` / tree `7606970036deb01130b50e92d24b858454615598`。不退回A0、不从主档案HEAD起步。|
|技术仓库|入口下wolvrix，HEAD `cba9c32240f3cd06c5b675968b56046e5b76f818` / tree `6bcc50560c2fb21f5e000cc521bec5a5e58d8483`，同方向分支；本step3环境返工不改技术代码。|
|依赖|XS `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6` detached，ready-to-run `912f92121570bd28cabbefa7fa56d25b9784c304`；其他逐仓库/父gitlink/483条alternates依baseline核实，不修库/fetch/切换。|
|允许提交文件|仅r_1入口Makefile、scripts/vrt_common_env.mk、scripts/vrt_common_env.py及必要的入口环境/Git作用域辅助脚本、公共工具/依赖锁文件；用途仅为baseline §7公共编排与诊断门禁。不得混入RA1 emitter优化。|
|禁止修改|主入口或主技术代码、其他方向、XiangShan/build.mill/测试/difftest/依赖/插件jar、GRH IR/pass、输入、Git数据库/全局配置/父gitlink；不得改requirements、baseline、pi_plan、race、.runner。|
|工程交付|正式step_3_result.md、方向ptmp原始日志、公共精确父子SHA/tree/累计patch hash、环境/工具/wheel/插件锁和运行证据，交RA独立审查后再交PI；不推送、不将档案提交合入方向代码。|

开工与结束核实际路径/gitdir/common-dir/分支/HEAD/tree/gitlink/status及忽略现场，不能仅检查两个仓库。保留R/out的11个旧文件、.venv、XS/out/.docker-mill-out/build、所有Mill输出、两份v2 run及旧链接；不清理或加ignore制造clean。进程按实时exe/祖先/启动时间/占用判断，禁止旧PID处置。正式档案不能因技术cwd改变而另建同名项目。

### 本步必须解除的具体阻塞及有条件方案

目标阻塞是 L2 VcsVersion.scala:82 的实际Git rev-list exit128 / target1 make exit2；目标二/三未执行。PI独立判断 H1“外置Mill默认cwd发现入口库、hash来自XS”最优先；H2“GIT_* / config注入”未排除；H3对象缺失不获现有源码库可读证据支持。不能先把RA假设写成根因再修库，也不能再只做泛化工具盘点。

1. **先补观测与已证实的安全环境缺口。** 在上述入口范围修复v3根校验、保留空TOOL_EXTENSION、既定Verilator路径、HotSpot `-XX:+PerfDisableSharedMem`及run内tmp/error/dump路径、tracked真实owner检查；固定四包wheel字节锁，补必要工具realpath。Makefile先提供缺失的Git诊断/作用域核验入口与诊断/正式观测开关，然后才经Make调用。现有prepare/verify/observe实现不是v3已通过接口，必须返工；不能单纯source旧v2 env来跑v3。
2. **Make诊断入口包住原目标一，必须抓准失败。** 使用独立diagnostic run，捕获全部后代exec/chdir/文件写入；对Git在exec前留argv、cwd、exe、pid/ppid/starttime、白名单GIT_*和相关config来源，在exec后留输出及真实退出码。至少包括取得hash的rev-parse、exact/fallback describe、rev-list（原样--not/tag）、diff/status。实现可用入口日志wrapper加系统调用trace，绝不能依赖50ms轮询捕短命Git，也不能全量环境泄露凭证。Git对照由Make诊断目标执行同argv于捕获cwd及XS，核top/gitdir/common-dir/cat-file/history；只读取原日志不必再次遍历全部对象来取代准确exec。
3. **根据捕获证据在既定范围修复后立即回原目标。** 若H1成立，优先选工具已支持的cwd安排；否则按baseline §7.3严格范围适配默认Git调用，使同次version计算的hash/tag/count/dirty来自同一真实源码库。显式-C/--git-dir/--work-tree及合法嵌套子库调用原样透传；同一Git真实stdout/stderr/exit与在正确源码cwd直接执行结果必须一致，不能硬编码版本、hash、tag、dirty或简单把所有Git改到XS。需要给未命中/越界/显式参数情况提供不重定向证据。若H2成立，仅在对应工具进程范围处理已确认注入，证明别的子库发现不变，绝不全局export GIT_DIR。若正确XS/环境仍缺对象、需改插件或无法限定作用域，停止该链，将最小准确失败交PM/PI，不fetch、不改jar/build.mill。没有准确证据时本步只能写“假设待验证”，不可报根因已解除。
4. **完整目标不能被辅助工作替代。** 若本轮诊断未经修复已经成功，保留实际上下文与“未复现”事实，不装上无根据重定向；继续目标二/三。修复后新环境提交、新run，以同参数从目标一再起，成功就串行二/三；失败记录最早新错误并停止后段。变成Scala/firtool/Python/native/运行问题则交出准确命令/位置/退出/未测范围，不能自动换JDK/Mill/Scala或减周期。所有变更后都重新验证输出隔离与工具闭包。

原始关键证据的绝对路径已在baseline §7.1的L1/L2/RAE/E中展开。旧L2 `xs_wolf_grhsim_ir.processes.jsonl` 不是失败Git的精确exec，`mill-probe.strace`不是目标trace。四wheel和JDK/Mill单项身份已核实；prepare/verify通过不等于Scala/firtool/py_install/emu兼容。后继提交/完整锁仍未冻结，RA不能擅自转给RA2/3。

### 固定执行顺序、完整参数与隔离

由ENGINEER先实现缺失Makefile接口再调用；安装、构建、测试、Python/Git脚本工作流核验都必须走Make目标，不直接Python/pip/cmake/ctest/compiler/Java/Mill代跑，不source旧安装env.sh。下列是RA任务书必须落实的命令骨架，**不是本PI已执行的命令或已实现的新增接口**：

```bash
cd /home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1
VRT_CANDIDATE=$(git rev-parse HEAD) # 已提交的本次环境返工SHA；记录技术cba9c322
VRT_RUN=w1-r1-s3-a-0567b6c-cba9c32-v3-diag-01
VRT_RUN_ROOT="$PWD/ptmp/B1-c9a4c84b-v3/$VRT_CANDIDATE/$VRT_RUN"
# 用step_2_task的原子mkdir/重名后缀规则；已有目录拒绝覆盖，新根初始仅logs。
# vrt_stage沿用step_2_task定义：完整argv/cwd、ISO/epoch、非空原始输出、make和tee整数退出码。
vrt_stage env-prepare make -j1 vrt_common_env_prepare SKIP_WOLF_ENV_CHECK=1 VRT_ENV_ROOT="$VRT_RUN_ROOT" || exit $?
vrt_stage env-verify make -j1 vrt_common_env_verify SKIP_WOLF_ENV_CHECK=1 VRT_ENV_ROOT="$VRT_RUN_ROOT" || exit $?
# 检查此新文件仅有核定export/unset、无安装/命令替换，且所有检查成功后才加载。
source "$VRT_RUN_ROOT/env.sh" || exit $?
unset SKIP_WOLF_ENV_CHECK
```

prepare不能安装wolvrix/native或预编译Scala，verify probe输出只用mill-probe；目标用mill-target，禁止复用probe产物。路径映射完整沿用step_2_task表但环境版本改v3，root校验和observer必须同步，不能写进v2草案目录。新的candidate/run隔离关联完整入口SHA、技术SHA、公共patch和工具锁hash。诊断结束/修补后选择新唯一run，不覆盖旧链；正式冷编译另选 `w1-r1-s3-a-0567b6c-cba9c32-v3-cold-01` 及同样防覆盖后缀规则。

以下完整数组沿用step_2_task，不省略输出和仿真参数；新增的Git/观测控制变量由RA按实际实现接口明确填写，不能把未知开关当作已有功能。`MILL_OUTPUT_DIR`须以命令行传到nested make，空TOOL_EXTENSION须按v3正确处理：

```bash
VRT_ARGS=(
  "RUN_ID=$VRT_RUN" "PYTHON=$VRT_RUN_ROOT/venv/bin/python"
  "PIP_CONFIG_SETTINGS=--config-settings=build-dir=$VRT_RUN_ROOT/skbuild --config-settings=cmake.build-type=Release"
  "BUILD_DIR=$VRT_RUN_ROOT/build" "WOLVRIX_BUILD_DIR=$VRT_RUN_ROOT/wolvrix-build"
  "XS_WORK_BASE=$VRT_RUN_ROOT/xs" "XS_RTL_BUILD=$VRT_RUN_ROOT/xs/rtl"
  "XS_WOLF_FILELIST=$VRT_RUN_ROOT/xs/filelist/xs_wolf.f"
  "XS_DIFFTEST_GEN_DIR=$VRT_RUN_ROOT/xs/generated-src"
  "XS_GRHSIM_IR_BUILD=$VRT_RUN_ROOT/grhsim-ir"
  "XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=$VRT_RUN_ROOT/grhsim-ir/model"
  "XS_LOG_DIR=$VRT_RUN_ROOT/logs"
  CC=/home/gaoruihao/wksp/LLVM-22.1.2-Linux-X64/bin/clang
  CXX=/home/gaoruihao/wksp/LLVM-22.1.2-Linux-X64/bin/clang++
  CCACHE_DISABLE=1 VM_BUILD_JOBS=8 XS_VM_BUILD_JOBS=8 GRHSIM_MODEL_BUILD_JOBS=8 CMAKE_BUILD_PARALLEL_LEVEL=8
  XS_SIM_MAX_CYCLE=50000 XS_PROGRESS_EVERY_CYCLES=1000 XS_NUM_CORES=1 XS_EMU_THREADS=1 EMU_THREADS=0
  XS_SIM_TOP=SimTop XS_ZERO_INIT=0 XS_SIM_DEFINES=DIFFTEST XS_SIM_VFLAGS=+define+DIFFTEST
  XS_WITH_CHISELDB=0 XS_WITH_CONSTANTIN=0 XS_WOLF_GRHSIM_IR_REG_TO_MEM=1
  XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0 XS_WOLF_GRHSIM_IR_KEEP_ORIGINS=0
  XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=64 XS_WAVEFORM=0 XS_WAVEFORM_PATH=
  XS_COMMIT_TRACE=0 XS_RAM_TRACE=0 WOLVRIX_GRHSIM_WAVEFORM=0 WOLVRIX_GRHSIM_PERF=0
)
VRT_ARGS+=("VRT_ENV_ROOT=$VRT_RUN_ROOT" "MILL_OUTPUT_DIR=$VRT_RUN_ROOT/mill-target"
  "VERILATOR=/usr/local/bin/verilator" "TOOL_EXTENSION=")
VRT_COMPILE_START=$(date +%s.%N)
printf 'compile_start=%s\n' "$VRT_COMPILE_START" >> "$VRT_RUN_ROOT/logs/driver.log"
vrt_stage target1 make -j1 xs_wolf_grhsim_ir "${VRT_ARGS[@]}" || exit $?
vrt_stage target2 make -j1 xs_wolf_grhsim_ir_build_emu "${VRT_ARGS[@]}" || exit $?
VRT_COMPILE_END=$(date +%s.%N)
printf 'compile_end=%s\n' "$VRT_COMPILE_END" >> "$VRT_RUN_ROOT/logs/driver.log"
vrt_stage target3 taskset -c 2 make -j1 run_xs_wolf_grhsim_ir_emu "${VRT_ARGS[@]}"
VRT_FINAL_RC=$?
printf 'target_chain_exit=%s\n' "$VRT_FINAL_RC" >> "$VRT_RUN_ROOT/logs/driver.log"
exit "$VRT_FINAL_RC"
```

保持目标一实际嵌套调用 `mill -i -Djvm-xmx=40G -Djvm-xss=256m xiangshan.test.runMain top.XiangShanSim --target-dir <run>/xs/rtl/rtl --config TLConfig --issue E.b --num-cores 1 --target systemverilog --firtool-opt "-O=release --disable-annotation-unknown --lowering-options=explicitBitcast,disallowLocalVariables,disallowPortDeclSharing,locationInfoStyle=none" --split-verilog --dump-fir --firtool-opt "--default-layer-specialization=enable" --enable-difftest --full-stacktrace`，仅由原Make目标调用而非直接执行此内层命令。冻结GRH pipeline/defines/read_args不得变；two-state、seed0/reset50、Release/-O3、无PGO/LTO、phase timing关闭不变。CPU2 powersave、sibling18无研究负载，构建/仿真串行，资源不符等待而不挑CPU。

退出上述driver只停止该命令链，ENGINEER仍需完成失败取证/结果归档与现场保护。准许范围内修补后从新run重新目标一，不盲跑失败链的后段；只要到达阶段成功就立即继续，不等宽值优化才验证50k。

### 诊断/正式计时与RA审查门槛

- **diagnostic模式**完整记录trace和Git对照时间，允许跟踪器增加开销；任何此模式冷编译/50k时间不用于F06/F07排名，不通过估算减去开销还原。严守50k/1000和正确性。若此轮只到实际阻塞，记录未到达阶段，不捏造全链隔离通过。
- **正式冷编译模式**必须另起新run且同环境候选，禁用详细strace/高频全/proc扫描，保留baseline §7.5的统一1s后代/线程轻量证据，observer固定CPU0；新run不得复用诊断Scala/native/model/emu/缓存产物。准备锁定外部工具与四包wheel时间单列，正式F06连续时间含目标期间下载、Scala首次编译、py_install native、emit/model/emu，不允许先make py_install预热或从总时段扣除native。py_install是目标一依赖，包import若需检查先加合法Make入口，在安装后进行并如实记录位置/开销。OS page cache不清理，不把产物冷启动冒充硬件冷缓存。
- **F04/F05**补齐实际生成RTL、filelist顺序/defines、flat GRH/GrhSIM IR/model/emu hash；所有每1000周期有序采样、NEMU、终点PC/trap/instruction/state、host/model 50000及cycle limit/退出状态，无mismatch/ABORT/BAD TRAP；flags和运行时线程/affinity证明单线程。probe/version/prepare通过绝不能替代这些证据。
- **F07**最终仍A/B各至少三次交错完整50k，新RUN_ID独立日志，原Host time spent各值与中位数，candidate<A×0.99且max/min≤1.05；F06<1800s独立硬门槛，gsim约40s仅参照。公共后继精确锁未由PI冻结前，即使完整跑通也标“待核定目标证据”，不移植旧失败成绩或宣布可排名。
- **环境审查**除目标Git准确exec与同argv对照，还须审查HotSpot全部JVM实际选项/零外部任务写入、真正Verilator/backend、空TOOL_EXTENSION跨make值、工具realpath/运行库/wheel与Scala插件闭包、真实owner tracked检查、旧产物保留及短命进程/写入追踪。prepare/verify应拒绝坏工具/路径/锁，未覆盖即待验证。RA交PI的是精确代码/锁与证据闭包，不是未来实现承诺。

公共阻塞解除后，RA1下一技术任务立即回**通用宽值与边界缓冲emitter/runtime**；先阅读对应legacy helper，保留指针、调用方输出缓冲和局部frame/boundary策略，避免返回大std::array与热路径大临时复制。本step3不夹带此优化。RA2保留原通用调度、RA3保留原等价子图方向，不吸收彼此成果。

RA前两步已以新证据评为narrowed，不属于连续无推进；第三步须聚焦准确Git上下文与具体返工。后续若连续两步没有目标推进、阻塞缩小或独立新证据，RA必须重新定位并改变策略，不能原样重复工具盘点。RA2/3首ENGINEER仍真实尝试完整目标链至完成或最早实际阻塞。每RA用满6次成功ENGINEER、逐步审查及周报，done/no_value不提前停、未测不证伪，才进入PI最终验收。PI按周初规则只选至多一个F01–F08合格方向并列逐仓库精确候选；PM另派Agent集成至预记目标并验证，不拼接、无合格不集成，目标漂移/冲突/多库部分成功均报告重验，保留落选现场。本次不重置配额、不结束本周。
