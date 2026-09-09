# RA1 / D1：第 1 步完整目标工程任务

结论；实施 **grhsim-ir CPU 后端宽 slice 的调用方缓冲区写入与逐字变化检测**，在本次工程调用内执行完整 xiangshan coremark 50k 构建、正确性及性能流程，直到完成或暴露已尝试修复仍不能继续的最早实际阻塞。本任务不是勘察、基线统计或工具开发任务；RA 不代 PI 排名。

VRT_PRIMARY_GOAL: 优化 grhsim-ir 单线程 xiangshan SimTop coremark 50,000 周期；按最新用户计时修正要求，wolvrix 启动至完成 C++ 生成的 C_emit < 1800s，C++ 在 clang 中全量编译的 C_clang < 1800s，不含 XiangShan 生成 SV。按 PI A1–A8（A4 使用最新用户口径）提供正确性、同 CPU 单线程、基点/候选/gsim 各至少 3 次完整样本和可追溯证据。gsim 约 40s 仅为历史参照。
VRT_SUCCESS_CRITERIA: 本步实施 D1 候选并实际执行完整目标；完整通过须满足 A1–A7 的本步证据要求：候选正确、全部有效样本齐全、median(T_i) < median(T_b) 且 max(T_i) < min(T_b)、C_emit < 1800s 且 C_clang < 1800s、嵌套编译实际 -j16、无禁区改动。真实阻塞交付须有失败命令/退出码/原始日志、已尝试修复及下一验证入口；这只构成可审查的工程交付，不等于最终验收通过。A8 本步只能增加一次成功工程调用及其后续独立审查。
VRT_TARGET_PATH: 核对同技术基点和既有环境 → 构建并运行基点完整 50k → 实施宽 slice emit 候选 → 全量候选构建计时 → 候选完整 50k → 同条件 gsim 完整 50k → 补足三组各至少 3 次及独立语义证据；普通错误在本次调用内定位、修复并接续。不能在仅完成基点后主动结束。
VRT_TASK_KIND: target
VRT_NEXT_TARGET: 普通故障修复后立即重跑本书第 4 节相同参数的 xs_wolf_grhsim_ir_emu / run_xs_wolf_grhsim_ir_emu；参照缺失接 xs_gsim_emu / run_xs_gsim_emu。完整流程成功后由 RA 审查 step_1_result.md 并安排第 2 步独立复核或有证据的候选修订，不自行转 PI 总结。

## 1. 身份、输入与仓库责任

- 项目 `grhsim-ir-st-opt`，虚拟第 1 周，RA1，D1，step 1。规划执行编号 `grhsim-ir-st-opt-week-1-ra-1-step-1-plan`；工程 task_id 由 PM 固定并关联回执。本次 RA 调用不计费。R=3，每 RA 配额 6 次成功工程调用，当前 RA1/RA2/RA3 均 0/6，无已计费或未知技术调用，无历史步骤结果。
- 必读绝对目录 `/home/gaoruihao/wksp/wolvrix-playground/vrt/grhsim-ir-st-opt/` 下的 `requirements.md`、`project.json`、`week_1/pi_plan.md`、本任务书；同时读入口 `AGENTS.md`、`vrt/workflow/vrt-workflow.md`、`vrt/workflow/prompts/ra_plan_step.tmpl.md`。原始要求及 PI A1–A8 不因本书拆步而降低；本次运行中用户对 A4 的明确修正优先于旧 PI 文字，见下一段。RA 仅更新本任务书，交 PM/PI 同步共同口径，不自行修改 PI 规划或排名。

