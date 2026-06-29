# NO0208 Activity-Schedule 概率划分升级落地进展

记录日期：2026-06-25 起（**滚动进展日志**，每完成一步在 §进展 追加一节）
关联：[`NO0207`](./NO0207_activity_schedule_prob_partition_upgrade_plan_20260625.md)（总规划）
状态：**进行中**。按 [`NO0207`](./NO0207_activity_schedule_prob_partition_upgrade_plan_20260625.md) 分步落地，一步步来，不一次到位。

## 目的与原则

- 本文是 [`NO0207`](./NO0207_activity_schedule_prob_partition_upgrade_plan_20260625.md) 的实现进展记录，逐步追加。
- 每步只做一件事，保证默认路径（`partitionPolicy="plain"`）行为不变、可随时回归。
- 凡涉及独立的结构 gate / runtime gate / A/B 复测，按 `RULES.md` 仍可另起独立 `NOxxxx`；本文只记录主线进展与改动清单。

## 阶段映射（对照 [`NO0207`](./NO0207_activity_schedule_prob_partition_upgrade_plan_20260625.md) §5）

| 步骤 | 内容 | 状态 |
| --- | --- | --- |
| **Step 1** | 参数 + 门控开关 + 框架接缝（不实现算法） | ✅ 完成（2026-06-25） |
| **Step 2** | Phase A：静态概率传播 `π` + 源代表（仅 prob 策略；纯分析） | ✅ 完成（2026-06-25） |
| **Step 3** | Phase B：节点成本 `w(v)`（类别对齐 NO0190；GRHSIM 槽位取整） | ✅ 完成（2026-06-26） |
| **Step 4** | Phase C：超图聚合结构 | ✅ 完成（2026-06-26） |
| **Step 5** | Phase D：MFFC 忠实度校验 + 合并到理想（`η`） | ✅ 已测+已合并（η 0.92→**0.96**，nodes 1.40M→1.19M，over-split −38%；残余为合理约束） |
| **Step 6** | Phase E：概率驱动粗化（增益+三层无环+φ/W/F） | ✅ 完成并优化（full XiangShan gate 通过；coarsen 117.5s→12.5s） |
| **Step 7** | Phase F：概率加权 DP | ✅/⚠️ 已实现；`cost=pi` 被 Step 7.5 否定，Step 7.6 已修正为 mixed DP cost，默认仍关闭 |
| **Step 7.5** | final weighted-boundary stats + Phase F A/B 判定 | ✅ 完成（2026-06-27）；新增 weighted 指标与 `probDpCost` 门控 |
| **Step 7.6** | mixed DP cost 修正 + 参数扫描 | ✅ 完成（2026-06-28）；推荐 `mixed-pi α=1.0 penalty=1.25` 作为显式 Phase F 候选 |
| **Step 8** | Phase G：FM 边界精修 | ✅ 本地实现+小图验证完成；full XiangShan structure gate 正向；CoreMark 50k plain 对比负向 |
| —    | Phase H（profiling 回灌）首版暂缓；Phase I（门控/统计）随各步增量 | 暂缓 |

---

## 进展

### Step 1 — 参数、门控开关与框架接缝（2026-06-25）✅

**目标**：建立 `partitionPolicy` 门控开关与全部 NO0207 §4 新参数，搭好「prob 路径」的接缝；**不实现任何新算法**。默认 `plain` 必须与现状逐字节一致。

**改动清单**

1. `wolvrix/include/transform/activity_schedule.hpp` — `ActivityScheduleOptions` 新增字段（占位默认，现阶段不参与划分决策）：

   | 字段 | 默认 | 含义 |
   | --- | --- | --- |
   | `partitionPolicy` | `"plain"` | 门控开关，`"plain" \| "prob"` |
   | `piDataInput` | `0.1` | 数据 InputPort 变化概率先验 |
   | `piRegRead` | `0.2` | RegisterRead 变化概率先验 |
   | `piHighThreshold` | `0.9` | 高活跃节点阈值 |
   | `phiMin` | `0.6` | 内聚度下限 |
   | `cBpMiss` | `8.0` | 分支预测失误惩罚（相对 `C_check_fast`） |
   | `footprintMaxBytes` | `32*1024` | `F_max`：宿主 x86 L1D 容量假设 |
   | `fmRefineMaxRounds` | `4` | FM 边界精修轮数 |

2. `wolvrix/lib/core/transform.cpp` — pass-arg 解析新增（沿用既有 `parseStringArg/parseDoubleArg/parseSizeArg` 模式）：
   - `-partition-policy` / `-partition-policy=`（两种形式）
   - `-pi-data-input` / `-pi-reg-read` / `-pi-high-threshold` / `-phi-min` / `-c-bp-miss`（double，空格形式）
   - `-footprint-max-bytes` / `-fm-refine-max-rounds`（size，空格形式）

3. `wolvrix/lib/transform/activity_schedule.cpp`：
   - `run()` 在 `costModel` 校验之后增加 `partitionPolicy ∈ {plain,prob}` 校验，非法即报错；并 `logInfo("activity-schedule partition policy: ...")`。
   - 在 `final_materialize` 调用（`materializeComputeNodeSchedule`）前增加 **prob 接缝**：当 `partitionPolicy=="prob"` 时打印「算法尚未实现，暂经 plain 路径产出（输出一致）」并仍走 plain。这是后续 Phase A–G 的替换点。

**设计选择**

- **prob 当前 == plain（按构造）**：接缝只多一条日志，随后调用与 plain 完全相同的 `materializeComputeNodeSchedule`，因此 `prob` 输出与 `plain` 逐字节一致，开关可安全开启。
- 默认 `plain`，所有现有脚本/Makefile 无需改动，行为不变。

**验证**

```sh
cd wolvrix/build
cmake --build . --target transform-activity-schedule -j$(nproc)   # OK，~15s
./bin/transform-activity-schedule ; echo $?                        # EXIT=0（全部用例通过）
cmake --build . --target transform-pass-manager -j$(nproc)         # OK
./bin/transform-pass-manager ; echo $?                             # EXIT=0
```

- 库（含 `grhsim_cpp.cpp` / `activity_schedule.cpp` / `transform.cpp`）整体编译链接通过。
- `transform-activity-schedule` 全用例通过 → 默认 `plain` 路径未回退。
- `transform-pass-manager` 通过 → 共享 pass-arg 解析器改动无副作用。

**Step 1 边界（明确不做）**

- 不实现 Phase A–G 任何算法逻辑。
- numeric 参数当前只接 `-name value` 形式；`-name=value` 形式与 `scripts/wolvrix_xs_grhsim.py` / Makefile 的 env→arg 接线，留到对应 phase 真正消费该参数时再加（默认 plain 无需）。
- 未新增 `partition_policy` 等 stat 列到 `summary_stats` JSON，仅用 `logInfo` 暴露；统计列随 Phase I 增量补。
- 未加「prob==plain 一致性」单测；待 prob 真正分叉时再补 A/B 一致性/对照测试。

**下一步**：Step 2 = Phase A 静态概率传播（`π` 计算 + 源代表相关性修正），挂在 `buildActivityOpData` 拓扑之后，先只产出 `pi[op]` 与统计，不改划分决策。

---

### Step 2 — Phase A 静态概率传播（2026-06-25）✅

**目标**：在已有拓扑序上正向计算每个 op 的静态变化概率 `π∈[0,1]`，含源代表相关性修正；产出 `pi[op]` + 统计供检视。纯分析，不改划分；仅在 `partition-policy=prob` 下计算，`plain` 完全不受影响。

**关键设计：在 PRE-clone 逻辑图上计算**

- `cloneSourceUsesForCompute` 会把每个 source（寄存器读/常量/…）**逐使用点克隆**，若在 post-clone 图上以 op 身份做源代表，同一寄存器的多个 clone 会被当成不同源 → 去相关失效、概率虚高。
- 故 `π` 在**第一次** `buildActivityOpData`（source clone 之前）的逻辑图上计算，结果按 op index 存入 `piByOpIndex`，跨 post-clone 的 opData 重建仍有效。这也更符合语义——`π` 描述的是逻辑，不是 clone 工件。

**传播规则**（`computeActivityPi`，对照 problem-v2 §7.2/§7.3）

- 源先验：`kConstant=0`、`kRegisterReadPort/kLatchReadPort=piRegRead`、`kMemoryReadPort≈π(地址)`（取操作数 max）；外部输入（无 eligible def）按 `piDataInput`、视为独立源。
- 透传（`kAssign/kSlice*/kReplicate/kNot/kShift/kReduce*`）：`π=max(操作数)`。
- `kMux`（操作数 `[sel,a,b]`）：`π=π(sel)+(1-π(sel))·max(π(分支))`。
- 算术/逻辑/比较/拼接（默认）：乘积补 `1-Π(1-π)`，但按**源代表去相关**——同源（追溯到同一 read op）的输入取组内 `max` 再相乘，避免 reconvergent fanout 把概率推到饱和。
- 每 op 维护源代表 `rep`：全部输入共享同一真实 rep 且无外部/多源时继承，否则标记多源。

**改动清单**

- `wolvrix/lib/transform/activity_schedule.cpp`：新增 `ActivityPiStats` + `computeActivityPi(...)`（返回 `piByOpIndex`，`-1=非 eligible`）；在 `build_op_data done` 后、source clone 前调用（gated `prob`），`logInfo` 输出 `high_activity`/`multi_source`/6 桶直方图；在 export 段导出 `…activity_schedule.op_pi` 会话值（按 op index）。
- `wolvrix/tests/transform/test_activity_schedule_pass.cpp`：加 `<cmath>`/`<utility>`；新增用例「Phase A static probability propagation」。

**验证**

```sh
cmake --build wolvrix/build --target transform-activity-schedule -j$(nproc)   # OK
wolvrix/build/bin/transform-activity-schedule ; echo $?                        # EXIT=0
```

单测断言（`piRegRead=0.2`/`piDataInput=0.1` 默认）全部通过：

| 节点 | 期望 `π` | 验证点 |
| --- | ---: | --- |
| `kConstant` | `0.0` | 常量恒不变 |
| `kRegisterReadPort` | `0.2` | 源先验 |
| `kConcat(同一 read 的两条 assign)` | `0.2` | **源去相关**（否则会算成 0.36） |
| `kConcat(两个不同寄存器读)` | `0.36` | 独立源乘积补 `1-0.8²` |
| `kMux(sel=read, a=read, b=const)` | `0.36` | `0.2+0.8·0.2` |

