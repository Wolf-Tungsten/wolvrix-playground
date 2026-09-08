# Week 1 RA 1 Step 1 Task

结论：这是方向 1 的第 1/6 次工程调用，类型为完整目标基线尝试。工程师只从未修改的方向 1 基线执行 fresh GrhSIM IR 生成、build-only 编译计时和 Xiangshan CoreMark 50k 单线程运行，完成全部流程或停在最早真实阻塞；本步不实现优化、不运行局部替代测试。

VRT_PRIMARY_GOAL: 原始目标是降低 grhsim-ir 路线 Xiangshan CoreMark 50k 的单线程仿真时间（GSim 约 40 s 仅作参考）且 fresh 编译小于 30 分钟；方向 1 假设通用高频 op 与指针式 emitter fast path 可在不改 GRH IR/pass、Xiangshan/测试源码、不使用多线程和模块名特判的前提下，将最终 50k 中位时间较共同基线降低至少 1%；按 PI 固定验收 A01-A10 判定。
VRT_SUCCESS_CRITERIA: 本步只能证明共同基线流程可执行并取得一份基线编译/50k 证据或暴露最早阻塞，不能替代最终性能验收；三条目标命令退出码为 0、compile_elapsed_sec < 1800 且一次 50k 正确运行仅闭合本步的 A01、A04、A05、A06、A07、A09 部分证据，不能证明方向 1 假设或 A08 的 1% 改善。
VRT_TARGET_PATH: 从方向 1 根 worktree 的 fresh `make xs_wolf_grhsim_ir` 生成模型，到同一 `STEP_ROOT` 的 `make xs_wolf_grhsim_ir_build_emu` build-only 计时，再到 `make run_xs_wolf_grhsim_ir_emu` 在 CPU 2、单线程、50000 cycles 上运行；生成物、对象、emu、日志和缓存均按本任务路径隔离。
VRT_TASK_KIND: target
VRT_NEXT_TARGET: 若生成、编译和 50k 均完成且记录了退出码/正确性/CPU 证据，下一调用进入方向 1 第 2/6 次通用 profiling；若任一命令首次非零、超时、缺少 fresh 产物、difftest mismatch/abort/fatal、终点或 progress 不一致，下一调用仅针对该最早阻塞修复环境/入口或定位故障，然后在新的 `STEP_ROOT` 重跑同一完整三阶段目标，未闭合前不得转 profiling。

## 1. 固定输入与现场

