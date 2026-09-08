# RA1 第3步任务书：v3 公共环境返工、准确 Git 诊断与完整目标续接

执行编号：`week-1-ra-1-plan-step-3-env-v3-c9a4c84b`；第1虚拟周，RA_PLAN_STEP。本文由RA独立规划、静态核对及归档；所有下列工程命令均交下一 ENGINEER 实施，本次未执行。不得另启Agent。

VRT_PRIMARY_GOAL: 优化 grhsim-ir 单线程 XiangShan CoreMark 50000 仿真周期窗口的实测性能，编译 <30min 为独立硬门槛，按 PI F01–F08 验收；RA1 原方向为通用宽值与边界缓冲 emitter/runtime，gsim约40s仅为用户参照。
VRT_SUCCESS_CRITERIA: 在一次 ENGINEER 调用中补齐 B1-c9a4c84b-v3 环境门禁，捕获 VcsVersion 失败 Git 的准确上下文并区分 H1/H2/H3；只在证据支持的范围修复，立即串行重接完整三目标至50000周期或最早实际新阻塞，提交原始退出/日志/隔离和版本证据。局部prepare/verify通过、未复现、失败定位均不得冒充全链通过或方向证伪。
VRT_TARGET_PATH: 当前目标一在 VcsVersion.scala:82 rev-list Git128 / make2，目标二/三及py_install native未到达；本blocker解除F02/F03/F05的准确Git发现、外写、工具路径/空值传递阻塞，不夹带宽值优化。
VRT_TASK_KIND: blocker
VRT_NEXT_TARGET: 诊断目标一成功立即同run执行make -j1 xs_wolf_grhsim_ir_build_emu和taskset -c 2 make -j1 run_xs_wolf_grhsim_ir_emu；有合法修复则提交后以新run从make -j1 xs_wolf_grhsim_ir重起三目标。诊断完整成功再以同候选新cold run执行同链；前步失败停止后段并归档。阻塞解除后下一技术任务回通用宽值/边界缓冲方向。

## 1. 权威输入、回执与证据关系

本文别名均可展开为绝对路径，禁止因技术cwd改变而复制项目档案：

|别名|绝对路径|
|---|---|
|A，档案主检出|`/home/gaoruihao/wksp/wolvrix-playground`|
|J，唯一正式档案根|`/home/gaoruihao/wksp/wolvrix-playground/vrt/grhsim-ir-st-opt`|
|D，三方向父目录|`/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1`|
|R，工程入口|`/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1`|
|XS，只读源码|`/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1/testcase/xiangshan`|
|Q，只读回执|`/home/gaoruihao/wksp/wolvrix-playground/vrt/grhsim-ir-st-opt/.runner/c9a4c84b9a384fd1967b6c0a21ad71aa`|
|E，PI v3证据|`/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/evidence/pi-env-v3`|
|RAE，step2独立审查证据|`/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1/ptmp/ra-review-step2-c9a4c84b`|
|P，本次规划取证|`/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1/ptmp/ra-plan-step3-c9a4c84b`|
|L1，step2首run日志|`/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1/ptmp/B1-c9a4c84b-v2/aaca3fafe3134f7147f1f3e866cfcb1401c5be35/w1-r1-s2-a-0567b6c-cba9c32-v2-01/logs`|
|L2，step2修正run日志|`/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1/ptmp/B1-c9a4c84b-v2/3eea16676f73cba5f87364e8959049437de40308/w1-r1-s2-a-0567b6c-cba9c32-v2-01/logs`|

ENGINEER必读：A/AGENTS.md、R/AGENTS.md；A/vrt/workflow/vrt-workflow.md及prompts下race_contract.md、ra_plan_step.tmpl.md、primary_goal_contract.md（旧执行器强制描述以现workflow为准）；J/requirements.md、project.json；J/week_1/baseline.md完整v1/v2及§7、pi_plan.md原方向1/F01–F08及第158行起step3交接、race.md全部历史和最新v3；J/week_1/ra_1/steps/step_1_task.md、step_1_result.md、step_1_review.md、step_2_task.md、step_2_result.md、step_2_review.md及本文。原文勘误优先级按最新PI规范，不改旧档案。

PI档案精确提交为 `a5fe01b747f6510b25c6cdb4d34bbd082b309d21`，父 `6bfd6a55f828d2636dba6c16fac0b44ee1eb16cf`；step2审查提交 `1127d47acc91729789a6cb32c70847301901aec7`，结束补记即6bfd6a55。E/commit-after.log与Q/call-0f9717167e69459c9e88ed140dcd9b0d.log相互印证；同时读取Q/call-0d7755d1f0d8436f99aea6643cee9182.log、call-39b9dd9eb26145bc8bd311aeae9ed244.log。三回执SHA256依次为 `735b62aca9c030a11317a45bb506c3b8837cf84e41bfd5d826d89b10073ad7ed`、`8910330c13f8c4fd204a98cd8b19a78858a491d38eb30406380cb0c4f5e98e92`、`024fe183ba5817b3c5ba86bb60f7b3ecf91b6fe78c10ea73e48a77e47722c895`，摘录在P/receipts-read.log。

本RA读取Q/state.json的updated_at=`2026-09-08T22:43:16.382120+08:00`，pending为本文执行编号，running仅本RA call `efc627f640f5468d8b1857f9b6ce49af`，recovery_required=false。两个ENGINEER task `week-1-ra-1-step-1-eng-c9a4c84b`、`week-1-ra-1-step-2-eng-env-and-target-c9a4c84b`均returned/exit_code=0，无未知工程调用；PI同任务3次failed/1后returned/0不扣工程配额。R=3、W=6，RA1=2/6余4，RA2/3各0/6余6。本RA不计费，不预记step3成功。下一工程开工重新读实时回执，不能照抄PM的pending=null或本文running快照。

两run必须读取的实际文件均为driver.log、commands.jsonl、xs_wolf_grhsim_ir.raw.log、**xs_wolf_grhsim_ir.processes.jsonl**、mill-probe.strace、tools.jsonl、pinned.sha256、wheels.lock、wheels.sha256.jsonl、wheel-resolve.json。commands字段为command/exit；process字段含pid/ppid/start_ticks/cwd/exe/env。不能凭裸名processes.jsonl缺失否认已有记录，也不能把mill-probe.strace当失败目标trace。P/runs-read.log记录原文件hash、命令和关键摘录。