**最新用户计时修正（本次 inbox 已领取）。** 原文：“需求里的编译时间是指从wolvrix启动到cpp编译完成的时间，不含sv生成过程 / 从wolvrix启动到完成cpp生成<30min, cpp在clang中编译的时间<30min / 不要把xiangshan生成sv的过程纳入编译时间”。据此固定两个独立硬门槛：`C_emit` 从运行 wolvrix 的进程启动至全部目标 C++ 生成完成，包含加载/ingest、未改动的 GRH 流程、grhsim-ir 转换/优化及 emit；`C_clang` 从全量目标 C++ 编译启动至最终链接完成、产生可运行 emu，另列模型 TU、harness 和链接各阶段。两者各严格 <1800s；不再用旧“项目更新开始到 emu 的合并 C<1800s”门槛。同时报告从 wolvrix 启动到 clang 完成的总 wall time `C_total`、roundtrip/存储/阶段间开销，以及项目自身构建/安装的 `C_setup`、SV/FIRRTL 生成耗时（若发生），但后两者不纳入两个门槛。不把 emit 后 JSON 存储/roundtrip 混入 C++ 生成终点，不截去 emit 前处理；保留独立时间戳。该修正是用户更新，不是 RA 放宽验收；其他约束仍完整有效。
- RA 2026-09-09 开工复核：入口分支 `grh/grhsim-ir`，HEAD `f8de5725d4874f974ff50af548a95bc6fdd7ae8a`，工作区/索引干净；相对 `d4e802932c3e5f777963263c7db798ab398041eb` 仅 PI 三个项目档案。子模块 `wolvrix` 分支 `grh/grhsim-ir`，HEAD `b9931ed852532d161fea06d0ee0b5bbe07c43466`，工作区/索引干净，入口 gitlink 一致。本次 RA 只在入口现有分支显式暂存并提交本任务书，使用 `docs:`、项目名、week 1、RA1；不切分支、不修改代码/gitlink，不提交或手工改写 `.runner/`。
- 工程师后续在现有入口及 `wolvrix/` 两层分别创建 `vrt/grhsim-ir-st-opt/week_1/r_1`。入口从 PM 派发确认的、仅增加本项目档案的当时精确提交出发，技术树须与 `d4e8029` 一致；子模块从上述完整 `b9931ed...` 出发。先记录实际 SHA、分支、状态、两层差异，再操作。若分支已存在或现场偏离，区分任务残留/用户改动/其他方向产物，保留现场交 PM，不能 reset、clean 或盲目重做。
- 入口允许必要 Makefile 工作流支撑；技术实现优先限于 `wolvrix/lib/grhsim/backend/cpu_emit.cpp`，必要的公开接口/说明限于 grhsim-ir 后端及其文档。工程提交按两层责任分别显式暂存，记录精确实现提交及入口引用；gitlink 更新仅随 PM 工程派发明确责任执行，不在本次 RA 规划中操作。档案始终在固定项目目录，不随技术 cwd 迁移。
- 禁止修改冻结的 `wolvrix/include/core/` GRH IR、`wolvrix/lib/core/grh.cpp`、GRH transform/pass 及其流水线；禁止修改 xiangshan、difftest、既有测试源码/夹具和参考实现；禁止多线程仿真、特定模块名匹配或按测试数据写死结果。D1 不修改分区/调度算法，不实施 D3 图替换，不合并其他方向候选。
- 仅复用入口 `build/`、`wolvrix/build/` 和既有 `.venv/`、依赖、工具链；下述模型子目录只是既有环境内的产物隔离，不是新环境。各方向由 PM 串行占用环境；D2/D3 仍从相同技术基点开始，不能继承 D1 代码或生成物。`ptmp/98b594db-week-1-ra-1/`、其 worktree 和其他已列出的 worktree（包括 `/tmp/wolvrix-prev`）保持原状，不作为本项目实现、基点产物或性能证据。

## 2. 方法与等价边界

依据；现场源码 `cpu_emit.cpp:812` 的宽 `sliceStatic/sliceDynamic/sliceArray` 经 `expression()` 返回 `std::array`；`compute():1322` 随后生成 `cpu_value`、比较并赋值。该文件 `compute():1243` 起的宽 bitwise/shift/arithmetic 已采用指针输出及 changed 汇聚。此次不重复已存在的 bitwise 优化，也不把未测的 slice 覆盖率或临时拷贝成本当作实测收益。

动作；在 `compute()` 为受支持的二态宽 slice 生成直接写目标槽位的代码：

1. 对结果宽度 >64、源为宽二态 logic 的 `core.compute.sliceStatic`、`sliceDynamic`、`sliceArray`，按 op、类型、宽度及已证明的布局条件选择快速路径，不读取设计模块名称。保持 scalar 路径及未证明条件的原语义路径。
2. 无 fanout 的结果使用调用方提供的 local frame/boundary 目标缓冲区；有 fanout 时在计算每个输出 word 的同时与旧值比较、写入并 OR 得到 changed，接入当前 `changed` 分组或 `activate()`。保持现有激活集合、事件/提交顺序和状态读取快照；不能漏掉 unchanged→changed、changed→unchanged、同值重复写或仅最高有效位变化。
3. **先读 legacy**：`wolvrix/lib/emit/grhsim_runtime.cpp:652` 的 `grhsim_slice_words(src, srcWords, start, width, out, destWords)`、`:1512` 的旧返回值版本；并参照 `wolvrix/docs/emit/grhsim-xiangshan-width.md` 的宽值缓冲区说明。新 helper 置于 grhsim-ir emitter 生成的 runtime 范围，优先沿用 pointer + caller output、固定 frame/boundary、无堆分配的策略，不新增返回值 `std::array` helper，不在热路径制造大数组副本。legacy 源只读。
4. 明确 ABI 每个参数及存储单位：`src/srcWords` 是最低 word 在前的源缓冲区及 word 数；`start` 是 bit 偏移；`width` 是输出有效 bit 数；`out/destWords` 是调用方缓冲区及容量；changed 返回输出有效存储是否变化。例如 130-bit 源、start=63、width=65，要跨源 word 拼出两个输出 word，最高输出 word 仅保留 1 bit；越界源位补零。静态/动态/数组索引必须分别说明 bit 偏移计算。
5. 检查 `value()`、`readAliases_` 和 layout 生命周期，证明源/目的不重叠才直接写；不能把 legacy helper 的先清零当成支持别名的依据。若存在合法重叠，以局部必要缓冲和安全方向处理或拒绝快速路径，说明代价。对 start 越界、64-bit 移位、最后不足 64 bit、索引宽于机器字、`index * elementWidth` 溢出，保持已定义语义并验证；不能引入 UB 或用截断低位索引代替范围检查。若发现现有语义错误，先给反例，在 D1 内最小修复，不扩展冻结 IR。
6. 保存本目标实际命中 op/位宽/数量、代表性前后生成代码、未命中原因；诊断运行可采样确认执行覆盖，但正式计时关闭插桩。用生成代码/独立边界验证证明删除的搬运，最终用完整 T 判断是否有效。若目标不命中或无收益，不以静态代码更短宣称成功；将证据交 RA 调整方法。

