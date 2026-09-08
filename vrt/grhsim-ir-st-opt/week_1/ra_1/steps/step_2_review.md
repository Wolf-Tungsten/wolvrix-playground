VRT_VERDICT: continue

执行编号：`week-1-ra-1-review-step-2-c9a4c84b`；2026-09-08，RA1 独立证据审查。仅只读取证、结果归档与技术建议；未实施修复、安装、构建、目标测试、依赖更新或子 Agent 派发。

VRT_PRIMARY_PROGRESS: narrowed。第1步实际目标暴露 Mill/ASM major69；第2步经合法 Makefile 环境入口换用核定 JDK17/Mill0.12.15，真实目标越过原错误并编译 build.mill，首先发现 nested Mill 输出越界，再于修正 run 暴露 VcsVersion 的 Git 上下文问题。获得了实际 JVM、写入和失败栈新证据，故不属于连续两步“无推进/无缩小/无新证据”。但两步均没有 RA1 emitter/runtime 优化或完整 A，公共环境排障不等于方向完成或证伪。下一步必须从泛化环境盘点转为准确捕获并修复 Git cwd、补齐已证实的隔离缺口，解除后立即接完整链。

VRT_EVIDENCE_CHECK: 两公共提交和累计 patch hash 匹配；prepare/verify 命令确实退出0，证明范围限于已核四包、工具启动和 probe。完整目标一两次均退出2，二/三均未执行。修正 run 的全局写入隔离不通过：原始 strace 和 maps 已证明 `/tmp/hsperfdata_gaoruihao` 写入；目标没有 strace、Git 环境未采集。源码对象当前可读，不支持直接判为 XiangShan Git 数据库损坏。公共补丁仅属环境编排，但存在下述返工项，**不建议将 aaca3fa/3eea166 直接冻结为三方向已验证公共环境**；交 PM 派 PI 核定后续规范和适用关系。

VRT_NEXT_STEP: PM 先派 PI 处理本文公共问题；下一 ENGINEER 只续接 RA1 入口 `3eea16676f73cba5f87364e8959049437de40308` / 技术 `cba9c32240f3cd06c5b675968b56046e5b76f818`，经 Makefile 在新 candidate/run 捕获准确 Git argv/cwd/仓库上下文，实施最小合法入口修复并补隔离、工具校验，再严格串行 `make xs_wolf_grhsim_ir` → `make xs_wolf_grhsim_ir_build_emu` → `taskset -c 2 make run_xs_wolf_grhsim_ir_emu`。前一步失败不盲跑后一步。本 RA 未执行这些工程命令。

## 1. 实时回执、精确版本与取证位置

已读主 AGENTS、workflow、race_contract、ra_review 模板、requirements/project、baseline 全164仓库清单及§6 v2、pi_plan 三方向/F01–F08及交接、race 文末、step_1 task/result/review（含勘误）、step_2 task/result。运行回执读自：

- `/home/gaoruihao/wksp/wolvrix-playground/vrt/grhsim-ir-st-opt/.runner/c9a4c84b9a384fd1967b6c0a21ad71aa/state.json`
- `/home/gaoruihao/wksp/wolvrix-playground/vrt/grhsim-ir-st-opt/.runner/c9a4c84b9a384fd1967b6c0a21ad71aa/call-0d7755d1f0d8436f99aea6643cee9182.log`

开工实时 pending/running 是本 RA 审查（不是 PM 派发前 pending=null）。两任务 `week-1-ra-1-step-1-eng-c9a4c84b`、`week-1-ra-1-step-2-eng-env-and-target-c9a4c84b` 均 returned/exit_code=0，无未知/运行中的 ENGINEER；RA1 **2/6，余4**，RA2/3 **各0/6，余6**。目标失败和内部重试不取消或重复计费；成功调用不等于技术通过。

以下别名只为避免重复，均对应实际绝对位置，不省略候选或 run 身份：

