# Week 1 PI 技术规划

## 总述

本周以冻结的 `baseline.md`（SHA-256 `b70c5fdfa81c7f2ecae06cdb4d249fcdcf9f0d1abda9dbae9e645bf95dd22ca8`）和 `race.md` 为唯一共同起点，赛马三个互不交换实现的方向。R=3，每方向固定 6 次工程调用，当前均为 0/6；不得提前停止。目标是保持行为等价和单线程约束，降低 GrhSIM IR 路线 Xiangshan CoreMark 50k 实测时间，同时完整编译小于 30 分钟。GSim 约 40 秒是差距参考，不代替本路线实测。

未运行新鲜完整目标是本 PI 动作的唯一目标证据缺口；三个方向的第 1 次工程调用必须从各自未修改共同基线实际执行完整生成、编译和 50k 流程，直至成功或留下最早真实阻塞。局部测试、静态统计、旧日志和“未测”均不能替代或证伪目标。

## 统一目标操作

对方向 `i`，`RA_ID` 必须设为已派发编号 1、2 或 3，`STEP` 设为本次固定编号如 `step_1_baseline`，`RUN_TAG` 设为唯一日志名。先复核 `race.md` 的 commit/status/163 项哈希；只复用共同 RTL 和 generated-src，禁止复用现有 GrhSIM IR 模型/对象/emu。下列操作是完整固定命令。最终复测在一个新的 `STEP_ROOT` 只执行一次 emit/build，再用第三条 run-only命令依次取 `RUN_TAG=final_run_1`、`RUN_TAG=final_run_2`、`RUN_TAG=final_run_3` 三个样本，不重复 emit。