## 3. 已核实环境与执行风险

| 现场事实（只读，尚非工程结果） | 工程动作及缺口 |
| --- | --- |
| 入口 `build/xs/rtl/rtl/SimTop.sv`、`SimTop.fir`、`build/xs/wolf/wolf_emit/xs_wolf.f`、`testcase/xiangshan/build/generated-src/difftest-extmodule.cpp` 存在；coremark 与 NEMU 参考库存在 | 对 filelist 全部输入、包含文件、宏、RTL/FIRRTL、generated-src、程序/参考库做 SHA256 清单并核实共同来源。文件存在不能证明版本；不能借历史候选产物补来源 |
| 默认 `build/xs/grhsim-ir/xiangshan_flat_grh.json` 不存在；该目录已有旧 IR JSON 和旧 emu | 本步基点/候选均从既有冻结 RTL 用原流水线重新 ingest/转换，`RESUME_FROM_FLAT_GRH_JSON=0`，耗时计入 C_emit；各自产生并比对 flat GRH 哈希。旧 IR/emu 保留，不作为样本 |
| `reference/gsim/build/gsim/gsim` 存在，但 `build/xs/gsim/` 不存在 | 核验参考工具版本/哈希，从既有 FIRRTL 生成本项目 gsim emu 并实跑；不能填写历史 40s 或借旧 worktree emu |
| `wolvrix/build/CMakeCache.txt` 是 Release、`/usr/bin/c++`；已有 `wolvrix/build/skbuild/` 是 Release、LLVM 22.1.2 clang/clang++、gmake；`pyproject.toml` 的 build-dir 是 `build/skbuild` | 本方向包构建和相关检查使用既有 `wolvrix/build/skbuild/`，不把不同编译器缓存混为一个。冻结实际 compiler/flags；模型与 gsim 均用核实的 LLVM clang++。不另建 CMake tree/venv |
| 当前 shell 未设置 `WOLF_ENV_SOURCED/VIRTUAL_ENV`；`env.sh` 会直接执行 venv/pip 初始化 | 不直接 source 该 bootstrap。只激活已有 `.venv/bin/activate`，确认目录存在并在 Makefile 内检查包/tool 路径；示例显式使用 `SKIP_WOLF_ENV_CHECK=1` 跳过该 bootstrap 检查。若需安装，只用 `make py_install`；缺环境入口先补 Makefile 目标，不能直接 python/pip 初始化 |
| `xs_wolf_grhsim_ir_emu` 已串接 `xs_wolf_grhsim_ir`（依赖 `py_install`）及 `xs_wolf_grhsim_ir_build_emu`；后者默认 VM_BUILD_JOBS=4；difftest/grhsim.mk 的模型构建另有 GRHSIM_MODEL_BUILD_JOBS | 同时传 `-j16`、`VM_BUILD_JOBS=16`、`XS_VM_BUILD_JOBS=16`、`GRHSIM_MODEL_BUILD_JOBS=16`，记录最终进程参数/MAKEFLAGS/jobserver。控制整个编译阶段总并发上限 16，避免外层 16 加内层独立 16 同时超配；必要时在入口目标先构建模型再构建 harness，两段都为 16，禁止改 difftest |
| `test_grhsim_cpu_emit/mapping` 顶层 recipe 写死 `-j2`；`test_cpu_emit.cpp` 内部还直接发出 make/verilator `-j2` | 顶层 -j16 不足。先在入口补第 4 节检查目标，IR/mapping 检查用真实 -j16。若运行完整既有 emit suite，必须从执行入口规范嵌套 make/Verilator 的 -j 参数并记录（可用本任务 ptmp 包装入口），不得改冻结测试源码或把实际 -j2 报成 -j16；无法合规执行的该项如实留缺口 |
| `args.h` 默认 seed=0、reset_cycles=50；emu 的 reset 循环与 cycles 计数分离，tick 在上限处检查；有 difftest 时取 guest cycles/trap cycleCnt 检查 | 保持 -C 50000，检查实际 Guest cycle、trap cycleCnt、退出原因和默认重置/种子。上限退出不要求 CoreMark 两迭代自然结束；若计数不等于约定，不能改周期参数蒙混通过 |
| `emu.cpp:520` 的 `[CYCLE_LIMIT]` 输出独立于 `EMU_PROGRESS_EVERY_CYCLES`，有 difftest 时每 10000 周期硬编码打印 | 明确的口径风险：先关闭所有可配进度/插桩，仍继续完整目标实跑；若实际保留该硬编码输出，保存原始输出，将样本标成诊断/待口径核定，不能声称严格满足 PI“周期进度关闭”或自行放宽 A3/A5。禁止修改测试源码、过滤后冒充从未输出或关掉 difftest。交 RA/PI 核定，其他技术验证继续；不是在静态检查阶段停止整个工程调用的理由 |

