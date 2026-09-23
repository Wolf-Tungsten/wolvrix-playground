# NO00058：机制税与框架税画像基线（纯 profile 节点）

- 状态：profile（2026-09-23 用户指示设立；本节点只做画像，不做优化尝试）
- 目的：把 NO00057 及近期节点积累的近期 profile 数据汇总为自包含基线，指导后续节点；
  后续节点的假设必须引用本文件的数字来论证收益上界。
- 数据版本：GrhSIM-IR 当前最佳 NO00055（wolvrix `7b1fd50`，71.309667 s）；
  gsim 归档 46.965 s。测量配置：`coremark-2-iteration.bin`，100k cycles，
  `XS_NUM_CORES=1 XS_EMU_THREADS=1 XS_EMU_CPU=2`，trace 全关。
- 仪器：GrhSIM-IR 动态插桩构建 `ptmp/no00057_semantic_fixpoint_20260922/flow-dyn`
  （dynamic-stats，计时仅诊断用）；gsim 画像构建 `build/xs/gsim-prof/`
  （`GSIM_EMIT_RUNTIME_PROFILE=1`，与归档参考 emu 隔离）；gperftools 画像
  `ptmp/no00057_semantic_fixpoint_20260922/profile-old`；两侧干净 perf stat。

## 1. 差距总账（两端 100k 端到端实测）

| 指标 | gsim | GrhSIM-IR | 比值 |
|---|---|---|---|
| Host time（归档/正式） | 46.965 s | 71.310 s | **1.518×** |
| instructions /100k（30k 窗口外推） | 135 G | 382 G | **2.83×** |
| host cycles /100k | 190 G | 279 G | 1.47× |
| IPC | 0.71 | 1.37 | 我们优 1.93× |
| branch-misses /100k | 3.80 G | 2.82 G | 我们少 0.74× |
| 求值体积（node/op 执行次数） | 82.9 G nodes | 99.5 G ops | **1.20×** |
| 每求值单位指令数 | 1.63 instr/node | 3.84 instr/op | **2.36×** |

核算：时间比 = 指令数比 ÷ IPC 比 = 2.83 ÷ 1.93 ≈ 1.52 ✓ 与墙钟实测吻合。
**结论：差距不在求值体积（仅 1.20×），而在每 op 指令数（2.36×）——框架税；
我们的 IPC 优势（无分支形态）抵消了一部分。**

## 2. 框架税（framework tax）构成

定义：每求值 op 超出原始逻辑本身的指令开销（活动度/写回/扇出/提交/物化机制）。

- 相位分割（NO00055 画像，71.5s eval 内）：**compute 53.63 s（75.0%）**、
  commit 16.85 s（23.6%）、publish 0.86 s（1.2%）。
- 动态 op 混合（99.48G ops/run）：and 26.0% / or 21.6% / mux 11.6% / eq 6.9% /
  bitSelect 4.8% / concat 4.2% / sliceStatic 3.6% / state.read 3.4% / add 3.1% /
  logicNot 2.2% / constant 1.9%。
- **boundary 写回：22.13G 次/run（≈110.6k 次/eval），真实变化率仅 5.73%**；
  按 op kind 分布 and 7.15G（变化率 1.35%）/ mux 2.89G（13.3%）/ eq 2.77G（2.31%）。
- 扇出发布：grp_pub 854.7M/run（grp_fire 255.4M，有效率 29.9%）。
- commit 端口：port_eval 669.6M/run（≈1,669/round），开火率 70.3%；
  每次开火评估 ~93 cyc（NO00047 归因：误预测 ~29 cyc + L1 miss + 调用体）。
- memWrite 门卫：mw_gate 3.62G/run（开火率 18.3%），enable 逐端口测试为剩余成本。
- 零产出激活：**70.1%** 的 compute 超节点激活无 boundary 产出（993.4M 次激活/run，
  平均 ~100 ops/激活）。
- NO00047 静态解剖（compute 单元体）：物化族（写回 tracked 21.9 + 扇出 flags 16.4 +
  changed 声明 10.0 + 扇出 pflags 4.0）≈ 单元行数 40%。

**框架税的失败攻击记录（勿再进入）**：boundary 写回打包（−7.48%/−3.66% 实测回归，
写回单价在 OoO 下≈0，且打包致超节点碎片化 +24%）、锥克隆 wake-subsumption
（净 −0.91%）、fanout 批量 OR（NO00050 用户判 FAILED）、物化门三变体（NO00047
clang 控制流惩罚）、commit lean-write（幅度不足）。

## 3. 机制税（mechanism tax）构成