|别名|实际绝对位置|
|---|---|
|A（档案主检出）|`/home/gaoruihao/wksp/wolvrix-playground`|
|R（RA1入口）|`/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1`|
|L1（首次工程run日志）|`/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1/ptmp/B1-c9a4c84b-v2/aaca3fafe3134f7147f1f3e866cfcb1401c5be35/w1-r1-s2-a-0567b6c-cba9c32-v2-01/logs`|
|L2（修正工程run日志）|`/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1/ptmp/B1-c9a4c84b-v2/3eea16676f73cba5f87364e8959049437de40308/w1-r1-s2-a-0567b6c-cba9c32-v2-01/logs`|
|E（本RA只读证据）|`/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1/ptmp/ra-review-step2-c9a4c84b`|
|P（PI原始环境证据）|`/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/evidence/pi-env-v2`|

读取 R/ptmp/step2-opening 的开工、递归、driver、状态和回执取证；用 E/recursive-opening.tsv 独立重核原 isolation-verified.tsv 的489仓库及486个已检出父 gitlink。原TSV SHA256仍为 `6149d82c9e892b1fe92ce0682b5f37cabf5500c51fcbd4f35037d90044a343db`，164条 baseline 映射到489条方向记录无不符。当前只有 RA1 入口因两公共提交与历史起点不同，其他488仓库 HEAD/tree均匹配，486个父gitlink匹配；三处 openc910 未检出是原排除项。P 的五份已冻结证据hash也匹配；历史证据与本次现场分开保留。

|仓库|当前 HEAD / tree|分支与现场|
|---|---|---|
|A|开工 `4eb27647b3fa9310c0228abb50a898e3a9a4f1a9` / `2fb4487e45f30d514a447f28fd861d97f15c1b7b`|`grh/grhsim-ir`；仅 step_2_result.md 未跟踪；本次只提交 result/review/race|
|R|`3eea16676f73cba5f87364e8959049437de40308` / `7606970036deb01130b50e92d24b858454615598`|`vrt/grhsim-ir-st-opt/c9a4c84b/week_1/r_1`；仅11个旧 out 未跟踪文件；无未提交源码 diff|
|R/wolvrix，A/wolvrix|`cba9c32240f3cd06c5b675968b56046e5b76f818` / `6bcc50560c2fb21f5e000cc521bec5a5e58d8483`|分别方向同名分支、`grh/grhsim-ir`；源码clean；父gitlink未改|
|R/testcase/xiangshan|`4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6` / `bb4b5dc0ed12891829b69028b09e6352993c6d4d`|detached、源码clean；忽略 out、.docker-mill-out、build 保留|
|RA2/3入口|`0567b6c7d0261ddd1834daffa8f15327c7f5810a` / `8544a4528fac5f15fb59d57e6ef5622eccea2e99`|各独立同编号分支，clean；技术均cba9c322，XiangShan均4a6e3da8 detached/clean|

完整 gitdir/common-dir/分支/status/父gitlink见 E/roots-opening.log 与 recursive-opening.tsv。入口 gitdir=`A/.git/worktrees/r_1`，common-dir=`A/.git`；技术 gitdir=`A/.git/modules/wolvrix/worktrees/wolvrix`，common-dir=`A/.git/modules/wolvrix`。RA2/3对应 r_2/r_3 与 wolvrix1/wolvrix2。依赖私有工作目录及自身.git保持不变，但新增只读事实：483个依赖检出都有 `objects/info/alternates` 指向主检出相应对象库（E/dependency-alternates.tsv）；三方向 XiangShan均借读 `A/.git/modules/testcase/xiangshan/objects`。私有gitdir不能表述成对象库完全自包含。当前无缺对象证据；该拓扑需要 PI 补充描述与保留责任，不授权共享可变cache/build，也不授权本RA修改Git数据库。

## 2. 实际diff、命令与计时核对

共同起点入口 `0567b6c7d0261ddd1834daffa8f15327c7f5810a` → 本方向公共提交 `aaca3fafe3134f7147f1f3e866cfcb1401c5be35` → `3eea16676f73cba5f87364e8959049437de40308`，父子链逐项一致。独立执行 `git diff --binary <基点> <提交> | sha256sum` 得：

- 首补丁 `3460712b4b4d8efd80a47ed34318670e1c8660767d3bb238fb316fe34a5d20e6`。
- 累计补丁 `955f8b192b97165e32a30e8a55a8d64cf3bdd36d62e3ebf1c7ca6a881018ffa9`。