- 全部既有用例（默认 `plain`）仍通过 → plain 路径未回退；`prob` 下 `op_pi` 正确导出。
- 注：`logInfo` 在单测 harness 不显示（实跑/全 XS 流程才会打印 `probability(pi)` 直方图行）。

**Step 2 边界 / 已知局限**

- 源代表以 read op 身份为粒度，**未按 register symbol 归并**：同一寄存器的多个 read port 暂不互相去相关（待 refine）。
- 外部输入统一按 `piDataInput`，**未区分时钟（π=1）与数据**：时钟识别待后续。
- `π` 仅 `prob` 下计算；`piByOpIndex` 覆盖 PRE-clone op，clone op 的 `π`（=其原件）待 Phase B 消费时按需补。
- 尚未在真实 XiangShan 上检视 `π` 直方图（需跑 emit 流程，下一步可选）。

**下一步**：先在真实电路上跑 `-partition-policy=prob` 看 `probability(pi)` 直方图，判断静态模型是否合理；再进 Step 5 的 η 测量 / Step 3 Phase B 节点成本。

---

### Step 2 实测 — 真实 XiangShan `π` 直方图（2026-06-25）

完整 XiangShan（resume 自 `build/xs/grhsim/wolvrix_xs_post_stats.json`，`-partition-policy=prob`，stop-after-activity-schedule；全程 153s，`build_op_data` 4.98M ops 仅 6.2s、π 计算紧随其后开销可忽略）跑出 PRE-clone 静态 `π`：

| 指标 | 数值 | 占比 |
| --- | ---: | ---: |
| ops（PRE-clone） | 4,981,292 | — |
| compute_ops | 4,374,899 | 87.8% |
| high_activity（π≥0.9） | 3,228,950 | **64.8%** of ops |
| multi_source | 4,194,135 | **95.9%** of compute |

| `π` 桶 | 计数 | 占比 |
| --- | ---: | ---: |
| [0, .05) | 29,038 | 0.6% |
| [.05, .2) | 325 | ~0% |
| [.2, .5) | 1,185,161 | 23.8% |
| [.5, .8) | 400,192 | 8.0% |
| [.8, .95) | 258,822 | 5.2% |
| [.95, 1] | 3,107,754 | **62.4%** |

**判定：静态 `π` 在真实 XiangShan 上严重饱和，暂不可用于驱动划分。**

- 62% 的 op 落在 `π≥0.95`、65% 高活跃——模型认为整个设计几乎每周期都在变，与事件驱动仿真的「真实活动稀疏」前提直接矛盾（CPU 大部分数据通路/寄存器堆/缓存每周期其实空闲）。
- 根因：**乘积补累积 + 96% multi_source**。源去相关只在输入共享「同一 read op」时生效；真实 XiangShan 里逻辑相关信号经不同 read port / slice 进来被当独立源 → `1-Π(1-π)` 几层组合逻辑内就冲到 ~1。以 op 身份做源代表太粗，`multi_source=96%` 量化了这点。
- 这正是「先验证模型是否合理」的答案：**不合理（过饱和）**；只花 6s 拿到，避免在坏信号上白搭 Phase E/F。基础设施本身正确（PRE-clone 计算、去相关、框架均单测验证过），问题在静态模型对深层真实逻辑的精度。

**对路线的影响**：π 能区分冷热前不应据它做粗化/DP（否则 `p(e)·W` 与增益近退化）。改进方向按性价比：
1. **源代表按 register symbol（及 slice 同源）归并**——直击 96% multi_source，最便宜的高杠杆，改完重测直方图看是否去饱和。
2. 若仍饱和：抑制累积（更低先验 / 阻尼 combine / 控制类用 max、数据类用乘积补）——无 ground truth 时偏 hack。
3. 兜底：**profiling（层次 3）**实测活动——Step 1 决策暂缓，本结果是「可能需提前」的证据。

---

### Step 2 实测 2 — symbol 级源去相关：负结果（2026-06-25）

把源代表从「read op 身份」改为「register/latch symbol」（同一寄存器经不同 read port / slice 进入识别为同源，外部输入按 value id 归并），重测真实 XiangShan：

| 指标 | op 身份 rep | symbol rep | Δ |
| --- | ---: | ---: | ---: |
| multi_source | 4,194,135 | 4,194,075 | **−60** |
| π≥0.95 | 3,107,754 | 3,107,737 | −17 |
| high_activity | 3,228,950 | 3,228,896 | −54 |

**几乎无变化**（multi_source 仅降 60 / 4.19M）。代码确已生效（直方图有微动），效果可忽略。

**结论（强化判定）**：饱和**不是**同一寄存器多 read port 的 reconvergence 造成，而是**真实的多寄存器扇入**——post-reg-to-mem 设计里每个寄存器基本只有一个 read port 扇出，多源来自逻辑真的依赖很多不同状态元件。更根本地：**前向乘积补 π 在真实深/宽组合逻辑上结构性饱和**——它度量「P(任一输入变化)」，深逻辑里单调冲向 1，把「某输入翻转」与「输出真翻转」混为一谈（mux 未选中通路、掩码位、稳定算术都不改变输出，前向模型看不到）。**这不是相关性建模能修的。**

> 完整根因分析（为何前向乘积补会饱和、为何去相关救不回）见本文 **§附录 A**。

**路线决策（待拍板）**：静态层次 2 对真实 XiangShan 不可用。
- ✅ **转向 profiling（层次 3）**：用实测每-op/超节点变化频率当 π；基础设施已有（`NO0189`/`NO0190` per-supernode `f`/`a_succ`、`EMU_RUNTIME_PROFILE` per-op 变化计数）。有原则，但改变部署模型（发布前需一次 profiling 跑）。
- ⚠️ 廉价试探：大幅降先验 / 阻尼 combine——只平移饱和深度、无 ground truth 仍是猜，不作主路径。

---

### Step 2 实测 3 — transition-density 转移函数：去饱和成功（2026-06-25）

按用户判断「概率传播算法有误」，把 Phase A 的「一律乘积补」换成 transition-density 式转移函数（根因分析见本文 **§附录 A**）：逻辑掩蔽点（AND/OR、mux 选择、比较/归约位宽收缩）衰减活动度，仅 XOR/算术/拼接透传，信号概率固定 p1=0.5。重测真实 XiangShan（同口径）：

| `π` 桶 | 旧（乘积补） | 新（transition-density） |
| --- | ---: | ---: |
| [0, .05) | 29,038 (0.6%) | 45,627 (0.9%) |
| [.05, .2) | 325 (~0%) | 1,120,416 (22.5%) |
| [.2, .5) | 1,185,161 (23.8%) | 2,526,864 (50.7%) |
| [.5, .8) | 400,192 (8.0%) | 880,570 (17.7%) |
| [.8, .95) | 258,822 (5.2%) | 162,206 (3.3%) |
| **[.95, 1]** | **3,107,754 (62.4%)** | **245,609 (4.9%)** |
| **high_activity（π≥0.9）** | **3,228,950 (64.8%)** | **294,299 (5.9%)** |

**饱和消失**：π≥0.95 从 62.4% → 4.9%，high_activity 从 64.8% → 5.9%。分布从「双峰、重心在 1」变成「集中 0.05–0.5、少量高活跃尾」——这才像真实电路活动（稀疏的 ~6% 高活跃 + 中低活动主体），模型现在能区分冷热、可用于驱动划分。**用户「算法有误」判断成立；根因是公式（乘积补无脑累加）而非「前向静态本质不可行」。**

**下一步**：π 可用，但 p1=0.5 与各转移函数系数是 prototype heuristic，需 sanity-check（结构是否合理）并可能微调；之后可续 Phase B（节点成本）/ Phase E（增益）。

---

### Step 2 实测 4 — 完整 XiangShan π 合理性核对（per-kind / per-depth，2026-06-26）

新增按 op-kind 与逻辑深度的 π 均值插桩，在完整 XiangShan 上核对（aggregate 直方图同实测 3）。

**按 op-kind 均值（节选，count）——与语义/直觉一致**：

| op kind | mean π | 解读 |
| --- | ---: | --- |
| kConstant | 0.000 (27.5K) | 常量恒不变 ✓ |
| kRegisterReadPort | 0.200 (286K) | 等于先验 ✓ |
| kMemoryReadPort | 0.109 (1.9K) | 地址驱动、低 ✓ |
| kEq/kNe/kLt/kGt/kGe | 0.21–0.27 | 比较：位宽收缩→低 ✓ |
| kAnd/kOr | 0.27–0.29 (1.37M) | 逻辑掩蔽→中低 ✓ |
| kMux | 0.447 (782K) | 选择→中 ✓ |
| kAssign/kSlice/kNot | 0.32–0.45 | 透传，继承输入 |
| kConcat | 0.514 (257K) | 透传：任一片变即变 ✓ |
| kAdd / kSub | 0.56 / 0.38 | 算术透传→高 ✓ |
| kXor | 0.732 (31K) | 透传 + 本就高活跃 ✓ |

控制/比较逻辑低活跃、算术/XOR 数据通路高活跃——模型现在能**按 op 语义区分冷热**。

**按逻辑深度均值**：

| 深度 | mean π | count |
| --- | ---: | ---: |
| d0 | 0.182 | 314K |
| d1-2 | 0.196 | 529K |
| d3-5 | 0.236 | 510K |
| d6-10 | 0.284 | 722K |
| d11-20 | 0.376 | 894K |
| d21-40 | 0.476 | 940K |
| d41+ | 0.497 | 1.07M |

π 随深度**温和上升并在 ~0.5 附近 plateau**（旧模型深度 ~10 就冲到 1）——饱和确已消除；残余上升来自透传类（XOR/算术/拼接）的合理累积，收敛到 ~0.5 而非 1，可接受。

**结论：完整 XiangShan 上 π 合理。** per-kind 符合转移函数意图与电路直觉，per-depth 不再饱和；固定 p1=0.5 够用。遗留小项（不阻塞）：kLShr=0.88、kSliceArray=0.78 偏高（小 count、passthrough 继承活跃操作数）；深逻辑 ~0.5 plateau 的残余上升，若 Phase E 需要可再细化透传类衰减。