## 4. 实际 Makefile 入口与本次执行顺序

所有构建、测试、安装及 Python 实验脚本只能经项目 Makefile。不能在 shell 直接调用 cmake/ctest/python/pip/编译器/链接器；下面新增目标须由工程师先实现再调用，不能假称已有。只读 Git、哈希、进程和环境查询可直接执行。长命令使用后台或可轮询会话，单次等待 ≤60s，保留真实退出码，不能只返回 tee 的成功。

**固定参数。** 在入口运行，以下 Bash 数组仅组装 make 参数；CPU 2 当前位于允许集合 0–31，工程时重查并由 PM 保证同 CPU、无其他方向或构建负载。若 CPU 2 不可用，记录理由并为三组统一选择一个可用 CPU，不能组间切换。

```bash
TASK_ROOT=/home/gaoruihao/wksp/wolvrix-playground
TASK_LOG="$TASK_ROOT/ptmp/grhsim-ir-st-opt/week_1/ra_1/step_1"
TASK_BUILD="$TASK_ROOT/build/xs/grhsim-ir/vrt-grhsim-ir-st-opt-week1-ra1-step1"
TASK_GSIM="$TASK_ROOT/build/xs/gsim/vrt-grhsim-ir-st-opt-week1-ra1-step1"
TASK_CPU=2
TASK_LLVM=/home/gaoruihao/wksp/LLVM-22.1.2-Linux-X64/bin
mkdir -p "$TASK_LOG/tmp"
source "$TASK_ROOT/.venv/bin/activate"
export TMPDIR="$TASK_LOG/tmp" CCACHE_DISABLE=1 CMAKE_BUILD_PARALLEL_LEVEL=16
export EMU_RUNTIME_PROFILE=0 EMU_PHASE_TIMING=0
COMMON=(--no-print-directory -C "$TASK_ROOT" -j16
  VRT_BUILD_ROOT="$TASK_BUILD" VRT_GSIM_BUILD="$TASK_GSIM"
  VRT_LOG_DIR="$TASK_LOG" VRT_CPU="$TASK_CPU"
  SKIP_WOLF_ENV_CHECK=1 PYTHON="$TASK_ROOT/.venv/bin/python"
  WOLVRIX_BUILD_DIR="$TASK_ROOT/wolvrix/build/skbuild"
  CC="$TASK_LLVM/clang" CXX="$TASK_LLVM/clang++"
  PIP_CONFIG_SETTINGS='-Cbuild.tool-args=-j16'
  XS_NUM_CORES=1 XS_SIM_TOP=SimTop XS_ZERO_INIT=0 XS_SIM_DEFINES=DIFFTEST
  XS_EMU_THREADS=0 EMU_THREADS=0 XS_EMU_CPU="$TASK_CPU"
  VM_BUILD_JOBS=16 XS_VM_BUILD_JOBS=16 GRHSIM_MODEL_BUILD_JOBS=16
  GRHSIM_MODEL_CXXFLAGS='-std=c++20 -O3' EMU_OPTIMIZE=-O3
  NO_DIFF=0 DIFFTEST_PERFCNT=0 DIFFTEST_QUERY=0
  XS_WITH_CHISELDB=0 XS_WITH_CONSTANTIN=0
  XS_SIM_MAX_CYCLE=50000 XS_WAVEFORM=0 XS_WAVEFORM_FULL=0 XS_WAVEFORM_PATH=
  XS_COMMIT_TRACE=0 XS_RAM_TRACE=0 XS_PROGRESS_EVERY_CYCLES=0
  XS_LOG_BEGIN=0 XS_LOG_END=0 WOLVRIX_GRHSIM_WAVEFORM=0 WOLVRIX_GRHSIM_PERF=0
  GSIM_EMIT_RUNTIME_PROFILE=0 PGO_CFLAGS= PGO_LDFLAGS=
  XS_WOLF_GRHSIM_IR_REG_TO_MEM=1 XS_WOLF_GRHSIM_IR_KEEP_ORIGINS=0
  XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0
  XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=
  XS_LOG_DIR="$TASK_LOG/raw-xs")
```