实际仅 Makefile、scripts/vrt_common_env.mk、scripts/vrt_common_env.py。内容是准备/验证入口、env文件选择、py_install时间标记、目标observer、输出映射及变量传播；无技术源码、冻结GRH/pass、测试或依赖源码改动，无宽值优化。第二提交增加命令行 MILL_OUTPUT_DIR、把 .docker-mill-out 纳入观察、降低Java/emu详细快照频率。范围类型符合 PI 环境授权，但实现质量与固定工具不全合格（§4），不能因“纯环境”直接冻结。

完整最外层命令、全部参数、cwd、ISO/epoch时间、tee退出码在 L1/L2 的 driver.log，执行脚本为各自 prepare-driver.sh/target-driver.sh；commands.jsonl提供helper内每个子命令的完整argv/cwd/起止/退出码。已交叉核工程原始回执3977–4268、4596–5322、5611–5898、6109–7059。Python/venv/pip/Java/Mill probe均由新Makefile目标调用，未发现本步直接source旧安装env的重犯。原目标参数保持 TLConfig、E.b、单核、systemverilog、原firtool flags、enable-difftest、JVM XMX40G/XSS256m、50k/1000与原GRH流程。

|run/命令阶段|实际时间（+08）与墙钟|退出码/范围|
|---|---|---|
|L1 prepare / verify|21:40:37.479–44.951，7.472s；21:40:44.954–46.989，2.034s|make=0、tee=0；两者通过各自局部检查|
|L1目标一外层 / 内层|21:42:12.974–21:43:30.239，77.264s；内层75.588s|make=2、tee=0；Mill受INT，nested报130；二/三未跑|
|L2 prepare / verify|21:44:01.326–11.786，10.460s；21:44:11.789–13.761，1.971s|make=0、tee=0|
|L2目标一外层 / 内层|21:44:33.709–21:45:42.137，68.427s；内层21:44:34.698–21:45:41.164，66.466s|make=2、tee=0；Git=128，Mill=1；二/三未跑|

result把L1的7.47s/2.03s列在L2环境下，现于审查纠正，结果原文不改。L2/xs/rtl/time.log（即 L2/../xs/rtl/time.log）仅为Mill失败段66.31s；没有完整冷编译结束时间，更不是<1800s成绩。准备内部venv/wheel-download/resolve/install和verify内部python-versions/pip-check/freeze/java-settings/mill-probe各自exit=0；命令计时全部见各run commands.jsonl。目标一先依赖sim-verilog失败，py_install未开始；不存在wolvrix native安装、import、emit、emu或50k验证。

L1原日志确实显示JDK17和 `.docker-mill-out/*/compile.dest/classes`。工程在21:43:29核对当时exe/cwd/stat后向1648843、1648868发INT（L1/isolation-blocker.log），不是按旧1605023杀进程；但其实现以当前XiangShan cwd前缀选Java而非严格锁定observer后代，下一步应使用启动时间+进程树校验。两PID及修正run1651171/1651196当前均不存在，未发现残留目标进程。

L2/xs_wolf_grhsim_ir.raw.log显示build.mill编译完成、749任务图、VcsVersion.vcsState失败。可确认原major69在本次已到达路径消失，不代表所有Scala/firtool/JVM fork和RTL已兼容。实际仅 L2/../xs/rtl/time.log，SimTop.sv/filelist/IR/model/emu均未生成，skbuild/grhsim-ir目录不存在。

## 3. 工具、hash与旧现场的通过范围

两run的 pinned.sha256（JDK release/java/modules、基础Python、Mill种子、CoreMark、NEMU）独立校验exit=0；wheels.sha256.jsonl所列wheel当前字节全部匹配。Python四包版本及METADATA、pip check与freeze相符；没有额外解析包。L2/tools.jsonl现存可哈希条目全部重核通过，libjvm SHA256=`35f86cffa7a4edf211cb342c55427e1a3d7ac5ee28aa0d239d8ad8b0b7de743f`。这不证明尚未安装的wolvrix兼容。