---

### Phase D 实测 — computeNode 对 MFFC 的忠实度 η（完整 XiangShan，2026-06-26）

按「π 先行、MFFC 先量后改」，π 站稳后核对 seed。新增只读 `measureMffcCoverage`：在 builder 用的同一图上算 MFFC 参考（`rep[u]` 反向近似——只看 compute 消费者，全部同 rep 则继承、否则自成根），与 `computeNodeOfOp` 对比 compute→compute 边。完整 XiangShan：

| 指标 | 值 |
| --- | ---: |
| compute→compute 边 | 7,253,291 |
| MFFC 同锥边（rep 相同） | 3,406,953 |
| computeNode 同节点边 | 3,124,066 |
| MFFC 同锥但 builder 拆开 | 468,794 |
| **η_edge = cn_internal / mffc_internal** | **0.917** |
| split_frac（MFFC 内部边被拆比例） | 13.8% |
| MFFC 组数（理想锥） | 1,207,893 |
| 实际 computeNodes | 1,396,359 |

**结论：computeNode 已是相当忠实的 MFFC（η=0.92）。** builder 比理想 MFFC 多出 ~188K 节点（1.40M vs 1.21M，+15.6%）、拆开 13.8% 的 MFFC 内部边——轻度 over-split。

- seed 质量足够好，**不阻塞**，可直接在其上做 Phase B/E。
- 那 13.8% over-split 一部分**合理**（builder 的 `maxOpInComputeNode` cap、boundary capacity 限制；我的 MFFC 参考是无 cap 理想值），真正可修的「reconvergent-absorb 漏吸收」是其子集。
- 且 Phase E 概率粗化会把相邻 computeNode 合并（最终 compute_supernodes≈72K，相对 1.4M 收敛 ~19×），over-split 大部分会被自然吸收。

故 Phase D 收敛为「已验证 computeNode 忠实 MFFC」；进一步改 builder 压低那 14%（用户已授权）属可选优化，待 Phase E 若发现 seed 碎片化拖累再回头。

---

### Phase D 实现 — MFFC 合并把 computeNode 提升到接近理想（2026-06-26）

按用户「直接达成理想、不埋雷」，新增 `mergeComputeNodesToMffc`（仅 prob，插在 builder 的 cycle-split 循环之前）：用 `rep[u]` 把同 MFFC 锥的 computeNode 合并。

**第一版（并查集按 rep-equal 边合并）翻车**：cap-limited 的任意合并会让同锥节点跨 topo **straddle**（中间夹着别的锥的 split-point），造成 quotient 环 → cycle-split storm，`compute_node_build` 卡 5 分钟+，已 kill。

**第二版（topo 连续分块）成功**：同锥节点按 topo 排序后做「连续分块」合并（受 `maxOpInComputeNode` cap），连续分块保证无环；intent/indivisible 节点排除在合并外（保 reg-to-mem）。结构重建复用 `recomputeComputeNodeOwnersAndBoundaries` + `buildComputeDag`，cap 偶发的 straddle 环交给已有 cycle-split 兜底。

完整 XiangShan（同口径）：

| 指标 | 合并前 | 合并后 |
| --- | ---: | ---: |
| **η_edge** | 0.917 | **0.961** |
| compute_nodes | 1,396,359 | **1,188,094** |
| common_expr（over-split 指示） | 819,288 | **508,876（−38%）** |
| mffc_but_cn_split | 468,794 | 318,824 |
| cycle_split_iters | 8 | 50（兜底，无 storm） |
| compute_node_build 耗时 | ~21s | ~110s（仅 prob，一次性） |
| final supernodes | 72,682 | 74,107（全程 materialize 正常） |

**结论**：spurious over-split 大幅消除（common-expr −38%），η 0.92→0.96，节点 1.40M→1.19M，全程正确 materialize。残余 4%（η 未到 1.0）来自**合理约束**：`maxOpInComputeNode` cap（巨锥必拆）、reg-to-mem intent 节点排除、~50 个 straddle 环被拆回。真 1.0 需放弃 cap / 破坏 reg-to-mem，不取。seed 现已接近理想 MFFC，作为后续 Phase B/E 的干净基础。

遗留：`compute_node_build` 在 prob 下慢到 ~110s（50 次 cycle-split 各重建一次 DAG）；若需要可优化（更省的环修复 / 减少 straddle）。

---

### Step 3 — Phase B 节点成本 / footprint 模型（2026-06-26）✅

**目标**：在 `partition-policy=prob` 下新增 op 级成本分析，产出后续 Phase C/E/F 可消费的 `compute_weight`、`change_weight`、`footprint_bytes`。纯分析，不改变 plain 输出，也不改变当前 prob 的 plain-through 划分决策。

**关键口径修正**

- `w(v)` 不再使用裸 `bitwidth` 线性计费，而是 `c_class(kind) * compute_units(width)`。
- `compute_units(width)`：`width<=64` 计 1 个执行槽；`width>64` 按 `ceil(width/64)` 计 64-bit word 数。
- footprint 与 compute cost 分离，按 GRHSIM C++ 存储桶估算：`<=1/8/16/32/64` 分别约 `1/1/2/4/8` bytes，wide 为 `8*ceil(width/64)`。
- 类别沿用 NO0190 的 comp/src/sink/const 口径，但仍不引用旧回归系数。当前占位：`comp=1.0`、`src=2.0`、`const=0.125`、`sink=0.0`，后续参数扫描再标定。

**改动清单**

- `wolvrix/lib/transform/activity_schedule.cpp`
  - 新增 `ActivityCostClass`、`ActivityCostStats`、`ActivityCostModel`。
  - 新增 `computeActivityCostModel(...)`，紧跟 Phase A 的 `piByOpIndex` 计算后运行，仅 `prob` 策略启用。
  - 导出 session values：
    - `*.activity_schedule.op_compute_weight`
    - `*.activity_schedule.op_change_weight`
    - `*.activity_schedule.op_footprint_bytes`
  - 日志新增 `activity-schedule cost-model` 与 `cost weight mean by kind`，用于真实电路 sanity-check。
- `wolvrix/tests/transform/test_activity_schedule_pass.cpp`
  - 新增「Phase B activity cost model」用例，覆盖 8/9/31/64 位同为 1 个 compute unit、65 位进 2 个 units、source/const 类别系数、footprint 桶化、`change_weight=weight*pi`。

**验证**

```sh
cmake --build wolvrix/build --target transform-activity-schedule -j$(nproc)  # OK
wolvrix/build/bin/transform-activity-schedule                                # EXIT=0
cmake --build wolvrix/build --target transform-pass-manager -j$(nproc)        # OK
wolvrix/build/bin/transform-pass-manager                                      # EXIT=0
```

**边界**

- 当前 Phase B 仍是 PRE-clone op 级导出；Phase C 聚合到 computeNode 时需要用结果 value 的 `canonicalValues` 把 source clone 映射回原逻辑源，避免 clone 人为重复/丢失成本语义。
- footprint 的「按 value/slot 去重」将在 Phase C 聚合时落地；Phase B 只提供单 op 的结果 footprint 估计。
- `cost-model` 日志尚未在完整 XiangShan 上复核，下一步可在真实电路上跑一次 `-partition-policy=prob` sanity-check 后进入 Phase C。

---

### Step 3 实测 — 完整 XiangShan cost-model sanity（2026-06-26）

命令口径同 Step 2 实测（resume 自 `build/xs/grhsim/wolvrix_xs_post_stats.json`，`-partition-policy=prob`，stop-after-activity-schedule）。首次运行发现 `.venv` 仍加载旧 native 包，未打印 `cost-model`；执行 `python3 -m pip install --no-build-isolation -e wolvrix` 刷新 editable 安装后重跑通过。

关键日志：

| 指标 | 数值 | 判定 |
| --- | ---: | --- |
| ops（PRE-clone） | 4,981,292 | 同 Step 2 |
| `total_weight` | 5,430,820.125 | 数量级正常 |
| `total_change_weight` | 1,968,472.064 | `change/weight≈0.363`，与 π 主体在 0.2–0.5 区间一致 |
| `total_footprint_bytes` | 16,268,133 | 仅全局 sanity；真正约束待 Phase C 聚合 |
| `units[1]` | 4,896,870（98.3%） | 标量槽占绝大多数，符合 GRHSIM 执行粒度 |
| `units[2]` | 32,900 | 少量 65–128 bit wide |
| `units[3,4]` | 13,671 | 合理尾部 |
| `units[5,8]` | 15,052 | 合理尾部 |
| `units[9,16]` | 21,772 | 需关注但不异常 |
| `units[17+]` | 1,027 | 极少数超宽 value |

类别计数：

| 类别 | count |
| --- | ---: |
| const | 27,507 |
| src | 288,355 |
| comp | 4,361,136 |
| sink | 304,294 |

per-kind 均值（节选）：

| kind | mean weight | 解读 |
| --- | ---: | --- |
| `kRegisterReadPort` | 2.027 | src=2，少量 wide read 拉高，合理 |
| `kMemoryReadPort` | 3.332 | memory read 更宽，归 src 后成本高于普通 comp，符合预期 |
| `kAssign` | 1.071 | 大多标量，少量 wide passthrough |
| `kSliceStatic` | 1.019 | 基本标量 |
| `kMux` | 1.012 | 基本标量 |
| `kAnd/kOr` | 1.138 / 1.124 | 少量 wide 逻辑 |
| `kConcat` | 1.458 | 拼接 naturally 更宽，合理 |
| `kShl` | 5.481 | 明显 wide-heavy，后续 Phase C/E 需要关注是否过度主导成本 |
| `kConstant` | 2.985 | 被超宽常量拉高；const 仍按 `0.125*units`，但 wide constants 可贡献 footprint/weight |

**结论**：Phase B cost-model 在完整 XiangShan 上基本合理。`units[1]` 占 98% 说明槽位取整没有把普通 8/9/31/64 位错误放大；`total_change_weight/total_weight≈0.36` 与 Phase A π 分布一致；src/memory read 成本高于普通 comp 符合预期。需关注但不阻塞：`kConstant` 和 `kShl` 的均值被少量超宽 value 拉高，Phase C 聚合时应观察 wide-heavy computeNode 是否影响增益排序。

