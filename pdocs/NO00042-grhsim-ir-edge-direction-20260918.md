# NO00042：事件门控链激活成本——commit 武装与条件打包（否决）→ 端点单元边沿方向快路径

日期：2026-09-18。最终判定：**ACCEPTED（+2.085361%，页帧驱逐协议下 6 次交替秩次判据通过）**。

本节点围绕同一瓶颈——事件门控链（commit 侧写端口门 + compute 侧 44xx 端点
assert/DPI 门）在每次激活时的逐门扫描与单元机体空转——先尝试 commit 侧
生产者武装（变体 A，否决并回退），再试端点条件打包预过滤（变体 B，否决并
回退），最终采用**端点单元边沿方向快路径**（变体 C）：单事件单方向的
quiescence 合格单元只在事件处于活跃电平时运行机体。冻结 GRH、GRH pass、
XiangShan 与测试源码不修改。

## IDEA（2026-09-18）

### 瓶颈证据

- 新鲜 profile（`ptmp/no00042_probe_20260918/profile_no41/`，NO00041 正式
  二进制 sha256 `f6ba3f597ba5…`，200Hz、16,176 样本、墙钟 80.90 s）：
  compute 65.42% / commit 20.75% / main_other 8.68% / evaluator 4.09%。
  热点已极度扁平（top-30 compute task 仅占 compute 7.26%）；commit 侧
  4454–4496 族 20 个 task 合计 14.27% 总样本（commit 的 68.8%）；44xx
  端点族在 NO00041 致密化后仍占约 3–5%（top-30 中 17 个、合计 3.3% 起）。
- 静态普查（NO00041 正式 model）：426 个 commit task 含 **38,476** 个
  `if((cpu_edge_snapshot_N) && EN && idx<count)` 事件门（窄 memWrite
  `cpu_write_cell` 33,292 / 宽 memWrite `cpu_stage_cell` 4,074 / 暂存
  regWrite 1,104），每 posedge 激活全量逐门求值（早期出局链已排除
  非边沿激活）；compute 侧 821 个提升 run、13,193 个端点门（NO00041）。

### 变体 A：commit 事件门 fired-sticky 武装（REJECTED）

机制：memWrite 门的 EN/IDX 操作数生产者变化置 per-gate 武装位（u64 字
预过滤），清除语义为 fired-sticky（位清零 ⟹ 上次扫描未触发且条件操作数
未变 ⟹ 跳过安全；触发保持武装以对多写者 cell 保序）。任务适用性经
"稳定历史扫描 + 非活跃边沿快路径 ⟹ 到达门链时边沿恒真"证明，门条件
省略边沿合取。

- 首版覆盖 `gate_arm_gates=23867 tasks=39 words=4061`（run 被 NO00018
  武装 op 打断，中位块长 2）；单对筛选 old 80.876 / new 82.298 =
  **−1.76%**（REJECTED，低于 +0.4% 证伪门）。
- 修正（K≥1 事件项集合推广 + `chainTransparent` 致密化）后覆盖
  `gate_arm_gates=36368 tasks=46 words=752 sites=34546`（94.5% 门、
  48.4 门/字）；单对筛选 old 81.055 / new 83.022 = **−2.43%**。
- **证伪证据**（dyn-stats 构建 + 100k 运行，
  `dynrun2/xs_wolf_grhsim_no00042_dyn2.log`）：`port_eval=1,402,073,114`、
  `port_fire=1,150,450,077`（含 NO00018 端口），触发/求值比 **82%**——
  commit 写端口门是每 posedge 真实工作的活跃端口，并非静默门；热字内每门
  额外位测试 + fired 累积 + 字存回与生产者置位（grp_fire=268,065,905 次
  变化组发布）超过冷字跳过收益。机制前提（门大体静默）对该族不成立。
  源码已回退（工作区零残留），本记录保留全部数据。
- 辨析：NO00018 武装成功因 direct-commit 体含 `current==value` 自检，
  未武装端口跳过即幂等无操作；memWrite 暂存写无此性质，须 fired-sticky，
  而触发率高达 82% 使保持武装的门承担纯增量开销。

### 变体 B：端点条件打包预过滤（REJECTED）

机制：44xx 端点门条件（1 位 boundary 字节）按值分配打包位
（`cpu_eflags`），生产者在字节真实变化时精确维护位（无清除语义），
提升 run 内同字门组包入 `if(cpu_eflags[W])` 预过滤块；覆盖
changed/fanout/silent 三种标量存储变体（含 dyn 形态）。覆盖
`endpoint_pack_runs=820 gates=13193 values=5473 words=820`。

