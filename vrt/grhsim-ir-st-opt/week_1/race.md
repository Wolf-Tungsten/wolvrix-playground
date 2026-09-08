# Week 1 方向隔离与赛马记录

当前记录以文末 B1-c9a4c84b-v2 补充为准；以下初建记录原样保留为隔离历史，其中“共享只读”和用量已在补充中纠正。

会话后缀：`c9a4c84b`。三方向均从 baseline.md 的入口 `0567b6c7d0261ddd1834daffa8f15327c7f5810a` 与 wolvrix `cba9c32240f3cd06c5b675968b56046e5b76f818` 建立，未从旧 r_2/r_3 成果续接。

|方向|入口分支/目录|wolvrix 分支/目录|起点核查|产物隔离|
|---|---|---|---|---|
|1|`vrt/grhsim-ir-st-opt/c9a4c84b/week_1/r_1`; `/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1`|同名分支；目录下 `wolvrix/` 独立 worktree|入口 HEAD=`0567b6c7d0261ddd1834daffa8f15327c7f5810a`；技术 HEAD=`cba9c32240f3cd06c5b675968b56046e5b76f818`；clean|`ptmp/` 及 `build/` 仅本目录|
|2|同上 r_2|同上 r_2|同两 SHA；clean|仅 r_2|
|3|同上 r_3|同上 r_3|同两 SHA；clean|仅 r_3|

实际建立方式为 `git worktree add -b ...`；三个入口 worktree 与三个 wolvrix worktree 均已存在并可复核，未清理/复用旧 worktree。XiangShan、gsim 及递归依赖保持共享只读，基线提交与输入指纹见 baseline.md；若任何依赖需修改，必须先交 PI 追加共同基线，不能只升级一个方向。工程师必须在每步记录 `git status --short`、HEAD、父 gitlink、生成物绝对路径和日志来源。

候选提交栏：方向 1/2/3 均为“尚无候选（0/6 工程调用）”。方向内只能续接本方向提交；禁止 merge、cherry-pick、copy 其他方向实现或生成物。所有研究档案仍写入 `/home/gaoruihao/wksp/wolvrix-playground/vrt/grhsim-ir-st-opt`。

复核证据：`ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/evidence/isolation-verified.tsv`（489 行，SHA-256 `6149d82c9e892b1fe92ce0682b5f37cabf5500c51fcbd4f35037d90044a343db`）逐方向核对递归仓库 HEAD/tree/status；入口和 wolvrix worktree 创建命令及输出保存在同目录 `evidence/isolate.log`。隔离阶段无失败命令、无残留构建/仿真进程；未运行优化、构建或目标测试。

## 当前补充：B1-c9a4c84b-v2（2026-09-08）