完整 stop-after-activity-schedule 通过：`pass activity-schedule done 206278ms`，`total done 227714ms`，最终 `compute_nodes=1,188,094`、`compute_supernodes=73,605`、`commit_supernodes=502`，与 Phase D 口径一致。

---

### Step 4 — Phase C 超图聚合结构（2026-06-26）✅

**目标**：在 computeNode/MFFC seed 层建立概率超图聚合结构，为 Phase E/F 的概率驱动 coarsen/DP 提供数据；仍然只做分析/导出，不改变 final partition。默认 `plain` 不构建这些大数组。

**实现口径**

- 新增 `ActivityHypergraphAggregate`：
  - 每个 computeNode 维护 `W`、`change_weight=Σw·π`、`footprint_bytes`、`active_prob`、`[min_topo,max_topo]`、`op_count`。
  - 跨 computeNode 边维护 `edge_from/edge_to/edge_count/edge_total_prob`，其中 `edge_total_prob` 由边界 source value 的 canonical def op `π` 聚合。
- footprint 现在按 computeNode 内 canonical result value 去重，不再简单按 op 重复累加。
- source clone 通过 `canonicalValues` 回溯到原始 value / 原始 def op，clone source 的 `π/w/footprint` 语义与 PRE-clone Phase A/B 数据一致。
- 修复一个实际缺陷：`buildComputeNodeRewrite(...)` 之前没有把传入的 `canonicalValues` 保存到 `ComputeRewriteBuild::canonicalValues`；Phase C 单测暴露了 memory-read clone 的 `change_weight` 会缺失。现已保存。
- 导出 session values：
  - `*.activity_schedule.compute_node_weight`
  - `*.activity_schedule.compute_node_change_weight`
  - `*.activity_schedule.compute_node_footprint_bytes`
  - `*.activity_schedule.compute_node_active_prob`
  - `*.activity_schedule.compute_node_min_topo`
  - `*.activity_schedule.compute_node_max_topo`
  - `*.activity_schedule.compute_node_op_count`
  - `*.activity_schedule.compute_node_edge_from`
  - `*.activity_schedule.compute_node_edge_to`
  - `*.activity_schedule.compute_node_edge_count`
  - `*.activity_schedule.compute_node_edge_total_prob`

**单测**

- 新增「Phase C activity hypergraph aggregation」用例：
  - 构造 `MemoryReadPort -> And -> {Xor, Or}`，让 `And` 成为 common expression 边界。
  - 验证 `source clone + And + Xor` computeNode 的 `W/change_weight/footprint/active_prob`。
  - 验证 `And+Xor -> Or` 聚合边 `count=1`、`total_prob=π(and)=0.1`。
  - 该用例覆盖 canonical source clone：若 clone 不回溯原始 memory-read value，`change_weight` 会低估并失败。

**本地验证**

```sh
cmake --build wolvrix/build --target transform-activity-schedule -j$(nproc)  # OK
wolvrix/build/bin/transform-activity-schedule                                # EXIT=0
cmake --build wolvrix/build --target transform-pass-manager -j$(nproc)        # OK
wolvrix/build/bin/transform-pass-manager                                      # EXIT=0
.venv/bin/python3 -m pip install --no-build-isolation -e wolvrix              # OK，刷新 editable native 包
```

**完整 XiangShan sanity（stop-after-activity-schedule）**

命令口径同 Step 3，输出目录 `/tmp/xs_prob_phase_c_probe`，确认 `.venv` 已重装 editable 包。完整 stop-after 通过：`pass activity-schedule done 216863ms`，`total done 238159ms`。

关键 Phase C 日志：

| 指标 | 数值 |
| --- | ---: |
| computeNodes / hypergraph nodes | 1,188,094 |
| 聚合边数 | 3,348,059 |
| boundary_values | 3,796,122 |
| inter_node_boundary_values | 3,781,469 |
| canonical_clone_values | 2,068,514 |
| Phase C 聚合耗时 | 10,475ms |
| total_weight | 7,699,600 |
| total_change_weight | 2,397,380 |
| total_footprint_bytes | 19,301,152 |
| mean_active_prob | 0.565 |
| edge_total_prob | 1,342,060 |

分布（节选）：

| 指标 | p50 | p90 | p99 | max |
| --- | ---: | ---: | ---: | ---: |
| `W` | 2 | 9.125 | 101.375 | 3,513.38 |
| `footprint_bytes` | 2 | 15 | 192 | 180,180 |
| `active_prob` | 0.5545 | 0.9985 | 1.0 | 1.0 |
| `edge_count` | — | 1 | — | 108 |
| `edge_total_prob` | — | 0.7 | — | 107.871 |

**判定**

- Phase C 结构在 full XiangShan 上可构建，耗时约 10.5s，规模/内存形态可接受；final materialize 仍正常完成。
- `canonical_clone_values=2,068,514` 与 source clone 数一致，说明 clone canonical 口径被真实电路大量使用，必须保留。
- 大多数 computeNode footprint 很小（p90=15B），但 top 节点达 180KB 且 `active_prob=1`，后续 Phase E 的 `F_max`/`φ` 约束必须认真参与，不能只看 `W` 或 edge gain。
- `active_prob` p90 接近 1，说明按「边界/源 union」估计时很多簇几乎总激活；Phase E 增益应更多依赖 `change_weight`、`φ` 与 footprint，而不是单独按 `active_prob` 排序。

---

### Step 6 — Phase E 概率驱动 coarsen 第一版（2026-06-27）✅

**目标**：让 `partitionPolicy="prob"` 首次真正参与 compute supernode 划分，而不是只做 Phase A/B/C 分析后落回 plain coarsen。第一版按保守原则实现：局部候选、可回退、默认 `plain` 不变；先通过小图 gate，full XiangShan 结构 gate 留作下一步。

**实现口径**

- `materializeComputeNodeSchedule` 新增 prob 分支：`plain` 仍走原有 out1/in1/siblings fixed-point；`prob` 走 `tryMergeNodeProb`，之后继续复用现有 DP 分段和 final materialize。
- 候选来源：
  - 共享前驱 siblings：同 `preds` bucket 内相邻 sibling pair。
  - chain 补充：`pred -> succ` 且二者互为唯一邻居（受 `enableChainMerge` 控制）。
- 增益第一版：
  - `directSaved = p(lhs->rhs)*W(rhs) + p(rhs->lhs)*W(lhs)`。
  - `checkSaved = C_check(lhs)+C_check(rhs)-C_check(merged)`，`active_prob` 在 `[0.2,0.8]` 额外加 `cBpMiss`。
  - `increased = max(0, active(merged)*W(merged) - active(lhs)*W(lhs) - active(rhs)*W(rhs))`。
  - `gain = directSaved + checkSaved - increased`；高活跃簇允许 `gain==0`。
- 约束第一版：
  - `maxOpInComputeSupernode` 仍作为 op 数上限。
  - `W_max` 暂用同一个 `maxOpInComputeSupernode` 的量级作保守权重上限（后续若需要再加独立参数）。
  - `footprintMaxBytes` 阻止超大工作集合并。
  - `phiMin` 参与内聚度门槛；高活跃簇门槛减半。
  - 合并后必须通过现有 `orderNodeClustersTopologically`；若失败，整轮 batch 回退并计 `prob_reject_cycle`。
- 导出 `*.activity_schedule.prob_coarsen_stats` 字符串，含 `candidates/merges/gain/reject_*`，同时日志的 `compute-node coarsen detail` 增加 prob 统计列。

**测试**

```sh
cmake --build wolvrix/build --target transform-activity-schedule -j$(nproc)  # OK
wolvrix/build/bin/transform-activity-schedule                                # EXIT=0
cmake --build wolvrix/build --target transform-pass-manager -j$(nproc)        # OK
wolvrix/build/bin/transform-pass-manager                                      # EXIT=0
ctest --test-dir wolvrix/build --output-on-failure -R 'transform-activity-schedule|transform-pass-manager'  # 2/2 PASS
```

新增小图用例：

- `Phase E probability coarsen merges sibling candidates`：`shared -> {y,z}`，`maxOpInComputeNode=1`，`phiMin=0`，`footprintMaxBytes=1024`，断言 `prob_coarsen_stats.merges > 0`。
- `Phase E probability coarsen respects footprint cap`：同图但 `footprintMaxBytes=1`，断言 `merges==0` 且 `reject_footprint>0`。

**边界 / 下一步**

- 这不是最终 Phase E：还没有桶队列、top-k 候选、多轮局部增量更新、限深 BFS 分层无环检查，也没有 full XiangShan structure gate。
- 当前 active 概率合并用 `max(lhs,rhs)` 作保守近似，避免 Phase C 观察到的 `active_prob` 高饱和继续放大；若 full gate 显示过保守，再改成更精确的 union/相关性估计。
- 下一步应跑完整 XiangShan `-partition-policy=prob` + stop-after-activity-schedule，检查 `prob_candidates/prob_merges/reject_*`、`compute_supernodes`、boundary edges、timing 和是否无环；结构合理后再进 Step 7 概率加权 DP。

---

### Step 6 实测 — 完整 XiangShan structure gate（2026-06-27）✅

命令口径：

```sh
WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1 \
WOLVRIX_XS_GRHSIM_POST_STATS_JSON=build/xs/grhsim/wolvrix_xs_post_stats.json \
WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1 \
WOLVRIX_XS_GRHSIM_PARTITION_POLICY=prob \
WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE=108 \
WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE=4096 \
.venv/bin/python3 scripts/wolvrix_xs_grhsim.py \
  unused SimTop /tmp/xs_prob_phase_e_gate /tmp/xs_prob_phase_e_gate/out.json /dev/null info
```

先执行 `.venv/bin/python3 -m pip install --no-build-isolation -e wolvrix` 刷新 editable native 包。`STOP_AFTER_ACTIVITY_SCHEDULE=1` 下未写 `out.json`，只写 `activity_schedule_supernode_stats.json`，属正常。

**结果：activity-schedule 完整通过，无环。**