|原始事实|独立证据及限制|
|---|---|
|L1 prepare/verify=0；目标一make2/nested130|prepare7.472s、verify2.034s；目标内75.588s/外77.264s；classes实际写XS/.docker-mill-out，二/三未跑。raw SHA256 `628661cec123c3a254d6dde7dfb4029edf8421d160df79bee5a0cc1b95812038`。|
|L2 prepare/verify=0；目标一make2/Mill1/Git128|prepare10.460s、verify1.971s，不能移用L1时间；目标内66.466s/外68.427s。越过major69并进入749任务图，VcsVersion.scala:82 bad object；二/三、native未跑。这些失败时间不是F06。raw SHA256 `f4abb02ffad234b3ddf3dced213256506bc2c70a9b63d434c25a6d23c9af62bd`，commands `d022163eadc01aefee958878bd1f2c169039b379c11907eecc26ebcc6a01e3c5`。|
|H1有机制证据，尚未抓准失败exec|RAE/VcsVersion.bytecode.log：rev-parse/exact describe显式vcsBasePath，fallback describe/rev-list/diff用默认cwd。RAE/observed-git.tsv仅抓入口status；不能替换失败rev-list。E/git-context-current.log与RAE/git-context.log：XS count11810/exit0，入口及mill-target查相同XS hash exit128；XS可达遍历118746项、无missing，仅证明已查历史可读。|
|实际环境缺口|RAE/outside-run-writes.log、L2 probe trace及目标maps有/tmp/hsperfdata写入；L2 trace SHA256 `68d037fd4e59109fd330eba300f818a0ab44079b57bca13945450dcd5534f275`。helper指定不存在的/usr/bin/verilator；Makefile按双引号cut导致空TOOL_EXTENSION被解析成export整行；tracked检查错误地总在R执行。|

还须读E的repos/links/alternates-opening.tsv和closing.tsv、git-context-current.log、run-evidence.log、tools-read.log，以及RAE的roots/recursive-opening/closing、gaps.log、tools-check.log、hashes-preservation.log。两run all.sha256仅L2的48份当时日志快照，不是完整工具/run封存。P/pi-review-evidence-read.log保存关键原始摘录。本次不重跑对象遍历或目标验证。

## 2. 现场续接及允许改动

本RA于22:44:59 +08起只读复核489仓库，P/audit.sh、audit-opening.log和roots/repos/links/alternates-opening记录实际path/gitdir/common-dir/branch/HEAD/tree/status、忽略输出及父gitlink。486个已检出父gitlink匹配；489行links另含3个未检出openc910排除项。以下为现场，不是要求新建分支：

|仓库|HEAD / tree|分支、Git关系与状态|
|---|---|---|
|A|a5fe01b747f6510b25c6cdb4d34bbd082b309d21 / d7db031b22afb2245b7adfe4385d6913bd8b42e8|grh/grhsim-ir；gitdir/common=A/.git；开工clean，仅供本任务书档案提交。|
|R|3eea16676f73cba5f87364e8959049437de40308 / 7606970036deb01130b50e92d24b858454615598|vrt/grhsim-ir-st-opt/c9a4c84b/week_1/r_1；gitdir=A/.git/worktrees/r_1，common=A/.git；仅旧out11文件未跟踪。|
|R/wolvrix|cba9c32240f3cd06c5b675968b56046e5b76f818 / 6bcc50560c2fb21f5e000cc521bec5a5e58d8483|同R分支，gitdir=A/.git/modules/wolvrix/worktrees/wolvrix，common=A/.git/modules/wolvrix；clean。A/wolvrix同SHA/tree，grh/grhsim-ir、clean。|
|XS|4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6 / bb4b5dc0ed12891829b69028b09e6352993c6d4d|私有.git/common，自身detached、源码clean；旧out/.docker-mill-out/build保留。|
|XS/ready-to-run|912f92121570bd28cabbefa7fa56d25b9784c304 / f922f0f8e37aef82e65248349daf2a59f35aa54c|私有detached/clean，父gitlink匹配。|
|D/r_2、D/r_3|各0567b6c7d0261ddd1834daffa8f15327c7f5810a / 8544a4528fac5f15fb59d57e6ef5622eccea2e99|分别完整分支vrt/grhsim-ir-st-opt/c9a4c84b/week_1/r_2、r_3；入口及技术clean；wolvrix各cba9c322、XS各4a6e3da8。仅核身份，不取实现/生成物。|

共同源码起点A0=`0567b6c7d0261ddd1834daffa8f15327c7f5810a`，方向链A0 → `aaca3fafe3134f7147f1f3e866cfcb1401c5be35` → `3eea16676f73cba5f87364e8959049437de40308`。首patch SHA256 `3460712b4b4d8efd80a47ed34318670e1c8660767d3bb238fb316fe34a5d20e6`，累计 `955f8b192b97165e32a30e8a55a8d64cf3bdd36d62e3ebf1c7ca6a881018ffa9`。两份仍是草案，不冻结、不退回A0、不从主档案HEAD开工程。保留原out、.venv、XS/out/.docker-mill-out/build、全部旧run及链接；不清理、加ignore或重建隔离制造clean。

递归依赖身份以baseline §5和§7.2为准，D/evidence/isolation-verified.tsv SHA256=`6149d82c9e892b1fe92ce0682b5f37cabf5500c51fcbd4f35037d90044a343db`。161×3=483个依赖的私有gitdir通过alternates借读对应主对象源；按仓库父边界递归解析modules，不能按任意目录层级拼接。E/alternates-opening.tsv SHA256=`5dc8f7c0cfdbbaf0163f75870b7fc07bd598f3ec0298945caaf969e71812f5ec`，repos=`fb39b7d1edf5e9f363447d3328e9cd49b6471ab7a05423123bb9582175822c5f`，links=`adee6234e83236bc1501898cf13b89f56d344cb7d4dedad085071e78bc5fff40`。对象借读不授权共享可变cache或改Git数据库；禁止fetch/gc/prune/repack、补对象、修改alternates/config、依赖切换或父gitlink修改。

**工程可改且可提交的范围仅R/Makefile、R/scripts/vrt_common_env.mk、R/scripts/vrt_common_env.py及必要入口环境/Git作用域辅助脚本和工具/依赖锁。** 禁止改主技术/入口代码、RA2/3、XS/build.mill/插件jar/依赖/difftest/测试源码、输入、冻结GRH IR/pass、本次已核定race/requirements/baseline/pi_plan/.runner；不实施任何优化、多线程仿真或模块名匹配。发现遗漏库、污染、规范不能落实或目标漂移，留准确证据交PM/PI，不扩大许可。

