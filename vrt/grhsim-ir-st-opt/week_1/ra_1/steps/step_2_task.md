# RA1 第2步任务书：环境与输出隔离 blocker（B1-c9a4c84b-v2）

VRT_PRIMARY_GOAL: 优化 grhsim-ir 单线程 XiangShan CoreMark 50k 性能，参照 gsim 约40s，编译 <30min；RA1 后续仍聚焦通用宽值与边界缓冲 emitter/runtime，遵守 legacy 指针及调用方输出缓冲策略。
VRT_SUCCESS_CRITERIA: 在本次 ENGINEER 调用中，经本方向 Makefile 实现并验证私有环境/输出隔离后，按固定参数串行完成 `xs_wolf_grhsim_ir` → `xs_wolf_grhsim_ir_build_emu` → `run_xs_wolf_grhsim_ir_emu`，或保留最早新阻塞的整数退出码、非空日志和路径证据；解除 F02/F03/F05 的具体阻塞。环境获准不等于兼容已证实，本步不证明原优化方向有效或无效，也不产生排名候选。
VRT_TARGET_PATH: 从共同 B1-c9a4c84b-v2 起点，在 RA1 私有 r_1 入口先补齐 `vrt_common_env_prepare`/`vrt_common_env_verify`（当前 Makefile 中不存在，名称为待实现接口），再立即接回完整 50k 目标链；不做宽值代码优化、不改测试或冻结 GRH IR/pass。
VRT_TASK_KIND: blocker
VRT_NEXT_TARGET: 成功则下一 ENGINEER 继续同一隔离口径的完整 A/宽值边界候选；失败则下一步只针对本报告记录的最早新错误修复并重接同一三目标链，不能将未测或环境失败判为方向证伪。

## 待验证假设、精确起点与边界

假设是：PI 核定的 Ubuntu OpenJDK17.0.20+8-1-24.04-Ubuntu 与 Mill JVM 0.12.15（原 `-i`）能够在不改 XiangShan/测试源码的情况下消除 major69 阻塞；私有 venv、Mill/Ivy/Coursier/XDG/PIP/TMP、RTL/filelist/generated-src、IR/model/emu/skbuild 和日志映射能够避免旧 `out`、`testcase/xiangshan/out`、`.venv` 与用户 cache 污染。必须用真实子 JVM 和实际写入路径证明，静态变量存在或 `--version` 单独成功均不足。

精确工程起点：入口 `/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1`，分支 `vrt/grhsim-ir-st-opt/c9a4c84b/week_1/r_1`，HEAD `0567b6c7d0261ddd1834daffa8f15327c7f5810a`；嵌套 wolvrix HEAD `cba9c32240f3cd06c5b675968b56046e5b76f818`。XiangShan `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`、ready-to-run `912f92121570bd28cabbefa7fa56d25b9784c304`、gsim `a3ecb26aa0c18f55c7fbba20e7a9b9d14a25442a`；递归清单按 baseline v2。档案 HEAD `719fc9a655034dd104eda63218703e451f8e42bf` 不得进入技术起点。保留现有 `out/`、XiangShan/out、`.venv`、build/xs、旧日志；旧 PID1605023 当前不存在，续接时仍须重新核进程，不能按旧 PID kill。

范围仅为本方向入口 Makefile/必要环境辅助脚本的公共环境编排修复及一次完整目标尝试。公共修复必须独立提交并记录精确 SHA/patch hash，不能夹带 RA1 优化；RA 审查后交 PM/PI 冻结其精确提交与三方向适用关系，其他方向不得自行 copy/cherry-pick。禁止修改 baseline、requirements、pi_plan、race、`.runner`、XiangShan/测试/依赖源码、GRH IR/pass，禁止多线程仿真和模块名匹配。

## PI 核定工具、输入与未验证项

