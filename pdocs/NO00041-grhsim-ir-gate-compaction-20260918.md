# NO00041：event-gated 端点门控链致密化（合并同条件门 + 提升共享事件守卫 + 冷体下沉提示）

日期：2026-09-18。最终判定：**ACCEPTED（+10.849160%，页帧驱逐协议下 6 次交替秩次判据通过）**。

本节点针对 NO00040 诊断定位的最热结构残余——event-gated system/DPI 端点
task 族（44xx）的门控链取指/分支成本——在 CPU 发射层做纯结构变换：
相邻同条件门合并、共享 cevent 守卫提升、常量门体冷下沉提示。
冻结 GRH、GRH pass、XiangShan 与测试源码不修改。

## IDEA（2026-09-18）

### 瓶颈证据

- NO00040 compute 诊断（`ptmp/no00041_commit_history_20260918/compute_diag/`）：
  **44xx assert/DPI 端点族**（task 4413–4453 中 41 个进入 top-400）合计
  **13.30% 总样本 / 19.66% compute**，top-20 热点 task 全部被该族占据。
- 该族每 task 机器码 93–200 KB（task_4415 = 141,265 B、task_4444 =
  200,002 B），但单次激活的热路径只是 ~400–500 个门检查——assert 通过、
  fwrite 不写，门体几乎从不执行。
- 反汇编（NO00040 正式二进制，task_4415 @0x43ad770）证实 Clang -O3 把门体
  **inline 在门链中**：`cmp;jne +0x4db`（跳过 ~1.2 KB 体到下一门）。不触发
  时每次激活执行 ~450 个 taken 前跳、跨 ~141 KB 取址；按族份额与激活频率
  （~2 eval × 50% 静默通过率）折算每次激活 ~10–20 k 周期，取指重定向与
  BTB/uop-cache 压力是族成本大头，而非门 ALU（~2.3 k 指令）。
- 源级普查（本节点，NO00040 flow-densify-final model）：4413–4453 族 30 个
  task 合计 15,500+ 个 `if(cevent && pred)` 门；task_4415 单 task 500 门 /
  仅 222 个相异条件 / **276 对相邻同条件**（assert 的 `xs_assert_v2` 与
  `fwrite` 成对同门；task 4427/4428/4429 为 384 门 / 96 相异 / 288 对）；
  门体 **90%+ 常量-only**（仅引用字面量与 `staticScalars_`/`staticStrings_`
  常量，无 `cpu_at`/`cpu_cached` 运行时引用）；全部以同一 `cpu_cevent_*`
  局部量为前件。
- 对照 gsim（NO00039 普查）：断言谓词是普通活动门控图节点，输入不变不求值，
  无门链扫描成本。grhsim 因 system/DPI 单元每轮播种（NO00017 语义强制），
  门链扫描是该表示差异的固有残余——本节点不改播种语义，只压缩扫描本身的
  取指/分支形态。

### 机制（发射层 `cpu_emit.cpp` computeGroup）

对 unit 体内**连续**的 event-gated 副作用门（`core.system.task` /
`core.dpi.call`、空 results、带 computeGuardGroup 的 cachedGuard、
sampleEvents 对该 op 无发射即历史已 direct-sample/batch/alias）：

- **G1 合并**：run 内相邻且条件文本相同的门合并为单 `if(cond){A;B}`——
  门体为外部 void 调用（无 results 即无 inout/output 回写），两调用间无
  任何仿真状态写，合并保持调用顺序与次数，语义逐字等价。
- **G2 提升**：run ≥2 且共享同一 cachedGuard 时外提 `if(guard){...}`，
  内层只测各自的调用条件；`guard && cond` ≡ `if(guard) if(cond)` 短路等价。
  事件未触发的激活（hist 变化但非有效边沿，如时钟下降沿唤醒）从 ~500 次
  首操作数短路降为 1 次外门跳过。