## 3. 可区分假设、准确捕获与条件修复

H1优先：外置Mill sandbox默认cwd发现R，version hash却取自XS，造成跨库rev-list。H2待排除：继承GIT_*或config改变库发现。H3仅在正确库仍失败时考虑：对象/parent/tag/alternates历史缺口。前两步narrowed，不是连续无推进；此次不重复泛化工具盘点。

先只补观测和已证实的v3安全缺口，首diagnostic run使用`VRT_GIT_SCOPE=observe`，不改变Git查询。Git记录wrapper以固定真实`/usr/bin/git`避免递归，在exec前记录原始参数数组、物理cwd、真实exe及hash、pid/ppid/starttime、run与Mill祖先链；捕获真实Git子进程身份和退出，stdout/stderr原字节各存独立文件，并原样返回给调用者。不能只记录wrapper自身而漏真实exec；必须配合完整后代系统调用trace。跟踪fork/clone/vfork/execve/execveat、chdir/fchdir、open/openat/openat2/create/rename/unlink、write/pwrite/writev、dup/close及共享可写mmap/msync等，重建cwd/dirfd/FD继承/symlink最终路径，保留删除的短命文件记录。系统调用内容不得全量导出环境、HTTP凭证或配置秘密；只白名单Git环境及与库发现相关的安全config字段，记录来源文件/作用域。/proc仅补证，50ms轮询不能替代exec覆盖；不能用probe trace或前后hash宣称没有创建后删除。

环境白名单至少涵盖GIT_DIR、GIT_WORK_TREE、GIT_COMMON_DIR、GIT_OBJECT_DIRECTORY、GIT_ALTERNATE_OBJECT_DIRECTORIES、GIT_CEILING_DIRECTORIES、GIT_DISCOVERY_ACROSS_FILESYSTEM、GIT_CONFIG及SYSTEM/GLOBAL/NOSYSTEM、GIT_CONFIG_COUNT/KEY和值中影响库发现的安全项；敏感值标存在并脱敏，未采集不能记unset。配置查询使用真实Git只读`config --show-origin --show-scope`按安全键过滤，不能改全局/库配置；必要日志子查询须标diagnostic，不能与插件实际查询混同。

必须覆盖取得hash的rev-parse、exact describe、fallback describe、rev-list的**实际完整argv（含是否--not和原tag）**、diff/status。Make诊断入口在失败sandbox仍存在时做同argv对照，或由wrapper在真实Git退出后、返回Mill前完成对照并独立留证，防止sandbox销毁导致不能重放；重放不能改原返回码/输出。禁止重建消失sandbox冒充原现场。对照在捕获cwd及XS分别保持捕获环境运行真实Git，另记top/gitdir/common-dir/HEAD、cat-file -t/-p和必要历史；Git失败128是对照数据，不是诊断入口自动吞成成功。对照工具的退出0只表示完整采集/比对完成。

|观察结果|工程决定及验收|
|---|---|
|同argv在捕获cwd失败、XS成功，发现库不同；H2未改变这一关系|支持H1。先查固定Mill已支持的cwd安排（只读核其接口后由Make验证，本文不假定存在某选项）。若无支持，才实现baseline §7.3受限默认查询适配。|
|捕获环境覆盖正确库，精确局部清理后同argv恢复|支持H2。仅在该run已识别工具进程范围清理已证实影响发现的注入，保留合法嵌套库行为；全链禁止全局export GIT_DIR/GIT_WORK_TREE。|
|正确XS及捕获环境下仍失败|按实际hash/tag/parent/tree与alternates来源给H3最小证据；停止该链交PI。不fetch、修库、换版本、借其他方向对象。|
|首诊断未经Git修复即目标一成功|记“未复现”、实际查询和证据覆盖，不装无依据重定向；立即继续目标二/三。缺准确证据不等于H1已消除。|
|无法可靠识别作用域，或需改XS/build.mill/插件/依赖/Git数据库|停止该链，报告准确命令/退出码/源码依据及待PI决定项，不扩大wrapper。|
|转为下载/Scala/firtool/Python/native/运行错误|报告最早新阻塞与未到阶段；允许范围内修补则提交、新run重起，否则交RA/PI；不换JDK/Mill/Scala、减周期或绕过正确性。|

受限适配谓词须同时满足：本run启动标识匹配；实时Mill祖先pid/starttime/exe与固定0.12.15对应；真实sandbox或经exec证明由其派生而落到R的默认cwd；已捕获的version查询类别；XS路径/HEAD/gitdir固定且可读。**R路径本身或某hash绝非充分条件。** 无显式库选项且在合法子库执行的查询原样透传；所有`-C`（含组合/重复形式）、`--git-dir`、`--work-tree`及无法完整解释的选项保守透传，不能误吞`-c`等配置参数。非Mill进程、越界sandbox、旧run/PID复用、未命中类别均不重定向；发现缺证时拒绝启用适配，而非推广到全部Git。

hash/tag/count/dirty必须作为同次version计算来自同一个真实库，不可只修rev-list而留下错误tag/dirty；结果与正确XS直接执行同argv的stdout/stderr/exit逐字节一致。禁止硬编码版本/hash/tag/count/dirty、伪造成功和按模块名匹配。wrapper只随已识别Mill启动域注入，退出该域即撤销，普通py_install及别的工具不得继承有效重定向。

Make作用域验证需提供正反用例的原始命令/输出/退出、命中理由及未命中理由：真实捕获类别；显式-C/--git-dir/--work-tree；真实合法XS子库；普通R Git；非Mill父进程；旧run或不匹配starttime；未知参数/类别。均只读既有库，不创建测试Git数据库。对预期非零返回单独比较，不用“所有Git退出0”作验收。若本次没有启用适配，验证observe模式恒等透传并明确无修复结论。

## 4. v3环境门禁与路径所有权

静态核对R/Makefile:3,34–47,393,687,725,1169及scripts/vrt_common_env.mk、py：prepare/verify、三目标及内部observe/check已存在，**仍是v2草案且必须返工**。root_path只接受v2；configuration写/usr/bin/verilator且无PerfDisableSharedMem；Makefile空值解析有错；git helper固定cwd=R；observe(trace=False)无目标精确exec。以下新增接口均是本任务选择的待实现合同，ENGINEER先实现再调用，不把名称当作既有能力：