|wheel|版本|SHA256|
|---|---|---|
|pip|24.0|`ba0d021a166865d2265246961bec0152ff124de910c5cc39f1156ce3fa7c69dc`|
|scikit_build_core|1.0.3|`ae95427b7d3c14a6cf8bbfd4d901f6138ab64c99e20cbe8ea7d75cd26093f085`|
|packaging|26.3|`d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c`|
|pathspec|1.1.1|`a00ce642f577bf7f473932318056212bc4f8bfdf53128c78bbd5af0b9b20b189`|

两run wheels.lock一致，SHA256=`cb980c72f1673db6e70639fc5f3dc05060e55af5ab7df023d571d98b5a4419b7`。精确下载URL/版本/hash见各run wheel-resolve.json及E/wheel-inputs.tsv，实际安装使用no-index/require-hashes；公共锁尚待PI冻结，不能靠下一次网络重新解析当不可变锁。Scala/Mill外部插件的完整解析/运行库闭包也待补锁。

L2/all.sha256 的48条全部 `sha256sum -c` 通过，清单自身hash=`5a8f9e6ea972858e75e015962c94797ceed00184f4b13398e88dcf83a660e6e0`。它仅覆盖生成清单时的非空logs文件，不覆盖随后新增final-common-env.patch、env/verified、全部cache、完整run或空文件；L1无all.sha256，不能称两run完整封存。已独立核累计patch。关键原始日志hash：L1目标raw=`628661cec123c3a254d6dde7dfb4029edf8421d160df79bee5a0cc1b95812038`；L2目标raw=`f4abb02ffad234b3ddf3dced213256506bc2c70a9b63d434c25a6d23c9af62bd`；L2 commands=`d022163eadc01aefee958878bd1f2c169039b379c11907eecc26ebcc6a01e3c5`；L2 probe strace=`68d037fd4e59109fd330eba300f818a0ab44079b57bca13945450dcd5534f275`。

旧现场：两run的old-before/old-after-verify及target old-before/old-after字节比较均exit=0；所列旧普通文件当前hash均匹配（E/hashes-preservation.log）。R/out仍11文件、旧.venv、R/build、XS/out、用户原缓存均保留。L1监测脚本未包含XS/.docker-mill-out，因此其unchanged=True不能证明该目录未写；原raw明确发生写入，后续docker-mill-out-after.sha256只提供事后清单。L2才加入这一目录并证实其前后不变。未删除首次失败产物。

generated-src：L1之前不存在；L1创建的链接在L2 prepare时被保留为 L2/../preserved/generated-src（仍指向L1的xs/generated-src），当前XS/build/generated-src指向L2的xs/generated-src。两run与旧链接均保留，生产/消费解析在已检查位置一致，但未实际生成内容。工程helper `git('ls-files',...)` 总在入口R检查，不能检查嵌套XS的跟踪文件；本RA另在XS执行ls-files确认本现场该路径无跟踪源码，未来保护逻辑仍须修正。

## 4. 公共补丁返工依据与冻结建议

