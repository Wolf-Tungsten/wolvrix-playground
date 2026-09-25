# NO00012: 逐值变化率画像——812,234 boundary 值逐值 chg 基线、受监测集激活经济学普查、宽值成本基线（诊断）

| 字段 | 值 |
|---|---|
| 父节点 | NO00010（当前最佳，诊断节点无代码分叉） |
| 角色 | 诊断 |
| 状态 | ACCEPTED |
| 锚定指标 | M-vchg（逐 boundary 值 chg 计数画像）、M-econ（受监测集激活经济学普查 = 逐值 chg × 生产/消费单元 fire × 扫描顺序）、M-wide（宽值 >64b 成本基线） |
| 指标阈值 | 诊断节点以交付定量基线为验收（有效性/确定性/闭合/门关一致性门槛见「假设提出 · 预注册」） |
| 回退预算 | 无性能语义改动；当前最佳指针不动（53.426 s），如实登记 |
| RUN_ID | no00012_vchg_build_20260925 / no00012_vchg_run_20260925 |
| 工作区 | ptmp/no00012_vchg_profile_20260925/ |

## 基础选定（BASELINE）

- **父节点**：NO00010（当前最佳指针，GrhSIM-IR PGO 构建 Host 53.426 s，wolvrix 实际对应提交 `eed8839`；索引中 `1f8bcc9` 为 NO00009 提交，系登记笔误，本节点一并修正）。诊断节点，无生产代码分叉、无迂回；产出逐值变化率首批定量基线，供后续优化节点预注册阈值。
- **立项动机（为什么是现在）**：NO00008 因子表把 2.0× 指令差距闭合于"每单位工作指令密度"（ir/gsim = 8.54×），但 NO00009（值承载）与 NO00011（语句粒度/op 图融合）两条证伪已把密度差距的两个形态候选排除——剩余密度构成（宽度规范化、change-detect 与 fanout 簿记、宽值 helper）中，**change-detect/fanout 簿记的经济学分析缺少逐值变化率数据**：检测本身是负载（and/eq/mux/state.read 四类合计 wr 14.2 B = 142K/cycle），其存在意义是激活滤波；判断"哪些受监测值的监测是净亏损"需要逐值 chg（值变化频次）× 生产/消费单元 fire × 扫描顺序的联合普查，而该联合所需的逐值 chg 维度本分支从未测量（仅有逐 kind 聚合：and 1.35%、eq 2.31%、mux 13.29%、state.read 14.57%）。
- **两次候选优化因缺该维度而盈亏反号（本节点勘察，ptmp/no00012_scout_20260925/，生产 checkpoint 口径）**：
  1. **检测值迁移**（单消费者纯计算 op 迁入消费单元，消除 boundary 写+检测）：静态合格候选 90,930 个（动态 21,909 检测/cycle），但迁移使被迁 op 在消费单元每次 fire 都重新求值——净盈亏 = 省下的"写+检测+读"对"多出的重算×单元 fire 差"；候选的 new_edges（迁移后所在单元新增输入边）分布 0:12,172 / 1:22,827 / 2:26,207 / ≥3: 39,724，激活放宽代价使净符号取决于被迁值的 chg 率；new_edges==0 子集仅 ~13K instr/cycle（0.34%）——无逐值 chg 无法判定其余 95%+ 候选的符号。
  2. **端口武装消除**（mux/or 等 → 1 port 类 ~65K 检测/cycle）：武装使 commit 端口跳过求值，同样卡在逐值 chg——若被武装值几乎不变（冷），武装簿记是纯赚；若热，武装的置位/扫描成本可能超过省下的端口求值。
  3. 勘察同时**证伪并排除**（登记防止后续节点重复进入）：宽度规范化消除（27 个采样 task .o 反汇编：静态 6.78M 个 grhsim_trunc_u64/grhsim_cast_u64 调用仅 3,185 条 and-imm 存活 = 0.33%，clang 局部消除+movz/byte-op 吸收）；state.read 别名扩展（发射器已有 readAliases 机制 54,751 别名，剩余多为 snapshot/sink 阻塞——difftest 观察的 w64 寄存器 12,775/cycle 不可动）；常量可折残余（12,331 ops = 0.35% 静态，过小）。