|接口/变量|实现责任与输出|
|---|---|
|既有vrt_common_env_prepare / verify /内部check / observe|更新v3根、候选和锁校验，保留空值、真实owner保护、工具闭包、JVM隔离和观测方式；拒绝坏路径/hash/空值。prepare不编译目标；verify成功才发布纯env。|
|新增vrt_common_env_git_diagnose|校验新env后包住原`xs_wolf_grhsim_ir`，传播完整VRT_ARGS，启用诊断trace和Git记录，输出logs/git-events.jsonl、每exec原始stdout/stderr、同argv对照及目标原始日志；返回真实目标退出码，采集失败另列并非零。|
|新增vrt_common_env_git_compare|读取本run捕获记录做/校验上述对照，不凭空补argv；没有失败exec则明确not-reproduced/missing，不伪造。短命cwd的及时对照由诊断入口完成，此目标汇总或复核其原始记录。|
|新增vrt_common_env_git_scope_verify|按§3正反用例证明恒等透传/限定适配；日志落run，不能绕过env校验或修改Git库。|
|新增vrt_common_env_evidence|在成功、失败或verify失败后均能经Make做只读收尾，归档本run已完成阶段、版本/产物hash、前后递归与进程状态；不运行未到目标，不重装，不掩盖原退出。这个单独证据目标可读取未verified根，但不能借此放行构建。|
|新增VRT_OBSERVE_MODE=diagnostic/formal、VRT_OBSERVER_CPU=0、VRT_OBSERVER_INTERVAL=1|各层Make及helper明确传播；formal禁详细trace/高频全proc，只1s本次后代/线程观测；observer自身CPU0，目标不得继承CPU0。|
|新增VRT_GIT_SCOPE=observe/scoped、VRT_GIT_EVIDENCE_ROOT|observe默认只记录；scoped仅有本方向准确证据和已提交实现后启用。证据根只读引用本方向此前诊断run，保存证据hash/源候选关系，不复用其产物或可变cache。|

环境prepare仅接受原子新建、最初只有logs的run；拒绝已存在venv/tools/build等或路径symlink越界。候选SHA完整40位、等于实际已提交入口HEAD，且技术和全部父gitlink锁匹配。所有命令的解释器、日志和临时路径均在Make编排中落实，禁止直接Python/pip/cmake/ctest/compiler/Java/Mill代跑或source旧安装env.sh；无入口先加入口。SKIP_WOLF_ENV_CHECK只限prepare/verify的单目标引导，不能混合目标、伪置WOLF_ENV_SOURCED或省略依赖验证。新env只允许核定export/unset及字面值，无eval、安装、命令替换；verify核验后发布，随后才source。

|用途|相对VRT_RUN_ROOT路径/固定要求|
|---|---|
|工具/Python|tools/bin/mill、tools/mill/download/0.12.15；venv、wheels、logs/wheels.lock。Mill种子仅允许核定distribution单文件只读取种，不复制用户cache。|
|PATH|JDK17/bin、run/tools/bin、run/venv/bin、LLVM22.1.2/bin、/usr/local/bin和必要系统路径；Git记录入口仅在受限工具域。|
|Mill|MILL_VERSION=0.12.15；MILL_FINAL_DOWNLOAD_FOLDER=tools/mill/download；probe=mill-probe、实际目标=mill-target，禁止classes/cache复用；MILL_OUTPUT_DIR命令行穿透nested make。|
|XDG/cache|cache/xdg、config/xdg、data/xdg；cache/coursier、cache/ivy、cache/pip、cache/ccache且CCACHE_DISABLE=1；拒绝用户共享可变cache。|
|tmp/JVM|TMPDIR/TMP/TEMP=tmp，java-home、tmp/java、logs；不改HOME。全部实际JVM固定`-XX:+PerfDisableSharedMem -Duser.home=<run>/java-home -Djava.io.tmpdir=<run>/tmp/java -Divy.home=<run>/cache/ivy -XX:ErrorFile=<run>/logs/hs_err_pid%p.log -XX:HeapDumpPath=<run>/tmp/java`。|
|源码编译|skbuild、build、wolvrix-build及实际CMake/FetchContent/native临时输出；不能回落wolvrix/build/skbuild。|
|目标|xs/rtl（实际RTL在xs/rtl/rtl）、xs/filelist/xs_wolf.f、xs/generated-src、grhsim-ir/model、grhsim-ir/emu、logs。|

JAVA_OPTS/JAVA_TOOL_OPTIONS明确传播上述固定项，核所有launcher/fork JVM实际argv、允许环境、maps和trace；JDK_JAVA_OPTIONS/_JAVA_OPTIONS/CLASSPATH/PYTHONPATH/PIP配置等未核定注入须留安全证据并按工具范围处理，PIP_CONFIG_FILE禁用户配置。TMPDIR不控制HotSpot perfdata，**不批准/tmp例外**；外部任务写入即隔离失败，停止相关链。工具专用tmp/error/dump/jline/JNA/解析器路径均须实测，不能仅以环境变量存在作通过。

Verilator固定`/usr/local/bin/verilator`（5.051 devel v5.050-126-gdaf582661），核symlink/launcher真实后端verilator_bin、资源和运行库，以及子make实际解析；禁止系统伪链接或升级。TOOL_EXTENSION按“已设置但空”保持精确空字节，不能or回落或按引号cut；纯env、顶层Make、observer、nested Make、JVM逐层记录origin、length=0和安全转义表示。

路径映射前用真正owner的`git ls-files -- <repo-relative-path>`检查tracked及嵌套gitlink，核链接目标owner，不能只在R查XS。记录原lstat/realpath/内容hash/占用、生产者和消费者解析。XS/build/generated-src与XS_DIFFTEST_GEN_DIR/XS_DIFFTEST_MACROS必须指向同run；只能对既有忽略输出入口用合法链接编排，原目录/链接完整保留原位或新run/preserved，不能覆盖删除。XS/build、.docker-mill-out及动态发现路径均纳入；遇tracked源或跨方向指向停止。新普通文件内容必须落run。切换映射前核本次后代+exe+启动时间+真实占用；不能按旧PID、仅XS cwd或批量进程名kill。

