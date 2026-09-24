# GrhSIM-IR XiangShan CoreMark 索引（微观指标驱动 · 节点树）

2026-09-23 方法论重启：旧索引及 NO00001–NO00059 报告已删除，历史结论不继承。节点编号自 **NO00001** 重启（沿用五位编号；旧编号随旧报告删除一并作废，新分支自 NO00001 重新计数），编号单调递增。节点以父指针组成树，允许从任意历史节点分叉与组合。

## 当前最佳

指针：**NO00004**（编译器 PGO 施加于 GrhSIM-IR emu，wolvrix `dc3e3cb` + 根仓库本节点提交，发射源与 NO00003 逐字节一致，仅编译 flag 变化），Host **55.864 s**（3 次有效均值，SD 0.270 s）；端点 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`。

**对照锚点（2026-09-24 起，用户指示两侧统一启用 PGO）**：gsim+PGO = **27.376 s**（3 次有效均值，SD 0.065 s；`make xs_gsim_emu_pgo` 构建，与非 PGO 归档模型源逐字节一致；同窗口非 PGO 对照 46.873 s，PGO 改善 −41.6%，p=0.05；测量细节见 goal 文档锚点节）。当前最佳对 gsim+PGO ≈ **2.041×**（剩余差距 ~28.5 s）；gsim 非 PGO 归档 46.965 s 仅作历史参考。

## 节点树

| 编号 | 报告 | 父节点 | 角色 | 锚定指标 | 判定 | 最终性能（Host s） | 关键结论 |
|---|---|---|---|---|---|---|---|
| NO00001 | [报告](NO00001-grhsim-ir-anchor-profile-20260923.md) | 无 | 诊断 | Host time 100k | ACCEPTED | 77.155 | 定标基线（wolvrix `4de8c01`）；噪声底 0.22%（3+3 协议可分辨 ≥3%）；M1–M4 定量基线：model_step 占 99.5%（compute 76.9% / commit 21.8% / publish 1.1%），任务级分布长尾无单点热点 |
| NO00002 | [报告](NO00002-grhsim-ir-disable-text-share-20260924.md) | NO00001 | 优化 | M-share ≤1%；M-tput ≥+6% | ACCEPTED | 70.134 | 关闭 shape-twin/branch-block 文本共享：M-share 36.29%→0%，M-tput +10.0%（dynOps 逐键不变），compute −7.76 s；编译时间几乎不变（195.95 vs 191.20 s），共享机制的运行时代价是纯损失； −9.42% Host，秩次判据 p=0.05 |
| NO00003 | [报告](NO00003-grhsim-ir-falling-edge-elision-20260924.md) | NO00002 | 优化 | M-neg ≤1.5% 且降 ≥80%（基线 2.868%） | REJECTED | 70.231（锚定 parity） | 下降沿 eval 整体消除被双重机制证伪：① 设计固有 neg 真实工作（409 ICG 锁存 latchWrite@ClockGate.sv:11 enable=¬clock + 2 negedge 边沿项 + 21 非 quiescent 系统单元）否决全部 4 个 1-bit 输入；② M-neg 基线 2.868%<3%（neg 单价 19.9 µs = pos 的 1/34，活动驱动已压制 neg 成本），收益上限 ≤2.0 s。设施保留：边沿分裂计时 + 资格分析器（fp_evals=0，对最佳点零回退） |
| NO00004 | [报告](NO00004-grhsim-ir-compiler-pgo-20260924.md) | NO00002 | 优化 | M-tput ≥+3%（基线 1.4184 Gop/s） | ACCEPTED | 55.864 | clang 三阶段 PGO（插桩构建→带 difftest 训练→profile-use 重建，合计 695.95 s 过门槛）：M-tput +25.6%（dynOps 由源逐字节一致锁定不变），−20.27% Host，秩次判据 p=0.05；收益分布：commit −58.6%（16.93→7.01 s，偏斜分支扫描对布局优化高响应）+ compute −8.4%；PGO 后 commit 相位收益基线重置为 7.0 s；`analyze_grhsim_cpu_profile` 地址连续假设与 PGO 函数重排不兼容（任务级 profile 链路待修）；llvm-bolt / -march=native 为后续正交手段 |
| NO00005 | [报告](NO00005-grhsim-ir-gsim-native-work-20260924.md) | NO00004 | 诊断 | M-vol（两侧原生动态指令量）、M-cpi（两侧原生 CPI） | ACCEPTED | 55.864（指针不动） | gsim 环比口径建立：2.04× Host 差距 = 原生指令量 **2.4386×**（模型净 2.4477×）× CPI **0.8389**（ir 反优 16%），频率闭合 0.03%——剩余路径是模型净工作量削减而非 CPI；compute_task 一类（3.84 M instr/cycle）= gsim 全部模型执行（1.93 M）的 2.00×，commit+infra+evaluator 结构开销 0.87 M/cycle（18%）gsim 无对应类；CPI 归因：gsim 巨型 subStep（327 函数/.text 78.6MB）分支与取指 miss 密度显著更高；任务级 profile 链路修复（两参 tick）并双链路互证（80.5/11.0 vs 80.2/10.9 pp） |
| NO00006 | [报告](NO00006-grhsim-ir-supernode-granularity-20260924.md) | NO00004 | 优化 | M-act（dynOps/cycle）≥25%；M-tput ≥6% | REJECTED | 55.840（+0.09%，持平） | compute supernode 上限 128→64 单变量实验：粒度 −45%（unit 1.82×、ops/activation −47.7%）但激活数 +60.6%（扇出边密度驱动），dynOps 仅 −16.01%（弹性 ≈−0.2）未达 25%；instr −6.05% 被 CPI +6.49%（branch-miss +37%、icache +19%、evaluator +0.98pp）全数抵消，Host 持平；boundary 写 −14.2% 同步下降；gsim 低 op 求值量非粒度效应（同尺寸激活率 27.4% vs ~10.6%）——差距主因是激活率/扇出精度结构 |
| NO00007 | [报告](NO00007-grhsim-ir-cone-guard-20260924.md) | NO00004 | 优化 | M-act 降 ≥40%；M-tput 降 ≥10% | REJECTED | 55.864（指针不动，F1 提前止损无生产构建） | 变化 token 粘性掩码 + RS 区域守卫（单位内输入精度）：F1 门触发——动态 k̄=9.59（k≤2 仅 31.4%、k≥9 占 39.3%）把锥并集残余推到 61.81%>60%（普查 k=1/2/3 残余 23.4/38.4/49.1% 外推闭合），M-act −26.15% 未达 −40%（需残余 ≤41.6%⇔k̄≤2.3）；正确性多重验证（双构建端点四字段精确匹配、snl=0、deadpub=0、tok_sum 双构建 0.004%、旧口径 7e-9 一致、终态复跑逐项一致）；gsim k≈1 即时求值 vs ir 批量粘性激活是锥精度机制结构瓶颈；设施门控留存（GRHSIM_CONE_GUARD，门关与 NO00004 逐字节一致） |
| NO00008 | [报告](NO00008-grhsim-ir-gsim-activation-profile-20260925.md) | NO00004 | 诊断 | M-gact（gsim super 激活/cycle）、M-gwork（动态 node/enode/cycle）、因子表 F | ACCEPTED | 55.864（指针不动） | gsim 侧首批动态口径（原生 runtime profile，零冻结面改动；有效性/确定性/模型一致性门全过）：M-gact 17,631.8 act/cycle（全局激活率实测 20.83%；同尺寸 n_comp 55–65 桶 20.44%——NO00006 的 ~10.6% 估计作废，ir 27.4% 差距实为 1.34×）；M-gwork 829,144 node + 4,256,657 enode/cycle（241.4 enode/act、0.452 instr/enode）；M-gchg 派生下界 10,786.9 changes/cycle；**因子表 F 闭合残差 0%：2.0× 指令差距完全闭合于每单位工作指令密度 8.54×**（ir 3.86 instr/dynOp vs gsim 0.45 instr/enode，粒度覆盖仅 4.28×），变化流密度 1.175× 非主因；变化检测 ir 221,343 vs gsim 87,965 次/cycle（2.52×）；sink 类 fire 份额 54.2%；Pareto 平坦（Top 20 仅 15.6%），super 个案优化无空间；后续方向排序：每 dynOp 指令密度 > boundary 检测频次 > 变化流密度 |

## 机制证伪表

`REJECTED` 节点的机制性错误结论与证据指针。新假设与表内条目冲突时，须先给出反驳证据方可立项。历史结论不继承，以本分支证据重建。

| 机制类 | 机制层面证据（节点） | 备注 |
|---|---|---|
| 下降沿 eval 整体消除（冻结双相 tick 的 neg 半周视为纯簿记） | NO00003：XS 上 4 个 1-bit 输入全部被资格否决，neg eval 含设计固有真实工作——409 个 ICG 使能锁存 `latchWrite@ClockGate.sv:11`（enable=¬clock，k+1 gated clock 依赖其新值）+ clock input.read 上 2 个 negedge 边沿项 + 21 个非 quiescent 系统单元（188 op，difftest DPI 等）；且 M-neg 基线实测 2.868%（<3% 门槛），neg eval 单价 19.9 µs 仅为 pos 的 1/34（活动驱动已压制 neg 成本） | 保留真实 negedge 工作的选择性消除不受结构证伪约束，但收益上限 ≤2.0 s（M-neg 2.868%×Host），立项前须论证可在该上限内取得 ≥3% 显著收益；边沿分裂计时 `[grhsim-cpu-edge]`、资格分析器、M-neg 锚定基线为可用设施 |
| 尺寸上限细化 compute supernode 以降低 op 求值量（dynOps 由激活粒度决定的命题） | NO00006：cap 128→64（unit 1.817×、ops/activation −47.7%），激活数 +60.6%（扇出发布 +51.9%：消费者摊入更多单元，value→consumer-unit 边密度控制激活数），dynOps 弹性 ≈−0.2 仅 −16.01%；boundary 写 −14.2%（同步下降非增长）；instr −6.05% 被 CPI +6.49%（branch-miss 密度 +37%、icache +19%、evaluator 份额 +0.98pp）全数抵消，Host +0.09% 持平 | gsim 低 op 求值量**非**粒度效应；继续细化单调恶化 CPI。后续激活率机制（支撑集纯化锥、输入端口级精度、扇出结构、单 pass 调度）不受本条证伪约束，但立项须论证如何在不增长扇出边密度的前提下降低激活率。⚠ 本条原引"同尺寸激活率 ir 27.4% 对 gsim ~10.6%（instr 加权估计）差 ~2.6×、激活率结构是差距主因"的推断已被 NO00008 实测修正：gsim 同尺寸（n_comp 55–65）激活率 **20.44%**/cycle、全局 20.83%，~10.6% 估计作废——同尺寸差距实为 **1.34×**，变化流密度比仅 1.175×，"激活率结构主因"推断强度下调（NO00008 因子表闭合主因为每单位工作指令密度 8.54×） |
| 单位内输入精度锥守卫（变化 token 粘性掩码 + RS 区域守卫压缩每激活 op 数，不动分区/边/激活条件） | NO00007：守卫池 18,132 单元/68.46% dynOps（T=0.5 选择器）；粘性掩码在 unit 级批量激活语义下 k̄=9.59（k≤2 仅 31.4%、k≥9 占 39.3%；chg/act 31.36% × rounds/eval 2.005，两次执行间变化批进同一掩码），锥并集残余 61.81%（普查残余-k 曲线外推闭合）>60% F1 门；M-act −26.15% < −40% 阈值（需残余 ≤41.6%⇔k̄≤2.3，差 4 倍非边际）；正确性多重验证（双构建端点四字段精确匹配+DIFFTEST 干净、snl=0、deadpub=0、tok_sum 0.004%、±55/993M 静默激活归因、终态复跑逐项一致） | gsim 每值持久 flag + 单 pass 即时求值保持 k≈1；ir 的 unit 级批量激活把 k 推到 ~10——残余由激活批量决定而非锥结构，与 NO00006 合流：dynOps 两个乘数的削减都被激活语义卡住。后续降低每激活 token 批量的机制（逐变化即时求值、round 级掩码消费、逐变化扇出精度）不受本条证伪约束，立项须实测论证 k̄≤2.3 且池残余 ≤40% 可达；可用设施：GRHSIM_CONE_GUARD 门控发射器（门关=父节点逐字节）、`analyze_grhsim_cone_guard` 普查、snx/tok/snl 计数器 |