其他影响仿真的 `EMU_*`、GRHSIM/GSIM profile、环境变量须读取、白名单冻结，避免继承历史实验开关。日志配置 seed=0/reset=50 须从实际二进制使用的 args 源和运行输出核对。`EMU_THREADS=0` 是 difftest 关闭 `EMU_THREAD` 编译宏的现场语义；不能仅依赖此设置推断单线程。

**工程师先补的最小 Makefile 支撑（不是独立辅助步骤）。** 依据是上述已查实的计时/全量重建入口缺失、嵌套 -j2 与环境 bootstrap，不发展通用框架：

| 待新增入口目标 | 必需合同 |
| --- | --- |
| `vrt_grhsim_ir_full_build VRT_VARIANT=baseline\|candidate VRT_LOG_DIR=...` | 在既有 build/skbuild 下先核验缓存编译器、包加载实际路径和冻结输入；列明保留的第三方缓存、作废的本方向对象。先经 py_install 生成当前候选工具，单列 C_setup；全量候选模型 C++/库/emu 必须新生成新编译，不能把已编译候选模型对象当公共缓存。目标内部顺序调用下列现有 xs 目标，单调时钟分别记录第 1 节的 C_emit、C_clang、C_total、roundtrip/存储和各子阶段，结束检查实际 emu。已有脚本 timed 日志仅有阶段耗时，不含精确进程边界，须以入口最小包装补齐启动及 emit 完成时间；禁止计入 SV 生成，不以各并行 TU 时间之和替代 wall time |
| `vrt_grhsim_ir_measure VRT_VARIANT=baseline\|candidate\|gsim VRT_SAMPLE=1 VRT_LOG_DIR=...` | 最小计时包装接到既有运行目标的 `XS_EMU_PREFIX`：同 CPU、同 stdbuf 缓冲；对子进程启动前/退出后读取单调时钟，保存原始 stdout/stderr、argv/cwd、开始/结束、rc、T，保留原始 emu rc 与 make rc。记录该 emu PID 的 `/proc/<pid>/task`、Threads、亲和性、CPU；包装进程不算仿真线程，EMU 内不得有并行执行线程。禁止把整个 make wall time或 Host time spent 当 T |
| `vrt_grhsim_ir_checks VRT_LOG_DIR=...` | 在既有 skbuild 内以 -j16 构建、经 CTest 执行既有 `grhsim-ir-tests`、`grhsim-cpu-mapping-tests`；另用本任务 ptmp 下不修改仓库测试源码的独立边界实验，核对实际生成 slice helper/代码与逐 bit 独立 oracle、已有 scalar 路径及激活边界。所有编译/运行都在该 Makefile 目标内，实验产物放 `wolvrix/build/artifacts/`，临时材料/日志放 TASK_LOG。不能复制被测实现作为 oracle；emit suite 的 -j2 问题按第 3 节处理 |

新增目标必须消费 COMMON 中的 `VRT_BUILD_ROOT/VRT_GSIM_BUILD/VRT_LOG_DIR/VRT_CPU`；baseline/candidate 对应 `VRT_BUILD_ROOT/<variant>` 和其 `model/`，gsim 对应 VRT_GSIM_BUILD，不能依赖未导出的 shell 变量或误选旧默认 emu。入口新增目标的源码/配方、真实展开命令和参数随结果归档；只写目标名称而没有实现、或只生成工具却未接回完整运行，不算完成。新增 helper 的边界实验属于候选正确性证据，不改 xiangshan 或既有测试目录。若上述动作可以用已验证现有等价目标完成，记录精确替代，不绕过 Makefile。

**完整构建/运行的现有核心命令。** `VRT_VARIANT` 包装必须调用这些实际存在的入口；阶段日志使用独立 RUN_ID，不覆盖失败尝试。下面以基点为例，候选将 baseline 全部换为 candidate；两者都保持 `RESUME=0`，生成目录首次必须为空（emitter 拒绝覆盖非空目录）。重试先保留证据，再通过带路径白名单的 Makefile 清理目标只清本次方向产物或改用同父目录新的 attempt 子目录；不能删除历史现场。