| 指标 | 数值 |
| --- | ---: |
| total done | 290,828ms |
| pass activity-schedule done | 269,193ms |
| final_materialize | 129,249ms |
| coarsen | 117,488ms |
| compute_node_build | 101,376ms |
| compute_nodes | 1,188,094 |
| pre-DP clusters_before | 1,188,094 |
| clusters_after prob coarsen | 928,020 |
| prob_candidates | 392,573 |
| prob_merges | 260,074 |
| prob_gain | 813,857.676 |
| reject_size | 58,093 |
| reject_weight | 35,321 |
| reject_phi | 1,998,997 |
| reject_footprint | 0 |
| reject_cycle | 0 |
| coarsen iterations | 11（tail stop，最后 delta=125） |
| DP segments / compute_supernodes before final split | 71,299 |
| final compute_supernodes | 71,337 |
| commit_supernodes | 502 |
| boundary_values | 1,514,185 |
| boundary_activation_edges | 3,067,308 |
| dag_edges | 1,534,219 |
| compute_ops_max / p99 | 108 / 108 |

**判定**

- 正确性/结构 gate 通过：final materialize 完成，`reject_cycle=0`，最终 `compute_ops_max=108` 保持 cap。
- prob coarsen 有实际作用：从 1.188M cluster 合到 928K，接受 260K 次 merge。
- 当前约束很保守：`reject_phi≈2.0M` 是主拒绝项，说明 `active=max(lhs,rhs)` + `phiMin` 组合强烈抑制低内聚合并；`reject_footprint=0`，说明 full 规模下 footprint cap 不是第一版瓶颈。
- 性能风险明确：coarsen 本身 117s，完整 activity-schedule 269s，明显慢于 Phase C plain-through 约 216s。第一版每轮重建 aggregate + 排序候选，11 轮约 10~11s/轮，符合预期但不可长期接受。
- 结构变化方向中性偏小：compute_supernodes 71,337，接近 Phase C 73,605 / Phase D 74,107 的量级，未出现结构爆炸；是否 runtime 有收益必须进入 emit/build/runtime 或先做 Phase F 概率加权 DP 对照。

**下一步建议**

1. 先优化 Phase E 实现形态：避免每轮全量重建 aggregate / 全量排序，至少加 top-k / 单轮候选 budget / 增量或局部重算，否则后续参数扫描成本过高。
2. 再决定是否直接进 Phase F 概率加权 DP。当前 Phase E 已经让结构 gate 通过，但收益未知、compile-time 变慢；Phase F 可能更直接改变 final `compute_supernodes` 的边界成本。
3. 如果先做 runtime gate，需完整 emit/build/50k，会把现在 117s coarsen 成本带进去；建议先做 emit-only/structure 对比，确认 generated code 形态没有明显回退。

### Step 6 优化 — 复用 singleton hypergraph 的 fast coarsen aggregate（2026-06-27）✅

实现：

- `tryMergeNodeProb` 不再每轮默认调用 `buildActivityHypergraphAggregate(...)` 全量重扫 graph/op/boundary；prob materialize 现在接收 Phase C 的 singleton `ActivityHypergraphAggregate` seed。
- 每轮 coarsen 从 seed 快速汇总当前 cluster：
  - node metrics：`weight/change/footprint/op_count` 求和，`active_prob` 取 max；
  - edge metrics：遍历 seed edge，用 `view.clusterOfNode` 重映射到当前 cluster pair，跳过 internal edge 后累计 `edgeTotalProb`。
- 保留 fallback：seed 不存在或尺寸不匹配时仍走原全量 aggregate，保证未来调用方式变化时行为可恢复。
- 增加可观测性：`prob_coarsen_stats` 和 coarsen detail 中记录 `seed_aggregates/full_aggregates/aggregate_ms`（本次完整 gate 后又补了普通 log 字段，未为该小日志补丁重跑完整 gate）。

验证：

```sh
cmake --build wolvrix/build --target transform-activity-schedule -j$(nproc)
wolvrix/build/bin/transform-activity-schedule
cmake --build wolvrix/build --target transform-pass-manager -j$(nproc)
wolvrix/build/bin/transform-pass-manager
ctest --test-dir wolvrix/build --output-on-failure -R 'transform-activity-schedule|transform-pass-manager'
```

均通过。

完整 XiangShan structure gate 命令：

```sh
WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1 \
WOLVRIX_XS_GRHSIM_POST_STATS_JSON=build/xs/grhsim/wolvrix_xs_post_stats.json \
WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1 \
WOLVRIX_XS_GRHSIM_PARTITION_POLICY=prob \
WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE=108 \
WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE=4096 \
.venv/bin/python3 scripts/wolvrix_xs_grhsim.py \
  unused SimTop /tmp/xs_prob_phase_e_fast_gate /tmp/xs_prob_phase_e_fast_gate/out.json /dev/null info
```

结果：`activity-schedule` 完整通过，`STOP_AFTER_ACTIVITY_SCHEDULE=1` 下仍只写 `/tmp/xs_prob_phase_e_fast_gate/activity_schedule_supernode_stats.json`，不写 `out.json`。

| 指标 | 优化前 | 优化后 |
| --- | ---: | ---: |
| total done | 290,828ms | 185,000ms |
| pass activity-schedule done | 269,193ms | 164,089ms |
| final_materialize | 129,249ms | 24,201ms |
| coarsen | 117,488ms | 12,476ms |
| compute_node_build | 101,376ms | 101,789ms |
| probability-hypergraph build | 约 10.5s | 10,431ms |
| clusters_after | 928,020 | 920,723 |
| prob_candidates | 392,573 | 400,850 |
| prob_merges | 260,074 | 267,371 |
| prob_gain | 813,857.676 | 1,186,578.580 |
| reject_size | 58,093 | 59,550 |
| reject_weight | 35,321 | 35,411 |
| reject_phi | 1,998,997 | 1,959,301 |
| reject_footprint | 0 | 0 |
| reject_cycle | 0 | 0 |
| coarsen iterations | 11 | 11 |
| DP segments | 71,299 | 71,405 |
| final compute_supernodes | 71,337 | 71,443 |
| commit_supernodes | 502 | 502 |
| compute_ops_max / p99 | 108 / 108 | 108 / 108 |

判定：

- 主要瓶颈解除：coarsen `117.5s → 12.5s`，final materialize `129.2s → 24.2s`，完整 activity-schedule `269.2s → 164.1s`。
- 结构 gate 仍通过：`reject_cycle=0`，`compute_ops_max=108`，commit supernode 数不变。
- 结果结构与第一版接近但不完全相同：fast aggregate 对 cluster `footprint/active/edgeTotalProb` 使用 seed 汇总近似，避免每轮 canonical value 去重；这会改变候选排序/接受边界，优化后 clusters 更少一些（920,723 vs 928,020），但 cap/cycle/backstop 仍成立。
- 当前剩余大头已经回到 `compute_node_build≈102s`，其中 50 次 cycle split 重建仍是下一阶段若要继续降 compile-time 的重点。

### Step 7 / Phase F — 概率加权 DP segment（2026-06-27）✅/⚠️

实现：

- `ClusterValueEdges` 记录每个 fanout entry 对应的原始 `ValueId`。
- `buildComputeSupernodeSegments` 的 cost 从整数 boundary count 泛化为 double 权重；plain 路径传 `nullptr`，仍等价于每个 value 权重 1。
- prob 路径为每个 boundary value 计算 `activityPiForValue(...)`，DP cost 从：
  - `incoming_unique_boundary_values + segment_penalty`
  - 改为 `sum(pi(crossing_value)) + segment_penalty`
- 目标：在容量约束不变时，优先把高活动边留在同一 final compute supernode，允许低活动边被 cut。

新增小图单测：

- 三段链 `xor -> reduce_and -> logic_not`，`maxOpInComputeSupernode=2`，关闭 coarsen 专测 DP。
- `xor` 输出活动度高于 `reduce_and` 输出；测试断言 DP 把 `xor/reduce_and` 放同一 segment，把低活动 `reduce_and -> logic_not` 边切开。

验证：

```sh
cmake --build wolvrix/build --target transform-activity-schedule -j$(nproc)
wolvrix/build/bin/transform-activity-schedule
cmake --build wolvrix/build --target transform-pass-manager -j$(nproc)
wolvrix/build/bin/transform-pass-manager
ctest --test-dir wolvrix/build --output-on-failure -R 'transform-activity-schedule|transform-pass-manager'
```

均通过。

完整 XiangShan structure gate 命令：

```sh
WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1 \
WOLVRIX_XS_GRHSIM_POST_STATS_JSON=build/xs/grhsim/wolvrix_xs_post_stats.json \
WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1 \
WOLVRIX_XS_GRHSIM_PARTITION_POLICY=prob \
WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE=108 \
WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE=4096 \
.venv/bin/python3 scripts/wolvrix_xs_grhsim.py \
  unused SimTop /tmp/xs_prob_phase_f_gate /tmp/xs_prob_phase_f_gate/out.json /dev/null info
```

结果：`activity-schedule` 完整通过，`STOP_AFTER_ACTIVITY_SCHEDULE=1` 下只写 `/tmp/xs_prob_phase_f_gate/activity_schedule_supernode_stats.json`，不写 `out.json`。

| 指标 | Phase E fast aggregate | Phase F prob DP |
| --- | ---: | ---: |
| total done | 185,000ms | 187,523ms |
| pass activity-schedule done | 164,089ms | 166,174ms |
| final_materialize | 24,201ms | 24,596ms |
| coarsen | 12,476ms | 12,601ms |
| dp_segment | 2,285ms | 2,410ms |
| clusters_after | 920,723 | 920,723 |
| DP segments | 71,405 | 70,558 |
| final compute_supernodes | 71,443 | 70,596 |
| commit_supernodes | 502 | 502 |
| boundary_values | 1,513,446 | 1,513,448 |
| boundary_activation_edges | 3,065,763 | 3,068,358 |
| compute_compute_value_pairs | 2,712,661 | 2,715,256 |
| dag_edges | 1,526,750 | 1,528,961 |
| outdeg_mean / p99 / max | 21.221 / 165 / 11,101 | 21.505 / 166 / 11,192 |
| compute_ops_max / p99 | 108 / 108 | 108 / 108 |
| reject_cycle | 0 | 0 |
| prob seed/full aggregates | 未在该日志打印 | 11 / 0 |
| prob aggregate_ms | 未在该日志打印 | 2,259ms |

判定：