- **测量路径（生产管线零改动）**：在既有 dynamicStats_ 插桩通道（`cpu_emit.cpp`，与 cpu_dyn_sn_* / cpu_dyn_wr/ch 同模式）扩展**逐值打包计数器** `cpu_dyn_vw[result.index] += (wr<<32)|chg`（uint64 打包，一次 RMW/检测点，值空间 3,379,132 × 8 B = 27.0 MB 成员数组，与既有 34 MB 内联 dyn 数组成员同先例）；覆盖 compute() 全部 10 个检测发射点（宽 concat ×2、replicate 广播、replicate/bitwise/shift/arithmetic words_changed ×5、主窄路径 ×2——`cpu_dyn_ch[kind]` 的全部累加点，含 input.read/memRead/state.read 走主路径者）；退出时按 `[grhsim-vchg] v <idx> wr=<w> ch=<c>` 转储非零项。插桩仅在 dynamicStats_ 开时发射，生产管线（门关）逐字节一致由 neutral reemit 门验证。诊断构建复用 NO00011 dyn 流程（reemit + 独立构建目录，源 checkpoint 与 NO00011 dyn-unfused 相同 = NO00004 归档 `ptmp/no00004_compiler_pgo_20260924/flow/xiangshan_grhsim_ir.json`，即 NO00010 真实生产模型：ops=3,531,463、values=3,379,131、boundary 值 812,234；`build/xs/grhsim-ir/` 下 13M-op 旧模型为陈旧产物，本节点不使用）。
- **基线测量（配置未变，复用归档值，不重跑）**：
  - GrhSIM-IR 当前最佳：Host **53.426 s**（NO00010，3 次有效均值，SD 0.099 s）；端点 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`。
  - gsim+PGO 锚点：Host **27.376 s**（3 次有效均值，SD 0.065 s）；端点 `instrCnt=238550、cycleCnt=99998、guest=100001、PC=0x80000b40`。差距 **1.952×（~26.1 s）**。
  - ir 侧动态聚合（NO00001 M4 / NO00008 归档口径；本节点勘察已对 NO00010 代码态 dyn 日志复核一致：wr=22,134,521,354 = 221,343/cycle、ch=1,267,630,634 = **12,676.2 changes/cycle**、变化率 5.73%、silent=1,565,541,060 = 7.07%）：
    - supernode 激活 993,413,585（9,934/cycle），body 执行 904,557,815（9,045/cycle），quiescence 跳过 8.94%；
    - boundary results **812,234**（25.30/unit）；ops/unit 均值 110.01；chg/act 31.36%；
    - dynOps = 99,479,933,605（994,792/guest cycle；evals=200,102）。
  - 指令归因（NO00011 生产构建 perf 归档）：ir 总 **4,020,950 instr/guest-cycle** = compute 3,227,616（80.3%）+ commit 440,696（11.0%）+ evaluator eval() 133,496 + model_infra 110,174（含 cpu_direct_state_changed 59,108）+ libc 35,786（memcmp 23,724）+ 其余；gsim 总 1,965,434（model_step 1,922,980）。CPI 两侧已拉平（ir 0.6679 vs gsim ~0.676）——剩余 Host 差距 ≈ 纯指令数 2.04×。
  - 逐 kind 检测聚合（同一 dyn 日志 per-kind 行；chg 率 = ch/wr）：core.compute.and wr=7,153,968,704 chg 率 1.35%；core.compute.eq 2.31%；core.compute.mux 13.29%；core.state.read 14.57%；core.compute.mux ch=384,133,054 为单 kind 最大 chg 来源（30.3%）；silent 集中于 or（520,849,948）/prioritySelect（337,735,807）/bitSelect（228,717,782）。
  - 宽值静态（本节点勘察，生产 checkpoint 生成代码）：`grhsim_insert_scalar_words` 静态调用站 **75,766**；memcmp 23,724/cycle（libc 归因）；宽值（>64b）检测点与逐 helper 动态成本待 M-wide 普查量化。
  - gsim 侧动态（NO00008）：M-gact 17,631.8 act/cycle、M-gwork 4,256,657 enode/cycle、M-gchg 派生下界 10,786.9 changes/cycle、变化检测 87,965 次/cycle（ir 221,343 = 2.52×）。
- **输入核对**（sha256，与 NO00001–NO00011 相同，输入未变）：
  - `testcase/xiangshan/ready-to-run/coremark-2-iteration.bin` = `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`
  - `testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so` = `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`
- **代码状态核对**：wolvrix `5d409f3`（工作区干净）；根仓库 `194a2ad`（NO00011 提交）；xiangshan/reference 子模块不动。冻结面（GRH IR、GRH 已有 pass、XiangShan 与测试源码）零改动；wolvrix 改动仅为 dynamicStats_ 插桩扩展（门关 = 父节点逐字节，neutral reemit 门验证）；根仓库改动仅为测量设施（Makefile 目标 + 分析脚本 + 单测）。
- **资源配置**：与 NO00001–NO00011 一致：`XS_EMU_CPU=2`、`XS_EMU_THREADS=1`、`XS_NUM_CORES=1`、`XS_SIM_MAX_CYCLE=100000`、waveform/commit/RAM trace 全关；编译 `VM_BUILD_JOBS=32`；测量时机器空载；逐次 `posix_fadvise(DONTNEED)` 驱页缓存。
- **计时边界与止损线**：
  - 诊断构建（wolvrix 重建 + reemit + emu 编译）：墙钟如实记录；诊断构建不走全流程门槛（先例 NO00001/NO00008），参照量级登记（NO00011 dyn-unfused：reemit ~数十 s、编译 231 s）。
  - 诊断仿真：插桩使 emu 减速，时间不进任何性能基线；运行上限 **300 s**（NO00001 起先例；NO00011 dyn-unfused 同流程实测 Host 163.4 s，本节点新增一次 RMW/检测点，预计 +20–60%）；超时记 `REGRESSION_KILLED`（诊断口径），失败 `INVALID`。
  - 本节点无生产构建、无 3+3 性能复测（无性能语义改动）。

## 假设提出（HYPOTHESIS）

- **假设（诊断性）**：ir 的 221,343 次/cycle boundary 写检测（gsim 87,965 的 2.52×）与 9,045 body/cycle 的激活结构，其经济性的逐值分布未知：逐 kind 聚合（and 1.35% chg 率 vs mux 13.29%）已显示数量级差异，逐值维度必有更极端的冷/热结构（静态 812,234 个受监测 boundary 值中，动态 chg 合计 1.27 B 的分布未测）。若存在显著冷尾（大份额受监测值几乎不变），则"受监测集收缩"（冷值去监测化 = 语义/读写属性驱动的 IR 层变换，非 emit 层）成为可预注册的优化候选；若热值集中，则候选为扇出结构精简。本节点测量逐值 chg 画像并与单元 fire/扫描顺序联合，给出受监测集经济学候选集（或其确证为空）。
- **创新点**：本分支首个**逐值**变化率口径（此前全部动态计数为逐 kind/逐 unit 聚合——NO00008 建立了 gsim 侧逐 super 口径，本节点建立 ir 侧逐值口径）；首个"检测经济学"联合普查（逐值 chg × 生产单元 fire × 消费单元 fire × 生成代码扫描顺序，四者此前分属不同测量域从未联合）；首个宽值成本基线（NO00009 证伪注记中唯一未量化的 compute 密度分量）。
- **瓶颈证据（本分支实测）**：见 BASELINE——① 两次候选优化（检测值迁移、端口武装消除）的盈亏符号都卡在逐值 chg 未知；② NO00008 因子表剩余主因子"每 dynOp 指令密度 8.54×"的两个形态候选已被 NO00009/NO00011 证伪，change-detect/fanout 簿记（ir 221,343 检测/cycle ≈ 每次检测 cmp+分支+条件置位，量级估计 0.4–0.9 M instr/cycle ≈ compute 的 12–28%）是下一个待分解分量，其可压缩性取决于逐值 chg 分布；③ 宽值 helper（75,766 静态调用站）与 memcmp（23,724/cycle）成本未量化。
- **微观指标与总目标的定量关系**：
  - **M-vchg** = 逐 boundary 值 chg 计数（`[grhsim-vchg]` 行，确定性计数）。交付：分布表（零 chg 份额、十分位、Top 1%/10% 份额）、按 producer kind × 位宽分层、与逐 kind 聚合对照。与总目标关系：检测成本 ∝ 受监测值数 × 生产 fire；监测收益 ∝ (1 − chg 率) × 消费 fire 跳过——逐值 chg 是该成本/收益两侧共同的缺失乘数。
  - **M-econ** = 受监测集激活经济学普查：逐值 chg 率 × 生产单元 body fire（sn 行）× 消费单元 fire × 生成代码扫描顺序（eval 内 task 序列、task 内 unit 序列，由生成 C++ 解析）→ 每个受监测值的"监测净成本"估计与**可盈利受监测集收缩候选集**（或其为空的确证）。与总目标关系：直接回答"221,343 检测/cycle 中多少是可消除的净亏损"，为下一优化节点提供预注册阈值与目标集。
  - **M-wide** = 宽值（>64b）成本基线：逐 helper 静态调用站（insert_scalar_words 75,766 等）× 动态执行/cycle（perf 归因）× 宽检测点分布；与 compute instr 的关系定量登记。
- **预注册**：
  - **测量方法与运行秩序**：wolvrix 重建（`make build`）→ 聚焦测试 → 门关一致性门（stats-off reemit 对 NO00010 归档模型逐字节）→ 诊断 reemit（`make reemit_grhsim_ir GRHSIM_REEMIT_DYNAMIC_STATS=1`，源 checkpoint = NO00004 归档，与 NO00011 dyn-unfused 同源）→ 诊断编译（`make xs_wolf_grhsim_ir_build_emu`，独立构建目录）→ 2 次诊断运行（`make run_xs_wolf_grhsim_ir_emu`，taskset -c 2、逐次 posix_fadvise、上限 300 s）→ 分析（`make analyze_grhsim_vchg_profile`）。
  - **有效性门槛**：两次运行端点精确匹配 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`，退出 0，无 difftest mismatch（插桩不改变行为）。
  - **确定性门槛**：两次运行的 `[grhsim-vchg]` 行集**逐字节一致**（固定输入下确定性计数）；不一致则排查非确定来源并降级相关结论。
  - **闭合门槛**：单次运行内 Σwr（vchg 行）== Σwr（同日志 kind 行）且 Σch（vchg 行）== Σch（kind 行）精确相等（同一计数点集的两路聚合）；并对归档值闭合（wr=22,134,521,354、ch=1,267,630,634）。超出 0 残差即排查覆盖缺口并如实登记。
  - **门关一致性门槛**：插桩后的 wolvrix 以 stats-off reemit 同一 checkpoint，生成模型与 NO00010 归档生产模型（`ptmp/no00010_fanout_epilogue_guard_20260925/flow/model`）逐字节一致（`.o` 除外）；且诊断构建生成代码与 NO00011 dyn-unfused 归档（`ptmp/no00011_expr_fusion_20260925/flow-dyn-unfused/model`）的差异仅限 vchg 插桩行。
  - **口径登记**：silent 类（无扇出、无检测的 boundary 写，15,654/cycle = 7.07%）无比较点，不在 vchg 计数内——其逐值变化率不可测（加比较会改变成本结构），M-vchg 的作用域为**受监测 boundary 值**（wr>0 者 + 生产单元从未 fire 的零写值），silent 类以既有逐 kind 聚合如实登记。
  - **证伪标准**：本节点为诊断节点，无机制假设可证伪；若插桩链路无法产出 VALID 数据（构建失败、端点不符、计数非确定、闭合残差非零未归因），记录口径缺口，对应指标不交付。
  - **验收（诊断节点）**：全部有效性/确定性/闭合/门关门槛通过 + M-vchg/M-econ/M-wide 三基线交付 + 当前最佳指针不动（53.426 s 如实登记）；若 M-econ 候选集为空，确证登记机制证伪表。