- 项目档案：`/home/gaoruihao/wksp/wolvrix-playground/vrt/grhsim-ir-st-opt`；结果必须写入 `/home/gaoruihao/wksp/wolvrix-playground/vrt/grhsim-ir-st-opt/week_1/ra_1/steps/step_1_result.md`。
- 写入本任务前的主档案现场：`/home/gaoruihao/wksp/wolvrix-playground` 分支 `grh/grhsim-ir`，HEAD `aacf116febf77180beddb31d937f8f26a317082f`，tree `e79c6c03d6c3cb211bf1202467caa8d9c2169c2b`，`git status --porcelain=v2 --branch --untracked-files=all` 仅显示分支头且退出码 0；该档案仓库是唯一允许提交任务书的位置。
- 方向 1 根：`/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-ea895152/week_1/r_1`，分支 `vrt/grhsim-ir-st-opt/ea895152/week_1/r_1`，B0 HEAD `3a8558a1618e978c32fc8d3d70c26268879af41d`，tree `2d98c233ac99b19b22fb7cd5b2068cb5252f8642`，开工核查为干净。
- 方向 1 B5：`/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt/grhsim-ir-st-opt-ea895152/week_1/r_1/wolvrix`，分支 `vrt/grhsim-ir-st-opt/ea895152/week_1/r_1`，B5 HEAD `cba9c32240f3cd06c5b675968b56046e5b76f818`，tree `6bcc50560c2fb21f5e000cc521bec5a5e58d8483`，开工核查为干净。
- 根 HEAD 的 B5 gitlink 必须为 `cba9c32240f3cd06c5b675968b56046e5b76f818`；共同基线文件 SHA-256 为 `b70c5fdfa81c7f2ecae06cdb4d249fcdcf9f0d1abda9dbae9e645bf95dd22ca8`；递归 163 项 `path<TAB>HEAD` 清单 SHA-256 为 `38b1c6a8b242b0f876b879b8ae4947990f7af1bbd7c0225f4819c9d24672ced4`。
- 只读输入：RTL `/home/gaoruihao/wksp/wolvrix-playground/build/xs/rtl/rtl`（树 SHA-256 `ec1f3ec08a5ea5fc385b0a1782dad6a5445dd56765487c420501549ed06c6ad0`）；difftest generated-src `/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/build/generated-src`（树 SHA-256 `e0ffc561110cf8c38d6967d55389363601487c039016b9659c0909862dc1db95`）；workload `/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/ready-to-run/coremark-2-iteration.bin`（SHA-256 `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`）；NEMU `/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`（SHA-256 `094c1c4aacec1bc4af4da4fee9a07d92dd9726a23e0fadba163214a299207ff9e`）。只读输入不得重写。
- 共享环境入口 `/home/gaoruihao/wksp/wolvrix-playground/env.sh`（SHA-256 `af581b9382a0050caa3a1d2943966fd6a3bc6f01d59ffd54785ce6a4a9e85ed4`）；复用 `.venv` Python 3.12.3 和既有构建环境，不自行搭建环境，不使用其他方向或根旧 `build/xs/grhsim-ir` 的模型、对象或 emu。
- 主机/工具固定口径：`corvus02`、Ubuntu 24.04.4、kernel `7.0.0-28-generic`、AMD Ryzen 9 7950X3D、32 threads（CPU 2 的 SMT sibling 为 18）；Git 2.43.0、GNU Make 4.3、CMake 3.28.3、Clang/Clang++ 22.1.2、Verilator 5.051、ccache 4.9.1、glibc 2.39、numactl 2.0.18。编译允许 16 路，模拟只能使用 CPU 2 的一个 host 线程。

## 2. 待验证假设与判据

方向 1 的技术假设是：至少一种仅由 op kind、类型、位宽、alias 规则、拓扑/fanout 或活动依赖决定的通用 lowering/emit，可保持边沿和状态语义，同时使最终同口径 50k 中位时间较共同基线低至少 1%。本步不实现或评价该 fast path，仅建立未修改基线和最早阻塞位置。

- 证明方向 1 假设：后续 A01-A10 全部满足，特别是通用性、完整 fresh 生成、正确性、单线程和最终三次中位数至少 1% 改善。
- 证伪方向 1 假设：实现及等价性证据完整、最终三次同口径 50k 正确，但 A08 改善低于 1%。
- 本步命令失败、实现缺失、局部回归通过但未完成 50k、未测或使用旧产物，均为“目标未完成”，不是技术证伪。

## 3. 工程范围与禁止项

本次只做共同基线目标尝试，允许生成本步骤的模型、JSON、C++、对象、emu、日志和缓存；不得提交或修改源码。不得修改冻结的 GRH IR/pass（包括 `include/core/grh.hpp`、`lib/core/grh.cpp`、`include/core/transform.hpp`、`lib/core/transform.cpp`、`include/transform`、`lib/transform`）、B2/B3/B4 或 Xiangshan/测试源码，不得更新其 gitlink，不得 merge/cherry-pick/rebase/copy 方向 2/3 的任何源码或生成物，不得按模块/实例/层级名称匹配，不得以多线程仿真加速。