- 结构 gate 通过：`reject_cycle=0`，`compute_ops_max=108`，commit supernode 数不变。
- Phase F 确实改变了 DP 切分：final compute supernodes `71,443 -> 70,596`，平均 compute ops/supernode `90.34 -> 91.42`。
- 但仅看 unweighted 结构指标，收益不成立：`boundary_activation_edges`、`compute_compute_value_pairs`、`dag_edges` 均小幅增加。这可能是合理的概率加权效果（切更多低 π 边、保留高 π 边），但当前 stats 还没有输出 weighted boundary cost，无法证明 runtime 方向变好。
- 下一步不建议直接用 Phase F 进 runtime gate；应先补 weighted-boundary 统计（例如 final boundary 的 `sum(pi(value))` / by-kind weighted activation），再决定是保留 `cost=pi`、改成 `1+α*pi`、还是加入 segment penalty scale 参数扫描。

---

### Step 7.5 — final weighted-boundary stats + Phase F A/B 判定（2026-06-27）✅

**目标**：补上 Step 7 的判定缺口。仅看 unweighted `boundary_activation_edges` 无法判断概率 DP 是否“切更多低 π 边、保留高 π 边”；必须在 final compute-supernode 结果上输出 weighted boundary cost，并用同源码 A/B 对比 Phase E baseline vs Phase F。

**实现**

- `ActivityScheduleSummaryStats` / `summary_stats` JSON 新增 final weighted 指标：
  - `boundary_value_pi_sum` / `boundary_edge_pi_sum`
  - `compute_compute_edge_pi_sum` / `compute_commit_edge_pi_sum`
  - `boundary_value_change_weight_sum` / `boundary_edge_change_weight_sum`
  - `compute_compute_edge_change_weight_sum` / `compute_commit_edge_change_weight_sum`
  - `activation_edge_pi_by_source_kind` / `activation_edge_change_weight_by_source_kind`
- 统计口径：
  - value 口径：每个跨 supernode value 算一次；
  - edge 口径：按 fanout target 展开，和 `boundary_activation_edges` / `compute_compute_value_pairs` 对齐；
  - `pi(value)` 复用 Phase A 的 `activityPiForValue(...)` canonical 口径；
  - `change_weight(value)=pi(value)*source_compute_weight`，source clone 回溯 canonical 原值。
- 新增 `ActivityScheduleOptions::probDpCost` / CLI `-prob-dp-cost true|false` / XS 环境变量 `WOLVRIX_XS_GRHSIM_PROB_DP_COST`。
  - `probDpCost=false`：prob coarsen 仍开启，但 DP 回到 unweighted，作为 Phase E fast aggregate baseline；
  - `probDpCost=true`：启用 Step 7 当前 `cost=pi` 概率 DP。
- 默认值改为 **false**：Step 7.5 A/B 证明当前 `cost=pi` 没有 weighted 收益，故不应作为默认 prob 路径。

**本地验证**

```sh
cmake --build wolvrix/build --target transform-activity-schedule -j$(nproc)
cmake --build wolvrix/build --target transform-pass-manager -j$(nproc)
ctest --test-dir wolvrix/build --output-on-failure -R 'transform-activity-schedule|transform-pass-manager'
```

结果：2/2 PASS。新增小图覆盖：

- `probDpCost=true` 时三段链 `xor -> reduce_and -> logic_not` 保留高 π 边、切低 π 边，`compute_compute_edge_pi_sum≈0.095`。
- `probDpCost=false` 时同图回到 unweighted tie-break，切高 π 边，`compute_compute_edge_pi_sum≈0.19`。

**完整 XiangShan A/B（stop-after-activity-schedule，同源码）**

公共口径：

```sh
WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1 \
WOLVRIX_XS_GRHSIM_POST_STATS_JSON=build/xs/grhsim/wolvrix_xs_post_stats.json \
WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1 \
WOLVRIX_XS_GRHSIM_PARTITION_POLICY=prob \
WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE=108 \
WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE=4096 \
WOLVRIX_XS_GRHSIM_PROB_DP_COST=<0|1> \
.venv/bin/python3 scripts/wolvrix_xs_grhsim.py \
  unused SimTop /tmp/xs_prob_phase_7_5_dp_<off|on> /tmp/xs_prob_phase_7_5_dp_<off|on>/out.json /dev/null info
```

结果均通过，无环、cap 正常。输出 JSON：

- baseline：`/tmp/xs_prob_phase_7_5_dp_off/activity_schedule_supernode_stats.json`
- Phase F：`/tmp/xs_prob_phase_7_5_dp_on/activity_schedule_supernode_stats.json`

| 指标 | `probDpCost=false`（Phase E baseline） | `probDpCost=true`（Phase F `cost=pi`） | Δ |
| --- | ---: | ---: | ---: |
| total done | 185,760 ms | 187,075 ms | +1,315 ms |
| pass activity-schedule | 164,323 ms | 165,681 ms | +1,358 ms |
| compute_supernodes | 71,443 | 70,596 | **−847** |
| dag_edges | 1,526,750 | 1,528,961 | +2,211 |
| boundary_values | 1,513,446 | 1,513,448 | +2 |
| boundary_activation_edges | 3,065,763 | 3,068,358 | +2,595 |
| compute_compute_value_pairs | 2,712,661 | 2,715,256 | +2,595 |
| boundary_value_pi_sum | 513,383.666 | 513,384.841 | +1.175 |
| boundary_edge_pi_sum | 1,045,171.534 | 1,045,480.524 | **+308.990** |
| compute_compute_edge_pi_sum | 915,448.728 | 915,757.718 | **+308.990** |
| boundary_edge_change_weight_sum | 1,292,711.596 | 1,293,086.328 | **+374.732** |
| compute_compute_edge_change_weight_sum | 1,152,421.710 | 1,152,796.442 | **+374.732** |

**判定**

- Step 7 的“unweighted 指标小幅上升可能合理”被 Step 7.5 否定：weighted edge pi / weighted change weight 也小幅上升。
- 当前 Phase F `cost=sum(pi(crossing_value))+segment_penalty` 只减少 supernode 数（71,443→70,596），没有降低 final boundary 的概率加权代价；不应进入 runtime gate，也不应作为 Phase G/FM 的基准。
- 保留实现和门控，默认 `probDpCost=false`，即 `partitionPolicy=prob` 默认停在 Phase E fast aggregate。
- 下一步应先修正 Phase F cost，再考虑 Step 8/FM。候选方向：
  1. 改 `cost=1+α*pi`，避免 DP 为了减少 segment 数过度牺牲 boundary；
  2. 扫描/门控 `segment_penalty`，当前固定 1 可能过强；
  3. 用 `pi*W(dst)` 或 `change_weight` 贴近 Phase E/NO0190 目标，而不是只用 source `pi`；
  4. weighted stats 作为 gate：Phase F 必须同时满足 `compute_supernodes` 不爆、`boundary_edge_pi_sum` 或 `boundary_edge_change_weight_sum` 不升。

---

### Step 7.6 — mixed DP cost 修正 + 参数扫描（2026-06-28）✅

**目标**：修正 Step 7.5 发现的 DP cost 方向错误。纯 `cost=pi` 会把每段固定 penalty 变成主导项：DP 倾向减少 segment 数，最终虽然 `compute_supernodes` 下降，但切出了更多高权重 boundary。修正思路是把 edge-count 的稳定项保留下来，再叠加概率项：

- `pi`：`cost(value)=pi(value)`，保留失败基线；
- `change`：`cost(value)=pi(value)*source_weight(value)`；
- `mixed-pi`：`cost(value)=1 + α*pi(value)`；
- `mixed-change`：`cost(value)=1 + α*pi(value)*source_weight(value)`；
- `segment_penalty` 独立参数化，只在 `probDpCost=true` 时参与；`probDpCost=false` 固定回到 unweighted DP 的 `penalty=1.0`，确保 Phase E baseline 不被参数误伤。

**实现**

- `ActivityScheduleOptions` 新增：
  - `probDpCostMode`，取值 `pi|mixed-pi|change|mixed-change`；
  - `probDpAlpha`；
  - `probDpSegmentPenalty`。
- CLI 新增 `-prob-dp-cost-mode` / `-prob-dp-alpha` / `-prob-dp-segment-penalty`，XS 脚本新增对应环境变量：
  - `WOLVRIX_XS_GRHSIM_PROB_DP_COST_MODE`
  - `WOLVRIX_XS_GRHSIM_PROB_DP_ALPHA`
  - `WOLVRIX_XS_GRHSIM_PROB_DP_SEGMENT_PENALTY`
- 默认仍为 `probDpCost=false`；显式启用 Phase F 时的默认参数改为 `mixed-pi, α=1.0, segment_penalty=1.25`。

**本地验证**

```sh
cmake --build wolvrix/build --target transform-activity-schedule -j32
cmake --build wolvrix/build --target transform-pass-manager -j1
ctest --test-dir wolvrix/build --output-on-failure -R 'transform-activity-schedule|transform-pass-manager'
```

结果：2/2 PASS。

**完整 XiangShan scan（stop-after-activity-schedule）**

公共口径同 Step 7.5，差异仅为 `WOLVRIX_XS_GRHSIM_PROB_DP_COST*` 参数。`baseline` 仍使用 `/tmp/xs_prob_phase_7_5_dp_off/activity_schedule_supernode_stats.json`，即 `probDpCost=false` 的 Phase E fast aggregate。

| case | compute_supernodes | dag_edges Δ | boundary_activation_edges Δ | boundary_edge_pi_sum Δ | boundary_edge_change_weight_sum Δ |
| --- | ---: | ---: | ---: | ---: | ---: |
| `cost=pi` | 70,596 | +2,211 | +2,595 | +308.990 | +374.732 |
| `mixed-pi α=0.5 p=1.0` | 72,259 | −723 | −813 | −287.834 | −383.691 |
| `mixed-pi α=1.0 p=1.0` | 72,266 | −711 | −806 | −306.385 | −402.242 |
| `mixed-pi α=2.0 p=1.0` | 72,299 | −658 | −800 | −331.556 | −423.178 |
| `mixed-pi α=1.0 p=1.25` | 71,656 | −227 | −200 | −202.453 | −289.575 |
| `mixed-pi α=2.0 p=1.25` | 72,078 | −582 | −597 | −302.017 | −391.538 |