1. **已证实外部写入，F02不通过。** L2/mill-probe.strace:144–149、582–587、739、759记录JDK在`/tmp/hsperfdata_gaoruihao/1650925`、`1650951`创建并删除文件；目标processes.jsonl的1651171/1651196 maps还有对应`rw-s`映射。E/outside-run-writes.log提取了证据。`java.io.tmpdir`与TMPDIR并未控制HotSpot perfdata；旧路径inventory没有/tmp，故unchanged=True不能证明全隔离。请PI决定工具专用禁止共享perfdata（例如验证`-XX:+PerfDisableSharedMem`的实际效果）或允许何种明确例外；本RA不加选项、不改规范。若改共同环境，三方向全部A/B按新口径重测。
2. **准确Git子进程证据缺失。** observe(...trace=False)只50ms轮询；GIT_DIR/GIT_WORK_TREE/GIT_COMMON_DIR/GIT_OBJECT_DIRECTORY/GIT_ALTERNATE_OBJECT_DIRECTORIES及GIT_CONFIG相关变量均不在采集allowlist，也未被明确清理/核定。没有目标strace，不能把probe strace冒充目标系统调用证据。当前遗留sandbox已不存在，只能用原process日志及现存mill-target父路径取证；最早失败rev-list没有被轮询捕获。ENGINEER须经Makefile在诊断run捕获exec/chdir/仓库发现和白名单Git环境，无凭证泄露；诊断strace耗时不报作正式性能。
3. **错误工具路径及环境值。** helper:91固定`VERILATOR=/usr/bin/verilator`，实际该路径不存在（ls exit2），与B1的`/usr/local/bin/verilator`不符；后者当前hash=`fb2cc573b1055cf096c90e1efc9966fe56bdb4b265c83590cf2a49f7a0defcdf`。未到native不能当成已造成当前失败，但verify不应放过它。PATH也排除了/usr/local/bin。另Makefile:46按双引号解析env，新的`export TOOL_EXTENSION=''`被解析为整行字符串，目标两个JVM实际环境均`TOOL_EXTENSION=export TOOL_EXTENSION=''`，不是已核定空值。修复入口的字面变量传递并核子make；恢复既定工具不需要升级依赖。
4. **工具/锁闭包不全。** tools.jsonl对LLVM clang/clang++只记录symlink而未hash最终clang-22；JDK内链接目标也需闭包核定。补齐Git可执行文件、编译器realpath、必要运行库、版本与hash，固定已解析wheel锁与Scala插件闭包，记录实际加载库。准备成功不等于完整工具锁已冻结。
5. **输出与进程保护需收紧。** 在真正拥有文件的XS仓库查tracked状态；切换输出前按当前exe/启动时间/后代归属及真实输出占用检查。补全旧XS/build及其他实际写入路径，保留短命文件写入证据。observer采样和固定列表只能给有限通过；本次没有证明所有XDG/native/difftest写入都隔离。编译与仿真观测开销/线程采样口径最终由PI统一，不能将诊断开销或observer线程误算为模型并行加速。

上述没有发现禁区源码修改，但第1、3项已是实证不合格，第2、4、5项是闭包/保护缺口。建议将两提交作为保留的环境修复草案交PI，返工验证后再冻结精确后继提交、累计patch、工具锁及三方向采用关系。RA2/3不得自行采用这两个未冻结提交，也不得继承其缓存/生成物。

## 5. bad object：独立证据、可区分假设与最小合法方案

原栈定位在VcsVersion.scala:82 `$anonfun$calcVcsState$5`，由XS/build.mill:164的publishVersion→VcsVersion.vcsState触发，外层XS Makefile:275 sim-verilog、入口Makefile:557。不是Python/native或RA1优化错误。

从L2私有cache实际加载的`de.tobiasroeser.mill.vcs.version_mill0.11_2.13-0.4.0.jar`（SHA256=`a8e0cc9ef56e1473518df6590c205143ab21c0bc714ac2ce1d69316d293cd0d1`）做只读javap反汇编，未运行插件/目标代码。E/VcsVersion.bytecode.log表明：`git rev-parse HEAD`及exact-tag describe显式用vcsBasePath；fallback `git describe --abbrev=0 --tags`、出错的`git rev-list <hash> [--not <tag>] --count`及diff使用默认cwd，$5没有捕获vcsBasePath。故源码库获得hash、另一个cwd计算count的错配是具体可检验机制；无需猜“仓库损坏”。

独立Git只读证据 E/git-context.log（含所有命令及逐条exit）：

- 在`R/testcase/xiangshan`，cat-file -t/-p能读4a6e3da8 commit/tree/parent，rev-list该hash --count返回**11810、exit0**；rev-list --objects --missing=print遍历118746条对象、exit0、无`?`缺对象标记；非shallow。通过只覆盖当前该可达历史与对象可寻址性，并非全Git数据库逐字节fsck。
- 在R和L2/../mill-target，Git发现的是RA1入口worktree的gitdir/common-dir与3eea166；cat-file相同XS hash失败128，rev-list相同hash稳定复现**同一fatal bad object、exit128**。这是跨仓库查XS对象的预期失败，不证明XS对象缺失。
- XS的exact-tag describe返回128（无exact tag），fallback nearest-tag返回`v3.2.2-alpha`、exit0；源码库的fallback/tag路径本身可用，实际target fallback的tag及argv仍缺捕获。
- 原目标Java1651171 cwd是XS，MillMain1651196 cwd是L2/../mill-target/mill-no-server/6e4daa68/sandbox（现已消失）。目标轮询捕获1651196直接子进程1651651在**R**执行`git status -uno --porcelain`，其子Git再递归检查XS；见E/observed-git.tsv。这个status不是失败rev-list，不能偷换成失败调用的精确cwd，但证明目标内部确有入口Git上下文。

