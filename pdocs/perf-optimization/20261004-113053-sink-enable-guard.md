# 20261004 sink 簇使能守卫（公共 guard）细分

> 状态：**已完成。结论：不采纳（实测 -0.5% 一致性小幅回退），机制保留、默认关闭。**
> 本文是完整闭环记录：调研 → 静态普查 → 动态 profile → A1 实施 → 标准口径 A/B → 收档。

## 元信息

- 日期 / 作者：2026-10-04 / kimi（方案经作者逐轮评审定稿；结论经作者确认收档）
- wolvrix commit / 根仓 commit：`66000f6`（V3-M3）+ A1 实施改动（未提交工作区）/ `1b94a8d`
- 上游基线记录：[20261004-075148-v3-sixphase-baseline.md](20261004-075148-v3-sixphase-baseline.md)
- 对应 backlog：README 优化候选 #1（sink 簇内按使能锥细分）

## 基线性能

不重复登记，直接引用基线记录：M0 存档 85.9s vs 当前 V3-M3 223.4s
（100k CoreMark 周期，3+3 交替同口径）= 2.60× 回退。本项针对基线归因
**第一成本项"事件即激活"**：sink 簇按事件签名聚类、事件发生即整体点火、
逐 op 查 en；M0 旧数据门控下这些写只在输入变化时运行。

本记录新增的定量证据（普查脚本 `scripts/grhsim_reset_write_census.py` +
探针 `ptmp/grhsim_reset_census_20261004/probe_en_groups*.py`，数据
`ptmp/grhsim_reset_census_20261004/`，跑当前 V3-M3 dump
`build/xs/grhsim-ir/xiangshan_grhsim_ir.json`，3.77M op / 99,583 regWrite）：

- 每 guest 周期点火的两个巨簇：`acts=[0]` 74,967 写 + `acts=[0,8]` 17,477 写
  （另含 7,188 系统任务 + 6,365 断言，本方案同样适用但暂未计入普查）。
- `[0]` 簇 en 形状：or-top 43.9% / **const1 28.0%（恒真写，守卫无意义）** /
  and-top 19.2% / reduceOr 5.2% / slice 2.8% / 其他 <1%。
- 静态可分组性（分组阈值 T≥8，探针 greedy 指派）：
  A1（en 同值）25.5%（1,244 组，碎片化）；A2（顶层 and 共享操作数）+3.3%；
  B 类静态线索（共享析取项 / 共享 slice 源）+28.4%；残余需任意分组。
- **警示案例（静态分组 ≠ 可省工作）**：最大静态组 20,259 写 100% 落在
  `logEndpoint`（difftest 性能计数器），en 形为
  `(reset|clean) | (¬reset∧¬clean ∧ e_i)`，两分支互补，有效守卫只能是事件
  并集而事件高频触发——静态上最大的组恰恰是活动度最高、最不可跳过的组。
- 附带事实：全部 99,583 个写与 state 一一对应（无多写者）；420 个事件聚类
  全 posedge；`[0,8]` 的第二事件是内部 resetSync 复位树。

## 优化方案

- **动机**：基线归因第一成本项（见上）。
- **假设（两级使能）**：在 sink 超节点调用点、事件签名门控之内再串一级
  **使能守卫（公共 guard）**——一个布尔值 g，编译期可证组内每个写的
  `en_i ⇒ g`。`g=0` 时整组跳过，与逐 op 进入后各自空转**逐拍等价**
  （en=0 的写无提交、无变化检测、无 fanout 置位）。只跳过可证明的空转，
  不门控任何生产者的发布、不引入激活旗标通道，v2 三条边界规则不破
  （值依赖 ≠ 激活依赖，latch-ICG 死锁的激活环无结构基础）。
- **守卫的三个来源**（按是否需在图里造值分类）：
  - **A1：共享 en 值本人**。一组写的 en 操作数是同一个 value id（CSE 产物）。
    guard = 该值；它已是 boundary 槽（sink 操作数全走 boundary），零新增。
  - **A2：en 顶层 and 的共享操作数**。`en_i = and(g, e_i)`，`and(g,·) ⇒ g`
    是重言式，证明为语法级。guard = 共享操作数值；可能需按 C3 规则补
    boundary 槽，值本身不用造。
  - **B：合成析取（唯一需要造值的情形）**。无共享结构时，
    `guard = or(en_1, …, en_k)`——"组内是否有写被使能"的精确条件，天然被
    每个 en 蕴含。由 B6 之后、封板之前的语义 pass 补一个 variadic or op
    （纯增量，不改写任何现有 op；此后无 simplify，存活由构造保证）。
    guard op 是普通非 sink op，数据门控维护（任一成员 en 变化唤醒重算），
    值经现有 boundary 规则开槽。**只为低活动组采用**；高活动组留给逐 op
    检查（本来也不是浪费）。维护成本：k 输入 or 每次唤醒读 k 个操作数，
    净收益 ≈ `s·k·c_op − (1−s)·c_read − m·k·c_read`（s=skip 率，m=成员 en
    有变化的轮次占比），必须逐组裁定。