## 代码实施（IMPLEMENTED）

诊断节点，无生产语义改动（不改冻结面、不改任何锚定构建产物；插桩仅在 `dynamicStats_` 开时发射，门关 = 父节点逐字节，由 neutral reemit 门验证）。改动两处：

1. **`wolvrix/lib/grhsim/backend/cpu_emit.cpp`（dynamicStats_ 插桩扩展）**：
   - 新增逐值打包计数器 `cpu_dyn_vw`：`std::array<std::uint64_t, values+1>` 成员（生产模型 3,379,132 项 = 27.0 MB，与既有 34 MB 内联 dyn 数组成员同先例；模型对象由 harness 堆分配），值语义 = `(writes<<32)|changes`，每个检测点一次 RMW。
   - 覆盖 `compute()` 全部 10 个 `cpu_dyn_wr/ch` 检测发射点：宽 concat ×2（group/activate 两路）、replicate 1-bit 广播（`cpu_rchanged`）、replicate/bitwise/shift/arithmetic `*_words_changed` ×5、主窄路径 ×2（group/activate 两路）——`input.read`/`state.memRead`/`state.read` 均经主路径或宽路径覆盖。发射侧经 `dynVw` 串（`cpu_dyn_vw[<result.index>]`），`dynamicStats_` 关时不构造任何文本。
   - 退出转储：`[grhsim-vchg] v <idx> wr=<w> ch=<c>` 非零项循环，插入既有 `[grhsim-dyn] kind` 打印之后（同一 `dump_runtime_profile` 链路，`EMU_RUNTIME_PROFILE=1` 触发）。
   - 名称保留集登记 `cpu_dyn_vw`（端口名冲突校验）；`init()` 复位 `cpu_dyn_vw.fill(0)`。
   - **语义约束**：计数器只读模型状态不写；插桩行全部位于既有 `if (dynamicStats_)` 发射分支内，stats-off 发射输出逐字节不变（neutral 门实测）；silent 类（无扇出 boundary 写）无比较点，不在计数内（口径见预注册）。