- **G3 冷体下沉**：门体全部实参为编译期常量（IR 级判据：arg ∈
  staticScalars_/staticStrings_，无运行时数据依赖）时，条件包
  `__builtin_expect(!!(...),0)`。Clang 据此把从不执行的门体移出热
  fall-through 路径（沉到函数尾/冷段），门链变为致密顺序流。常量-only
  判据把从不触发的 assert/fwrite 诊断体与每周期触发的 difftest 事件流
  DPI（运行时参数，如 4454+ 族）自然区分——后者不加提示，避免反向伤害。

不重排不同条件的门（副作用顺序保持）；不触碰 IR、分区、调度、提交语义；
触发条件为 op 种类 + guard 分组 + 参数常量性，通用结构特征，无模块名匹配。

### 预期收益与证伪标准

- 预期：族 13.3% ×（取指/重定向占比 ~50–70%）× 致密化命中 ≈ **+1.5~4%**；
  附带门数减半（合并 ~5.5k 相邻对）与热 text 收缩的正向分量。
- 证伪门：reemit 单对筛选 **<+0.4%** 则调整变体（合并/提升/提示可分解）
  或放弃；正式判定以 6 次交替复测秩次门（max(new)<min(old)）为准。
- 历史失败模式辨析：NO00039/40 的发射层失败均为**新增**指令/内联扰动
  （写路径内联 -8.85%、publish restrict -1.29%、lut-fold +0.95% 指令）；
  本方案纯删除门分支并移动冷体，不新增任何运行时工作，且作用于中型
  函数（100–200 KB）而非 300 KB 级 commit 巨型函数。

## BASELINE（2026-09-18）

- 对照（old）：NO00040 flow-densify-final 二进制
  （`ptmp/no00041_commit_history_20260918/flow-densify-final/emu/emu`，
  sha256 `6dff0a3d4421cea1ca564a6935cef1aac9fdd7f5c9373b1a9c1c2c759daa251d`，
  即随 NO00040 提交 `03dfb41` 接受的版本）。其正式成绩：三次 new 均值
  **90.475667 s**（相对 NO00039 old −1.032961%）。
- 测量口径：`make benchmark_grhsim_ir`（scripts/benchmark_grhsim_ir.py），
  CPU2 单核、XS_EMU_THREADS=1、100k cycles、waveform/commit/RAM trace 关闭，
  交替 old/new，**每次运行前对被测 emu 执行 posix_fadvise(DONTNEED) 页帧
  驱逐**（NO00040 修正协议，`--evict-page-cache` 默认开）；止损 1.5×
  （基线 91.0 s → 136.5 s）；预注册顺序与二进制哈希写入 `preregister.json`。
- 等价门槛：`instrCnt=240349`、`cycleCnt=99996`、IPC 2.403586、末端 PC
  `0x80000c0c`、guest cycles 100001、退出码 0、NEMU 对拍无 mismatch。
- 基线 commit：wolvrix 子模块 `03dfb41`（NO00040，`feat: densify
  event-gated endpoint boundary inputs in data layout`）。
- 筛选路径：`make reemit_grhsim_ir` 自 NO00040 checkpoint
  （`flow-densify-final/xiangshan_grhsim_ir.json`，含致密化最终 mapping），
  发射层变更无需 remap。

## 阶段记录

### IMPLEMENTED（2026-09-18）

实现（wolvrix 子模块工作区差异，基线 `03dfb41`；`lib/grhsim/backend/cpu_emit.cpp` +172/−13，`tests/grhsim/test_cpu_emit.cpp` +68/−2）：

- **G1/G2/G3 一体实现**于 `computeGroup` 的 op 发射循环：`sideCallGate()`
  认证可变换门（`core.system.task`/`core.dpi.call`、空 results、在
  computeGuardGroup 内有 cachedGuard、每条事件历史的 `stage()` 均为空操作
  即 batched/aliased/direct-sampled），随后把同一 guard 的连续门组成 run：
  run ≥2 时外提 `if(guard){...}`（G2）；run 内相邻同条件文本的门合并为
  单 `if` 多块体（G1，每体独立花括号作用域避免 `cpu_args` 重声明）；
  门体全部实参为 `core.compute.constant` 产出（IR 级常量判据，等价于
  发射文本无运行时引用——helper read cache 已证明不缓存常量）时条件包
  `__builtin_expect(!!(...),0)`（G3，run 内门与孤门均适用）。