工具身份固定JDK17.0.20+8-1-24.04-Ubuntu、Mill0.12.15 JVM/原-i、Python3.12.3、LLVM22.1.2、Make4.3/CMake3.28.3；Scala2.13.17/Chisel7.3.0/firtool-resolver2.0.1沿源码，不自选升级。JDK release/java/modules的hash依次为 `b8d3277e4f728d8ed638fc8eae2b66c7d10d7b8424985dfb4e5feb688aea66d2`、`4976918b29ece3fe634bdbcf1377676e42af429b5311ba234f6f95039117d4d4`、`499337b57cd61a672db7e1b35a3946bfb99508187367dc886c2bcbf28c65bf3a`；libjvm=`35f86cffa7a4edf211cb342c55427e1a3d7ac5ee28aa0d239d8ad8b0b7de743f`。Mill bootstrap /home/gaoruihao/wksp/mill=`af73fadc1fa005e43962bcd529690f448592f4e0786a90b712ac6509378a9eb2`；distribution /home/gaoruihao/.cache/mill/download/0.12.15，76195001 bytes=`ea1bba01e220f4ce20bb333247d254a2bf9b86554c10c3d7d7e16641ec0a76d8`。Python /usr/bin/python3.12=`1643dacd9feaedc58f3cc581e4d22577dfe25c09b10282936186ccf0f2e61118`；clang/clang++最终clang-22=`ff1c4a7557acb600225d4bb93e53b8ec4d29ce4cd625a92cf904a11676568487`；Verilator launcher=`fb2cc573b1055cf096c90e1efc9966fe56bdb4b265c83590cf2a49f7a0defcdf`。Git/Make/CMake及更多已核字节按baseline §7.4、E/tools-read.log。

四wheel锁文件必须保存L1/L2的相同字节，SHA256=`cb980c72f1673db6e70639fc5f3dc05060e55af5ab7df023d571d98b5a4419b7`，以下内容（末尾换行）固定；URL逐一取baseline §7末尾已冻结files.pythonhosted.org URL及L2/wheel-resolve.json，不重新自由解析，Make下载同字节后no-index/require-hashes安装：

```text
pip==24.0 --hash=sha256:ba0d021a166865d2265246961bec0152ff124de910c5cc39f1156ce3fa7c69dc
scikit_build_core==1.0.3 --hash=sha256:ae95427b7d3c14a6cf8bbfd4d901f6138ab64c99e20cbe8ea7d75cd26093f085
packaging==26.3 --hash=sha256:d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c
pathspec==1.1.1 --hash=sha256:a00ce642f577bf7f473932318056212bc4f8bfdf53128c78bbd5af0b9b20b189
```

补闭包：工具realpath最终字节/symlink链、Git/helper、LLVM运行库、Python/venv/wolvrix扩展、JDK外链配置/modules/libjvm、Verilator backend、firtool、Mill/Scala编译插件/传递jar/pom/解析元数据，以实际exec/classpath/maps和下载URL/坐标/版本/hash交叉核对。VcsVersion 0.4.0 mill0.11_2.13构件hash=`a8e0cc9ef56e1473518df6590c205143ab21c0bc714ac2ce1d69316d293cd0d1`；不能因构件名含mill0.11换jar。区分已知身份、已到阶段兼容、尚未到阶段；新字节/依赖变化交PI，不宣称完整锁已冻结。

## 5. ENGINEER命令合同与日志退出捕获

先按§2在R现有分支实现§4接口并提交公共环境代码，显式stage实际许可文件，提交信息以`vrt(grhsim-ir-st-opt): week 1`开头；禁止git add .、技术/gitlink/旧输出混入。下面是**工程实施后才可运行**的Bash步骤；不是本RA已执行实验。每次新run用未加载旧env的干净shell开始，不source旧安装文件；shell代码仅编排Make和只读Git，不直接运行工程脚本。可将驱动内容保存run/logs供复核；若作为脚本调用也须提供Make入口，不能绕开Make执行工程脚本。