冻结对象指纹必须保持：`include/core/grh.hpp=856ebe2c48eaf12e7bb08e14a7a77884ff815a20`、`lib/core/grh.cpp=9dd6f1498ac2c05dc4741c729ce7a02ee3578fa0`、`include/core/transform.hpp=6f4278553999fa4acb950d1094795dd8d6d6d872`、`lib/core/transform.cpp=7566dd3d81f79a47c1f8de83ec451de4d8fdc71d`、`include/transform` tree `b5c4a1fe42bc68abdc74ee0268f1515ec1917a38`、`lib/transform` tree `b4f0937527c722a1eabb17068491257ca733a49a`。

本步不作技术优胜、证明或证伪结论；工程结果和原始日志由后续 RA review 独立核查。

可变目录只有方向 1 根的 `ptmp/week_1/step_1_baseline/`（含 `tmp`、`pip-cache`、`ccache`、日志和 STEP_ROOT build）以及该方向 B5 的 `build/`。禁止写项目 `.runner/`、其他方向目录、根旧构建目录或参考 GSim 产物。

## 4. 固定目标命令

在方向 1 根 worktree 启动 Bash；`RA_ID=1`、`STEP=step_1_baseline`、`RUN_TAG=step_1_baseline_run_1` 固定如下。每条命令的 stdout/stderr 必须保存到本步骤日志，并用 `PIPESTATUS[0]` 或等价方式记录实际 Make 退出码；命令按顺序执行，首个真实失败即停止并保留后续未执行状态。

```bash
source /home/gaoruihao/wksp/wolvrix-playground/env.sh
RA_ID=1
STEP=step_1_baseline
RUN_TAG=step_1_baseline_run_1
RA_ROOT="/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-ea895152/week_1/r_${RA_ID}"
STEP_ROOT="$RA_ROOT/ptmp/week_1/$STEP"
mkdir -p "$STEP_ROOT/tmp" "$STEP_ROOT/pip-cache" "$STEP_ROOT/ccache"
export TMPDIR="$STEP_ROOT/tmp"
export PIP_CACHE_DIR="$STEP_ROOT/pip-cache"
export CCACHE_DIR="$STEP_ROOT/ccache"

COMMON_MAKE_ARGS=(
  "ENV_FILE=/home/gaoruihao/wksp/wolvrix-playground/env.sh"
  "BUILD_DIR=$STEP_ROOT/build"
  "WOLVRIX_DIR=$RA_ROOT/wolvrix"
  "WOLVRIX_BUILD_DIR=$RA_ROOT/wolvrix/build"
  "XS_ROOT=$RA_ROOT/testcase/xiangshan"
  "XS_RTL_BUILD=/home/gaoruihao/wksp/wolvrix-playground/build/xs/rtl"
  "XS_DIFFTEST_GEN_DIR=/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/build/generated-src"
  "XS_GRHSIM_IR_BUILD=$STEP_ROOT/build/xs/grhsim-ir"
  "XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=$STEP_ROOT/build/xs/grhsim-ir/model"
  "XS_WOLF_GRHSIM_IR_REG_TO_MEM=1"
  "XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0"
  "XS_WOLF_GRHSIM_IR_KEEP_ORIGINS=0"
  "XS_NUM_CORES=1" "XS_EMU_THREADS=1" "XS_SIM_TOP=SimTop" "XS_RTL_SUFFIX=sv"
  "XS_SIM_MAX_CYCLE=50000" "XS_LOG_BEGIN=0" "XS_LOG_END=0"
  "XS_PROGRESS_EVERY_CYCLES=1000" "XS_RAM_TRACE=0"
  "XS_WAVEFORM=0" "XS_WAVEFORM_FULL=0" "XS_COMMIT_TRACE=0" "XS_ZERO_INIT=0"
  "XS_WITH_CHISELDB=0" "XS_WITH_CONSTANTIN=0"
  "WOLVRIX_GRHSIM_WAVEFORM=0" "WOLVRIX_GRHSIM_PERF=0" "WOLF_LOG=info"
  "CC=clang" "CXX=clang++" "VM_BUILD_JOBS=16"
)

make -C "$RA_ROOT" xs_wolf_grhsim_ir "${COMMON_MAKE_ARGS[@]}" RUN_ID="${RUN_TAG}_emit"
/usr/bin/time -f 'compile_elapsed_sec=%e max_rss_kb=%M exit=%x' \
  -o "$STEP_ROOT/compile.time" \
  make -C "$RA_ROOT" xs_wolf_grhsim_ir_build_emu "${COMMON_MAKE_ARGS[@]}" RUN_ID="${RUN_TAG}_compile"
make -C "$RA_ROOT" run_xs_wolf_grhsim_ir_emu "${COMMON_MAKE_ARGS[@]}" \
  "XS_EMU_PREFIX=taskset -c 2 stdbuf -oL -eL /usr/bin/time -p" RUN_ID="$RUN_TAG"
```