唯一允许 Java 为 `/usr/lib/jvm/java-17-openjdk-amd64`，release SHA256 `b8d3277e4f728d8ed638fc8eae2b66c7d10d7b8424985dfb4e5feb688aea66d2`，java SHA256 `4976918b29ece3fe634bdbcf1377676e42af429b5311ba234f6f95039117d4d4`，modules SHA256 `499337b57cd61a672db7e1b35a3946bfb99508187367dc886c2bcbf28c65bf3a`。Mill bootstrap `/home/gaoruihao/wksp/mill` SHA256 `af73fadc1fa005e43962bcd529690f448592f4e0786a90b712ac6509378a9eb2`；核定 distribution `/home/gaoruihao/.cache/mill/download/0.12.15` SHA256 `ea1bba01e220f4ce20bb333247d254a2bf9b86554c10c3d7d7e16641ec0a76d8`，可从该单文件取种但不得复制整个用户 cache。Java25/Mill1.1.6/Azul21 仅为失败或误探测历史，排除下一目标口径。

基础解释器 `/usr/bin/python3.12`（3.12.3，SHA256 `1643dacd9feaedc58f3cc581e4d22577dfe25c09b10282936186ccf0f2e61118`）；固定 pip 24.0、scikit-build-core 1.0.3、packaging 26.3、pathspec 1.1.1。四项 METADATA SHA256 依次为 `90d11f277fd5868da679ee257c97656dde511c8aac7d025231407e6ce90839e2`、`bfd7fef484ff85c723956d256c4f906695879428b4069707e7e101aa5c460fe0`、`70fdb89fc4d4a9a043bf7372b8972bcc883fddff34ab55e9cf80d73875384763`、`68de3f158b6592f086e78754c962092f32a761944ab66a660c0d62ad79c4b69b`。wheel URL/hash、完整传递依赖锁、pip check、JDK libjvm/运行库指纹及兼容性均待工程补齐；任何版本变化交 PI，核定允许不等于已验证。安装仍必须通过 `make py_install`，不能直接 Python/pip/cmake/ctest/compiler。

固定输入及证据：requirements/project.json；baseline.md §6、pi_plan.md v2 交接、race.md v2、step_1_task/result/review；ENGINEER/RA/PI 回执三文件；原始日志目录 `/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1/ptmp/logs/w1-r1-s1-a-0567b6c-cba9c32/`（五文件，target1-mill SHA256 `7ba0a4f44c8c721d2ee6c019d7f8647f1ae392d9e1d8942fc06f695ce410df6e`）；隔离 TSV SHA256 `6149d82c9e892b1fe92ce0682b5f37cabf5500c51fcbd4f35037d90044a343db`；只读 v2 证据目录 `.../evidence/pi-env-v2/{roots-before.log,recursive-before.tsv,gitlinks-check.log,fingerprints.log,out-processes.log}`。

## ENGINEER 可执行命令（一次调用，缺入口先实现）

先在现有 r_1 分支实现两个待实现目标，再显式 stage 入口 Makefile 和实际新增的必要入口脚本，提交独立公共修复。不得 stage out、依赖/gitlink 或档案。以下各代码块在同一 Bash 会话依次执行；不表示目标已存在或已执行。技术修复提交后才取得 candidate SHA；其含义是本方向公共环境补丁版本，尚非 PI 冻结候选。保留所有失败 run，修补代码后新提交、新 run：