PI 执行编号 `week-1-pi-common-environment-amendment-c9a4c84b`。沿用本周与原方向，未重开周、未进行周末选优。环境核定及证据见 [baseline.md §6](baseline.md#6-公共环境补充-b1-c9a4c84b-v22026-09-08)，下一 RA/ENGINEER 任务边界及命令见 [pi_plan.md 追加交接](pi_plan.md)。全部正式档案只在 `/home/gaoruihao/wksp/wolvrix-playground/vrt/grhsim-ir-st-opt`。

### 源码、实际目录与用量

下表 `D` = `/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1`；`G` = `/home/gaoruihao/wksp/wolvrix-playground/.git`。三方向入口 HEAD 仍为 **0567b6c7d0261ddd1834daffa8f15327c7f5810a**、tree **8544a4528fac5f15fb59d57e6ef5622eccea2e99**；各 wolvrix HEAD 仍为 **cba9c32240f3cd06c5b675968b56046e5b76f818**、tree **6bcc50560c2fb21f5e000cc521bec5a5e58d8483**。入口父 gitlink 与 wolvrix、XiangShan、gsim HEAD 全匹配。未续接任何其他方向实现。

|方向/原技术方向|真实入口、技术根及分支|独立 gitdir|当前 status / 成功 ENGINEER 配额 / 候选|
|---|---|---|---|
|RA1 通用宽值与边界缓冲 emitter|`D/r_1`、`D/r_1/wolvrix`；二者分支 `vrt/grhsim-ir-st-opt/c9a4c84b/week_1/r_1`|`G/worktrees/r_1`、`G/modules/wolvrix/worktrees/wolvrix`|入口 `?? out/`；技术 clean；**1/6，余5**；无源码候选提交，无完整50k成绩|
|RA2 通用活动度与分区调度成本模型|`D/r_2`、`D/r_2/wolvrix`；二者分支 `vrt/grhsim-ir-st-opt/c9a4c84b/week_1/r_2`|`G/worktrees/r_2`、`G/modules/wolvrix/worktrees/wolvrix1`|两者 clean；**0/6，余6**；无候选|
|RA3 通用语义等价子图/状态访问替换|`D/r_3`、`D/r_3/wolvrix`；二者分支 `vrt/grhsim-ir-st-opt/c9a4c84b/week_1/r_3`|`G/worktrees/r_3`、`G/modules/wolvrix/worktrees/wolvrix2`|两者 clean；**0/6，余6**；无候选|

入口 worktree 的 common-dir 为 G，技术 worktree 的 common-dir 为 G/modules/wolvrix，仅 Git 对象/引用管理共享。各 `D/r_i/testcase/xiangshan` 和 `D/r_i/reference/gsim` 为本地独立目录、gitdir=`各自路径/.git`，均 detached/clean，HEAD 分别 `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6` 和 `a3ecb26aa0c18f55c7fbba20e7a9b9d14a25442a`，tree 分别 `bb4b5dc0ed12891829b69028b09e6352993c6d4d` 和 `306ba84c102e41a03f5d0b0ec5521747ff668861`。ready-to-run 及递归依赖也是方向私有检出；源码只读并核父 gitlink，不要求同名分支。因此初建段的“依赖共享只读”不是实际物理拓扑，应更正为“各方向独立检出，依赖源码只读；仅指纹明确的只读输入/工具可共享”。

本次逐项复核原 TSV 的489仓库 HEAD/tree 全匹配、486个已检出父gitlink全匹配；三处未检出 openc910 仍属 v1 排除项。489项仅入口r_1 status非空，其 out 为11个未跟踪普通文件，不能用“无 diff”声称完全clean；忽略缓存另行核查，见下段。原TSV历史hash未变。新只读证据在 `D/evidence/pi-env-v2/{roots-before.log,recursive-before.tsv,gitlinks.log,gitlinks-check.log,fingerprints.log,out-processes.log}`。

配额依据为 `.runner/c9a4c84b9a384fd1967b6c0a21ad71aa/state.json` 与指定 ENGINEER/RA 回执：唯一成功 ENGINEER `week-1-ra-1-step-1-eng-c9a4c84b` returned/exit_code=0；RA1审查已归档于 `12ed381becc6fbafebe4a52a71e57301ac28e090`。三次目标一失败重试属于同一成功工程调用，不重复扣费。RA审查“0/6已成功工程调用中的技术候选”有误，以此处1/6核算为准；下一RA追加勘误，不改.runner。本PI不占工程配额。PI读取时 pending/running 是本次PI，无未知工程调用；不把派发前PM快照误当实时状态。

### out 与缓存现场、v2 适用关系

`D/r_1/out` 11个文件均在20:50:04 +08生成，未见符号链接。daemonLaunchFingerprint明确为Mill1.1.6、Azul21.0.10；launcher/server日志记录PID1605023，与RA审查在入口执行bootstrap默认 `mill --version` 的回执吻合。这是RA探测现场；实际目标一20:44使用XiangShan版本文件选中的Mill0.12.15，在 `testcase/xiangshan/out` 编译build.mill后因major69失败。两套产物不能混同。入口out指向用户Coursier的JDK和classpath缓存；初轮target日志也使用用户 `.cache/mill` / `.cache/coursier`，r_1/.venv安装依赖而非按run隔离，故环境隔离仍有缺口。

PI未修改或删除入口out、嵌套out、.venv、build/xs、旧日志及共享缓存；没有按旧PID杀进程。核查时未见java/mill/emu/verilator/firtool进程，/proc/1605023不存在；旧锁/PID保留作证据，不代表当前持锁。后续每次开工重新核进程归属并记录。原review的F02全通过由此收窄：共同源码起点匹配，但可变产物隔离未通过，不能排名。

**三方向下一目标统一采用B1-c9a4c84b-v2**：Ubuntu JDK17.0.20+8-1-24.04-Ubuntu + Mill0.12.15 JVM / 原 `-i`；基础Python3.12.3及pip24.0、scikit-build-core1.0.3、packaging26.3、pathspec1.1.1，工具hash见baseline。v1 Java25保留失败历史，不再作为下一可比测量口径；Mill1.1.6/Azul21只作误探测来源。新组合、私有依赖安装、RTL/IR/emu/50k均**待工程验证**，不是已完成环境。

所有可变日志/build/cache/venv/tmp/Mill/Ivy/Coursier/skbuild按本方向ptmp与环境版本/candidate/run隔离；从新空输出生成，保留原现场。XiangShan硬编码generated-src等输出只能经合法入口编排重定向且生产/消费一致，不能改测试源码。公共修复仅允许入口Makefile/环境辅助目标；下一ENGINEER先实施再经Make调用，不直接source旧安装脚本或调用Python/pip/compiler。RA审查后交PI追加公共精确提交/工具锁，各方向才可采用相同核定补丁；当前无公共代码补丁已冻结，禁止自行copy/cherry-pick其他方向代码或产物。

源码起点、镜像、周期/采样/单线程/CPU/排名口径不变；任何公共起点/测量设施变化后全部受影响A/B需同口径完整重测，不能补齐者不排名。首轮仅阻塞历史，无有效成绩可迁移。RA1下一步写step_2_task并解除上述阻塞后立即回完整三目标；RA2/3首工程仍实际跑完整链到成功或最早实际阻塞。六次成功调用、逐步审查/周报和F01–F08齐备后才进入PI至多选一及PM派Agent集成流程；本次不选择、不集成。

### 本次档案仓库边界与交接状态

开工主入口 `/home/gaoruihao/wksp/wolvrix-playground`，gitdir=G，分支grh/grhsim-ir，HEAD=`12ed381becc6fbafebe4a52a71e57301ac28e090`、tree=`14f05945b19c10a6c18121b4ad1eef138c950d91`，clean。技术主检出 `/home/gaoruihao/wksp/wolvrix-playground/wolvrix`，gitdir=G/modules/wolvrix，grh/grhsim-ir、HEAD=cba9c32240f3cd06c5b675968b56046e5b76f818，clean。仅主入口三份周档案baseline/pi_plan/race显式stage并提交；本补充提交的父提交为上述12ed381，精确新提交号由PI最终回执给出。所有方向代码HEAD/分支/gitlink和技术主检出保持本表状态，r_1未跟踪out仍保留。新只读取证日志仅留ptmp、不入提交；.runner只读且连续可用，不修改、不清理、不提交、不推送或改写历史。

## RA1 步2审查交接（week-1-ra-1-review-step-2-c9a4c84b）

共同起点仍入口 `0567b6c7d0261ddd1834daffa8f15327c7f5810a`、wolvrix `cba9c32240f3cd06c5b675968b56046e5b76f818`，XiangShan `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`；RA1 仅续接本方向公共环境提交 `aaca3fafe3134f7147f1f3e866cfcb1401c5be35` → `3eea16676f73cba5f87364e8959049437de40308`，累计 patch SHA256 `955f8b192b97165e32a30e8a55a8d64cf3bdd36d62e3ebf1c7ca6a881018ffa9`。两提交仅入口 Makefile/环境辅助编排，未含宽值 emitter/runtime、GRH IR/pass、XiangShan、测试或依赖源码；**尚未由 PI 冻结**，RA2/RA3 不得自行采用。

本步独立复核：L1 首次 run 因 nested `MILL_OUTPUT_DIR=.docker-mill-out` 越界而中止；L2 修正 run 用 JDK17/Mill0.12.15 越过 major69，目标一 66.466s 内层/68.427s 外层退出2，在 XiangShan VcsVersion `git rev-list` 处 `fatal: bad object 4a6e3da8...`；目标二/三未执行。XiangShan 本身 `cat-file`、`rev-list --count`（11810）及对象遍历成功，故 bad object 更像 VcsVersion 默认 cwd 与入口 Git 上下文错配，尚无对象损坏定论。外部 `/tmp/hsperfdata_gaoruihao` 写入、`/usr/bin/verilator` 不存在、TOOL_EXTENSION 传值异常、目标 Git argv/GIT_* 未捕获，均需 PI/ENGINEER 处理。

RA1 当前 **2/6，余4**；RA2/RA3 各0/6。三方向仍独立 worktree/依赖检出，RA2/3 保持共同基点、clean、无成果。当前无完整50k、单线程、正确性、冷编译<1800s或三次交错A/B成绩；本方向无可排名候选。等待 PI 决定 Git cwd/环境注入、HotSpot perfdata 例外、工具路径/锁和依赖 alternates 的共同规范；排障后按原口径串行 `make xs_wolf_grhsim_ir` → `make xs_wolf_grhsim_ir_build_emu` → `taskset -c 2 make run_xs_wolf_grhsim_ir_emu`，前步失败不盲跑后步。所有两次 run、旧 out/.venv/Mill 输出和新证据均保留。

详细审查及两run完整绝对日志位置见 [step_2_review.md](ra_1/steps/step_2_review.md)（L1/L2以不同完整candidate SHA区分）。本次档案提交 `1127d47acc91729789a6cb32c70847301901aec7` 原样归档 step_2_result，并新增review和上述race追加；本段补记结束核查。主档案分支仍 `grh/grhsim-ir`，技术/方向代码未合入档案提交。只读证据根为 `/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1/ptmp/ra-review-step2-c9a4c84b`：roots-opening/closing.log、recursive-opening/closing.tsv记录HEAD/tree/分支/gitdir/common-dir/status/父gitlink；结束递归文件与开工逐字节一致，489仓库中仅RA1入口相对共同基点有上述两提交，486父gitlink全匹配，其他源码均clean。RA1入口仍11个旧out未跟踪文件，技术clean；忽略.venv/build/XS out与新旧run未清理，未见残留java/mill/emu/verilator/firtool。483处依赖私有gitdir通过alternates借读主检出Git对象库，三方向均有，需PI补充拓扑描述；这不授权共享可变缓存。result原hash `a42ed27962a401f5d08a5caa666b3885c7b3bbcb84f1a450fe445ee54eafaaf1` 提交后仍相同。

本次RA不冻结共同环境、不修改baseline/requirements/pi_plan/.runner，不取消已计费用量。PM应派PI评估返工与精确公共后继提交/工具锁/三方向应用关系；核定前RA2/3不复制，之后各自从原多仓库起点独立应用同一公共规范并重建，不接RA1优化或生成物。共同起点/测量口径变化时全部受影响A/B重测，无证据不可排名。RA2/3首个工程调用仍须真实尝试完整链至完成或最早阻塞；每方向用满6次成功ENGINEER、逐次RA审查及周报后才由PI选至多一个合格方向，PM再派Agent精确多仓库集成/复验，不拼接，无合格不集成，落选成果保留。