第一条入口依赖 `make py_install`；`emit.log` 必须显示安装来源是方向 1 的 B5 `WOLVRIX_DIR=$RA_ROOT/wolvrix`。若入口没有该依赖、来源不符或 fresh model/JSON 未生成，记录最早阻塞和退出码，不用旧产物补跑、不另建 Python/编译环境。

## 5. 开工/完工证据和交付

结果报告必须按 `primary_goal_contract.md` 写入 `step_1_result.md`，至少包含字段 `VRT_PRIMARY_PROGRESS`、`VRT_EVIDENCE`、`VRT_REMAINING_GAP`、`VRT_TARGET_RUN`（取值 `attempted`）、实际 `VRT_TARGET_COMMAND`、整数 `VRT_TARGET_EXIT` 和存在且非空的 `VRT_TARGET_LOG`。工程师需区分本步完成和原始目标完成，不得给出未经三次最终测量支持的性能结论。

开工及完工均记录以下信息，原始输出放在 `$STEP_ROOT`：

1. 根和 B5 的 `git rev-parse HEAD HEAD^{tree}`、`git branch --show-current`、`git status --porcelain=v2 --branch --untracked-files=all`；根 `git ls-tree HEAD wolvrix` 的 B5 gitlink；根及递归子仓库全部 modified/untracked 文件。
2. `git submodule status --recursive | wc -l`（必须为 `163`，退出码 0）；`git submodule foreach --recursive --quiet 'printf "%s\t%s\n" "$displaypath" "$(git rev-parse HEAD)"' | sha256sum`（必须为 `38b1c6a8b242b0f876b879b8ae4947990f7af1bbd7c0225f4819c9d24672ced4`，退出码 0）；`git submodule status --recursive | awk '$1 ~ /^[-+U]/ {print}'` 必须为空且退出码 0。
3. 主机/工具和单线程现场：`hostname`、`uname -a`、`lscpu`、工具版本；展开后的 `XS_NUM_CORES=1`、`XS_EMU_THREADS=1`、`taskset -c 2`，以及运行中可取得的 emu PID/CPU affinity/线程现场。不得在 CPU 2 或其 sibling CPU 18 并发编译或模拟。
4. 生成物来源、绝对路径和 SHA-256：model/JSON、build 目录文件树、emu、日志和缓存；来源必须是本次 B5 HEAD 及本次 `RUN_ID`，不能来自根旧 `build/xs/grhsim-ir` 或其他方向。只读输入的路径和 SHA-256 一并复核。
5. 三阶段完整命令、每条实际退出码；`compile.time` 必须含 `compile_elapsed_sec`、`max_rss_kb`、`exit`，build-only 退出码为 0 且 `compile_elapsed_sec < 1800`。run 原始日志必须包含 cycle/progress、seed、NEMU difftest、终点和 GNU `time -p` 的 `real`；本步只取得一个基线样本，不能与 A08 最终三次中位数混淆。
6. 正确性核查：run 退出码 0、到达 `XS_SIM_MAX_CYCLE=50000`、无 mismatch/abort/fatal；记录 `Guest cycle spent`、`cycleCnt`、`instrCnt`、终点 PC 和 50 条 progress（去除 `host_ms`/计时字段）。历史锚点为 `Guest cycle spent=50001`、`cycleCnt=49996`、`instrCnt=73580`、终点 `0x80001312`；不符即保留日志并报告阻塞，不得改口径。