```bash
cd /home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1
set -u -o pipefail
set +e
VRT_CANDIDATE=$(git rev-parse HEAD)
test "$VRT_CANDIDATE" != 0567b6c7d0261ddd1834daffa8f15327c7f5810a || exit 2
test -z "$(git diff HEAD --name-only)" || exit 2
VRT_RUN=w1-r1-s2-a-0567b6c-cba9c32-v2-01
VRT_PARENT="$PWD/ptmp/B1-c9a4c84b-v2/$VRT_CANDIDATE"
mkdir -p "$VRT_PARENT" || exit $?
VRT_RUN_ROOT="$VRT_PARENT/$VRT_RUN"
VRT_TRY=1
while ! mkdir "$VRT_RUN_ROOT"; do
  test -e "$VRT_RUN_ROOT" || test -L "$VRT_RUN_ROOT" || exit 2
  VRT_TRY=$((VRT_TRY+1))
  VRT_RUN="w1-r1-s2-a-0567b6c-cba9c32-v2-01-retry-$VRT_TRY"
  VRT_RUN_ROOT="$VRT_PARENT/$VRT_RUN"
done
mkdir "$VRT_RUN_ROOT/logs" || exit $?
git diff --binary 0567b6c7d0261ddd1834daffa8f15327c7f5810a "$VRT_CANDIDATE" > "$VRT_RUN_ROOT/logs/common-env.patch"
sha256sum "$VRT_RUN_ROOT/logs/common-env.patch" > "$VRT_RUN_ROOT/logs/common-env.patch.sha256"
vrt_stage() {
  local stage="$1"; shift
  local start end
  local -a rc
  start=$(date +%s.%N)
  { date -Ins; printf 'cwd=%s\n' "$PWD"; printf '[CMD] '; printf '%q ' "$@"; printf '\nstart=%s\n' "$start"; } >> "$VRT_RUN_ROOT/logs/driver.log"
  "$@" 2>&1 | tee "$VRT_RUN_ROOT/logs/$stage.stdout.log"
  rc=("${PIPESTATUS[@]}")
  end=$(date +%s.%N)
  printf 'stage=%s start=%s end=%s command_exit=%s tee_exit=%s\n' "$stage" "$start" "$end" "${rc[0]}" "${rc[1]}" >> "$VRT_RUN_ROOT/logs/driver.log"
  sha256sum "$VRT_RUN_ROOT/logs/$stage.stdout.log" >> "$VRT_RUN_ROOT/logs/raw.sha256"
  test "${rc[0]}" -eq 0 || return "${rc[0]}"
  test "${rc[1]}" -eq 0 || return "${rc[1]}"
  test -s "$VRT_RUN_ROOT/logs/$stage.stdout.log" || return 3
}
vrt_stage env-prepare make -j1 vrt_common_env_prepare SKIP_WOLF_ENV_CHECK=1 VRT_ENV_ROOT="$VRT_RUN_ROOT" || exit $?
vrt_stage env-verify make -j1 vrt_common_env_verify SKIP_WOLF_ENV_CHECK=1 VRT_ENV_ROOT="$VRT_RUN_ROOT" || exit $?
test -s "$VRT_RUN_ROOT/env.sh" || exit 2
cat "$VRT_RUN_ROOT/env.sh" >> "$VRT_RUN_ROOT/logs/env-reviewed.log"
# ENGINEER 在此核查文件仅含已核定的 export/unset，无安装、探测或命令替换；通过后才执行下一行。
source "$VRT_RUN_ROOT/env.sh" || exit $?
unset SKIP_WOLF_ENV_CHECK
```

准备目标须创建隔离 venv、固定上述依赖和私有 wheel/cache，私有工具入口，设置 `JAVA_HOME`、`MILL_VERSION=0.12.15`、私有 `PATH`；verify 须记录版本、路径、hash、完整依赖、pip check、实际子 JVM/classpath 与写入路径。不得把 static `MILL_OUTPUT_DIR` 当证明。环境变量须隔离 `MILL_OUTPUT_DIR`、`MILL_FINAL_DOWNLOAD_FOLDER`、XDG cache/config/data、`COURSIER_CACHE`、Ivy、TMPDIR/TMP/TEMP、PIP_CACHE_DIR、Java user.home/java.io.tmpdir；不重设 HOME，并核查 JAVA_TOOL_OPTIONS/JDK_JAVA_OPTIONS/CLASSPATH/PYTHONPATH/PIP 配置注入。`XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR` 必须设置；硬编码 generated-src 生产/消费要经入口合法输出映射，先保留旧现场/指纹，不改测试 Scala。