- 关键正确性论证：CoreMark 中 assert/fwrite 门从不触发（无输出），而
  cevent 每 posedge 为真 ⟹ 条件字节在每次扫描时点恒 0 ⟹ 预过滤跳过率
  ≈100%。
- 单对筛选（`screen-ep/`）：old 81.252 / new 82.026 = **−0.95%**
  （REJECTED）。失败归因：预过滤节省的门测试（≈2.4 s 量级估计）被生产者
  钩子开销反超——5,473 个谓词值散布于每轮活跃的计算超节点，每个求值点
  新增比较+分支（silent 路径新增变化检测），总量 ≈3 s；**读写两侧的成本
  不对称**（读侧每周期一次扫描 vs 写侧每轮每值求值）使任何逐值写侧钩子
  在该族上都不经济。源码已回退。
- 附带认知：44xx 残余成本的主体不是门谓词测试本身，而是**每次激活的
  单元机构**（帧清零、~30 缓存读、守卫组求值、采样），且单元在正负边沿
  两轮各激活一次（dyn 证实 315 个单元 act=402,258=每轮）。

### 变体 C：端点单元边沿方向快路径（筛选通过，正式验证中）

机制（发射层 `cpu_emit.cpp`，`planComputeQuiescence` + taskBody）：

- **观察**：dyn 数据显示 315 个端点单元每轮激活（正负边沿各一次）。
  NO00020 的 quiescence 只在 hist==event 时跳过；负边沿轮
  （hist=1, event=0）不满足静默条件，函数体（帧清零 + 缓存读 + cevent
  求值 + 门组守卫 + 发布）空转一遍，而单方向单元的所有门在该轮必然全假。
- **快路径**：quiescence 合格且全部守卫项共享同一 (event, direction) 的
  单元，函数体包入 `if(event)`（posedge 单元；negedge 单元为
  `if(!event)`）——机体只在真实边沿方向运行；延迟采样（dsample）保持在
  包装外，负边沿轮照常回写历史，边沿跟踪不变。等价于 commit 侧既有的
  `cpu_inactive_edge_sample` 快路径在 compute 侧的对应物。
- 语义约束：仅作用于 quiescence 资格已认证的纯门单元（全部副作用均为
  边沿守卫、历史仅本单元引用、结果仅 partition-local）；方向判定为
  `event_edges` 参数 + 事件值同一性的通用结构特征。负边沿轮跳过机体时
  门守卫全假、局部暂存仅服务门体，无副作用损失。
- 预期：293 个单元 × 100k 非活跃电平轮 ×（帧清零 + ~30 缓存读 + 守卫组
  + 调用开销）≈ **+0.5~1.5%**；证伪门同前。
- 该机制零新增运行时状态、零生产者钩子——与变体 A/B 的失败模式
  （写侧新增工作）正交。

## BASELINE（2026-09-18）

- 对照（old）：NO00041 正式二进制
  （`ptmp/no00041_gate_compact_20260918/flow-final/emu/emu`，sha256
  `f6ba3f597ba5fd1793bb18be1317a9f813f95d3549f93f3fb84583be2e5e866a`，
  随 NO00041 提交 `264b93e` 接受）。其正式成绩：三次 new 均值
  **81.050000 s**。
- 测量口径：`make benchmark_grhsim_ir`（scripts/benchmark_grhsim_ir.py），
  CPU2 单核、XS_EMU_THREADS=1、100k cycles、waveform/commit/RAM trace 关闭，
  交替 old/new，每次运行前对被测 emu 执行 posix_fadvise(DONTNEED) 页帧驱逐
  （NO00040 修正协议）；止损 1.5×（基线 81.1 s → 121.6 s）；预注册顺序与
  二进制哈希写入 `preregister.json`。
- 等价门槛：`instrCnt=240349`、`cycleCnt=99996`、IPC 2.403586、末端 PC
  `0x80000c0c`、guest cycles 100001、退出码 0、NEMU 对拍无 mismatch。
- 基线 commit：wolvrix 子模块 `264b93e`（NO00041，`feat: compact event-gated
  endpoint gate chains in cpu emit`）。
- 筛选路径：`make reemit_grhsim_ir` 自 NO00041 checkpoint
  （`flow-final/xiangshan_grhsim_ir.json`），发射层变更无需 remap。