baseline 绝对值：`compute_supernodes=71,443`、`dag_edges=1,526,750`、`boundary_activation_edges=3,065,763`、`boundary_edge_pi_sum=1,045,171.534`、`boundary_edge_change_weight_sum=1,292,711.596`。

**判定**

- `cost=pi` 明确失败：supernode 减少但 weighted/unweighted boundary 都上升。
- `mixed-pi` 方向正确：扫描到的所有 mixed 点都降低 `boundary_edge_pi_sum` 和 `boundary_edge_change_weight_sum`，同时 unweighted boundary/dag edges 也低于 baseline。
- `α=2.0` weighted 收益更大，但 supernode 增幅也更大；`α=1.0, penalty=1.25` 是当前最保守的正收益点：`compute_supernodes` 只比 baseline 多 213（+0.30%），同时 `boundary_edge_pi_sum` 降 202.453、`boundary_edge_change_weight_sum` 降 289.575。
- 因此 Phase F 修正后可以作为显式实验候选，但仍不改 `partitionPolicy=prob` 默认行为：默认 `probDpCost=false` 停在 Phase E；runtime gate 时显式设置 `WOLVRIX_XS_GRHSIM_PROB_DP_COST=1`。

---

### Step 8 — Phase G FM 边界精修第一版（2026-06-28）✅/⏳

**目标**：在 DP 产出的 compute supernode 分段之后，做概率加权的边界局部移动，降低 final weighted boundary cost。接入点位于 `buildComputeSupernodeSegments(...)` 之后、`flattenNodeSegments(...)` 之前；plain 路径不变。

**实现口径**

- 仅 `partitionPolicy="prob"` 生效；`fmRefineMaxRounds=0` 可显式关闭。默认 prob 路径现在是 Phase E + DP + FM，`probDpCost=false` 时仍用普通 DP 作为 FM 初始解。
- 第一版移动单位是 DP 看到的 `NodeClusterView` cluster（coarsen 后 computeNode 组），不拆 Phase E 已合并的 cluster；后续如 full gate 显示收益不足，再评估更细的 singleton computeNode FM。
- 候选只来自直接邻居 supernode：有跨段 pred/succ 的边界 cluster 可移动到对应邻居段。
- 增益使用 `ClusterValueEdges` 的 final boundary value fanout 和 Phase F 的 value weight：`mixed-pi`/`mixed-change` 等模式复用 `buildProbSegmentValueWeights(...)`；`probDpCost=false` 时 FM 仍使用默认 `mixed-pi α=1.0` 权重评估边界。
- 约束：目标段 `maxOpInComputeSupernode`、`footprintMaxBytes`、`phiMin`、weight cap；source 段不允许被移空。
- 无环检查：采用保守 topo-order segment 检查，要求移动后所有外部 pred segment `< newSegment <` 外部 succ segment。它会拒绝一部分理论可行的非连续重排，但保证不依赖 final Kahn 兜底。
- 统计：`prob_coarsen_stats` 与日志新增 `fm_rounds/fm_candidates/fm_moves/fm_gain/fm_reject_* / fm_ms`，XS 脚本新增 `WOLVRIX_XS_GRHSIM_FM_REFINE_MAX_ROUNDS` 便于 on/off A/B。

**本地验证**

```sh
cmake --build wolvrix/build --target transform-activity-schedule -j32
python3 -m py_compile scripts/wolvrix_xs_grhsim.py
wolvrix/build/bin/transform-activity-schedule
cmake --build wolvrix/build --target transform-pass-manager -j32
ctest --test-dir wolvrix/build --output-on-failure -R 'transform-activity-schedule|transform-pass-manager'
```

结果：全部通过。新增小图覆盖：

- `probDpCost=false + FM on`：三节点链 `xor -> reduce_and -> logic_not` 中，普通 DP 会切高 π 边；FM 移动中间节点后保留高 π 边、切低 π 边，`compute_compute_edge_pi_sum≈0.095`，`fm_moves>0`。
- 原 Step 7/7.5/7.6 的 DP 用例显式设置 `fmRefineMaxRounds=0`，继续验证纯 DP 行为，避免被 FM 后处理掩盖。

**边界 / 下一步**

- 完整 XiangShan structure gate 见下一节；CoreMark 50k plain 对比见再下一节。
- 若 full gate 中 `fm_moves` 很少或收益有限，再评估把移动单位从 coarsen cluster 下探到 singleton computeNode。

---

### Step 8 实测 — 完整 XiangShan FM structure gate（2026-06-28）✅

公共口径：

```sh
WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1 \
WOLVRIX_XS_GRHSIM_POST_STATS_JSON=build/xs/grhsim/wolvrix_xs_post_stats.json \
WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1 \
WOLVRIX_XS_GRHSIM_PARTITION_POLICY=prob \
WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE=108 \
WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE=4096 \
WOLVRIX_XS_GRHSIM_PROB_DP_COST=<0|1> \
WOLVRIX_XS_GRHSIM_PROB_DP_COST_MODE=mixed-pi \
WOLVRIX_XS_GRHSIM_PROB_DP_ALPHA=1.0 \
WOLVRIX_XS_GRHSIM_PROB_DP_SEGMENT_PENALTY=1.25 \
WOLVRIX_XS_GRHSIM_FM_REFINE_MAX_ROUNDS=<0|4> \
.venv/bin/python3 scripts/wolvrix_xs_grhsim.py \
  unused SimTop /tmp/xs_prob_fm_gate_<case> /tmp/xs_prob_fm_gate_<case>/out.json /dev/null info
```

运行前刷新 native 包：

```sh
cmake --build wolvrix/build --target transform-activity-schedule -j32
.venv/bin/python3 -m pip install --no-build-isolation -e wolvrix
```

四组均 stop-after-activity-schedule 通过，无 final topo 环，`compute_ops_max=108` 不破；commit supernodes 均为 `502`。

| case | 输出目录 | total done | pass activity-schedule | final_materialize | dp_segment | fm_refine | fm_moves | fm_reject_cycle | compute_supernodes |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `dp0_fm0` | `/tmp/xs_prob_fm_gate_dp0_fm0` | 186,958 ms | 165,601 ms | 24,404 ms | 2,280 ms | 0 ms | 0 | 0 | 71,443 |
| `dp0_fm4` | `/tmp/xs_prob_fm_gate_dp0_fm4` | 193,130 ms | 171,789 ms | 31,054 ms | 2,293 ms | 6,818 ms | 172,701 | 762,430 | 71,443 |
| `dp1_fm0` | `/tmp/xs_prob_fm_gate_dp1_fm0` | 186,540 ms | 165,345 ms | 24,837 ms | 2,603 ms | 0 ms | 0 | 0 | 71,656 |
| `dp1_fm4` | `/tmp/xs_prob_fm_gate_dp1_fm4` | 194,101 ms | 172,716 ms | 30,951 ms | 2,589 ms | 6,347 ms | 175,258 | 770,865 | 71,656 |

以 `dp0_fm0`（Phase E baseline）为基准：

| case | dag_edges Δ | boundary_activation_edges Δ | boundary_edge_pi_sum Δ | boundary_edge_change_weight_sum Δ |
| --- | ---: | ---: | ---: | ---: |
| `dp0_fm0` | 0 | 0 | 0.000 | 0.000 |
| `dp0_fm4` | **−133,647** | **−171,643** | **−63,284.323** | **−54,929.540** |
| `dp1_fm0` | −227 | −200 | −202.453 | −289.575 |
| `dp1_fm4` | **−136,141** | **−175,015** | **−65,226.638** | **−56,841.157** |

绝对值：

| case | dag_edges | boundary_activation_edges | boundary_edge_pi_sum | boundary_edge_change_weight_sum |
| --- | ---: | ---: | ---: | ---: |
| `dp0_fm0` | 1,526,750 | 3,065,763 | 1,045,171.534 | 1,292,711.596 |
| `dp0_fm4` | 1,393,103 | 2,894,120 | 981,887.211 | 1,237,782.057 |
| `dp1_fm0` | 1,526,523 | 3,065,563 | 1,044,969.082 | 1,292,422.022 |
| `dp1_fm4` | 1,390,609 | 2,890,748 | 979,944.896 | 1,235,870.439 |

**判定**

- FM structure gate 明确正向：在默认 `probDpCost=false` 上，FM 降低 `boundary_activation_edges` 约 17.16 万、`boundary_edge_pi_sum` 约 6.33 万、`boundary_edge_change_weight_sum` 约 5.49 万。
- `mixed-pi` DP 与 FM 可叠加：`dp1_fm4` 是四组里结构指标最优，较 baseline 降低 `boundary_edge_pi_sum` 约 6.52 万、`boundary_edge_change_weight_sum` 约 5.68 万。
- 成本：FM 增加约 6.3–6.8s `fm_refine`，总 stop-after 增加约 6–8s；没有出现 materialize 长尾。
- `fm_reject_cycle≈0.76M` 较高，说明保守 topo segment 检查拒绝了大量候选；这是安全拒绝，不是 correctness failure。若后续需要更多收益，可优化无环检查而不是下探移动粒度优先。
- 下一步先做 plain 对照 runtime gate，确认是否存在“静态结构较差但实际仿真更快”的反例。

---

### Step 8 实测 — CoreMark 50k plain vs `dp1_fm4` runtime（2026-06-28）✅/❌

目的：回答 `dp1_fm4` 虽然相对 plain 静态结构更差，是否仍可能在实际 `coremark` 50k 仿真时间上更好。

公共口径：

- workload：`testcase/xiangshan/ready-to-run/coremark-2-iteration.bin`
- difftest：on（`--diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`）
- cycle bound：`XS_SIM_MAX_CYCLE=50000`
- waveform / commit trace / GrhSIM perf：off
- `XS_PROGRESS_EVERY_CYCLES=25000`
- 两组各自 fresh emit/build，独立 `XS_GRHSIM_BUILD`，共同 resume 同一份 `build/xs/grhsim/wolvrix_xs_post_stats.json`

运行目录 / 日志：

| case | build dir | build log | runtime log |
| --- | --- | --- | --- |
| `plain` | `build/xs/grhsim_plain_coremark50k` | `build/logs/xs/xs_wolf_grhsim_build_coremark50k_plain_20260628.log` | `build/logs/xs/xs_wolf_grhsim_coremark50k_plain_run_20260628.log` |
| `prob_dp1_fm4` | `build/xs/grhsim_prob_dp1_fm4_coremark50k` | `build/logs/xs/xs_wolf_grhsim_build_coremark50k_prob_dp1_fm4_20260628.log` | `build/logs/xs/xs_wolf_grhsim_coremark50k_prob_dp1_fm4_run_20260628.log` |