```bash
cd /home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1
set -u -o pipefail
set +e
export GIT_OPTIONAL_LOCKS=0
VRT_CANDIDATE=$(git rev-parse HEAD) || exit $?
git merge-base --is-ancestor 3eea16676f73cba5f87364e8959049437de40308 "$VRT_CANDIDATE" || exit $?
test "$VRT_CANDIDATE" != 3eea16676f73cba5f87364e8959049437de40308 || exit 2
test -z "$(git diff HEAD --name-only)" || exit 2
test "$(git -C wolvrix rev-parse HEAD)" = cba9c32240f3cd06c5b675968b56046e5b76f818 || exit 2
VRT_MODE=diagnostic
VRT_SCOPE=observe
VRT_SCOPE_EVIDENCE=
VRT_RUN_BASE=w1-r1-s3-a-0567b6c-cba9c32-v3-diag-01
VRT_RUN=$VRT_RUN_BASE
VRT_PARENT="$PWD/ptmp/B1-c9a4c84b-v3/$VRT_CANDIDATE"
mkdir -p "$VRT_PARENT" || exit $?
VRT_RUN_ROOT="$VRT_PARENT/$VRT_RUN"
VRT_TRY=1
while ! mkdir "$VRT_RUN_ROOT"; do
  test -e "$VRT_RUN_ROOT" || test -L "$VRT_RUN_ROOT" || exit 2
  VRT_TRY=$((VRT_TRY+1))
  VRT_RUN="$VRT_RUN_BASE-retry-$VRT_TRY"
  VRT_RUN_ROOT="$VRT_PARENT/$VRT_RUN"
done
mkdir "$VRT_RUN_ROOT/logs" || exit $?
git log --format='%H %P %T %s' 0567b6c7d0261ddd1834daffa8f15327c7f5810a..HEAD > "$VRT_RUN_ROOT/logs/candidate-chain.log"
git diff --binary 0567b6c7d0261ddd1834daffa8f15327c7f5810a "$VRT_CANDIDATE" > "$VRT_RUN_ROOT/logs/common-env.patch"
sha256sum "$VRT_RUN_ROOT/logs/common-env.patch" > "$VRT_RUN_ROOT/logs/common-env.patch.sha256"
vrt_stage() {
  local stage="$1"; shift
  local start end
  local -a rc
  test ! -e "$VRT_RUN_ROOT/logs/$stage.stdout.log" || return 4
  start=$(date +%s.%N)
  { date -Ins; printf 'cwd=%s\n' "$PWD"; printf '[CMD] '; printf '%q ' "$@"; printf '\nstart=%s\n' "$start"; } >> "$VRT_RUN_ROOT/logs/driver.log"
  "$@" 2>&1 | tee "$VRT_RUN_ROOT/logs/$stage.stdout.log"
  rc=("${PIPESTATUS[@]}")
  end=$(date +%s.%N)
  { date -Ins; printf 'stage=%s start=%s end=%s command_exit=%s tee_exit=%s\n' "$stage" "$start" "$end" "${rc[0]}" "${rc[1]}"; } >> "$VRT_RUN_ROOT/logs/driver.log"
  sha256sum "$VRT_RUN_ROOT/logs/$stage.stdout.log" >> "$VRT_RUN_ROOT/logs/raw.sha256"
  test "${rc[0]}" -eq 0 || return "${rc[0]}"
  test "${rc[1]}" -eq 0 || return "${rc[1]}"
  test -s "$VRT_RUN_ROOT/logs/$stage.stdout.log" || return 3
}
vrt_finish() {
  local saved="$?" evidence_rc
  trap - EXIT
  printf 'driver_exit=%s\n' "$saved" >> "$VRT_RUN_ROOT/logs/driver.log"
  vrt_stage evidence-final make -j1 vrt_common_env_evidence "VRT_ENV_ROOT=$VRT_RUN_ROOT"
  evidence_rc=$?
  printf 'evidence_exit=%s\n' "$evidence_rc" >> "$VRT_RUN_ROOT/logs/driver.log"
  if test "$saved" -eq 0 && test "$evidence_rc" -ne 0; then saved=$evidence_rc; fi
  exit "$saved"
}
trap vrt_finish EXIT
vrt_stage env-prepare make -j1 vrt_common_env_prepare SKIP_WOLF_ENV_CHECK=1 "VRT_ENV_ROOT=$VRT_RUN_ROOT" || exit $?
vrt_stage env-verify make -j1 vrt_common_env_verify SKIP_WOLF_ENV_CHECK=1 "VRT_ENV_ROOT=$VRT_RUN_ROOT" || exit $?
test -s "$VRT_RUN_ROOT/env.sh" || exit 2
cat "$VRT_RUN_ROOT/env.sh" >> "$VRT_RUN_ROOT/logs/env-reviewed.log"
# verify已验证文件仅核定export/unset字面值，无命令替换/安装；人工核对相同hash后才加载。
source "$VRT_RUN_ROOT/env.sh" || exit $?
unset SKIP_WOLF_ENV_CHECK
```

上面候选门禁不能替代开工对未跟踪文件/递归依赖的核查；只允许已记录的旧out。环境源码若有修补，必须新提交、新SHA目录、新run，从prepare重新开始，不能把旧日志迁移到新SHA伪装被测版本。作用域修复后的诊断run将VRT_SCOPE设scoped，VRT_SCOPE_EVIDENCE设为实际先前诊断根的绝对路径并核hash；未获证据支持始终observe。变量由driver显式传Make，env.sh不得覆盖这些driver变量。

紧接使用全部固定参数，不能只写“沿用上次”：

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
  "VERILATOR=/usr/local/bin/verilator" "TOOL_EXTENSION="
  "VRT_OBSERVE_MODE=$VRT_MODE" VRT_OBSERVER_CPU=0 VRT_OBSERVER_INTERVAL=1
  "VRT_GIT_SCOPE=$VRT_SCOPE" "VRT_GIT_EVIDENCE_ROOT=$VRT_SCOPE_EVIDENCE")
```

首诊断用下段，诊断入口内部仍执行原`make -j1 xs_wolf_grhsim_ir`及完整数组。成功不等对照报告完工才继续目标二/三；失败则停止后段、保留及时Git对照，通过单独Make compare汇总后退出driver：

```bash
printf 'measurement_mode=diagnostic\n' >> "$VRT_RUN_ROOT/logs/driver.log"
vrt_stage target1-diag make -j1 vrt_common_env_git_diagnose "${VRT_ARGS[@]}"
VRT_TARGET1_RC=$?
if test "$VRT_TARGET1_RC" -ne 0; then
  vrt_stage git-compare make -j1 vrt_common_env_git_compare "${VRT_ARGS[@]}"
  printf 'git_compare_exit=%s target1_exit=%s\n' "$?" "$VRT_TARGET1_RC" >> "$VRT_RUN_ROOT/logs/driver.log"
  exit "$VRT_TARGET1_RC"
fi
vrt_stage target2 make -j1 xs_wolf_grhsim_ir_build_emu "${VRT_ARGS[@]}" || exit $?
vrt_stage target3 taskset -c 2 make -j1 run_xs_wolf_grhsim_ir_emu "${VRT_ARGS[@]}"
VRT_FINAL_RC=$?
printf 'target_chain_exit=%s\n' "$VRT_FINAL_RC" >> "$VRT_RUN_ROOT/logs/driver.log"
test "$VRT_FINAL_RC" -eq 0 || exit "$VRT_FINAL_RC"
vrt_stage git-compare make -j1 vrt_common_env_git_compare "${VRT_ARGS[@]}" || exit $?
vrt_stage git-scope make -j1 vrt_common_env_git_scope_verify "${VRT_ARGS[@]}" || exit $?
exit 0
```

若根据失败证据实施受限修复，先新提交并新diag run，经Make作用域核验后，**同工程调用立即从原目标一重起**（下段三目标，VRT_MODE=diagnostic；时间只标diagnostic）。该run校验时VRT_GIT_EVIDENCE_ROOT指向保留的准确失败证据，验证helper支持这一只读来源且不复用生成物。若诊断已经无修复跑通，不装适配。

修复run在新prepare/verify及数组定义后、目标一之前执行以下门禁；此处scope验证从VRT_GIT_EVIDENCE_ROOT读取已捕获查询，用新候选适配代码作正反对照，不冒充新目标已经执行。三目标成功后再经同一Make compare入口核对新run的实际查询和输出；formal run不重复高频诊断。

```bash
vrt_stage git-scope-pre make -j1 vrt_common_env_git_scope_verify "${VRT_ARGS[@]}" || exit $?
```

诊断全链和作用域/写入验证通过后，同候选另新空正式run：在第一代码块中用`VRT_MODE=formal`、`VRT_RUN_BASE=w1-r1-s3-a-0567b6c-cba9c32-v3-cold-01`，保持实证决定的VRT_SCOPE及原诊断证据根；重新prepare/verify、完整VRT_ARGS，防覆盖规则相同。不要沿用刚source的旧run环境；工具配置只按新根重新生成。下面既用于修复后的诊断重起，也用于正式冷编译；由measurement_mode区分，不能把诊断时间叫cold成绩：

```bash
printf 'measurement_mode=%s\n' "$VRT_MODE" >> "$VRT_RUN_ROOT/logs/driver.log"
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