## 阶段记录

### IMPLEMENTED（2026-09-18）

变体 A 实现与回退过程见上（含 SEGFAULT 修正：`armableCommitGate` 误读
`planDirectSampling()` 之后才分配的 `directSampleStates_`，论证其对 commit
历史恒假后移除查询；单元测试 `testCommitGateArms` 曾覆盖单/双事件域武装与
回退域形状，回退时一并撤销）。

变体 B 实现（wolvrix 子模块工作区差异，基线 `264b93e`）：

- `planEndpointPacks()`（validate 末尾，`planDirectSampling` 之后——
  `sideCallGate` 依赖 `directSampleStates_`）：逐 compute task/word/unit/
  chunk 精确复刻 computeGroup 的 run 检测（`emitsNothing` + `sideCallGate`
  + 同守卫连续段 + G1 文本合并），对 extras 为空、条件为 1 位二态
  boundary 字节且生产者审计通过的合并组按序分配（字，位）；
  `endpointPackWords_[op]` 供发射、`endpointPackTargets_[value]` 供钩子。
- computeGroup run 发射：连续同字打包组包入 `if(cpu_eflags[W])` 块，
  其余门保持 G1/G3 逐字形态。
- 通用标量存储四变体（changed/fanout/silent × dyn/非 dyn）挂
  `endpointPackUpdates`；仅打包值的静默存储新增变化测试。
- 统计 `endpoint_pack_runs/gates/values/words` 入 historyBatchSummary。
- 聚焦测试：`testGateCompaction` 增补断言（`cpu_epack` 块存在且闭合、
  生产者 `if(cpu_epack)` 钩子、位更新表达式各 1）；`test_grhsim_cpu_emit`
  1/1 全绿（91.2 s，含 ASan/UBSan 执行型 fixture）。

变体 C 实现（wolvrix 子模块工作区差异，基线 `264b93e`；
`lib/grhsim/backend/cpu_emit.cpp` +~40/−0）：

- `planComputeQuiescence` 的资格走查新增 (event, direction) 同一性追踪
  （`edgeUniform`/`edgeDirection`），仅在 quiescence 合格且全部边沿项共享
  同一事件与方向时记录 `computeEdgeDirection_[unit]`；
  `edgeDirectionUnits_` 统计入 historyBatchSummary。
- taskBody 单元块：quiescence 包装内、机体（帧/字符串/helper 或
  computeGroup）外提 `if(event)`/`if(!event)` 方向包装
  （`// cpu_edge_direction`），延迟采样保持在包装外。不含任何新运行时
  状态。聚焦测试：`testGateCompaction` 增补断言（3 个 quiescence 单元全部
  获得方向包装）；`test_grhsim_cpu_emit` 1/1、`test_grhsim_cpu_mapping`
  2/2、`test_grhsim_cpu_schedule` 1/1 全绿。

### VALIDATED 进展：变体 C 筛选（2026-09-18）

- reemit 筛选（`ptmp/no00042_probe_20260918/flow-screen4`，自 NO00041
  checkpoint，无 remap）：`edge_direction_units=293`（quiescence 合格单元
  293/293 全部满足单事件单方向），其余发射统计不变
  （gate_hoisted_runs=821 等）。
- 单对筛选（`screen-ed/`，页帧驱逐协议，端点 240349/99996/100001/
  0x80000c0c 一致，退出码 0）：old 80.929 s / new **80.021 s =
  +1.122%**——越过 +0.4% 证伪门。单对无统计效力，进入完整 SV 路线正式
  构建与 6 次交替复测。

### 正式门槛（2026-09-18）

- 完整 SV→C++ 生成 **696.21 s**（<1800 s，完整 SV 路线、
  `XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0`、非 checkpoint 恢复，
  round-trip 校验通过；timeout 1800 截止机制在位未触发）。
- 正式 model 与筛选 model（flow-screen4）全部 **5,052 个源文件 md5 全等**。
- fresh 编译 **735 s**（<1800 s，exit 0）。
- HDLBits DUT=001 回归通过（`[TB] dut_001 passed: one=1`）。

### 正式 6 次交替复测：ACCEPTED（2026-09-18）

被测二进制 `ptmp/no00042_edge_direction_20260918/flow-final/emu/emu`
sha256 `d8cdcb69b1bcbd90e6b92d54cc6e3b91fd75a1c1f2c8b397dadd41ba2e09a1e6`
（正式 SV 路线构建）；对照 old 为 NO00041 flow-final sha256 `f6ba3f597ba5…`。