结构对照：

| case | compute_supernodes | dag_edges | boundary_activation_edges | compute_compute_value_pairs |
| --- | ---: | ---: | ---: | ---: |
| `plain` | 72,180 | 702,085 | 2,451,342 | 2,098,240 |
| `prob_dp1_fm4` | 71,656 | 1,390,609 | 2,890,748 | 2,537,646 |
| `prob_dp1_fm4 / plain` | 0.993x | 1.981x | 1.179x | 1.209x |

runtime 结果：

| case | gate | host time | cycles/s | 25k host_ms | instrCnt | cycleCnt | guest cycle spent |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `plain` | `coremark50k-fast` PASS | 326,433 ms | 153.17 | 128,141 | 73,580 | 49,996 | 50,001 |
| `prob_dp1_fm4` | `coremark50k-fast` FAIL | 628,792 ms | 79.52 | 264,415 | 73,580 | 49,996 | 50,001 |

机器解析命令：

```sh
.venv/bin/python3 scripts/grhsim_opt_metrics.py \
  --gate coremark50k-fast \
  --perf-log build/logs/xs/xs_wolf_grhsim_coremark50k_plain_run_20260628.log \
  --pretty

.venv/bin/python3 scripts/grhsim_opt_metrics.py \
  --gate coremark50k-fast \
  --perf-log build/logs/xs/xs_wolf_grhsim_coremark50k_prob_dp1_fm4_run_20260628.log \
  --pretty
```

判定：

- 两组 correctness 口径一致：difftest enabled，均跑到 50k cycle limit，`instrCnt=73580`、`cycleCnt=49996`、`Guest cycle spent=50001` 完全一致。
- `prob_dp1_fm4` 相对 plain 慢 `628792 / 326433 = 1.93x`，没有出现“静态结构更差但 runtime 更好”的反例。
- 25k 中途点也同向：`264415 / 128141 = 2.06x`，说明不是尾段偶然波动。
- 本轮结果说明当前 prob/FM 的 weighted-boundary 优化目标没有对齐 runtime 主成本；相对 plain 的 `dag_edges`、`boundary_activation_edges`、`compute_compute_value_pairs` 增幅直接体现在仿真时间回退上。
- 后续不建议继续把 `prob_dp1_fm4` 作为 runtime 候选推进。若继续研究 Step 8，应优先回到 plain 静态结构约束下优化，或只把 FM 用作 prob 内部诊断，而不是进入默认/候选 runtime 路径。

---

## 待办索引

- [x] Step 2 Phase A：`π` 传播 + 源代表 + 直方图/high-activity/multi-source 统计 + 小图单测
- [x] Step 3 Phase B：op 级 `compute_weight` / `change_weight` / `footprint_bytes`（GRHSIM 槽位取整）+ 小图单测
- [x] Step 3 完整 XiangShan cost-model sanity-check → **通过**（`units[1]=98.3%`，`change/weight≈0.36`；关注 wide `kConstant/kShl`）
- [x] Step 4 Phase C：computeNode 概率超图聚合 + canonical source clone 回溯 + 小图单测
- [x] Step 4 完整 XiangShan sanity-check → **通过**（1.188M nodes、3.35M edges、聚合 10.5s；关注 high-footprint/high-active 节点）
- [x] Step 6 Phase E 第一版：prob coarsen 接入 materialize（siblings/chain 候选、增益、`φ/W/F`、无环 backstop、stats）+ 小图单测
- [x] Step 6 完整 XiangShan structure gate → **通过**（`prob_merges=260074`、`reject_cycle=0`、`compute_supernodes=71337`；但 coarsen=117s，需优化）
- [x] Step 6 coarsen fast aggregate 优化 → **通过**（coarsen `117.5s→12.5s`、final materialize `129.2s→24.2s`、`reject_cycle=0`、`compute_supernodes=71443`）
- [x] Step 7 Phase F 概率加权 DP segment → **结构通过但收益混合**（`compute_supernodes=70596`，但 unweighted `boundary_activation_edges` 小幅上升；需补 weighted-boundary stats）
- [x] Step 7.5 final weighted-boundary stats + A/B 判定 → **当前 Phase F `cost=pi` weighted 也变差，默认关闭 `probDpCost`**
- [x] Step 7.6 mixed DP cost 修正 + 参数扫描 → **`mixed-pi α=1.0 penalty=1.25` 为保守正收益候选；默认仍关闭，显式 Phase F 可启用**
- [x] Step 8 Phase G FM 边界精修第一版 → **本地通过**（prob-gated、FM stats、`fmRefineMaxRounds=0` 可关）
- [x] Step 8 完整 XiangShan structure gate：Phase E/F × FM on/off 四组 A/B → **通过且结构正向**（最佳 `dp1_fm4`：`boundary_edge_pi_sum −65,226.638`、`boundary_edge_change_weight_sum −56,841.157`）
- [x] Step 8 runtime probe：`plain` vs `dp1_fm4` CoreMark 50k → **负向**（`326,433ms` vs `628,792ms`，`dp1_fm4` 慢 `1.93x`）
- [ ] （可选）若要拆分归因，再补 `dp0_fm0` / `dp0_fm4` / `dp1_fm4` 50k A/B；当前 plain 对照已足够否定作为 runtime 候选
- [x] 在真实 XiangShan 上 `-partition-policy=prob` 检视 `π` 直方图 → **发现过饱和（62% @ π≥0.95）**
- [x] symbol 级源去相关重测 → **负结果（Δmulti_source −60，饱和是真实多寄存器扇入）**
- [x] **算法修复（transition-density 转移函数）→ 去饱和成功**（π≥0.95: 62.4%→4.9%）；静态层次 2 可用，不转 profiling
- [x] transition-density per-kind/per-depth sanity-check（完整 XiangShan）→ **合理**（per-kind 符合语义、per-depth ~0.5 plateau 不饱和）
- [ ] （可选）细化透传类衰减以压低深逻辑 ~0.5 plateau；kLShr/kSliceArray 偏高复核
- [ ] 信号概率 p1 是否值得从固定 0.5 升级为真传播（常量按位、寄存器先验）
- [x] η 测量（完整 XiangShan）→ **η_edge=0.92，computeNode 忠实 MFFC**；over-split ~14%（部分合理）
- [x] MFFC 合并（topo 连续分块，仅 prob）→ **η 0.92→0.96、nodes 1.40M→1.19M、common-expr −38%**，残余 4% 为合理约束（cap/intent/cycle-safety）
- [ ] （可选）优化 prob 下 compute_node_build ~110s（减少 50 次 cycle-split 重建）；如需更高 η 评估放宽 cap / 合并 intent 的风险
- [ ] 时钟输入 `π=1` 识别
- [ ] numeric 参数 `=` 形式 + XS 脚本 env→arg 接线（待 phase 消费）
- [ ] `partition_policy`/`pi_*` 等 stat 列进 `summary_stats` JSON（Phase I 增量）
- [ ] prob==plain 一致性单测（prob 分叉前的回归锁）

---

## 附录 A：静态 π 饱和的根因分析（旧临时 NO0209 合并）

> 本附录把旧临时独立诊断文档的有效分析并入；该旧稿已删除，正式 `NO0209` 编号现在用于 `prob/FM` runtime 失败复盘。现象数据见上文 Step 2 实测 1/2，结论已被 transition-density 修复推翻（实测 3/4）。

### A.1 现象（乘积补版，PRE-clone 498 万 ops）

双峰、重心在饱和端：`[.2,.5)` 24%、`[.95,1]` **62.4%**；high_activity（π≥0.9）**64.8%**；multi_source **96%** of compute。两次实测（源代表 op 身份 vs register/latch symbol）几乎无差（Δmulti_source −60）。

### A.2 根因：前向乘积补度量错了量

1. **度量「P(任一输入变化)」而非「P(输出变化)」**：组合 op 用 `π=1-Π(1-π_in)`，是「至少一个输入变了」的概率。但 mux 未选中通路、掩码位、稳定比较/算术——输入动、输出不动，前向乘积补看不到，系统性高估。
2. **单调饱和**：`1-Π(1-π)` 只增不减，深逻辑必然冲向 1。`piReg=0.2` 下 combine `k` 个独立输入 `π=1-0.8^k`：k=2→0.36、k=5→0.67、k=10→0.89、k=20→0.99。降先验只把饱和往后推几层，治标不治本。
3. **相关性修正救不回**：去相关只合并同源输入；实测 96% multi_source 是**真实多寄存器扇入**（post-reg-to-mem 每寄存器基本只一个 read port），symbol 级去相关只动 `60/4.19M`。
4. **与真实活动差距**：62% 节点近 always-active 物理上不可信（CPU 大部分每周期空闲）。

### A.3 修复（推翻「静态不可用」结论）

把「一律乘积补」换成 transition-density 式转移函数：逻辑掩蔽点（AND/OR `p1=0.5`→敏感度 `0.5^(n-1)`、mux 选择、比较/归约位宽收缩 ×0.5）衰减活动度，仅 XOR/算术/拼接保留透传（乘积补），信号概率固定 `p1=0.5`。饱和消失（π≥0.95: 62.4%→4.9%、high_activity: 64.8%→5.9%；per-kind/per-depth 合理性见实测 3/4）。**根因是公式选错，不是「前向静态本质不可行」**——故不转 profiling。

### A.4 复现命令

```sh
WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1 \
WOLVRIX_XS_GRHSIM_POST_STATS_JSON=build/xs/grhsim/wolvrix_xs_post_stats.json \
WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1 \
WOLVRIX_XS_GRHSIM_PARTITION_POLICY=prob \
WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE=108 \
WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE=4096 \
.venv/bin/python3 scripts/wolvrix_xs_grhsim.py \
  unused SimTop /tmp/xs_prob_probe /tmp/xs_prob_probe/out.json /dev/null info
```

日志里 `grep` 关键行：`probability(pi)`（直方图）、`pi mean by kind` / `pi mean by depth`（合理性）、`mffc-coverage`（η）。