判断：**H1（优先）为VcsVersion默认cwd随外置Mill output/sandbox落到入口仓库，hash却来自XS，导致跨库rev-list。强证据支持，仍需准确失败exec及Git环境确认。** H2为继承Git环境重定向（本次未采集，不能排除）；H3为对象/alternates/历史损坏（当前commit与完整可达遍历成功，优先级低，不支持立即修库/fetch）。分辨标准及下一工程任务：

|假设|必须取得的验证|最小合法范围/结果分支|
|---|---|---|
|H1 cwd错配|Makefile诊断入口包住原目标，记录失败rev-list和fallback describe的完整argv、物理cwd、show-toplevel、absolute-git-dir/common-dir、实际对象查询；与源码cwd执行同argv对照|优先研究入口Mill wrapper提供正确启动工作目录/受支持选项；若工具做不到，PI可核准仅在已识别Mill sandbox、且无显式仓库参数的Git调用设置正确cwd的入口适配。保留显式-C/--git-dir与合法子仓库上下文；原样转发argv/输出/退出码，不伪造version/hash/tag/dirty。不改build.mill、插件jar或测试源码|
|H2环境注入|采集并对比Git专用环境与config来源，验证其是否覆盖cwd；不得输出凭证或假定无采集就是未设置|只在获准工具进程作用域清除/固定经确认的注入。禁止全局export GIT_DIR到整个三目标链，否则会破坏py_install及嵌套子库身份|
|H3对象/历史缺口|在实际失败Git上下文中cat-file/rev-list；对比XS及其alternates。仅若正确上下文仍失败，再列出缺失对象/父对象及精确来源|提交PM/PI核定共同依赖补充；不在RA审查修库，不fetch/repack/gc/切版本/借其他方向对象，不能把失败当依赖升级授权|

下一ENGINEER诊断目标内部应调用的只读Git核心命令（cwd由捕获值和XS各自指定；`<hash>`为原完整4a6e3da8 SHA；不是让本RA跑目标）：`git -C <cwd> rev-parse --show-toplevel --absolute-git-dir --git-common-dir HEAD`、`git -C <cwd> cat-file -t <hash>`、`git -C <cwd> rev-list <hash> --count`，若捕获`--not <tag>`必须原样对照；同时记录GIT_*允许字段与配置路径。诊断仍先添加Makefile目标再调用，不直接Python/pip/Java/Mill代跑。

需要PI决定的共同事项：上述Git环境/工作目录适配允许范围；HotSpot外部perfdata写入的处理及统一JVM参数；工具路径/完整锁与后继精确提交；483处依赖alternates及外部VcsVersion 0.4.0/Mill0.11交叉构件身份的补充清单。全部影响RA1/2/3的A/B；不得只升级RA1的JDK/Mill/插件，不把objects alternates共享误认成可共享编译缓存。RA审查不修改baseline/requirements/pi_plan，也不替PI冻结。

## 6. F01–F08与后续完整目标