不提交大型构建产物。若本次无源码变更，方向根/B5 不应产生候选 commit；若工具误写 tracked 文件，保留差异、列出文件和来源，停止技术判断并交 RA 复核，不得 reset/clean/覆盖。

## 6. A01-A10 状态与本步验收

以下状态为任务规划时的实际状态；“当前通过”仅表示基线/隔离核查，不表示目标优化通过。

| ID | 当前状态 | 本步必须取得的证据 / 缺口 |
| --- | --- | --- |
| A01 | 当前通过（方向 1 现场核查） | 开工/完工两层 HEAD/tree/branch/status、B0 B5 gitlink、163 项计数和清单哈希；任何漂移立即报告，不能纳入结果。 |
| A02 | 未测（当前无候选差异） | 完工 `git diff --name-status`、冻结 GRH IR/pass blob/tree、B2-B4/Xiangshan/test 源码及 gitlink 未变；本步不得改源码。 |
| A03 | 未测（当前无实现） | 本步无算法；确认没有模块名特判，后续实现必须仅按 op/type/width/topology/dependency/activity/cost。 |
| A04 | 未测 | fresh `xs_wolf_grhsim_ir` 退出码 0、emit 日志、model/JSON 绝对路径、来源 B5 HEAD 和 SHA-256；旧模型不得复用。 |
| A05 | 未测 | build-only `xs_wolf_grhsim_ir_build_emu` 退出码 0，`compile.time` 的 `compile_elapsed_sec < 1800`、max RSS、固定 `VM_BUILD_JOBS=16` 和 emu SHA-256。 |
| A06 | 未测 | 一次 `run_xs_wolf_grhsim_ir_emu` 原始日志、退出码 0、50000 cycle limit、无 NEMU mismatch/abort/fatal、终点/50 条 progress/seed；三次最终样本尚缺。 |
| A07 | 未测 | 展开命令、`XS_NUM_CORES=1`、`XS_EMU_THREADS=1`、CPU 2 affinity、PID/线程现场和主机指纹；禁止并发/多线程仿真。 |
| A08 | 未测且本步不判定 | 记录本步单个 GNU `real` 基线样本；最终需同一候选连续三次 run-only 中位数并较共同基线低至少 1%，本步不能宣称改善。 |
| A09 | 当前通过（隔离已核定） | 证明只读 RTL/generated-src/workload/NEMU 来源及 SHA-256；所有 model/object/emu/log/cache 位于方向路径，未使用根旧产物或其他方向产物。 |
| A10 | 未开始，RA 1 为 0/6 | 写入结果报告，列全部命令/退出码、modified/untracked、生成物来源/SHA 和剩余缺口；候选提交与 6 次调用仍待后续步骤。 |

## 7. 本步完成定义与剩余缺口

本步工程任务完成条件是：结果报告存在且字段完整；开工/完工 race 证据完整；三阶段命令已按顺序实际尝试至成功或最早真实阻塞；所有日志/临时产物在 `$RA_ROOT/ptmp/week_1/step_1_baseline/`，没有写 `.runner` 或其他方向。技术目标仍未完成，除非后续 2-6/6 调用实现并复核通用 fast path、冻结候选、完成 A01-A10，尤其是 A08 三次最终 50k 中位数至少改善 1%、A05 编译小于 1800 秒、A06 正确性和 A10 交付。

本步不得以静态扫描、局部测试、旧日志、预计耗时、GSim 参考时间或一次成功 run 替代完整目标；任何命令级失败均保留最早真实错误和下一调用的最小修复触发条件。