driver退出只停止命令链。ENGINEER即使外部中断/kill导致EXIT trap未执行，也须通过新增Make evidence入口补收尾并写step_3_result；记录interrupted和已知真实码，不能猜成功。日志写入失败、tee非零或观测缺失单独列，不吞目标错误、不执行失败链后段。阶段原stdout/stderr允许某流为空，但合并原始目标日志必须存在非空；不能填造输出。所有Make内部命令保存command数组/cwd/ISO与epoch起止/整数exit到commands.jsonl，外层vrt_stage保留make及tee两码。

对修复后的diagnostic三目标链，evidence收尾须经Make编排调用Git compare，保存新查询一致性和完整写入审计的独立整数退出码；其失败使driver验收非零，不能仅靠预检宣布作用域或隔离通过。formal evidence仅校验关联的同候选诊断证据及当前轻量记录，避免把详细trace带入正式计时。

固定内层调用只由原Make执行：`mill -i -Djvm-xmx=40G -Djvm-xss=256m xiangshan.test.runMain top.XiangShanSim --target-dir <run>/xs/rtl/rtl --config TLConfig --issue E.b --num-cores 1 --target systemverilog --firtool-opt "-O=release --disable-annotation-unknown --lowering-options=explicitBitcast,disallowLocalVariables,disallowPortDeclSharing,locationInfoStyle=none" --split-verilog --dump-fir --firtool-opt "--default-layer-specialization=enable" --enable-difftest --full-stacktrace`。禁止直接执行该内层命令。冻结GRH pipeline及defines/read_args不变；two-state、seed0/reset50、Release/模型与emu -O3、无PGO/LTO、phase timing关闭。没有资源时等恢复，不因一次调用预计耗时而跳过目标，不设“一工时=一小时”超时。

## 6. F01–F08、计时与证据验收

开工、每次映射变更、目标启动/结束均记录CPU2 governor=powersave、sibling=18、负载/频率/内存和所属进程；不得改governor或换CPU挑成绩，sibling18无研究负载，编译和仿真串行。正式observer仅自身CPU0/1s，不能使目标继承CPU0；实际emu和模型线程Cpus_allowed_list=2，EMU_THREADS=0及flags/运行线程共同证明单线程。诊断全后代trace提供短命线程/写入覆盖；正式同候选/环境轻量观察与其hash关联，代码/环境变化重做诊断。observer不是模型线程，不能借观察器豁免多线程仿真。

prepare的锁定外部工具/四wheel获取与安装时间单列；不得预编译Scala或先make py_install。正式F06从目标一到目标二成功的连续wall-clock，计入目标期间下载、Scala首次生成/编译、py_install native、emit/model/emu及其中检查开销，不事后扣native，不复用诊断classes/cache/venv/native/model/emu。包import如需检查先补合法Make入口，放安装之后并计时。cold指协议规定全新产物/无编译cache，不清OS page cache、不声称硬件冷缓存。详细诊断trace时间单列，不能估算扣除后报正式成绩。

|项|当前状态及本step3必须交付|最终不可缩减要求|
|---|---|---|
|F01|仅环境草案，无方向优化；新diff必须完全在许可入口范围|禁止冻结GRH/pass、XS/测试、模块名匹配、多线程；后续宽值helper沿legacy指针/调用方输出缓冲及local frame/boundary，不用大std::array返回/热路径大复制。|
|F02|源码独立性匹配，环境隔离失败/缺证；补真实owner、零外部任务写入、准确exec及前后多库状态|共同基点/所有父gitlink/输入匹配，无跨方向实现或产物，工具/输出来源完整。|
|F03|目标一阻塞，无RTL/filelist/IR/model/emu|CoreMark SHA256 `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`，NEMU `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`；完整源码/工具/命令与RTL每文件、filelist原顺序及路径归一化、defines/read_args、flat GRH/GrhSIM IR/roundtrip/model/emu hash。未生成明确列未到达。|
|F04|未测；到达50k则保留全部有序采样/NEMU和终态|每1000周期采样、PC/trap/instruction/state、host/model50000与cycle limit、退出状态和无mismatch/ABORT/BAD TRAP；与A完整对拍。现有CPU mapping/schedule/emit、GrhSIM IR及必要HDLBits回归经Make通过仍是最终硬门槛，本step3不修改测试，也不能以局部回归替代目标。|
|F05|一失败，二/三未到；本次修复后立即完整链|单核且单线程，50000/1000、波形关闭；真实目标日志、emu启动退出墙钟、实际线程/affinity，不以taskset参数代替证据。|
|F06|未测；另空formal run记录连续编译起止及native分段|每候选至少一次冷编译严格<1800s，8编译jobs；不能用快仿真抵销，也不以L2的68s失败冒充成绩。|
|F07|无A/B、不可排名；本次无优化候选|最终A/B各至少3次交错完整50k，例如A1/B1/A2/B2/A3/B3，各新RUN_ID/日志；同输入CPU/flags/工具，Host time spent每次原值和中位数，median(candidate)<median(A)×0.99，A/B各组max/min≤1.05；超噪声或缺样本不可排名。运行时只取emu启动至退出，排除构建/准备/gsim。|
|F08|本任务书不消费配额；新结果交RA独立审查再交PI|每RA用满6次成功ENGINEER、逐步审查、周报及可复现精确候选闭包；现在RA1=2/6、RA2/3=0/6。|

step3即使跑通也仅“待核定目标证据”，后继公共精确代码/总锁仍未由PI冻结。不可要求本次拿环境A与无优化的同代码伪装B去满足F07；最终原方向优化A/B任务仍需完成。不能把“未测”写为证伪，不能把prepare/verify成功写为全链兼容通过。

## 7. 工程交付、失败重接与后续赛马