```bash
source /home/gaoruihao/wksp/wolvrix-playground/env.sh
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

第一条入口依赖 `make py_install`，其日志必须显示从本方向 B5 安装。编译计时仅包围 build-only Makefile目标；退出码 0 且 `compile_elapsed_sec < 1800`。模拟固定 CPU 2且 `XS_EMU_THREADS=1`；编译可 16 路，性能测试期间不得并发编译、模拟或占用 CPU 2/18 的任务。最终测量以同一候选连续三次 run-only 的 GNU time `real` 中位数为主值；每次均保留原始日志、CPU/进程现场和 emu SHA-256。

## 方向 1：通用高频 op 与指针式 emitter fast path

目标：只在 GrhSIM dialect/GRH-to-GrhSIM lowering/CPU emitter/runtime 层引入通用 op 或专用 emit，减少宽值临时复制、重复掩码和无效 fanout 激活，不改变 GRH IR/pass。

理由：当前 CPU emitter 对宽位运算已有大量 pointer helper和 true-change路径；将剖析确认的高频通用形态映射为 caller-provided output buffer与原地安全 helper，有机会直接减少热路径指令和内存流量。

假设：至少一种由 op kind、类型、位宽、alias规则和 fanout决定的通用 lowering，可保持所有边沿/状态语义，并使最终 50k 中位时间较共同基线至少降低 1%。证明需通过 A01-A10；正确实现但最终收益不足 1% 才证伪。实现失败、局部回归或未完成 50k 只算未完成。

| 调用 | 工程动作、阻塞联系与回接 |
| --- | --- |
| 1/6 | 在未修改方向基线上执行完整统一目标操作并记录最早阻塞；成功则取得本方向共同基线编译时间和一次 50k 时间。不得用 emitter unit test替代。 |
| 2/6 | 若 1 阻塞，修复仅限本方向环境/入口并立即重试完整目标；否则用可关闭的通用计数/perf设施定位高频 op、临时复制和激活成本。输出按 op/type/width聚合，不得出现模块名规则；结论明确选择或否定一个 fast path，并回到目标命令。 |
| 3/6 | 实现最小 GrhSIM op/lowering/emitter/helper及 differential fixtures；宽值 helper遵循 legacy pointer/out-buffer、alias和数据移动策略。运行 `make test_grhsim_cpu_emit`、`make test_grhsim_cpu_mapping` 后提交 B5 候选。 |
| 4/6 | 从新步骤目录重新 emit/build/run完整 50k；核对 progress/终点、编译 <1800 s和初步时间。失败时定位第一个 mismatch、compile TU或 runtime热点，不能扩大到冻结范围。 |
| 5/6 | 根据 4 的唯一实证阻塞修正或回退无益子方案；补边界/ASan类 fixture并再次执行完整目标。辅助测试完成后同一调用必须回接 50k，除非留下更早命令级阻塞。 |
| 6/6 | 冻结精确 B5/root候选，独立复核 clean status/diff；新目录 fresh emit、fresh build计时，连续三次单线程 50k。提交候选及结果，报告中位时间、相对基线、距 40 s、编译时间和全部缺口。 |

预期产出：通用 op/emit候选及测试、op级剖析、生成 C++ shape对比、候选 commit、fresh compile记录、三次 50k原始日志和方向周报。

## 方向 2：活动度感知的分区与调度成本模型

目标：仅调整 GrhSIM CPU BackendMapping 的 node/supernode/active-word/function packing和 schedule顺序，减少跨分区值传播、函数调度、指令缓存压力和无效活动扫描；不改语义 op。

理由：现实现以静态 op/estimated-line上限和固定合并目标为主。通用的 crossing-value、fanout、估算代码行、活动频次和 locality成本可能生成更适合单线程 host CPU的布局，同时控制编译体积。

假设：一个不依赖模块名的确定性 cost model能保持 mapping verifier与 JSON roundtrip稳定，使 fresh编译 <30分钟并让 50k中位时间较共同基线至少降低 1%。满足 A01-A10为证明；正确且参数搜索覆盖预定小集合后仍不足 1%为证伪。编译爆炸或未测为未完成。

| 调用 | 工程动作、阻塞联系与回接 |
| --- | --- |
| 1/6 | 在未修改方向基线上执行完整统一目标操作；记录 partition统计、编译时间和一次 50k，或最早真实阻塞。 |
| 2/6 | 若阻塞先修复并重试；否则从 baseline mapping/生成 C++提取 crossing values、fanout、函数/TU size与活动统计，定义至多三个预注册参数点。统计只用于选择成本项，结果必须导向完整目标参数 A/B。 |
| 3/6 | 实现确定性通用 cost model与 verifier/tests，运行 `make test_grhsim_cpu_schedule`、`make test_grhsim_cpu_mapping`；禁止把 Xiangshan模块名或一次 profile地址写入算法，提交 B5候选。 |
| 4/6 | 依次对预定参数点 fresh emit/build和完整 50k；任一点不正确立即停止该点并保留最早 mismatch。以正确性、<1800 s和时间选择一个方向内候选，不从其他方向取代码。 |
| 5/6 | 修复选定点的 schedule/verifier/compile-size或 runtime瓶颈，补循环、边沿、跨状态、多写口和确定性回归；随后重跑完整目标，不以结构统计收尾。 |
| 6/6 | 冻结精确候选，fresh build计时并连续三次单线程 50k；提交候选及报告，列 mapping参数、结构指标、编译时间、中位时间、基线/40 s差距与缺口。 |

预期产出：通用成本公式与参数边界、mapping/schedule回归、稳定 JSON证据、各预定点 build/50k日志、精确候选 commit和方向周报。

## 方向 3：GrhSIM 内行为等价子图替换

目标：在 GRH 已转换为 GrhSIM 后，以通用结构、类型、位宽、读写/事件依赖证明识别子图，替换为更低开销的 GrhSIM语义或 publication路径；优先状态读-切片-掩码-写、重复地址计算、unchanged-state/history扫描，不修改 GRH pass。

理由：B5 已有 `grhsim.reg-to-mem` SemanticTransform和完整 event/history模型。对可证明等价的重复子图做 GrhSIM层融合，可减少 compute op、状态流量和激活边，同时与方向 1 的单 op ABI、方向 2 的分区布局保持独立。

假设：至少一种不依赖名称、带严格 alias/enable/mask/event前置条件的子图替换能在 differential、HDLBits/CPU回归和完整 difftest中等价，并使最终 50k中位时间较共同基线至少降低 1%。满足 A01-A10为证明；已实现且等价、覆盖目标动态形态但收益不足 1%为证伪。覆盖不足、mismatch或未测为未完成。

| 调用 | 工程动作、阻塞联系与回接 |
| --- | --- |
| 1/6 | 在未修改方向基线上执行完整统一目标操作；记录 transform命中统计、编译时间和一次 50k，或最早真实阻塞。 |
| 2/6 | 若阻塞先修复并重试；否则以 analysis-only通用报告确认动态相关候选形态、等价前置条件和拒绝原因。报告结果必须选出一个替换或证明本方向当前无覆盖，并在后续回接完整目标。 |
| 3/6 | 实现一个最小 GrhSIM SemanticTransform/融合 op及正反例，覆盖 alias、mask、enable、边沿/history、多写口和宽值；运行 `make test_grhsim_reg_to_mem`、`make test_grhsim_cpu_mapping`，提交 B5候选。 |
| 4/6 | fresh emit/build/run完整 50k并审计命中数、IR roundtrip、终点和时间；mismatch从首个 progress差异和最小 fixture定位，不能通过放宽正确性规避。 |
| 5/6 | 修复等价条件或删除无效替换，运行 `make test_grhsim_reg_to_mem_generated`及相关 CPU测试；随后再次执行完整目标，或保留最早命令级阻塞。 |
| 6/6 | 冻结精确候选，fresh build计时及连续三次单线程 50k；提交候选和报告，列命中/拒绝统计、中位时间、基线/40 s差距、编译时间及未覆盖语义。 |

预期产出：等价条件文档、analysis命中报告、GrhSIM transform/op与 differential fixtures、roundtrip证据、精确候选 commit、fresh compile和三次 50k日志。

## 固定最终验收表

RA只能拆解实施，不能删除、改号、降级或改写下列验收。

| ID | 原始要求 / 操作 | 通过判据 | 证伪或排除判据 | 必需证据 |
| --- | --- | --- | --- | --- |
| A01 | 同一多仓库基线 | B0-B5和163项哈希匹配 `baseline.md`，方向只续接自身提交 | 任一 gitlink/输入偏移或混入其他方向即排除排名 | 开工/完工 HEAD/tree/status、递归哈希、diff |
| A02 | 禁止范围 | 冻结 GRH IR/pass blobs/trees、B2-B4及测试源码不变 | 任一禁止路径变化即排除；不得靠回退后隐藏证据 | `git diff --name-status`、父 gitlink、候选提交 |
| A03 | 通用性 | 匹配仅基于 op/type/width/topology/dependency/activity/cost | 模块、实例、层级名称特判即排除 | 源码审查、正反例说明 |
| A04 | 完整生成 | 统一 `make xs_wolf_grhsim_ir` 退出码 0，fresh model来自候选 | 局部生成、旧 JSON/模型或无日志不通过 | 命令、Make日志、model/JSON SHA-256、来源 commit |
| A05 | 编译 <30 min | 统一 build-only Make目标退出码0，fresh `compile_elapsed_sec <1800` | 超时、增量旧对象、无计时均不通过 | `compile.time`、build日志、emu SHA-256、固定 jobs=16 |
| A06 | 完整正确性 | 每次 50k退出码0、cycle limit=50000、NEMU无 mismatch/abort/fatal，终点/50条 progress与共同基线一致 | 任一 run不一致即不通过；局部测试不能替代 | 三次原始 run日志、规范化 diff、计数/PC/seed |
| A07 | 单线程 | `XS_NUM_CORES=1`、`XS_EMU_THREADS=1`、taskset CPU2，禁止多线程加速 | 使用多个 host CPU、并发模拟或污染 CPU2/18即重测 | 展开命令、taskset/进程现场、主机指纹 |
| A08 | 性能优化与报告 | 最终候选三次 `real`中位数比共同基线中位数至少低1%；报告绝对秒数、cycles/s、加速比和距40 s差距 | 不足1%为该假设证伪；未测/旧日志为未完成 | 三次 GNU time、原始日志、计算表 |
| A09 | 构建环境复用与隔离 | 只读复用两项共同输入；模型/对象/log/cache全在方向路径 | 使用根旧 GrhSIM产物或其他方向产物即排除 | 路径、输入/输出 SHA-256、污染检查 |
| A10 | 交付完整 | 每方向用满6次，B5/root候选已提交，方向周报对 A01-A09逐项结论 | 少调用、未提交、缺命令/退出码/缺口即不参加选优 | 6组 task/result/review、report、commit |

“证伪”只用于实现与等价性证据完整但 A08不成立的技术假设；环境失败、实现失败或未完成实验均报告“目标未完成”。

## 可比排名规则

1. 只比较 A01-A07、A09-A10全部通过且 A08达到至少 1%改善的候选；否则无优胜方向。40 s为明确报告的参考目标，不因未达到40 s自动抹去真实改善。
2. 共同基线时间 `T_base` 取三个方向第1次调用中所有成功、未修改基线的单线程50k `real`中位数；目标至少取得3个样本。样本不足时，各受影响方向须在第6次调用前补足同口径基线，否则不排名。
3. 候选主指标 `T_candidate` 为同一 host、CPU2、workload/参数、无并发条件下连续3次 `real`中位数，越小越优。相差超过1%时按中位数排序。
4. 候选中位数差不超过1%视为性能并列；依次以更小 fresh compile elapsed、更小3次最大 runtime决胜。仍相同则 PI选择代码差异更小、通用测试覆盖更完整者并写明依据。
5. 周末至多选一个精确候选，不拼接方向。集成后候选 tree或目标引用变化必须重跑 A04-A09；无合格者保持技术集成代码不变。

## 本动作证据与剩余缺口

| 动作 | 结果 | 退出码 |
| --- | --- | ---: |
| 读取 workflow、race contract、PI template、requirements | 完成；无历史 week 报告 | 0 |
| 核对 B0-B5 commit/tree/gitlink/status、163项依赖、输入/工具 | 完成；详见 `baseline.md` | 0 |
| 新建3个 B0 worktree与3个 B5 worktree | 均从共同 commit建立 | 0 |
| 首次递归 clone命令 | `d` 未定义，首项前停止，无残留依赖 clone | 1 |
| 修正后的3组递归 shared clone/checkout | 均完成 | 0 |
| 三方向 `submodule init`、commit/status/hash复核 | 163/163、干净且一致 | 0 |

剩余缺口：未执行本周新鲜完整生成、fresh编译计时、CoreMark 50k或 GSim参考复测；这是 PI规划动作与工程配额边界，最小接续任务就是分别派发方向1/2/3的第1次 ENGINEER调用，在各自 `race.md`路径执行统一目标操作并提交最早阻塞或完整基线证据。