- **为什么不做"大图（A 段）层面规范化造守卫"**（评审结论，三条）：
  ① A1/A2 没有缺失的 value 可造——SSA+CSE 已让共享子表达式显式存在，
  缺的是分组决定、boundary 发布、调用点检查三件后端的事，不是图形状问题；
  ② A 段没有合成判据——事件签名 B2 才有、sink 簇 C2 才建、分组还需活动度
  数据，信息不存在，不是时机偏好；
  ③ A 段造出的守卫值活不到用的时候——它在图里唯一消费者是 C2 之后的
  调用点，属死值会被 A5 DCE 依法删除；锚定保活会改变 en 形状，干扰
  reg-to-mem（XS 1,945 族）与 pack-bit（3,774 打包字）的形状匹配。
- **改动点（分层，emit 保持薄）**：
  - 语义层：A1/A2 **零改动**；B 加一个 B6→B8 间物化 pass（暂定名
    `grhsim.materialize-sink-guards`，只吃经活动度裁定的分组计划，补
    variadic or，phase=general）。
  - mapping：C2 同签名簇内按（签名，守卫值）细分（聚类规则其余不变）；
    超节点携带 `enableGuard: ValueId?` 属性（与 `eventActs` 同级）；
    C3 把该值计入超节点消费值集 → 按现有 boundary 规则开槽。
  - emit：调用点 `if (actBitsGuard(sig) && read(enableGuard)) sn();`，
    与读 eventAct / 读操作数同一个 read() 通道，不合成任何逻辑。
- **风险与回退**：
  - 主风险：活动度不足以覆盖守卫维护成本（警示案例已见）——动态 profile
    裁定，数据不达标则放弃本项；
  - 分组碎片化（A1 达 1,244 组 @T≥8）→ 调用点固定开销，需成本模型选组；
  - 语义风险：低（跳过条件有编译期蕴含证明 + 五道正确性门槛）；
  - 回退：pass 参数 / C2 分组开关，可整体关闭回到单签名巨簇。

## 结果性能

### 动态 profile（前置测量）

数据 `ptmp/sink_guard_profile_20261004/`（groups.json / probe_report.tsv /
summary.md / 运行日志）。口径：CoreMark 100k 周期（difftest 逐拍无
mismatch），eval() 内 `cpu_round==1`、`pGeneral()` 之后采样，evals=190,000；
en 值由 probe 从 boundary/regLatch 成员**精确重算**（非近似）。

- 入组 1,015 组（A1 903 / BMOD 112），覆盖 Σk=23,747 写 = 基数 92,444 的
  25.7%（const1 22,015 写不可守卫、k<8 零散 2,388、无法精确解析弃组
  846 组/44,275 写，含 20,255 写的 logEndpoint 高活动 mega 组）。
- **Σ s·k = 16,509**（每 eval 可跳过的 op 检查数，占基数 17.9%）。
- **s 分布：s>90% 的组 819/1,015（Σk 14,499）**；s≤10% 的 85 组（5,966，
  高活动，成本模型会排除）。
- 净收益模型（`net = s·k·c_op − (1−s) − m·G`，仅 net>0 组）：c_op=2/3/4 →
  +32.8k / +49.3k / +65.8k instr/eval，全档为正。
- 收益集中地：dataBanks_*、inner_bpu/cache/tage/inner_ifu/sc/mbtb、
  renamePipeDispatch、splitPipeline、LoadUnit_0-2、ptw、fpRat、
  vecOG2ForVector——"大部分周期空闲"的区域，与设计直觉一致。

**架构事实核查（二轮订正）**：profile agent 曾按 `_val_<id>` 成员名匹配得出
"97.5% 的 en 不是 boundary 值、在 sink 体内就地计算"，**经生成物实证证伪**：
sink 超节点体内只有写 op，en 全部经 `boundaryValueStore` 成员读取——成员名
多为 declared-symbol 派生（如 `..._bpu_s1_fire` 一名被 132/148 个写共享），
仅无名值用 `_val_<id>`，按 `_val_<id>` 匹配必然漏判（实证：writeOp 14615 的
or 形 en 读 `boundaryValueStore.cpu_l_soc_socMisc_axi4deint__GEN`；C1 注释
"sink 操作数锥留在非 sink 框架、值成为 boundary"与生成物完全一致）。影响：
① A1 守卫值全部现成可读，A1 只剩 C2 分组 + emit 调用点；② 情形 B 的 union
守卫可直接消费成员 en 的 boundary 槽，无需克隆锥；③ 弃组多为可读值，
25.7% 是覆盖面下界。

### A/B 实测（标准口径，最终裁定）