环境安装单列计时；py_install 的 native 编译计入冷编译证据，不预热后声称冷编译。每个命令必须 tee 原始日志并捕获 `PIPESTATUS[0]`，记录 ISO 起止时间、非空 stdout/stderr、整数退出码；前一目标失败不得盲跑后一个。建议工程师用如下参数数组（Makefile 变量名以实际入口为准，缺失变量需记录而非伪造）：

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
```

执行顺序必须严格为（目标一现有 XS_WOLF_DEPS 包含 py_install；prepare/verify 不得提前安装 wolvrix 或触发 native 编译）：

```bash
VRT_COMPILE_START=$(date +%s.%N)
printf 'cold_compile_start=%s\n' "$VRT_COMPILE_START" >> "$VRT_RUN_ROOT/logs/driver.log"
vrt_stage target1 make -j1 xs_wolf_grhsim_ir "${VRT_ARGS[@]}" || exit $?
vrt_stage target2 make -j1 xs_wolf_grhsim_ir_build_emu "${VRT_ARGS[@]}" || exit $?
VRT_COMPILE_END=$(date +%s.%N)
printf 'cold_compile_end=%s\n' "$VRT_COMPILE_END" >> "$VRT_RUN_ROOT/logs/driver.log"
vrt_stage target3 taskset -c 2 make -j1 run_xs_wolf_grhsim_ir_emu "${VRT_ARGS[@]}"
VRT_FINAL_RC=$?
printf 'target_chain_exit=%s\n' "$VRT_FINAL_RC" >> "$VRT_RUN_ROOT/logs/driver.log"
exit "$VRT_FINAL_RC"
```

上述门禁保留 make 与 tee 的整数退出码，失败后退出本次命令链，但 ENGINEER 仍须完成失败取证和结果交付。CPU 2、governor powersave、sibling 18 和无额外研究负载须记录；不改变 governor、不改 CPU 挑成绩，资源不满足则等恢复。EMU_THREADS=0 及运行时线程树必须核实；保持原 GRH pipeline、two-state、seed=0、reset_cycles=50、Release/-O3、无 PGO/LTO、8 编译 jobs、phase timing 关闭。50k 是同一镜像的 50,000 仿真周期窗口，必须到 host/model cycle limit；每 1000 周期有序采样、NEMU difftest、终点 PC/trap/instruction/state 和退出状态均保留，无 mismatch/ABORT/BAD TRAP。运行报告区分 emu 进程启动至退出计时与 Make 外围计时，性能报告使用原始 Host time spent。

## 交付、验收与失败续接

工程必须交付 `step_2_result.md` 和本方向 ptmp 原始证据，列公共补丁 commit/patch hash、工具/wheel/输入及生成物 hash、完整命令/cwd/起止/退出码、CPU/线程、环境安装与冷编译分段时间、完整 50k 采样/终态/对拍，或未测范围与最早错误。F01–F08 及 F07 三次交错 A/B、median(candidate)<median(A)*0.99、波动≤1.05、编译<1800s 规则保持不变；本步单次成功也不是最终候选或排名。环境补丁经 RA 审查后由 PM 交 PI 冻结，冻结前 RA2/3 不得复制。

失败时保留所有目录、未跟踪/忽略产物、进程和原始日志；若仍 major69，记录实际 launcher/fork JVM/class 来源并在既定组合内修复；若转为下载、Scala、firtool、Python、native 或运行错误，下一步只处理该新阻塞。不得升级 JDK/Mill、清理旧现场、缩减 F01–F08 或把未测当证伪。若发现基线/输入/测量口径变化，立即交 PM/PI，所有受影响 A/B 必须重测。

本次规划时 RA1 仍余 5 次工程调用（本步 ENGINEER 成功返回后余4），最终仍缺、逐步审查、完整优化实现、至少三次 A/B、F01–F08 闭环和 PI 最终选择；不具备周末选优或集成条件。

## 待实现入口的固定接口和核验闭包

`vrt_common_env_prepare VRT_ENV_ROOT=<新根>` 与 `vrt_common_env_verify VRT_ENV_ROOT=<同根>` 是本任务选定的实现接口，仍未实现。本 RA 只读 `Makefile:29–40,389–392,544–585,682–732,1164–1208`、`env.sh`、XiangShan `build.mill:149,234` 和 difftest `FileControl.scala:25`，未调用 make 或 Mill。ENGINEER 必须先实现接口，再运行上文命令。新根已由 driver 原子创建且只含 logs，prepare 应接受这一状态，拒绝已存在 venv/tools/build 或外部指向，失败不覆盖。

prepare 的职责是经 Makefile 引导固定依赖安装、单文件 Mill 种子拷贝及 hash 核验；不得调用目标源码编译。verify 的职责是经 Makefile 记录 Python 四版本、pip check 和工具 hash，以 **XiangShan 源码 cwd + 私有 `mill-probe` 输出 + 固定 `-i --version`** 核实 Mill/JVM，随后写纯变量环境文件；probe 生成物不得作为完整目标的 `mill-target` 输出。不得直接从 shell 启动 Python/pip/Java/Mill 做工程验证。准备阶段可以生成内部 draft env，最终 env.sh 只有在 prepare 和 verify 都通过后才发布；只有此时设置 WOLF_ENV_SOURCED。Makefile 引导豁免只适用于这两个单独目标，不允许混合 bootstrap 与目标链来跳过检查。后续目标验证实际私有 env/root，而非仅凭伪造标志通过。`make py_install` 保持 `--no-build-isolation` 并在目标一依赖中完成；目标一 py_install 起止单独标记，计入上文整体冷编译。import wolvrix 的验证若需要，放在目标一包安装之后的 Makefile 合法入口，不能先编译预热。

环境文件中的路径映射固定如下；环境辅助脚本须以实际工具接受的方式传递并核验，变量名不被支持时不可声称隔离已通过：

|用途|相对 VRT_ENV_ROOT 的私有路径/约束|
|---|---|
|venv、wheel 下载和锁|venv、wheels、logs/wheels.lock；基础 `/usr/bin/python3.12`，不使用用户 site-packages|
|工具种子|tools/bin/mill 与 tools/mill/download/0.12.15；种子字节前后相同，76195001 bytes|
|PATH|JDK17/bin、tools/bin、venv/bin、LLVM22.1.2/bin、必要系统路径；拒绝隐含旧工具注入|
|Mill|MILL_VERSION=0.12.15；MILL_FINAL_DOWNLOAD_FOLDER=tools/mill/download；最终 MILL_OUTPUT_DIR=mill-target；探测单独 mill-probe|
|XDG|XDG_CACHE_HOME=cache/xdg、XDG_CONFIG_HOME=config/xdg、XDG_DATA_HOME=data/xdg|
|缓存|COURSIER_CACHE=cache/coursier、Ivy=cache/ivy、PIP_CACHE_DIR=cache/pip、CCACHE_DIR=cache/ccache 且 CCACHE_DISABLE=1|
|临时|TMPDIR/TMP/TEMP=tmp；java.io.tmpdir=tmp/java；java user.home=java-home；ivy.home=cache/ivy|
|源码编译|skbuild、build、wolvrix-build；不能回落 wolvrix/build/skbuild；实际 CMake/FetchContent/native 输出也须在此闭包|
|目标输出|xs/rtl、xs/filelist/xs_wolf.f、xs/generated-src、grhsim-ir/model、grhsim-ir/emu、logs|

JAVA_OPTS 采用核定 JDK 专用 `-Duser.home`、`-Djava.io.tmpdir`、`-Divy.home`，确认子 JVM 生效；若需要 JAVA_TOOL_OPTIONS 传递相同路径，由辅助入口明确设置并记录（不得沿用未知注入）。清除未核定 JDK_JAVA_OPTIONS/CLASSPATH/PYTHONPATH/PIP 注入，PIP_CONFIG_FILE 禁用用户配置（记录最终值且不输出凭证）；不重设 shell HOME。源码 `forkEnv` 只声明 PATH，这使子 JVM 的继承和写入路径成为**必须实证的风险点**，不能靠环境表推断。发现无法通过现有选项/入口 wrapper 隔离，保留错误交 PI，不改 build.mill。

对于硬编码输出，prepare 在无所属构建进程、无跟踪源码且核对原位置及内容 hash 后，通过入口辅助脚本把 `testcase/xiangshan/build/generated-src` 映射到 `$VRT_RUN_ROOT/xs/generated-src`；若原目录存在，完整保留到本 run 的 `preserved/` 并记录原位置/新位置，绝不删除。`XS_DIFFTEST_MACROS` 的硬编码消费者与 `XS_DIFFTEST_GEN_DIR` 必须实际解析到同一新目录。r_1/out 与 XiangShan/out 优先原位保留，通过 MILL_OUTPUT_DIR 定向新输出；如果工具不遵守，只有 PI §6.4 允许的入口映射可使用，先保留旧目录再建立新链接，不能直接覆盖。不得改 NOOP_HOME 的源码身份或把源码目录链接到其他方向。旧 .venv/build/xs 及日志完全保留且不复用。

verify 必须提供一份实际路径观察日志；后续三个目标运行期间由同一入口辅助脚本持续记录子进程（pid/ppid/启动时间/cmdline/exe/cwd、Java classpath/允许环境、`/proc/<pid>/fd` 和 maps 中工具库），结合目标前后目录清单/mtime/hash 和 Mill 任务日志证明写入位置。记录 Java 父/子执行文件均为 JDK17、缓存/classpath 均来自本 run（只读系统库例外），核外部旧 out/cache 是否新增写入；取证不可输出凭证。不能声称一次 `/proc` 快照足以覆盖全部写入：遗漏短命进程或路径不明即 F02 待补证，不排名。监测属于入口辅助脚本经 Makefile 编排执行，不并行启动其它研究任务。

运行时另记录 `/proc/<emu>/status` 的 Cpus_allowed_list、`task/*/status` 与进程树，保证仿真线程无并行加速。目标启动前后可用以下只读命令留证，活动期间的数据由上述辅助脚本采集；不凭 XS_EMU_THREADS=1 或 taskset 参数直接认定通过：

```bash
{
  date -Ins
  cat /sys/devices/system/cpu/cpu2/cpufreq/scaling_governor
  cat /sys/devices/system/cpu/cpu2/topology/thread_siblings_list
  cat /proc/loadavg /proc/meminfo
  ps -eLo pid,ppid,tid,psr,comm,args
  pgrep -a -x 'java|mill|emu|verilator|firtool'
  printf 'pgrep_exit=%s\n' "$?"
} > "$VRT_RUN_ROOT/logs/resources-before.log"
```

前后全量版本/输入/生成物清单至少包含递归仓库 HEAD/tree/父 gitlink、工具可执行文件和 JDK release/modules/libjvm/运行库、wheel URL/hash/解析锁、CoreMark/NEMU、RTL 每文件、filelist 原始顺序/路径归一化及 defines/read_args、flat GRH/GrhSIM IR/roundtrip/model/emu。例如源码输入及完成阶段产物通过下列只读命令落日志（不可用不存在的产物冒充成功）：

```bash
sha256sum testcase/xiangshan/ready-to-run/coremark-2-iteration.bin testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so Makefile scripts/wolvrix_xs_grhsim_ir.py > "$VRT_RUN_ROOT/logs/inputs.sha256"
find "$VRT_RUN_ROOT/xs" "$VRT_RUN_ROOT/grhsim-ir" -type f -print0 | sort -z | xargs -0 -r sha256sum > "$VRT_RUN_ROOT/logs/generated.sha256"
```

CoreMark 应为 `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`，NEMU 应为 `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`；不符即停止。完整 RTL 生成使用原 TLConfig、issue E.b、NUM_CORES=1、systemverilog、split-verilog、dump-fir、enable-difftest、原 firtool flags、JVM_XMX=40G/JVM_XSS=256m 与原 `-i`，不得删 GRH pass/改序或改前端输入绕过错误。包安装和下载时间单列；目标期间首次 Scala/native 编译不得从 F06 总时段中隐去。

## 完整输入位置、开工证据和审查门槛

绝对路径别名：`A=/home/gaoruihao/wksp/wolvrix-playground`，`J=A/vrt/grhsim-ir-st-opt`，`D=A/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1`，`R=D/r_1`，`E=D/evidence`，`Q=J/.runner/c9a4c84b9a384fd1967b6c0a21ad71aa`。ENGINEER 必须阅读 A/AGENTS.md、A/vrt/workflow/vrt-workflow.md、A/vrt/workflow/prompts/ra_plan_step.tmpl.md、A/vrt/workflow/prompts/race_contract.md；J/requirements.md、J/project.json；J/week_1/baseline.md 完整164仓库清单及§6、pi_plan.md 原RA1/F01–F08和v2文末、race.md文末；J/week_1/ra_1/steps/step_1_{task,result,review}.md。三个 v2 档案的输入提交为719fc9a655034dd104eda63218703e451f8e42bf。

回执只读 Q/state.json 与 Q/call-3f97cc898c5b4d49abd5153fdd92fdfb.log、Q/call-a834fa3e81c54d43a9c6610d1f85e2c4.log、Q/call-4545fbeac9b048c0a077cdcd77a1c82e.log。原始 L=R/ptmp/logs/w1-r1-s1-a-0567b6c-cba9c32 下五文件完整名称为 driver.log、target1.stdout.log、target1-rerun.stdout.log、target1-mill.stdout.log、xs_simverilog_w1-r1-s1-a-0567b6c-cba9c32.log。E/isolation-verified.tsv 与 E/pi-env-v2/{roots-before.log,recursive-before.tsv,gitlinks-check.log,fingerprints.log,out-processes.log} 均为输入，hash 已独立复核匹配 PI；不得修改或以旧记录替代自己开工核查。

本 RA 21:19:27 +08 开工只读证据在 **R/ptmp/ra-plan-step2-env-v2-20260908/**：roots-before.log、receipts-read.log、recursive-read.log、baseline-manifest-read.log。此次重新核了 RA1 的163个已检出仓库，HEAD/tree 与原 TSV 一致、162个已检出父gitlink匹配，openc910 是基线排除项；没有操作 RA2/3。读取 PI recursive-before.tsv 的489条记录均为 match，仅旧 r_1/out 状态多行；不能将此历史证据当作对另两方向本次实时复核。

|本次实际仓库|HEAD / tree|gitdir / common-dir / 分支 / 状态|
|---|---|---|
|A 档案主检出|开工719fc9a655034dd104eda63218703e451f8e42bf / d84c2f8b37639b68dc998e7b24bff5cea87aeabc|A/.git / A/.git；grh/grhsim-ir；开工clean；已有忽略 .venv/build/env.sh/ptmp/.runner 等原位保留|
|A/wolvrix|cba9c32240f3cd06c5b675968b56046e5b76f818 / 6bcc50560c2fb21f5e000cc521bec5a5e58d8483|A/.git/modules/wolvrix；同common-dir；grh/grhsim-ir；clean，已有忽略build/pycache|
|R|0567b6c7d0261ddd1834daffa8f15327c7f5810a / 8544a4528fac5f15fb59d57e6ef5622eccea2e99|A/.git/worktrees/r_1 / A/.git；vrt/grhsim-ir-st-opt/c9a4c84b/week_1/r_1；11个out未跟踪文件；忽略.venv/build/env.sh/ptmp|
|R/wolvrix|cba9c32240f3cd06c5b675968b56046e5b76f818 / 6bcc50560c2fb21f5e000cc521bec5a5e58d8483|A/.git/modules/wolvrix/worktrees/wolvrix / A/.git/modules/wolvrix；同R分支；clean|
|R/testcase/xiangshan|4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6 / bb4b5dc0ed12891829b69028b09e6352993c6d4d|自身.git / 自身.git；detached；源码clean，忽略out|
|R/testcase/xiangshan/ready-to-run|912f92121570bd28cabbefa7fa56d25b9784c304 / f922f0f8e37aef82e65248349daf2a59f35aa54c|自身.git；detached/clean|
|R/reference/gsim|a3ecb26aa0c18f55c7fbba20e7a9b9d14a25442a / 306ba84c102e41a03f5d0b0ec5521747ff668861|自身.git；detached/clean|
|R/reference/gsim/ready-to-run|9f476f8b72eb517cb70c1ad1aa92638c419d3034 / f6a3f94842b47d93c2a5e4b305f4c2eb383edfa3|自身.git；detached/clean|

以上入口→wolvrix/XiangShan/gsim 与 ready-to-run 父 gitlink 全匹配。Git object/common-dir 共享不授权可变cache/build共享；依赖为各方向私有检出、源码只读。pgrep 精确 java/mill/emu/verilator/firtool 无匹配（exit=1），/proc/1605023 不存在，CPU2=powersave、siblings=2,18。回执读取时 updated_at=2026-09-08T21:15:43.698027+08:00，pending 是本次 RA 规划 task，running 仅本次 RA；前一 PM 已 returned/0，PI 也 returned/0；无未知工程调用。RA1=1/6，余5，RA2/3=0/6；本动作不计费。ENGINEER 成功返回本步后应为 RA1=2/6、余4，以实际回执为准，不能预记成功。

|验收|本步需交付；最终缺口不得省略|
|---|---|
|F01|仅公共入口修复的精确diff，无技术优化、测试/冻结源码变动|
|F02|所有仓库开工/结束HEAD/tree/gitdir/common-dir/分支/status/父gitlink，含未跟踪与忽略产物；全可变路径实际隔离证据|
|F03|输入hash、真实Make完整链、RTL/filelist/IR/model/emu映射与指纹；失败阶段后产物明确不存在或未测|
|F04|50k所有采样/终态/NEMU对拍；现有CPU mapping/schedule/emit、GrhSIM IR及必要HDLBits回归仍为最终硬门槛，本blocker不能用局部回归替代目标|
|F05|原完整50k命令真实退出和单线程证据；失败不可记通过|
|F06|全新输出，整体冷编译起止及py_install native分段；<1800s，否则不合格；环境依赖准备单列|
|F07|本步至多单次环境修复A证据，无优化对照；最终各至少三次交错A/B及1%/5%资格不变|
|F08|结果路径 J/week_1/ra_1/steps/step_2_result.md、原始证据、工程公共提交及patch hash；RA独立审查待做，最终6/6及周报未齐|

工程师必须完成结果报告，即使上述 driver 失败退出。所有外部超时与中断单独记，不猜整数成功码；网络失败记URL/版本/hash/错误码。若核定组合仍失败且需要改公共规范，不自动换工具，交 PM 安排 PI 决定。公共补丁 RA 审查后才交 PI 冻结精确入口SHA、工具/wheel/锁及三方向采用关系；本次授权的环境实现和目标尝试无需先等冻结，但不能把证据宣称为已冻结可比成绩。任何公共起点/测量口径变更后，全部受影响 A/B 均须重测；后方向从共同多仓库起点应用 PI 核定补丁，不能接前方向优化，生成物独立重建。

每方向用满6次成功工程调用并完成逐次RA审查/周报，PI才可选至多一个F01–F08合格优胜者；PM再派Agent集成其精确多仓库候选及复验。无合格方向不集成，禁止拼接，保留所有方向现场。连续两步无目标推进、无阻塞缩小、无新独立证据必须改变策略，不可反复外围盘点；未完成不是证伪。本周远未结束。