- 旁路条件：sampleEvents 非空（历史仍走 staged 采样）的门保持原路径——
  采样写的位置逐字不动；不同条件的门永不重排（副作用顺序保持）；
  空 results 保证无 DPI output/inout 回写，门体均为纯外部 void 调用。
- 重构提取 `dpiCallExpression()`（空 results 调用串）、`systemTaskBody()`、
  `sideCallExtras()`，经典路径（无 cachedGuard、非 run 孤门的非常量体）
  发射文本与改动前逐字一致。
- 统计计入 `packSummary()`（发射后诊断）：`gate_hoisted_runs` /
  `gate_hoisted_gates` / `gate_merged_gates` / `gate_cold_hints`。
- 聚焦测试（2026-09-18 全绿）：`make test_grhsim_cpu_emit` 1/1（91.0 s，
  含 ASan/UBSan 执行型 fixture）；`test_grhsim_cpu_mapping` 2/2；
  `test_grhsim_cpu_schedule` 1/1。`testComputeHistorySharing` 更新预期
  （该 fixture 每门独占 helper chunk，落 singleton 冷提示路径，
  `cpu_cold_gate`=12）；新增 `testGateCompaction`：同条件常量门对合并
  （`cpu_gate_merge ops=2`）+ guard 提升（`if(cpu_cevent_`=1）+ 常量体提示
  各 1，运行时参数门与无 guard 组孤门保持原路径，统计行精确匹配
  `gate_hoisted_runs=1 gate_hoisted_gates=2 gate_merged_gates=1 gate_cold_hints=2`。

（筛选与正式复测记录待补。）

### VALIDATED 进展：reemit 筛选（2026-09-18）

- reemit 自 NO00040 checkpoint（`make reemit_grhsim_ir`，无 remap，发射层变更）：
  emit 统计 `gate_hoisted_runs=821 gate_hoisted_gates=13193 gate_merged_gates=7181
  gate_cold_hints=11933`；`helper_read_cache_values=408161` 不变（不扰动读缓存
  规划）。首轮 reemit 曾暴露 run 检测缺陷——`core.compute.constant` 等无发射
  op 夹在门之间把 run 全部打断（hoisted_runs=1）——按"无发射 op 不破 run"
  修正后达到上述覆盖。
- 发射形态（task_4415 反汇编验证）：原 `if(cevent && pred)` 逐门内联体、
  ~450 个 taken 前跳跨 141 KB，变为单一提升 `if(cevent)` 外门 + 致密
  `cmpb;jne` 门链（每门 ~7–10 B），常量门体全部沉到函数尾区；热 task 函数
  尺寸 task_4415 141,040→99,856 B（−29.2%）、task_4417 125,904→78,736 B
  （−37.5%）、task_4444 201,280→155,104 B（−22.9%）；全 ELF .text
  90,406,120→89,505,896 B（−900,224 B，−1.00%）。生成源码规模
  1,036,084,391→1,035,867,244 B（−0.02%）。
- 单对筛选（`screen-g1/summary.json`，修正协议页帧驱逐，均退出码 0、
  端点 240349/99996/100001/0x80000c0c 一致）：old 92.435 s /
  new **81.233 s，+12.12%**——远超 +0.4% 证伪门，方向明确为正。
  单对无统计效力（p=0.5），按流程进入完整 SV 路线正式构建与 6 次交替复测。

### 正式门槛进展（2026-09-18）

- 完整 SV→C++ 生成 **689.77 s**（<1800 s，完整 SV 路线、
  `XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0`，非 checkpoint 恢复，
  round-trip 校验通过）。
- 正式 model 与筛选 model（flow-screen2）全部 **5,052 个源文件 md5 全等**，
  发射统计一致（gate_hoisted_runs=821 / gates=13,193 / merged=7,181 /
  cold_hints=11,933）。