```bash
make "${COMMON[@]}" xs_wolf_grhsim_ir_emu \
  XS_GRHSIM_IR_BUILD="$TASK_BUILD/baseline" \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR="$TASK_BUILD/baseline/model" \
  RUN_ID=ra1-step1-baseline-build
make "${COMMON[@]}" run_xs_wolf_grhsim_ir_emu \
  XS_GRHSIM_IR_BUILD="$TASK_BUILD/baseline" \
  RUN_ID=ra1-step1-baseline-sample1
make "${COMMON[@]}" xs_gsim_emu \
  XS_GSIM_BUILD="$TASK_GSIM" GSIM_CXX="$TASK_LLVM/clang++" \
  RUN_ID=ra1-step1-gsim-build
make "${COMMON[@]}" run_xs_gsim_emu \
  XS_GSIM_BUILD="$TASK_GSIM" RUN_ID=ra1-step1-gsim-sample1
```

这些原始命令能接完整目标，但单独运行不自动获得合格 C_emit/C_clang/T；正式证据由新增包装目标提供。顶层 `xs_gsim_emu` 的管道需入口包装检查子 make 退出码/生成物，不能仅相信 tee；底层 `xs_gsim_rtl` 会调用既有 RTL Makefile，必须确认同内容 frozen RTL/生成物，若再生成则单列耗时及输入变化，**不纳入编译验收计时**，不修改测试源码。gsim 的生成/clang 编译也分段记录，以同输入/资源口径供比较，不假定 gsim 采用 wolvrix。

**本次执行动作（全部属于同一工程调用）。**

1. 本人读 inbox；核对两层 Git 和 PM 精确分支安排。记录既有进程/CPU、环境和输入指纹；完成上述最小 Makefile 支撑。只执行所需安装，不重新搭环境。
2. 子模块仍在 b9931ed 技术树时，经 `make "${COMMON[@]}" vrt_grhsim_ir_full_build VRT_VARIANT=baseline VRT_LOG_DIR="$TASK_LOG"` 构建本项目基点；通过 `vrt_grhsim_ir_measure` 实跑至少 3 次完整 50k。可先取一次完整样本后在候选完成时补另两次，以免外围准备替代实现；不能只测基点后结束。基点 emu/模型必须来自本次技术树，有产物哈希，不能使用 old emu。其基点源码和构建配置在候选后仍可追溯。
3. 实施第 2 节候选；执行 `make "${COMMON[@]}" vrt_grhsim_ir_checks VRT_LOG_DIR="$TASK_LOG"`。普通编译/语义问题自行定位修复；不能因单项失败就结束调用。检查之外必须继续完整目标；不能用局部通过替代完整检查。
4. 清晰标记候选精确源码/未提交 diff 哈希，作废先前候选模型对象，经 `make "${COMMON[@]}" vrt_grhsim_ir_full_build VRT_VARIANT=candidate VRT_LOG_DIR="$TASK_LOG"` 完整记录 C_emit/C_clang/C_total/C_setup，再 `vrt_grhsim_ir_measure VRT_VARIANT=candidate VRT_SAMPLE=1/2/3`（三次分别调用）实跑 50k。C_emit 或 C_clang 任一达到 1800s 已否定本候选 A4 主张，保留过程证据；资源允许则继续完成以获得 A1/A2 及确切时长，不预估超时而免执行。不能因两个阶段之和超过1800s判失败，也不能把全流程中 SV 生成时间算入门槛。
5. 从同源既有 FIRRTL 经上述 `xs_gsim_emu` 构建本项目参照，再 `vrt_grhsim_ir_measure VRT_VARIANT=gsim VRT_SAMPLE=1/2/3`。基点/候选/gsim 样本串行、相同 CPU、无同时编译；所有失败/无效样本保留原因和后续替代样本，不能挑最快值。
6. 若正式日志不足以证明基点/候选可观测等价，额外运行完整 50k 的 commit trace（`XS_COMMIT_TRACE=1 XS_LOG_END=-1`），经相同 Makefile 运行入口生成诊断日志，比较全部提交 PC/指令/状态及最终周期/退出原因；只规范化时间戳/地址等已证明无关字段，保存比较命令和原始差异。这些不计入 T。正确性仍以 difftest 开启且无失配为必要条件；trace 不代替 difftest。

## 5. A1–A8 证据与判定

