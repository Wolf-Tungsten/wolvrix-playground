# supernode-align 专题索引

主题：超节点构造对齐——grhsim AM 的 compute block 构造 vs gsim 的 supernode 构造。目标：在同等超节点数量前提下，AM 跨超节点边数差距收敛（**自 NO0012 起主指标为 compute 网络口径：两侧同规则剔除 state-write 消费方**）；手段是扩展 coarsen 合并规则与图形级 pass，性能不回退为硬约束。

**口径沿革**：NO0002–NO0011 主指标 = cross_values（含 commit 消费方）；**NO0012 起主指标 = cross_values_compute_network**（commit 消费方作为 context 跟踪）；**NO0013 起节点单位 = atom（AM 侧）/ node（gsim 侧）**（atom 一等公民化落地，gsim when 折叠口径证实后裁定 gsim 统计不动）。旧文档比值按各自口径阅读。

**当前基线（自 NO0013 起，atom 口径）：gsim 打平图不变（88,375 超节点 / 178,151 compute_network），AM `xs_am_no0007p3_20260808`（22,565 块 / 2,620,125 atoms / 515,057）——当前读数 2.8911x（达标线 195,966），nodes 0.8608x，difftest 通过且仿真 −1.0%**。NO0010–NO0012 基线（打平图 instruction 口径）与旧最佳 2.91x（518,808，opt1）存档见各文档。

管理规则见 [../RULES.md](../RULES.md)。

## 记录索引