- HDLBits DUT=001 回归通过（`[TB] dut_001 passed: one=1`）。
- fresh 编译 **734 s**（<1800 s，exit 0）。
- **订正（2026-09-18）**：上述 734 s 实为 `-j4` 下测得。本次编译命令未显式传
  `VM_BUILD_JOBS=32`，落入根 Makefile `xs_wolf_grhsim_ir_build_emu` 当时的
  默认并行度 4；NO00001–NO00039 均显式以 `VM_BUILD_JOBS=32` 测量（fresh 编译
  约 205–265 s），故该数字与历史节点不可比。门槛判定不受影响（仍 <1800 s），
  且编译并行度只影响构建墙钟，不影响 emu 二进制性能结论。Makefile 默认值已
  订正为机器实际核数（`XS_VM_BUILD_JOBS=nproc`），后续节点按实际核数并行
  并在文档中记录 job 数。

### 正式 6 次交替复测：ACCEPTED（2026-09-18）

被测二进制 `ptmp/no00041_gate_compact_20260918/flow-final/emu/emu`
sha256 `f6ba3f597ba5fd1793bb18be1317a9f813f95d3549f93f3fb84583be2e5e866a`
（正式 SV 路线构建）；对照 old 为 NO00040 flow-densify-final
sha256 `6dff0a3d4421…`（复用其归档测量协议二进制）。

6 次交替（`ptmp/no00041_gate_compact_20260918/formal/summary.json`；
预注册 old1/new1/old2/new2/old3/new3；每次运行前对 old/new emu 均执行
posix_fadvise(DONTNEED) 页帧驱逐；CPU2、单核、XS_EMU_THREADS=1、
100k cycles、waveform/commit/RAM trace 关闭）：

| run | old Host (s) | new Host (s) | 退出 | 端点 |
|---|---:|---:|---|---|
| 1 | 90.647 | 81.310 | 0 | 240349/99996/100001/0x80000c0c |
| 2 | 91.697 | 80.943 | 0 | 同上 |
| 3 | 90.396 | 80.897 | 0 | 同上 |

六次均 NEMU 对拍通过、`instrCnt=240349`、`cycleCnt=99996`、IPC 2.403586、
末端 PC `0x80000c0c`、guest cycles 100001，退出码 0，无 mismatch。

- old 均值 **90.913333 s**（样本 SD 0.690182）、new 均值 **81.050000 s**
  （样本 SD 0.226338），降低 **10.849160%**。
- `max(new) 81.310 < min(old) 90.396`，Mann-Whitney U=0、单侧精确 p=0.05、
  Cohen d=−19.20、Cliff's delta=−1.0，**秩次判据通过**。

**最终判定：ACCEPTED（候选 G 一体机制：G1 相邻同条件门合并 + G2 共享
cevent 守卫提升 + G3 常量门体冷下沉提示，+10.849160%，秩次判据通过，
生成/编译门槛通过，100k 等价确认，HDLBits 回归通过）。** 按新均值计算，
GrhSIM-IR 为归档 gsim 46.965 s 的 **1.725753×**（上一节点 NO00040 为
1.926748×）——本节点是迄今单节点最大收益，收益来源不是削减动态求值量，
而是把 44xx 端点族每次激活的取指足迹从 ~100–200 KB/task 压到致密门链
（热 task 函数体 −23%~−37%），直接命中 gsim 与 grhsim 的代码布局差异。

**语义约束**：仅在同一 unit 内、相邻、同条件文本、空 results、体内无采样
发射的门之间合并/提升；不重排不同条件的门，副作用调用顺序与次数逐字不变；
`__builtin_expect` 仅为布局提示。IR、分区、调度、提交语义不变；冻结 GRH、
GRH pass、XiangShan 与测试源码未改。触发条件为通用结构特征（op 种类 +
guard 分组 + 参数常量性 + 历史采样空操作判据），不含模块名称匹配。

**后续方向**：(a) 门链残余——致密化后每次激活仍逐门测试 ~230 个谓词
（task_4415 余 ~100 KB 冷体中的运行时参数门未下沉、gate 本身的 load+test
可再做零检测预过滤）；(b) 同样的冷下沉思路可推广到 commit 侧 4454+ 事件
流 task 中从不触发的分支；(c) compute 主体（非端点族）的条件跳转与
text 仍是最大份额。三节点复盘提醒：NO00042 完成后应做 NO00040–42 复盘。