6 次交替（`ptmp/no00042_edge_direction_20260918/formal/summary.json`；
预注册 old1/new1/old2/new2/old3/new3；每次运行前对 old/new emu 均执行
posix_fadvise(DONTNEED) 页帧驱逐；CPU2、单核、XS_EMU_THREADS=1、
100k cycles、waveform/commit/RAM trace 关闭）：

| run | old Host (s) | new Host (s) | 退出 | 端点 |
|---|---:|---:|---|---|
| 1 | 81.038 | 79.604 | 0 | 240349/99996/100001/0x80000c0c |
| 2 | 81.321 | 79.430 | 0 | 同上 |
| 3 | 81.196 | 79.442 | 0 | 同上 |

六次均 NEMU 对拍通过、`instrCnt=240349`、`cycleCnt=99996`、IPC 2.403586、
末端 PC `0x80000c0c`、guest cycles 100001，退出码 0，无 mismatch。

- old 均值 **81.185000 s**（样本 SD 0.141820）、new 均值 **79.492000 s**
  （样本 SD 0.097180），降低 **2.085361%**。
- `max(new) 79.604 < min(old) 81.038`，Mann-Whitney U=0、单侧精确 p=0.05、
  Cohen d=−13.93、Cliff's delta=−1.0，**秩次判据通过**。

**最终判定：ACCEPTED（变体 C：端点单元边沿方向快路径，+2.085361%，秩次
判据通过，生成/编译门槛通过，100k 等价确认，HDLBits 回归通过）。** 按新
均值计算，GrhSIM-IR 为归档 gsim 46.965 s 的 **1.692622×**（上一节点
NO00041 为 1.725753×）。

**语义约束**：方向包装仅作用于 quiescence 资格已认证且全部边沿守卫共享同一
(event, direction) 的 compute 单元；机体在事件非活跃电平时被跳过（此时全部
门守卫必然为假、partition-local 暂存仅服务门体），事件历史延迟采样保持在
包装之外逐轮执行。IR、分区、调度、提交语义不变；冻结 GRH、GRH pass、
XiangShan 与测试源码未改。触发条件为 `event_edges` 参数 + 事件值同一性的
通用结构特征，不含模块名称匹配。

**保留实现**：wolvrix 子模块 `lib/grhsim/backend/cpu_emit.cpp`
（planComputeQuiescence 同一性追踪 + taskBody 方向包装）与
`tests/grhsim/test_cpu_emit.cpp`（testGateCompaction 增补断言）。

**后续方向**：(a) 负边沿轮仍运行 quiescence 检查 + dsample + 激活机构
（293 单元 × 100k 轮），可再做激活侧修剪；(b) 44xx 残余成本主体为机体
机构而非谓词扫描，帧/缓存读的削减空间未触及；(c) compute 主体 65% 的
平坦热点与 commit 侧 4454+ 族真实写回工作仍是最大份额；变体 A/B 的失败
数据（门触发率、生产者钩子成本）为后续机制划定了代价边界。

## NO00040–42 三节点复盘（2026-09-18）

- 当前最佳：79.492 s（NO00042 new 均值），为归档 gsim 46.965 s 的
  1.692622×；三节点推进 90.475667 → 81.050000 → 79.492 s。
- 已排除方向（本三节点新增）：lut-fold 全家族（NO00040，定量证伪）；
  commit memWrite 门 fired-sticky 武装（NO00042 变体 A，触发率 82%
  证伪前提）；端点条件逐值打包位（NO00042 变体 B，写侧钩子成本不对称）。
  共同教训：**写侧/生产者侧的逐值新增工作（钩子、映射、内联扰动）在本
  设计的高频求值路径上代价极高**；读侧纯删除（冷体下沉、布局致密、
  方向跳过）与测量协议（页帧驱逐）是近期全部收益的来源。
- 剩余主要差距（对 gsim 47 s）：compute 主体 53 s 中约 1.1G 次超节点激活
  的机体机构开销（激活精度差距——71% 激活无产出）与 4454+ 族每 posedge
  的真实写回工作；二者都要求"激活/求值精度"层面的机制，而非发射形态。
- 低收益微调检查：NO00041（+10.85%）与 NO00042（+2.09%）均为结构性机制，
  未陷入参数微调；但单位节点收益已从两位数降到个位数，下一节点应优先
  探索激活精度类机制（如事件驱动的端点单元调度、跨轮惰性）。