唯一工程结果为 `/home/gaoruihao/wksp/wolvrix-playground/vrt/grhsim-ir-st-opt/week_1/ra_1/steps/step_3_result.md`。不得在R另建vrt/grhsim-ir-st-opt，不在本RA调用提前写result。ENGINEER在R提交许可公共环境代码；结果在A现有grh/grhsim-ir单独显式stage归档，先核A实时HEAD/状态，不能切主分支或把档案提交合入方向代码。各提交前后记录完整SHA/父/tree/status，提交信息以`vrt(grhsim-ir-st-opt): week 1`开头；不推送、不改写历史、不提交.runner/ptmp/生成物/父gitlink。实际PM派发若另定结果归档责任则如实交接，不覆盖正在使用档案。

结果必须逐项提供：

1. 共同起点→aaca3fa→3eea166→本次每个完整环境SHA/父/tree；累计binary patch SHA256、分步patch、实际许可文件、技术仍cba9c322、锁hash，以及每run到底测哪个提交。新发现闭包若以锁更新形成新提交，应重建关联并重验，不能事后改名追认旧run。
2. 每阶段真实完整command/cwd/ISO与epoch起止/整数exit，外层make/tee、内层Mill/Git等分列；非空原始日志绝对路径与仓库内相对路径、stdout/stderr、driver和commands；trace原文件、Git准确事件/及时同argv对照/作用域正反证据、采集完整性或丢失项。
3. 环境prepare/verify/目标兼容分别判定；JVM真实选项与无外写、Verilator backend、TOOL_EXTENSION跨层空字节、全部已到工具/库/插件/四wheel/输入和生成物指纹。按阶段标尚未到达工具，不虚构总锁通过。
4. 前后多库path/gitdir/common/branch/HEAD/tree/status/父gitlink/alternates与忽略现场，旧out11文件、.venv、XS输出及两旧run/链接保留证据；输出owner检查、映射生产消费、进程实时exe/祖先/starttime/占用与清退或残留说明。三方向仅身份核对，无跨方向成果读取。
5. 若完成，给全链正确性/线程/50000终点、每1000采样和Host time spent、诊断与正式时间分列；若失败，列最早实际位置、可证假设、最后完成阶段、未到阶段、原始错误/退出和同参数新run重接建议，哪些需要PI决定；外部超时/中断另记。
6. 本步推进标签按实际选advanced/narrowed/verified/none，并在正文单列VRT_PRIMARY_PROGRESS、VRT_EVIDENCE、VRT_REMAINING_GAP、VRT_TARGET_RUN；attempted再列VRT_TARGET_COMMAND、VRT_TARGET_EXIT、VRT_TARGET_LOG，not_run必须明确VRT_BLOCKER。字段按现workflow作证据，不声称旧执行器会强制科学验收。

连续两步无目标推进、无阻塞缩小、无新独立证据时必须改变策略；本次H1/H2/H3和具体门禁是承接新证据，不能再次原样工具盘点。工程在合法范围排障成功后立刻三目标，不等宽值优化再跑50k；公共阻塞解除后RA1回通用宽值/边界缓冲方向，RA2保持通用活动度/分区调度，RA3保持通用等价子图/状态访问。

v3当前只冻结规范/门槛和四wheel字节锁。aaca3fa/3eea166与本步未来后继均须ENGINEER→RA独立审查→PI核定精确公共补丁/总锁；RA2/3只有PI公布后才能各自从共同A0/技术cba9c322应用同公共增量并独立构建，不能取RA1草案/优化/venv/cache/classes/RTL/IR/model/emu。共同起点/环境/测量改变，全部受影响A/B同口径重测，无证据不排名。

RA1首工程完整尝试义务已履行，RA2/3各自首工程仍实际走全流程至完成或最早阻塞；每RA用满6次成功工程并逐步审查/周报，done/no_value不提前终止。全部齐备后PI仅选至多一个F01–F08合格方向，精确列多库候选，由PM另派Agent集成到周初目标引用A及A/wolvrix的refs/heads/grh/grhsim-ir并复验；不拼接方向，无合格不集成，漂移/冲突/多库部分成功记录重验，落选成果保留。本次不选优、集成、换周、重置配额或结束原目标。

## 8. 本RA规划动作与档案提交记录

本RA仅静态读取接口、原始证据、实时回执和只读多库审计，没有运行make、安装、构建、实验或优化，没有子Agent、技术修改、Git数据库修复、推送或历史改写。首次大文件读取输出被截断，随后按阶段/字段提取原始证据；P/runs-read.log、pi-review-evidence-read.log、receipts-read.log保留实际名称与hash。未用一次cat的截断输出声称完整对象验证；既有对象遍历属于历史审查证据。

档案提交前A完整SHA=`a5fe01b747f6510b25c6cdb4d34bbd082b309d21`、grh/grhsim-ir、开工clean；本次仅新增本文。精确提交后SHA/父/tree和状态写P/commit-after.log及RA最终回复，避免同一提交自引用尚不存在的hash。P/commit-before.log、roots-closing.log及repos/links/alternates-closing.tsv记录结束核查。主wolvrix、R技术/依赖与RA2/3保持原身份；R旧out和忽略现场保留。所有取证临时日志仅P，不在/tmp或项目外落盘，不另写workflow外状态文件；.runner始终只读且连续可用。

提交前结束复核：P的repos/links/alternates opening与closing逐字节cmp均exit0，且opening与PI v3 closing也逐字节相同；489仓库、486已检出父gitlink和483借读关系保留（links文件另含3个not-checked-out排除项）。R累计patch仍`955f8b192b97165e32a30e8a55a8d64cf3bdd36d62e3ebf1c7ca6a881018ffa9`；status仅`?? out/`，技术clean。结束pgrep无匹配exit1、CPU2 powersave/siblings2,18，只是此时快照，不授权将来按旧PID处置。P/pi-args.txt与task-args.txt的静态diff exit0，完整数组无遗漏；没有通过make -n或启动工具做“静态检查”。实际Makefile确认目标emu文件为`<run>/grhsim-ir/emu/emu`，IR路径为`<run>/grhsim-ir/xiangshan_flat_grh.json`、`xiangshan_grhsim_ir.json`、`xiangshan_grhsim_ir_roundtrip.json`，工程须对到达阶段的实际文件留hash。原始核查记录P/final-static-review.log，最终仅本文显式stage并以Git whitespace检查核文档，不执行工程测试。