产物 `ptmp/sink_guard_ab_20261004/`（flow2.log / build_emu2.log / bench/ /
correctness_ab.log / coremark.log）。A1 生效确认：C2 诊断
`sink_guard_supernodes=1645 sink_guard_ops=25356`，生成代码守卫调用点 1,645
处一一对应，roundtrip 通过，流程 exit 0。

| 组 | 逐次 host_s | 均值 ± sd |
|---|---|---|
| M0 存档 | 86.351 / 85.940 / 85.923 | 86.07 ± 0.24s |
| NEW（含 A1） | 224.393 / 224.448 / 224.784 | **224.54 ± 0.21s** |

**A1 直接效果 = 224.54s vs V3-M3 记录 223.44s（222.813/223.891/223.603）→
+1.11s（+0.50%），变慢而非变快**；两组逐次值无重叠，同向一致。M0 侧 86.07s
与基线记录的 85.93s 一致（+0.16%），机器口径稳定。6/6 次命中预期 endpoint
（instrCnt=240,349 / cycleCnt=99,996 / pc=0x80000c0c）。

编译侧：emit 20.8s（基线 22.1s，同一量级）；emu 全量编译 923s vs 基线 14.5
min（+53s，+6%，新增 1,645 个函数的真实成本）。C2 pass 本身无额外开销
（merge 15.66s vs 基线 15.81s）。

**为什么亏（成本教训，对后续任何守卫类设计都成立）**：profile 的 skip 率
测量是对的，但成本模型漏算了三笔固定成本，恰好吃掉收益——

1. **逐 op en 检查比模型便宜得多**：sink 体内是热循环，分支预测器很快学会
   每个 en 的行为，同体 boundary 槽访问有局部性；真实成本接近"预测正确的
   分支"≈ 近乎免费，不是模型里的 2–4 instr。
2. **守卫读是缓存不友好的随机读**：1,645 个守卫值散布在 91 万字段的
   boundaryValueStore 里，每周期每个守卫一次潜在 cache miss。
3. **扫描路径变长**：+1,645 个超节点函数与调用点，每周期多 1,645 次
   call/ret + I-cache 压力。

**结论：不采纳**。方向在量级上本就是边际的（profile 最好档也只值 ~1–2%），
固定成本一进来就翻负。v2 架构当年选"事件即激活"隐含的就是这笔账。

## 正确性验证

全绿（日志 `ptmp/sink_guard_ab_20261004/`，单测日志
`ptmp/sink_guard_impl_20261004/`）：

- [x] `make test_wolvrix`：54/57，恰基线三项（transform-comb-lane-pack、
      transform-repcut、ingest-write-back-slice SEGFAULT），无新增失败
- [x] `make run_all_hdlbits_grhsim_ir_tests` 162/162
- [x] `make run_xs_bugcase_grhsim` 25/25
- [x] `make check_sim_refactor_baseline` 161/161 逐 eval 与黄金一致
- [x] XS 完整 CoreMark + NEMU difftest：**HIT GOOD TRAP、exit 0、逐拍轨迹
      instrCnt=663,688 / cycleCnt=297,291 与 V3-M3 完全一致**（语义未被改变）

另经单测钉住：守卫拆分结构（enableGuard == 成员共享 en）、compile&run 功能、
K=0 回退旧形态、mapping JSON 两阶段字节级 roundtrip、以及 C2.5 compact
重编号回归（f14 含阴性对照：禁用重映射即精确复现 XS 失败）。

## 后续

- **机制保留、默认关闭**：`XS_WOLF_GRHSIM_IR_SINK_GUARD_MIN` 默认已从 8 改为
  0（脚本 `scripts/wolvrix_xs_grhsim_ir.py`），pass 参数
  `--sink-enable-guard-min-size` 保留；wolvrix 改动（C2 细分 + enableGuard
  属性/序列化/校验器 + emit 调用点 + C2.5 compact 重映射修复 + 双单测 +
  文档）为未提交工作区改动，是否 commit 由作者定。
- **实施期修复的独立 bug（值得记住）**：C2.5 `clone-shared-boundaries` 的
  `model.compact()` 稠密重编号 value id，但未重映射超节点 attrs 里的裸
  ValueId——`enableGuard` 是 `CpuPartitionAttrs` 唯一存 value id 的字段，
  XS 上必触发（cloned=40,702），小设计 cloned=0 不暴露。教训：**mapping
  属性存 value id 的字段，必须同步注册进所有 value 重编号路径**。
- **若未来重启本方向，设计必须粗粒度化**：K=8 产生 1,645 组太多（固定成本
  主导）；潜在形态是大组（模块/单元级 union 守卫，数百而非数千组）+ 守卫位
  打包到少量字（避免散布大结构的随机读）。但即便乐观估计收益也在 ~1% 量级，
  优先级低于其他候选。
- profile 副产品可复用：`scripts/grhsim_reset_write_census.py`（折叠复位/
  条件常量装载普查）与 `ptmp/grhsim_reset_census_20261004/`（en 锥结构数据）。