|项|本步独立状态|最终仍缺证据|
|---|---|---|
|F01|源码边界通过；公共实现仍需返工|未改GRH/pass、XS/测试或技术方向代码；固定Verilator偏离须纠正，尚无优化候选diff|
|F02|源码/父gitlink/独立方向匹配；**环境隔离不通过**|L1输出越界、L2/tmp写入、Git/短命进程采集缺口；公共补丁未冻结，不能排名|
|F03|部分：输入hash、真实命令和局部工具证据通过|RTL/filelist顺序/defines、flat GRH/GrhSIM IR、model/emu与完整工具锁未齐|
|F04|未测|完整CPU mapping/schedule/emit、GrhSIM IR/必要HDLBits回归；50k每1000有序采样、NEMU、PC/trap/instruction/state/退出状态及无mismatch/ABORT/BAD TRAP|
|F05|失败/未完成|目标一两次exit2；目标二/三未执行。没有50,000 host/model周期/cycle limit，也无运行时EMU_THREADS=0、线程/affinity证据|
|F06|未测|py_install native和模型/emu编译均未发生；从空私有输出到build_emu成功的完整冷编译必须<1800s，失败66s/68s不能充当成绩|
|F07|未测/无资格|A/B各至少三次交错完整50k、CPU2/powersave/sibling18空闲、串行、原Host time spent各值及中位数；candidate<A×0.99且max/min≤1.05；gsim约40s仅用户参照|
|F08|本步结果原样归档并完成独立审查；最终未齐|RA1仅2/6，余4；RA2/3各0/6；后续逐步审查、方向周报、全证据、PI验收均未完成|

下一步实现与返回目标的顺序可直接转为工程任务：先落实PI核定的最小环境返工，公共提交与技术优化分开；新的`R/ptmp/<PI环境版本>/<candidate-sha>/<unique-run>`拒绝覆盖，保留本步两run、旧out/.venv/.docker-mill-out/所有Mill输出。prepare/verify经Makefile成功后仅加载其纯export/unset环境；补准确Git诊断、必要环境修复后立即串行跑原三目标，同step_2_task完整VRT_ARGS：50k、progress1000、CPU2、powersave、单核、EMU_THREADS=0、two-state、seed0/reset50、Release/-O3、8编译jobs、reg_to_mem1、resume0、keep_origins0、batch64、波形/perf/phase/trace关闭、原TLConfig/E.b/firtool/GRH pipeline。冷编译从目标一（含py_install）至目标二成功；安装依赖另计。前一失败记录整数退出码和原始输出即停止链，再交接准确新错误，不盲跑后段。下一成功A仍不是三次A/B或优化完成。

环境解除后RA1立即回到通用宽值/边界缓冲emitter/runtime候选：先比对legacy helper，再遵守指针、调用方输出缓冲及local frame/boundary，避免返回大std::array和热路径大临时复制；不混入RA2/3调度/等价子图成果，不改禁区。每方向须用满6次成功ENGINEER并逐次审查/周报，done/no_value不提前结束。周末全部配额与证据齐备后PI只选至多一个F01–F08合格方向；PM再派Agent精确多仓库集成与验证，禁止拼接，无合格不集成，全部落选现场保留。

## 7. 只读失败、结束现场与档案责任

只读失败也保留：E/git-context.log中R/mill-target cat-file与rev-list各exit128为区分上下文的预期失败；XS exact-tag describe exit128仅无exact tag。查已退出sandbox的ls/rg exit2，未重建目录；直接对带shell前缀Mill分发包javap os.proc读取exit1，改为只读提取class至E再javap成功（unzip提示572额外字节、exit1，非执行/编译目标，原包hash匹配）。查缺失`/usr/bin/verilator`和尚未生成skbuild/grhsim-ir的ls exit2；L1 preserved/generated-src不存在（原位置本就missing，ls exit2）。pgrep精确目标名无匹配exit1；无缺对象标记搜索exit1、未采集GIT_*搜索exit1，不能误写为完整目标通过。没有运行make、安装、测试、源码修复或Git数据库修复；E下仅审查日志/只读提取副本。

当前保留R入口`?? out/`、忽略.venv/build/env.sh/ptmp，XS忽略out/.docker-mill-out/build及两run。技术/依赖源码clean；主检出旧build/.venv等忽略现场原样保留。归档前后根状态、递归与进程复核见E/roots-closing.log、recursive-closing.tsv及最终提交回执；没有用清理/ignore制造clean，没有推送、合并方向代码或改父gitlink。

step_2_result.md原字节SHA256=`a42ed27962a401f5d08a5caa666b3885c7b3bbcb84f1a450fe445ee54eafaaf1`，本次原样显式stage；所有纠正只写本文。档案仅在A的`grh/grhsim-ir`提交本结果、本review、race的追加；提交父为4eb27647，最终精确提交号见本RA最终回执。不提交.runner、ptmp、生成物、baseline、requirements或pi_plan；档案提交不合入方向代码。
