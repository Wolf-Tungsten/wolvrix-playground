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

唯一允许 Java 为 `/usr/lib/jvm/java-17-openjdk-amd64`，release SHA256 `b8d3277e4f728d8ed638ec8eae2b66c7d10d7b8424985dfb4e5feb688aea66d2`，java SHA256 `4976918b29ece3fe634bdbcf1377676e42af429b5311ba234f6f95039117d4d4`，modules SHA256 `499337b57cd61a672db7e1b35a3946bfb99508187367dc886c2bcbf28c65bf3a`。Mill bootstrap `/home/gaoruihao/wksp/mill` SHA256 `af73fadc1fa005e43962bcd529690f448592f4e0786a90b712ac6509378a9eb2`；核定 distribution `/home/gaoruihao/.cache/mill/download/0.12.15` SHA256 `ea1bba01e220f4ce20bb333247d254a2bf9b86554c10c3d7d7e16641ec0a76d8`，可从该单文件取种但不得复制整个用户 cache。Java25/Mill1.1.6/Azul21 仅为失败或误探测历史，排除下一目标口径。

基础解释器 `/usr/bin/python3.12`（3.12.3，SHA256 `1643dacd9feaedc58f3cc581e4d22577dfe25c09b10282936186ccf0f2e61118`）；固定 pip 24.0、scikit-build-core 1.0.3、packaging 26.3、pathspec 1.1.1。四项 METADATA SHA256 依次为 `90d11f277fd5868da679ee257c97656dde511c8aac7d025231407e6ce90839e2`、`bfd7fef484ff85c723956d256c4f906695879428b4069707e7e101aa5c460fe0`、`70fdb89fc4d4a9a043bf7372b8972bcc883fddff34ab55e9cf80d73875384763`、`68de3f158b6592f086e78754c962092f32a761944ab66a660c0d62ad79c4b69b`。wheel URL/hash、完整传递依赖锁、pip check、JDK libjvm/运行库指纹及兼容性均待工程补齐；任何版本变化交 PI，核定允许不等于已验证。安装仍必须通过 `make py_install`，不能直接 Python/pip/cmake/ctest/compiler。

固定输入及证据：requirements/project.json；baseline.md §6、pi_plan.md v2 交接、race.md v2、step_1_task/result/review；ENGINEER/RA/PI 回执三文件；原始日志目录 `/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1/ptmp/logs/w1-r1-s1-a-0567b6c-cba9c32/`（五文件，target1-mill SHA256 `7ba0a4f44c8c721d2ee6c019d7f8647f1ae392d9e1d8942fc06f695ce410df6e`）；隔离 TSV SHA256 `6149d82c9e892b1fe92ce0682b5f37cabf5500c51fcbd4f35037d90044a343db`；只读 v2 证据目录 `.../evidence/pi-env-v2/{roots-before.log,recursive-before.tsv,gitlinks-check.log,fingerprints.log,out-processes.log}`。

## ENGINEER 可执行命令（一次调用，缺入口先实现）

以下命令是给工程师的完整执行脚本骨架；不表示目标已存在或已执行。所有输出放本方向 ptmp，目录冲突时保留旧目录并换新的唯一 run id，绝不覆盖：

```bash
cd /home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1
VRT_RUN=w1-r1-s2-a-0567b6c-cba9c32-v2-01
VRT_RUN_ROOT="$PWD/ptmp/B1-c9a4c84b-v2/0567b6c-cba9c32/$VRT_RUN"
# 先仅在本入口 Makefile/必要辅助脚本实现以下两个当前不存在的目标；保留公共修复独立提交和 patch hash
make -j1 vrt_common_env_prepare SKIP_WOLF_ENV_CHECK=1 VRT_ENV_ROOT="$VRT_RUN_ROOT"
make -j1 vrt_common_env_verify SKIP_WOLF_ENV_CHECK=1 VRT_ENV_ROOT="$VRT_RUN_ROOT"
source "$VRT_RUN_ROOT/env.sh"  # 仅加载上述成功目标生成的无安装副作用文件，绝不 source 旧 env.sh
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

执行顺序必须严格为：

```bash
make -j1 xs_wolf_grhsim_ir "${VRT_ARGS[@]}"
rc=${PIPESTATUS[0]}; test "$rc" -eq 0 || exit "$rc"
make -j1 xs_wolf_grhsim_ir_build_emu "${VRT_ARGS[@]}"
rc=${PIPESTATUS[0]}; test "$rc" -eq 0 || exit "$rc"
taskset -c 2 make -j1 run_xs_wolf_grhsim_ir_emu "${VRT_ARGS[@]}"
rc=${PIPESTATUS[0]}; exit "$rc"
```

实际脚本须将每条命令通过 `tee "$VRT_RUN_ROOT/logs/<stage>.stdout.log"` 包裹并在独立 driver.log 写入 `PIPESTATUS`、起止时间；上面仅表达目标与退出码门禁。CPU 2、governor powersave、sibling 18 和无额外负载须记录，EMU_THREADS=0 及运行时线程树必须核实；保持原 GRH pipeline、two-state、seed=0、reset_cycles=50、Release/-O3、无 PGO/LTO、8 编译 jobs。

## 交付、验收与失败续接

工程必须交付 `step_2_result.md` 和本方向 ptmp 原始证据，列公共补丁 commit/patch hash、工具/wheel/输入及生成物 hash、完整命令/cwd/起止/退出码、CPU/线程、环境安装与冷编译分段时间、完整 50k 采样/终态/对拍，或未测范围与最早错误。F01–F08 及 F07 三次交错 A/B、median(candidate)<median(A)*0.99、波动≤1.05、编译<1800s 规则保持不变；本步单次成功也不是最终候选或排名。环境补丁经 RA 审查后由 PM 交 PI 冻结，冻结前 RA2/3 不得复制。

失败时保留所有目录、未跟踪/忽略产物、进程和原始日志；若仍 major69，记录实际 launcher/fork JVM/class 来源并在既定组合内修复；若转为下载、Scala、firtool、Python、native 或运行错误，下一步只处理该新阻塞。不得升级 JDK/Mill、清理旧现场、缩减 F01–F08 或把未测当证伪。若发现基线/输入/测量口径变化，立即交 PM/PI，所有受影响 A/B 必须重测。

本步完成后仍缺 RA1 剩余 5 次工程调用、逐步审查、完整优化实现、至少三次 A/B、F01–F08 闭环和 PI 最终选择；不具备周末选优或集成条件。