| 编号 | 标题 | 日期 | 内容摘要 |
|---|---|---|---|
| [NO0001](NO0001_超节点构造对齐开题_20260803.md) | 超节点构造对齐开题 | 2026-08-03 | 开题：目标、指标口径、现状（AM coarsen 三规则）、测量与迭代计划 |
| [NO0002](NO0002_基线测量与口径固化_20260803.md) | 基线测量与口径固化（旧基线） | 2026-08-03 | 口径固化（cross_values 主指标）；旧基线：gsim 生产图 84,786/185,716，AM 25,860/1,503,473，比值 8.095；含口径勘误 |
| [NO0003](NO0003_归因轮询扼杀Out1链式合并_20260803.md) | 归因：轮询扼杀 Out1 链式合并 | 2026-08-03 | 块数/预算无关；gsim 鲸鱼尾；相位式调度落地生产：旧基线 8.10x→4.01x（744,513）；附规则沙盒 |
| [NO0004](NO0004_剩余差距归因与规则实验_20260803.md) | 剩余差距归因与规则实验 | 2026-08-03 | commit 182,810 结构性 + compute 3.31x；PrevSibling/MuxCond/预算均无效；replication 潜力 ~116k |
| [NO0005](NO0005_决定性归因差异在图形不在规则_20260804.md) | 决定性归因：差异在图形不在规则 | 2026-08-04 | gsim 式合并复刻在 gsim 图复现 204,972 ≈ 185,716；AM fanout≥2 value 2.44 倍于 gsim；路线转向图形级 pass |
| [NO0006](NO0006_图形级杠杆量化与可达性终审_20260804.md) | 图形级杠杆量化与可达性终审 | 2026-08-04 | alias 消除 -3.6%；logic_and 归因；1.10x 在范围内不可达的证明；最佳 4.01x；决策建议 |
| [NO0007](NO0007_next-state架构设计commit吸收_20260804.md) | next-state 架构设计：commit 吸收 | 2026-08-04 | 用户选定方向 2；写组重写为链逻辑+copy（无新 opcode）；**已被 NO0009 回滚** |
| [NO0008](NO0008_next-state_P1实施与指标验收_20260804.md) | next-state P1 实施与指标验收 | 2026-08-04 | 重写 pass + cycle_boundary 导出 + 分桶修复；commit 侧 -90.6%；**已被 NO0009 回滚** |
| [NO0009](NO0009_next-state方案终止与整体回滚_20260804.md) | next-state 方案终止与整体回滚 | 2026-08-04 | 用户裁定：链逻辑致纯组合节点过度激活、仿真性能严重恶化；全部还原；保留相位式 coarsen 与测量链 |
| [NO0010](NO0010_归零重启打平图基线_20260804.md) | 归零重启：打平图基线 | 2026-08-04 | T5 口径确认（gsim 精确命中 2,813,531）；收官复现 2,827,613（1.0050x）；新基线 rotation 7.64x / sequential 3.96x；复现配置固化为默认（HEAD≡收官） |
| [NO0011](NO0011_新基线归因与图形级pass落地_20260804.md) | 新基线归因终审与图形级 pass 生产落地 | 2026-08-04 | 新基线归因（fanout≥2 2.46x、出度1 链环 29.4 万、commit 19.5 万结构性）；容量路线 2.74x 终审封顶；CSE 被 Observable 封死的根因（84.4 万声明变量）与解锁+assign 别名+ROM 折叠落地生产：3.96x→3.65x，指令 -9.9%，difftest 通过 |
| [NO0012](NO0012_口径重构compute网络主指标_20260804.md) | 口径重构：compute 网络主指标与 commit 开销审计 | 2026-08-04 | 用户裁定：commit 块不被激活（act.f 入 commit 审计零剩余）；主指标改 compute 网络口径（两侧剔 state-write 消费方），结构性地板移除；新基线 opt1 2.91x / opt1cap 2.59x；新达标线 195,966 |
| [NO0013](NO0013_atom口径基线_20260808.md) | atom 口径基线：节点单位对齐与新读数 | 2026-08-08 | gsim when 折叠口径证实（126,005 根藏 87,356 嵌套 mux）；用户三点判断落地（am-graph NO0007：atom 一等公民化）；新基线 AM 22,565 块 / 2,620,125 atoms / 515,057 = **2.8911x**（现最佳），nodes 0.8608x，def_use_value_edges 证据边口径本无水分；旧口径数字存档不回改 |
| [NO0014](NO0014_分区算法无错图病灶定位_20260808.md) | 分区算法无错：图病灶定位与容量常数解构 | 2026-08-08 | 离线分区实验室（partition_lab 逐行移植，双侧重现 ±2-5%）；块数 3.9x = 容量常数机械商（同容量块数 1.15x）；3x 差距是图属性（序/容量不敏感）；三病灶消融：mux 全局融合 −80k、链预算 256→7000 −71k、mem.read 不拆 −59k；**cap24 块数对齐实测：83,673 超节点对齐达成但 host +9.2%（338.2s）、主指标恶化 3.23x——先修图再降容量** |
| [NO0015](NO0015_链粗化形状诊断与修复_20260808.md) | 链粗化形状诊断与修复 | 2026-08-08 | 诊断+修复全链：主因是候选供给（outdeg==1 占比 26% vs 81%）；mergeWhen 收官后 fanout 吸收 pass 落地（absorbFanoutAtoms，锚点档 396,008→192,054=**1.078x 达标**），但 host +139~164%（单次块激活重算 2.9x，激活次数不降）——cross 与 host 在复制语境下脱钩，出货默认关闭；上游归因终审：CSE/alias/unify 无罪，atom 级 51.6% vs 8.9% 大部分是 fold 粒度浓缩（指令级真实差距 18.7% vs 8.3%），主成分是固有的 1-bit 条件共享网络 + mem.read 读口（P-A array-split 待做）；copy 模式对照实测不如 absorb |
| [NO0016](NO0016_图结构差异根因firtool降低制造共享_20260808.md) | 图结构差异根因：firtool 降低制造共享 | 2026-08-08 | why 终审：分叉点在 MFC 产 .fir 之后——firtool `-O=release`+disallowLocalVariables 把单使用、含重复的 FIRRTL（2.48M 节点、fanout≥2 仅 8.4%）CSE/合并/提升为 68% 多使用的具名 wire SV；gsim 直读 FIRRTL 保持原形态（209k→253k 几乎不变）；聚合打包（slice/concat 网络）、when 压平（mux 显式化）、存储降低（mem.read 读口）同源于此降低；差异在模拟器拿到输入前已固化 |
| [NO0017](NO0017_图结构与性能因果归因_20260808.md) | 图结构与性能的因果归因：怀疑链的量化论证 | 2026-08-09 | ABCD 四层归因完成：①原始怀疑证伪——激活量 AM 仅为 gsim 0.72x、激活过滤净收益 7.4x、commit 相 26%、重发 3.6%、活动度分布同构；②干净定论 **AM 13.3x / legacy 20.7x vs gsim，引擎项为主**（同图对照 571.7s vs 27.6s），difftest <1%；③C2 粒度扫描单调降（cap100≈gsim 粒度最优，"小块少跨边"与运行时最优方向相反）；④D 引擎归一化：import 通道全通（结构证据：同管线块数 0.53x/commit 0.09x/dag 边 0.58x——块数差异来自图结构本身），执行对比被 AM 调度器对 import 图的兼容性 bug 阻塞（legacy 引擎同图证图完好、寄存器冻结 0 退休，已隔离）；emitter 新增 fullEvaluation/changedTrace/块 exec 导出/端口净化/fatal 支持 |
| [NO0018](NO0018_分区校准atom到block映射贴合_20260812.md) | 分区校准：atom→block 映射贴合 gsim node→supernode | 2026-08-12 | 同图校准完成：归因 mergeWhen 不对称（flatten 图 gsim 已死 1,183 vs AM 433,095 merges）、out1 host 32k instr vs 7k nodes、DP cap 9 vs 15；pair-F1 主指标 0.4260→**0.9255**（nesting 36.69→63.07%、single-source →51.65%）；state-anchor 两模式被 F1 否决（0.894/0.827），残余差距判定为 value 图 vs 诱导子图的固有边界；校准点锁定为 CLI 默认；fusion 锚点改为块内局部计算与 mergeWhen 解耦 |
| [NO0019](NO0019_E3块级运行时激活分布对照_20260812.md) | E3 块级运行时激活分布对照 | 2026-08-12 | emit-cost 入场裁决：**分区变量关闭**——coremark 50k 窗两侧激活分布同构（gini 0.744/0.758，top10% 份额 0.525/0.532），am 激活总量不劣于 gsim（compute 0.62x/含 commit 0.94x），80.4% 簇 am≤gsim（p50=0.514）；37% 非嵌套边界未落热路径；附带发现 commit 块过滤失效（p50=每 eval 必激活，占 33.9% 激活量）；difftest gsim 默认非 flatten 口径坑记录 |