定义：grhsim-ir 为支持多时钟/内部时钟而引入的不动点（round 收敛）与多事件域
机制，在本负载（XiangShan CoreMark，单时钟 posedge+negedge）上的运行时代价。

- 每 cycle 恒为 2 次 eval（posedge/negedge 各一），每 eval 恒为 2 轮
  （199,049/200,102；1,053 次 3 轮）；无 1 轮收敛。
- **edge 分列**：negedge eval 承载 6.5% 超节点激活、6% commit port_eval、
  0 次 memWrite 门、1% publish；但 commit task 进入 50/50（neg 侧几乎全部被
  inactive-edge 快路径跳过，cm_inactive=15.8M/run）。
- **round 分列**：round-2+ 的 commit port_eval 仅占 3%、commit 进入 5.5%、
  compute 多轮单元 0.37% 动态 op。
- 每轮常开端点单元：316 个单元 / 4.25G ops（4.27% 动态），内含 1.67G 次常量
  反复物化（emit 物化策略，当前约束下不可达）。
- eval() 扫描/调度占画像 3.77%（2.7 s）。
- **机制税可直接归因合计 ≈ 总时间 3-5%**（round-2+ 约 1-2%；negedge eval 的
  固定开销摊薄约 2-3%）。gsim 完全无法表达多时钟——该税是能力对价，
  不构成 52% 差距的解释。

**机制税的失败攻击记录（勿再进入）**：两波直线化（用户 2026-09-20 放弃）、
运行时条件跳过（NO00047/50/51 三次复证不盈利）、粒度旋钮双向（NO00036 细
−30.69% / NO00050 粗 −9.86%，128 局部最优）。

## 4. 剩余理论池与所在层面（后续节点的可行性地图）

| 池 | 规模（相对总时间） | 所在层 | 状态 |
|---|---|---|---|
| compute 零产出激活 | ~35% of compute ≈ 26% | 激活精度（粒度/门控） | 封锁（粒度双向 + clang 惩罚×3） |
| boundary 写回机制 | 22.1G 次/run，但单价≈0 | emit 形态/布局 | 三次测量证死（NO00057） |
| commit 端口调用体 | 470M 开火 × ~93 cyc ≈ 18% | emit ABI + L1 布局 | emit 层（本阶段禁止） |
| endpoint 每轮单元 | 4.27% dyn ops | emit 门控 + 常量物化 | emit 层禁止/常量物化 |
| eval 扫描/调度 | ~3.8% | emit/调度 | NO00019 已优化 |
| 机制税（多时钟/不动点） | 3-5% | 语义能力对价 | 不建议触碰（见 §3） |
| IR 语义化简残量 | ≤0.5% dyn（9 轮普查穷尽） | IR 图变换 | NO00057 穷尽，删 op 对 clang 反而回归 |

## 5. 对后续节点的硬性指导

1. 任何"删除/收窄/折叠现存 compute op"的 IR 变换在当前基线预期回归（clang
   代码生成敏感性，NO00056 + NO00057 四次独立复证）——不要再提此类方案。
2. boundary 写回的逐值比较已是 OoO 近零成本；按值打包/批量只会因 slice/拼接
   开销与超节点碎片化而回归。
3. 有意义的剩余杠杆只有两个层面：emit/执行机制框架（写回/扇出/commit 的批量
   形态、常量物化、端点门控——当前节点约束禁止）与激活精度（细粒度或两波——
   已关闭）。重启任一方向前必须先在节点文档中回答对应关闭证据为何失效。
4. 性能判定统一用 6 次新旧交替 + page-cache 驱逐 + 秩次门；筛查 1-3 对仅作
   方向证伪，不作收益证据。
5. 机制税（§3）是正确性能力，不是性能债；不要为抹平它而破坏多时钟语义。

## 复现与存档

- GrhSIM-IR 画像：`make profile_grhsim_ir GRHSIM_IR_PROFILE_FLOW=...`（见
  NO00057 profile-old/registration.json 的命令与环境）。
- 动态插桩：`make reemit_grhsim_ir ... GRHSIM_REEMIT_DYNAMIC_STATS=1` + 运行
  `EMU_RUNTIME_PROFILE=1`，分析 `scripts/grhsim_dynamic_stats.py`。
- gsim 画像：`GSIM_EMIT_RUNTIME_PROFILE=1 make xs_gsim_emu XS_GSIM_BUILD=build/xs/gsim-prof`
  + `EMU_RUNTIME_PROFILE=1 make run_xs_gsim_emu XS_GSIM_BUILD=build/xs/gsim-prof ...`
  （fire TSV 由 `GSIM_SUPERNODE_TSV` 指定）。
- 普查工具：`scripts/grhsim_*_census.py`（NO00057 归档 11 件 + 既往节点工具）。