2. **根仓库测量设施**：
   - `Makefile`：`analyze_grhsim_vchg_profile`（驱动下述脚本；变量 `GRHSIM_VCHG_MODEL/RUN1/RUN2/GEN_MODEL/OUTPUT`）与 `test_grhsim_vchg_profile`。
   - `scripts/grhsim_vchg_profile.py`：纯函数解析器（`[grhsim-vchg]`/`sn`/`kind` 行、端点四字段含千分位逗号容忍——NO00008 locale 教训）、闭合检查、分布统计、生成代码扫描顺序提取（eval task 序列 + task 内 unit 首现序列）、宽 helper 静态普查（20 个 helper 名，容忍模板实参）、模型连接（boundary 值 × producer kind/width/unit × consumer units/classes，分区树 kind-3 walk 与 value_slots 解析同 scouting v2 口径）、经济学联合表与冷度分桶、迁移候选 chg 重评分；编排 9 道门（双运行端点×2、difftest 干净、确定性×3、闭合×4）后输出 `summary.md/json`。
   - `scripts/test_grhsim_vchg_profile.py`：18 个单测覆盖全部解析器、闭合、分布、扫描顺序、helper 普查与分类函数。
- **与父节点差异**：无性能语义差异；当前最佳指针与归档二进制不变。
- **聚焦测试**：
  - `make test_grhsim_cpu_emit` / `test_grhsim_cpu_schedule` / `test_grhsim_cpu_mapping`：全部通过（stats-off 金样输出不变）。
  - `make test_grhsim_vchg_profile`：18 测试通过。
  - wolvrix 增量重建 20.73 s（`make build`）。
  - **门关一致性门（通过）**：① stats-off reemit 对 NO00010 归档生产模型逐字节一致（`diff -rq -x '*.o' -x '*.a'` 空差异，`NEUTRAL-IDENTICAL`）；② dyn 构建生成代码对 NO00011 dyn-unfused 归档：3,848 文件不同、717,246 行变更**全部**含 `cpu_dyn_vw`，零非 vchg 差异行（逐文件 `diff | grep -v cpu_dyn_vw` 全空）。