| PI 项 | 本次必须交付的证据/判据 | 尚不能由本次规划宣称的结论 |
| --- | --- | --- |
| A1 完整目标 | 全 SimTop/单核、coremark-2-iteration.bin、`-C 50000`、seed/reset、Guest cycle 与 trap 终点、退出码和原因；确认 `STATE_LIMIT_EXCEEDED` 的合法上限结束，不能将早停/超时算完整样本 | 目前未执行完整仿真 |
| A2 正确性 | `NO_DIFF=0`、实际无 CONFIG_NO_DIFFTEST、动态加载指定 NEMU 的证据；每次完整输出无 mismatch/assert；可观测行为比较及独立 slice 边界/alias/changed 证据。边界含 start=0/1/63/64/末位/越界，65/127/128/129/130 等宽度、全零/全一/单 bit/交替位、相同输入重跑和局部/跨 partition fanout | 仅 rc=0、静态等价说明或小测试通过均不足 |
| A3 单线程收益 | emu 实际线程/亲和性/CPU 证据；所有完整 T，分别 min/median/max；收益要求 median(T_i)<median(T_b) 且 max(T_i)<min(T_b)。若 min(T_i)>=max(T_b)，报告本候选性能假设被证伪；区间重叠为收益未证实 | 无样本不作证伪；固定周期日志口径若未闭合，样本标待核定，不冒充合格排名数据 |
| A4 两段各 <1800s、-j16（用户更新） | 至少一次候选完整 C_emit、C_clang、C_total 及各阶段日志；C_setup/SV 生成单列并排除门槛。全部生成 TU 与实际编译对象清单、链接产物、对象新鲜度/哈希、CCACHE_DISABLE、实际 clang/参数和嵌套并发证据。公共 RTL/工具链/依赖排除项逐项声明；重新 ingest/转换全计入 C_emit | C_emit>=1800s 或 C_clang>=1800s 不通过；增量/no-op/旧候选对象、缺任一阶段或实际 -j16 未核实均不能通过。旧 PI 合并 C<1800s 由本次用户修正替代，交 PM/PI 同步 |
| A5 gsim 同口径参照 | 各至少 3 次基点/候选/gsim 完整有效样本、同条件和指纹；T_b/T_i、1−T_i/T_b、T_i/T_g；另述距历史约40s差距，不把40作为实测分母 | gsim 未生成/未完成或固定日志问题未核定，比较未闭合 |
| A6 禁区/隔离/环境 | 两层前后 SHA、分支/status、diff、gitlink、允许文件清单，输入/环境/产物哈希；无 GRH/pass、xiangshan/测试修改、无模块名匹配/多线程/方向污染；legacy ABI 与搬运策略审查 | 不能以性能收益抵消违规；旧目录存在不是来源证明 |
| A7 完整目标优先 | 本次实际完整流水线每个已到达阶段的 argv、cwd、rc、日志；所有操作经 Makefile；有阻塞则失败点、最小复现、尝试修复及重入命令；辅助工作与实际阻塞/回接结果一一对应 | 普通错误未调查、预计耗时免跑、仅统计或写工具不通过 |
| A8 配额/审查 | 交付 step_1_result.md、实现提交、日志索引与稳定 task_id；由 RA1 独立审查成 step_1_review.md，PM 按回执计费 | 当前 0/6；即使本步全部技术通过也未完成 A8。三 RA 各满6且逐步审查/周报齐备后才交 PI，至多选一个候选，不拼接 |

输入/环境 manifest 另须列：两层及相关依赖 SHA；filelist 展开后的全部输入哈希、include/define/初始化、生成 flat GRH 及两次一致性；CPU 型号/编号/SMT 同胞/频率策略、内存/OS、编译器版本与二进制哈希、Release/优化选项、Python/native package 实际加载位置、gsim 版本/flags；最终 IR/生成 C++/库/emu/NEMU/程序哈希。当前 CPU 是 AMD Ryzen 9 7950X3D、32 logical CPUs，正式运行重新记录。不要倾倒无关或敏感环境变量。

## 6. 输出、失败接续与独立审查

产出固定为：

- 工程报告 `/home/gaoruihao/wksp/wolvrix-playground/vrt/grhsim-ir-st-opt/week_1/ra_1/steps/step_1_result.md`；RA 后续本人核验源码和原始证据，再写同目录 `step_1_review.md`。本次规划不预写结果/审查。
- 原始记录根 `/home/gaoruihao/wksp/wolvrix-playground/ptmp/grhsim-ir-st-opt/week_1/ra_1/step_1/`：`manifest/`、`build/{baseline,candidate,gsim}/`、`run/{baseline,candidate,gsim}/`、`checks/`、`diagnostics/`、`failures/`、`raw-xs/`、`timings.tsv`、`commands.tsv`；每次 attempt/sample 单独命名，日志含 rc，报告链接实际文件。不提交大型日志/模型。
- 模型/emu/IR 置于第 4 节 TASK_BUILD、TASK_GSIM，沿用既有 build 环境；测试产物在 `wolvrix/build/artifacts/`；临时流程材料在 TASK_LOG，不能写 `/tmp`。

