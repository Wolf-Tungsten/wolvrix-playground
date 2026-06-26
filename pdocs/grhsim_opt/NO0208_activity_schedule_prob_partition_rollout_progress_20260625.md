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
| Step 3 | Phase B：节点成本 `w(v)`（类别对齐 NO0190） | 待开始 |
| Step 4 | Phase C：超图聚合结构 | 待开始 |
| **Step 5** | Phase D：MFFC 忠实度校验 + 合并到理想（`η`） | ✅ 已测+已合并（η 0.92→**0.96**，nodes 1.40M→1.19M，over-split −38%；残余为合理约束） |
| Step 6 | Phase E：概率驱动粗化（增益+三层无环+φ/W/F） | 待开始 |
| Step 7 | Phase F：概率加权 DP | 待开始 |
| Step 8 | Phase G：FM 边界精修 | 待开始 |
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

## 待办索引

- [x] Step 2 Phase A：`π` 传播 + 源代表 + 直方图/high-activity/multi-source 统计 + 小图单测
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

## 附录 A：静态 π 饱和的根因分析（原 NO0209 合并）

> 本附录把原独立诊断文档 `NO0209` 的有效分析并入；`NO0209` 已删除。现象数据见上文 Step 2 实测 1/2，结论已被 transition-density 修复推翻（实测 3/4）。

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