## 结果测试（TESTED）

- **构建门槛（诊断口径，如实登记，不进性能门槛）**：wolvrix 增量重建 20.73 s；诊断 reemit 51.28 s；诊断 emu 编译 242.99 s（-j32；参照 NO00011 dyn-unfused 231 s，+5% 为 vchg 计数器编译成本）。日志/产物 `ptmp/no00012_vchg_profile_20260925/`（`build.log`、`reemit-dyn.log`、`build-dyn.log`、各 `.time`）。
- **运行登记**（`EMU_RUNTIME_PROFILE=1`、`taskset -c 2`、逐次 posix_fadvise 驱页缓存、上限 300 s）：

  | 运行 | Host s（墙钟） | 端点（instrCnt/cycleCnt/guest/PC） | vchg 行 | 判定 |
  |---|---|---|---|---|
  | run1 | 250.751 | 240349 / 99996 / 100001 / 0x80000c0c | 717,243 | VALID |
  | run2 | 248.794 | 240349 / 99996 / 100001 / 0x80000c0c | 717,243 | VALID |

  插桩减速 +53.5%/+52.3%（对 NO00011 dyn-unfused 同流程 163.369 s；逐值 RMW 成本），均在 300 s 上限内；诊断口径，不进任何性能基线。
- **门槛（10/10 通过）**：端点精确 ×2、difftest 干净、确定性 ×3（vchg/sn/kind 双运行逐字节一致，`cmp run1.keys run2.keys` 一致）、闭合 ×4（Σwr=22,134,521,354、Σch=1,267,630,634 与 run 内 kind 行及归档值双路精确相等——同一计数点集两路聚合零残差）。门关一致性：neutral reemit `NEUTRAL-IDENTICAL`；dyn 生成代码对 NO00011 dyn-unfused 差异 3,848 文件/717,246 行全部含 `cpu_dyn_vw`、零非插桩差异。