结论；工程师在本次调用内持续实现、测试、定位及修复普通错误，确实无法继续才交真实阻塞。每个失败记录“最早到达的目标阶段；具体错误/rc；原因证据；已尝试修复及各自结果；剩余条件；下一条 Makefile 命令”。

| 故障 | 本次接续动作 |
| --- | --- |
| 环境/包来源或版本偏离 | 查 cwd/实际加载包/缓存 compiler/Git diff，保留现场；普通包过期经 py_install 更新并单列 C_setup。属于他人技术改动/不明来源则交 PM 核查，不能清空现场或沿用不明产物 |
| emit/编译/链接失败、输出目录非空 | 保存失败日志与生成位置；定位首个真实诊断，修复 D1 或入口支撑；仅清理本方向已登记的候选产物，重新完整构建和计时。缺 unsupported op 时先给 op/type/参数/来源的最小证据，不按模块特判 |
| difftest/断言/边界失配 | 标记候选 A2 失败，保留首个失配、基点对照和复现；优先检查 start/宽度/alias/changed 激活，修复后先局部证据再回完整 50k。修改后旧 T/C 不代表新候选，重新全量计时与样本 |
| 超时/OOM/编译超限 | 保留运行时长、内存/进程、最后完成 TU/阶段、退出码和日志；不把预计时长当真实阻塞。尝试缩小 emitter 代码膨胀/临时缓冲（不是缩电路/周期或降 -j16），随后重入完整流程。明确是哪一段 C_emit/C_clang 超限；SV 生成及 C_setup 不计入门槛，资源条件无法继续如实交付 |
| 性能无收益/无命中 | 保存实际覆盖、全样本与正确性，不宣称方向无价值；本次若有明确原因可最小修订 D1 候选并重测，否则交 RA 改方法，不转去开发通用工具 |
| gsim 或固定进度日志口径未闭合 | 修复入口/配置并继续本方向实现和完整测试；真实受冻结源码约束的问题连同源码位置、实际日志交 RA/PI，待明确口径后接回同 CPU 的三组完整测量，不降低 A1–A8 |

后续任何 blocker/support 任务必须列已实证阻塞、不同结果如何改变下一动作和接回上述完整目标的条件；连续两步无目标推进、无阻塞缩小、无新增独立证据，由 RA 复核故障位置、改变方法并重写验证入口，不能原样继续外围工作。

结果报告使用“结论；依据/动作/缺口”，分别列 **本步实施与证据完成情况** 和 **最终 A1–A8 状态/缺口**，不要把工程调用成功当作技术通过。本周余下配额用于原方向的独立复核、边界/反例及有依据的修订，不仅重复写报告。

## 7. 持续 inbox 与交接

共享 inbox：`/home/gaoruihao/wksp/wolvrix-playground/vrt/grhsim-ir-st-opt/.runner/inbox.txt`；消费历史：同目录 `inbox-history.jsonl`。`VRT_INBOX`、`VRT_INBOX_ACTOR` 已设置，切换 cwd 后仍有效。所有角色/重试开工先执行并本人读取 history，再 consume；之后按实际时间最多每 3 分钟及提交/结束前重复两项，吸收其他 Agent 新消费记录：

```text
make --no-print-directory -C /home/gaoruihao/wksp/wolvrix-playground vrt_inbox VRT_INBOX_ACTION=history
make --no-print-directory -C /home/gaoruihao/wksp/wolvrix-playground vrt_inbox VRT_INBOX_ACTION=consume
```

长命令用后台/可轮询会话，单次等待 ≤60s，间隙查实际时钟和 inbox；后台代清空不算本人收到。非空内容是追加用户要求，立即简短确认内容及影响，不当 shell 执行；冲突具体说明，不扩大授权。消费只表示领取，仍有效要求、进展/缺口继续写报告和派发；不得自行截断 inbox、改写历史或执行器回执。若 PM 另行授权派生 Agent，完整传递本节、相同路径/命令；本次规划未派生 Agent。

当前有效追加要求：2026-09-09 22:02:15 +08:00 历史记录“编译的时候用16线程并行 -j16”，本书已落实为工程参数和嵌套验证要求，**尚无工程落实证据**；仿真仍单线程。本次另领取计时修正，全文及两个 <1800s 窗口见第 1 节，SV 生成明确排除；PM 须向后续工程师、其他方向及 PI 传递该最新口径。本次无性能/编译/正确性实测，无已计费工程任务。PM 下一轮只核查流程、档案提交和精确技术起点后派工程师；技术审查仍由 RA1 负责。

流程缺口；本次规划撰写初稿期间，22:12:36 至 22:18:44 +08:00 的本人轮询间隔超过 3 分钟；22:18:44 已本人领取上述计时修正、立即确认并更新全书。该间隔不能视作合规，后续撰写也须分段查钟/轮询，不仅在长工具命令期间检查。未丢弃消息或改写历史。