### 微观指标基线

- **M-vchg（逐值变化率画像）**（717,243 个被检测值；guest_cycles=100,001）：
  - **boundary 宇宙分解（静态 812,234）**：受监测（有其他单元消费者）812,228、无消费者单元 6；被检测且评估（dumped，wr>0）717,243；未 dump 95,366 全部"被评估但无检测"（**死值=0**——所有生产单元均 fire 过）：state.read 35,063（readAliases 别名子集）、or 14,984、mux 9,827、constant 8,761（staticScalars 子集）、bitSelect 8,385、and 5,781、prioritySelect 5,708、shl 3,389 等；nodetect 生产单元 body fire 合计 2.38B 与 silent 写 1.57B 同量级（别名/常量值贡献 fire 不产生写）。
  - **逐值 chg 分布**：零变化份额 **51.6%**（370,022 个值 100k 全程零变化）；p50=0、p90=1,476、p99=50,191、max=200,102（=evals 数，每次都变）；**Top 1% 值持有 46.9% 的全部变化、Top 10% 持有 95.9%**——变化高度集中。
  - **分层（producer kind × 位宽，按 chg 排序头部）**：mux 33–64b（36,619 值，rate 13.1%）、state.read 33–64b（23,495 值，14.6%）、and 1b（237,267 值，rate 1.34%，wr 7.14B 为单层最大检测量）、mux 2–8b（29,846 值，8.8%）、sliceArray 2–8b（2,245 值，53.1% 为最热层）、eq 1b（50,559 值，2.31%，wr 2.77B）等（全表 `analysis/summary.json`）。
- **M-econ（受监测集激活经济学普查）**：
  - **冷度分桶（被检测值）**：chg=0：370,022 值（51.6%），检测写 7.26B = **32.8%**，变化 0；(0,0.1%)：69,000 值（9.6%），检测 4.16B = 18.8%，变化 1.19M = 0.094%；[0.1%,1%)：103,934 值，检测 5.07B = 22.9%，变化 1.39%；[1%,10%)：85,565 值，检测 3.17B = 14.3%，变化 8.69%；≥10%：88,722 值（12.4%），检测 2.48B = 11.2%，变化 **89.8%**。**冷+近冷（<0.1%）合计：61.2% 的值、51.6% 的检测写、0.094% 的变化**——检测成本与变化产出严重错配。
  - **迁移经济学终裁（检测值迁移 = 单消费者纯计算 op 迁入消费单元，逐候选 chg 重评分，模型常数 K_DETECT=3/K_STORE=1/K_EVAL 按 kind/K_OP=3.86，widen 取上界）**：IR 静态合格候选 228,571 个；**聚合利润 −234.5B 模型指令/run（−2.34M/cycle）——无差别迁移机制证伪**（激活放宽 widen 243.9B 主导，save 仅 22.9B）；但 **profit>0 选择性子集 114,047 候选存在，合计 +87,130 instr/cycle ≈ compute 的 2.70%**（其中零新边子集 46,431 候选 +28,498/cycle ≈ 0.88%；按 kind：and +43.8K/cyc、or +9.4K、bitSelect +7.8K、logicNot +7.3K、eq +3.2K）。**可盈利受监测集收缩候选集非空**，选择性迁移为后续优化节点的预注册目标集与量级锚点。
  - **扫描顺序**：eval 内 task 4,436 个、task 内 unit 首现序列解析 31,612 单元（与 dyn sn 行数一致）——unit→(task, 序位） 映射已交付 `analysis/summary.json`，供 round 内传播分析复用。
- **M-wide（宽值 >64b 成本基线）**：
  - **静态普查（生成代码）**：宽值组装 helper `grhsim_insert_scalar_words` 75,775 站 + `grhsim_insert_words` 3,185 站（宽 concat 主成本形态）；宽位运算/shift/算术 helper 9,421 站（shl_words 3,145、or_words 2,469、lshr_words 2,177、and_words 2,093、xor 550、not 50、add 69、sub 59、ashr 4）；**宽检测 helper 仅 550 站**（bitwise 410、shift 43、arith 65、replicate 32——对比窄值检测站 716K）；`memcmp` 全模型仅 1 个静态站。
  - **宽 boundary 值**：8,588 个（boundary 的 1.06%），被检测评估 2,957 个；chg 合计 6.6M = **全部变化的 0.52%**，零变化份额 59.5%——宽值不是变化流主成分。
  - **memcmp 动态成本归因**：libc 归因 23,724 次/cycle 来自唯一静态站 `grhsim_SimTop.cpp` publish 路径（`std::memcmp(cpu_objects+p.offset, cpu_shadow+p.offset, p.size)`，memory-row 逐行比较提交）——**与宽值无直接关系**，属 commit memory 提交结构成本。

### 口径缺口与不确定度登记

1. silent 写（无检测点的 boundary 写，1.57B 次 = 7.07%）与别名/静态常量值（无发射）无逐值变化率（加比较即改变成本结构），以逐 kind 聚合与分解表登记；95,366 个未 dump 值全部"评估但无检测"（死值=0），与 scouting 的"never_eval"解读不同，以本分解为准。
2. wr_v ≈ 生产单元 body fire（group 路径）/ port fire（port 路径）；两者未逐值分解（round-0/round-N 分解仅有逐 kind 口径）。
3. 迁移利润模型常数来自反汇编普查与 M-idens（3.86 instr/dynOp）；widen 为上界（无共激活折扣）、profit 为保守下界；选择性子集结论对常数扰动的敏感性未全面扫描（常数 ±50% 下 profitable 计数与 Σprofit 方向不变，量级 ±~1pp——粗查）。
4. 宽 helper 动态执行次数未单独归因（内联于 compute_task perf 符号），量级可由静态站 × 属主单元 fire 估计（未做）。
5. consumer body fires 为联合量（消费单元可能因其他输入已激活），非该值独立贡献；扫描顺序映射未在利润模型中计价 round-2 影响。

### 结论（定量基线交付）

1. **逐值变化率首基线**：51.6% 受监测 boundary 值全程零变化，其检测占全部检测写的 32.8%；冷+近冷值合计 61.2% 的值、51.6% 的检测、0.094% 的变化；变化流 Top 10% 值持有 95.9% 变化。检测簿记（221,343 次/cycle × ~3 instr ≈ 0.66 M/cycle ≈ compute 的 20%）中约一半服务于几乎不变化的值。
2. **检测值迁移经济学终裁**：无差别迁移聚合 −2.34 M instr/cycle 证伪（激活放宽主导）；**选择性迁移（profit>0 子集 114,047 候选）持有 +87.1 K instr/cycle ≈ compute 2.70% 的可盈利候选集**——下一优化节点的明确目标集与预注册量级锚点（须 IR 层重分区实现，由依赖/消费属性驱动，非 emit 层）。
3. **宽值成本基线**：宽检测站仅 550（窄值 716K）、宽 boundary 值 1.06%、宽值变化 0.52%——宽值不是 compute 密度主因；memcmp 23,724/cycle 归于 commit memory publish 结构而非宽值。
4. **后续方向排序（由基线直接读出）**：选择性检测值迁移/冷值去监测化（上界 2.70% compute）> 宽值（<1%）；端口武装经济学随 coldness 表获得定价输入（武装值若为冷值则武装簿记纯赚的确证范围）；变化流集中度（Top 1% 值 46.9% 变化）提示热值扇出结构精简是冷值之外的独立轴。
- **判定**：预注册门槛全部通过（有效性 ✓、确定性 ✓、闭合 ✓ ×4、门关一致性 ✓ ×2）；M-vchg / M-econ / M-wide 三基线交付；当前最佳指针不动（53.426 s，如实登记）。**ACCEPTED（诊断节点，定量基线交付）。**
