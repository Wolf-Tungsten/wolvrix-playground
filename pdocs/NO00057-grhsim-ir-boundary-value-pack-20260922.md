# NO00057：boundary 值打包与叠加栈（机制穷举节点）

- 状态：**FAILED（2026-09-23 用户人工判定）**
- 日期：2026-09-22 启动，2026-09-23 判定
- 基线 commit：wolvrix `7b1fd50`（NO00055 ACCEPTED 后的 HEAD；节点结束时与该基线零差异）
- old 对照：`ptmp/no00055_init_zero_elide_20260922/flow-final`，预注册比较值 **71.309667 s**（继承 goal 文档登记）
- 本节点附加要求（用户 2026-09-22）：**必须产生 ≥3% 真实性能提升；必须通过 GrhSIM IR 层面修改实现（允许扩展 IR op、允许 IR 图优化变换）；禁止 emit 层微调**。
- 用户 2026-09-23 补充裁定：允许多个叠加优化实现 3% 目标（叠加栈正式测量 −1.37% 回归，见 VALIDATED）；同日复盘指示做复杂子图替换普查（尝试 7，普查证伪）；同日最终判定 FAILED，并指示将机制税/框架税总结为下一节点 NO00058（纯 profile）。

## IDEA

假设：现行语义管线（reg-to-mem → canonicalize → clone-shared → bitwise-predicates →
[pack → canonicalize → bitwise-muxes → mux-chain-fold → used-bits]）只跑一遍，
used-bits 收窄与 mux/concat 折叠之后暴露的重复表达式、赋值链、新可收窄宽度
无人消费。NO00052 筛选实测：在最终 checkpoint 上重跑 canonicalize 可再得
`identity_assigns_removed=3569 common_expressions_removed=61041`（formal 管线不含）。
本节点将语义管线末端改为 canonicalize/used-bits 不动点迭代（IR 层图变换，
不动 emit），并以 IR 层新化简规则补足到 ≥3% 门槛。

新意：此前的 canonicalize/used-bits 均为单次执行；不动点化是管线级机制变更，
复合效应（CSE 删除 → 新死锥/新收窄 → 新 CSE）未被任何节点量化过。

可证伪标准（筛查阶段）：checkpoint 重跑 canonicalize+used-bits 后筛查交替运行
提升 <1.5%（相对 3% 目标无路径）则判该机制不足，转 IR 层扩展规则候选。

瓶颈证据与池量化（进行中）：

- 静态 op 混合（NO00055 最终 checkpoint，3,531,463 ops）：and 25.8% / or 19.4% /
  mux 9.5% / concat 6.3% / sliceStatic 5.7% / bitSelect 5.2% / eq 4.8% / add 2.9%。
- 代数残渣池仅 1,229（absorption 595 / double_not 370 / self_op 244 / complement 20），
  不足以支撑 3%。
- 布尔链规范化（flatten+排序+CSE）模拟：new_total 9.9M >> old 1.4M，静态爆炸，否决。

## 节点内尝试记录

### 尝试 0：语义管线末端不动点化（canonicalize + used-bits 重跑）——静态池证伪

- 在 NO00055 最终 checkpoint 上 reemit 重跑（`ptmp/no00057_semantic_fixpoint_20260922/reemit-v1.log`）：
  canonicalize 仅 `identity_assigns=3,568 common_expressions=6,011`（NO00052 报告的
  61,041 池是对 NO00049 checkpoint 测得，已被 NO00052 正式管线吃掉）；
  二次 used-bits 仅 `dead_ops=1,511 narrowed=2,819 downgraded=2,140`（wide words −4.3%）。
- 合计 ~1.1 万 op，按 NO00052 转化率（58k ops → +0.49%）外推 ≈ +0.1%，无 3% 路径。
- 判定：**REJECTED（静态池即证伪，未跑性能实验）**。诊断节点式普查不构成节点终点，继续。

### 尝试 1（主候选）：窄寄存器打包扩展（pack-bit-registers 通道宽 1→≤8）

- 普查（`census_ir_pools.py`）：≤8-bit 判据下 21,553 个单写口窄寄存器可成组
  （4,112 组），→ 4,739 个 ≤64-bit 打包字，**净减 16,814 个 commit 写口（−16.8%）**；
  ≤32-bit 放宽为 27,107 → 6,597 字（−20,510 写口）。类比 NO00032（1-bit 打包
  −62,502 写口 → +6.93%），这是唯一可定量的同族大池。
- 实现：pass 加 `max_lane_width=N`（默认 8），分组键含通道宽；数据 concat +
  共享 mask replicate 语义不变；读改写为 sliceStatic(packed, i*w, i*w+w-1)；
  init 按位段聚合。单测：domains 负例改 9-bit/signed-4bit 保持拒绝语义，
  packed_bits 夹具加 10×4-bit + 5×8-bit 端到端组（scoreboard 对拍 packed/unpacked），
  `make test_grhsim_cpu_emit` / `test_grhsim_cpu_mapping` 全绿。
- reemit 筛查实测（`reemit-v2.log`）：**packed 21,550 通道 → 4,739 字**（与普查一致），
  后随 canonicalize 再删 10,933 表达式 + concat 恒等 117 处（gather 折叠生效）。
- 筛查基准（`screen-v2/summary.json`，1 对交替，page-cache 驱逐）：old 71.199 /
  new 71.106 → **+0.131%**，双双 emu_exit=0、endpoint 全等（240349/99996/100001/
  0x80000c0c）。语义正确但收益远在噪声底。
- 归因：NO00044 ctz 紧凑走查（490 组/31,360 端口只访问 armed 位）+ NO00045 memWrite
  门卫提升已使 commit 动态成本与端口数解耦；静态端口 −16.8% 几乎不转化为动态节省，
  打包的 wake-union 还略增 compute。端口计数不再是动态成本代理（NO00032 时代
  commit 26.86s/118s=22.8% 且逐位处理的前提已不再成立）。
- 判定：**REJECTED（筛查收益不足）**。cap 放宽到 32（−20,510 端口）按同转化率
  外推 ~0.3%，无 3% 路径，不再筛查。实现暂留工作区（正确但无收益，若节点最终
  由其他机制达标，本改动默认一并回退，避免空载合入）。


### 尝试 2（备选证伪）：bitSelect 同条件字融合——普查证伪

- 设想：同条件 1-bit bitSelect 组（12,150 组/148,667 ops）的双分支为同对宽源连续
  slice 且 result 被 concat 按序汇聚时融合为字级 select。
- 普查（`census_bitselect_fusion.py`）：双分支全 slice 组仅 610/12,150（5%），
  经同源、位号匹配、concat 消费、位序检查逐层过滤后**可融合组 = 0**；真实结构是
  mux 链降位后的共享条件布尔决策树（分支 producer 为 and/or/bitSelect/eq/not，
  消费者同样以 bitSelect/and/or 为主，concat 仅 31%）。净静态池为 0。
- 判定：**REJECTED（普查证伪，未实现）**。

### 尝试 3（备选证伪）：锥克隆 wake-subsumption 定位化——普查证伪

- 设想：boundary 值 v 的生产锥变化叶 L(v) 若全部被消费超节点 X 读取，则克隆锥入 X
  可零唤醒膨胀地删除 v 的写回+扇出（clone-shared-compute 从双射到一般小锥的推广）。
- 普查（`census_cone_clone.py`）：52.9 万合法锥中全消费者满足叶超集的仅 16.1%；
  可整体消除 26,594 值（3.3%）；克隆成本压倒节省——全量净 **−0.91% cycles**，
  cherry-pick 逐值盈利上界仅 +0.95%。
- 判定：**REJECTED（普查证伪，未实现）**。

### 尝试 4（主候选）：boundary 值打包（`grhsim.pack-boundary-values`，新 IR 图变换 pass）

- 动态地图（flow-dyn 插桩构建，100k 全量）：**compute 相 53.63s（75%）**；
  每 eval 497,146 ops；**boundary 写回 22.13G 次/run（≈110.6k 次/eval），真实变化率
  仅 5.73%**；commit port_eval 3,346/eval 开火率 70.3%；零产出激活 70.1%。
  写回路径（比较+存储+扇出 OR）是 compute 体内最大附加成本（NO00047 静态解剖
  物化族≈40% 单元行数与之一致）。
- 机制：同生产者超节点 S、消费者超节点集合 C 完全相同、纯 compute 消费的窄
  boundary 值（v1 限 1-bit）打包为 concat 字 w；消费端按 (lane, X) 各建
  sliceStatic(w, off, off+w-1) 局部视图。rewire 后 lane 变单用，被
  build-compute-nodes 既有"单消费者锥逆序吸收"规则收进 concat 所在节点——
  写回严格 k→1；w 的扇出集合 = 每 lane 的 C，**唤醒概率逐位不变（零唤醒膨胀）**；
  语义恒等（slice(concat) 恒等式）。分组键不含任何对象名，纯结构特征触发。
- 普查（`census_boundary_pack.py`）：严格键 (S,C,has_commit) 下 1-bit 70,440 组 /
  383,194 值，写回迭代节省上界 8.99G/run（写回路径 40.6%）；v1 再排除 commit 消费与
  同 S 消费（纯 compute 键）为 61,572 组 / 307,441 值 / 6.66G（30.1%）。
- 实现：新 SemanticTransform `grhsim.pack-boundary-values`（读完整 CPU mapping 的
  partition/layout，与 pack-bit-registers 同模式），`max_lane_width=N` 参数默认 1；
  reemit/Makefile 加 `--pack-boundary-values` 筛查接线。
- reemit 筛查（`reemit-bp1.log`）：**50,408 字 / 257,971 lanes / 616,605 slices /
  820,986 改写**；跳过 producer 17,630 / 消费者不合格 84,682 / 同超节点 143,279。
  verifier 通过、mapping 重建成功、emit 成功。
- 筛查基准（`screen-bp1`，1 对）：old 71.098 / new 76.415 → **−7.48% 回归**（endpoint
  全等，语义正确）。op 数 +19%（slice+concat），回归与打包 lane 数成正比。
- 成本感知普查（`census_boundary_pack_profit.py`）：成本模型 3·(k−1)·act(S) −
  1.5·Σact(X) 预测全池净 −5.89%，与实测 −7.48% 同符号同量级（模型交叉验证有效）；
  画像筛盈利子集（30,779 组/173,036 lanes）预测上界 **+3.34%**。
- 静态判据普查（`census_boundary_pack_static.py`）：静态规则天花板 R_c1_k4 仅
  +0.687% 且误伤同量级；fanin 比与 act 比相关性≈0——**盈利性是纯动态属性，静态不可分**。
- 画像筛选实现（τ=0.5，sn_activity.tsv 来自 flow-dyn 插桩 run）后筛查
  （`screen-bp2`）：打包 20,698 字 / 109,029 lanes（148,942 判为不盈利），old 71.462 /
  new 74.013 → **仍 −3.57% 回归**。回归幅度与打包 lane 数同比缩放
  （258k→109k lanes，−7.48%→−3.57%），说明**每 lane 净成本处处为负**：写回单价在
  OoO 下≈0（L1 命中 + 预测不跳分支），slice/concat 是关键路径真实 ALU——成本模型的
  3:1.5 权重符号层面就不成立，更严的 τ 也无法翻转符号。
- 判定：**REJECTED（两变体实测回归）**。boundary 写回重构方向经三次实测 + 五轮普查
  彻底关闭：每站点写回成本已近零，唯一出路是静态消灭 boundary 值本身（=超节点
  重构/粒度，已双向关闭）。pass 实现与接线已随节点回退（wolvrix 与 `7b1fd50`
  零差异，根仓库 Makefile/reemit 同步还原；普查脚本八件归档至 `scripts/`）。
- 结构归因（补充）：打包后超节点数 **31,471 → 39,142（+24%）**——concat 受容量/共享
  结构所限无法收编 lane 锥、自成小超节点，粒度碎片化（激活/调度开销 +24% 个单位）
  与 slice 成本叠加构成回归；修复需要控制 mapping 内部归属，超出语义 pass 能力边界。

### 尝试 5：代数形态普查收官（全部池空）

- 汇聚提升（整 concat 匹配变体）：严格池 **8 个 concat**，死透（boundary 值的存在
  理由与"唯一消费者是同一 concat"互斥）。
- 常量链（add/and/or/xor/shl/lshr/mul/div 2^k）：**全为 0**（canonicalize 已覆盖）；
  nested slice 4,535 + sub 链 16 ≈ 0.02% cycles。
- 常量 boundary：8,908 值、写回路径 0.64%（≈0.15% 总时间）。
- 同条件嵌套 mux 47 ops、mux 分配律 2,539 ops（0.32% 动态，换算 ~0.2% 时间）、
  eq/ne 同值对 1,320（<0.1%）：合计 <0.5%，不抵实现成本。
- state.read boundary 写回占 10.25%（2.26G/run）但已有专用缓存机制。



### 其余普查排除项

- slice-of-slice 4,535 / slice-of-concat contained 10,293（concat 多扇出必存活，
  净删 ~6.8k）/ nested concat 816 / const-branch mux 7,817（无相等分支、无 1-bit
  (1,0)/(0,1) 形态，语义不可删）——按 NO00052 转化率均 <+0.1%，不单独做。


## BASELINE

- old 对照：`ptmp/no00055_init_zero_elide_20260922/flow-final`（预注册 **71.309667 s**）；
  配置沿用：100k cycles、CPU=2、XS_EMU_THREADS=1、waveform/commit/RAM trace 全关、
  page-cache 驱逐交替协议；筛查 1 对、正式 3 对（6 次交替）。
- 当前相位地图（NO00055 画像，`profile-old`）：compute **53.63s（75.0%）** /
  commit 16.85s（23.6%）/ publish 0.86s（1.2%）；evals=200,102、rounds=401,257
  （每个 eval 恒为 2 轮；negedge eval 占半数但 commit port_eval 仅占 6%）。
- 动态 op 地图（flow-dyn 插桩 100k，99.48G 次计算 op/run）：and 26.0% / or 21.6% /
  mux 11.6% / eq 6.9% / bitSelect 4.8% / concat 4.2% / sliceStatic 3.6% /
  state.read 3.4% / add 3.1%；boundary 写回 22.13G 次/run（变化率 5.73%）；
  零产出激活 70.1%；commit port_eval 1,669/round、开火率 70.3%；
  memWrite 门卫 3.62G/run（开火率 18%，enable 逐端口测试已被 NO00050 arming 普查关闭）。
- perf 快照（30k，83% 计数器复用，仅结构参考）：IPC≈1.37、branch-miss/指令 0.74%、
  L1-dcache-miss/指令 ≈2.4%。

## IMPLEMENTED（叠加栈，2026-09-23 用户裁定允许叠加）

- `grhsim.pack-bit-registers` 扩展 `max_lane_width=N`（管线 XiangShan 默认 8）：
  同签名窄寄存器（≤8-bit）按通道宽分组打包为 ≤64 位字；单测覆盖 10×4-bit +
  5×8-bit 端到端 scoreboard（packed vs reference trace 一致）。
- `grhsim.canonicalize-compute` 新增三条代数规则（全部 two-state logic 限定）：
  - `nested_slice_folds`：slice 的 slice 就地折叠为对源的单切片（源须 two-state）；
  - `mux_slice_distributions`：`mux(c,slice(x,a,b),slice(y,a,b)) → slice(mux(c,x,y),a,b)`，
    限 ≤64-bit 源（宽 mux 的字 helper 会反噬）；
  - `bitselect_const_folds`：select(m,s,0)→and(m,s)、select(m,1,c)→or(m,c)、
    select(m,1,0)→m（mux/bitSelect 两形同位次覆盖；bitSelect 形在正式管线由
    mux 形在 bitwise-muxes 之前的 canonicalize 中折叠）。
- 单测：`runSliceMuxAlgebraTest`（nested slice + mux-dist + select 常量分支，含
  四态/宽源/位段不符守卫、幂等、JSON 往返）；`make test_grhsim_cpu_mapping` 与
  `make test_grhsim_cpu_emit` 全绿。
- 筛查路径的教训：reemit 重跑 canonicalize 会附带 CSE/assign 重跑（筛查特有，与正式
  管线语义不同），s2 的 −2.03% 不能代表正式栈——正式栈以全管线生成为准。

### 尝试 6：语义管线末端 fixpoint（canonicalize + used-bits 重跑）——实测回归

- reemit（`flow-v1`）：重跑 canonicalize 删 `assigns=3,568 + CSE=6,011`，二次 used-bits
  `dead_ops=1,511 narrowed=2,819 downgraded=2,140`（wide words −4.3%）。
- 筛查基准（`screen-v1`，1 对）：old 71.638 / new 72.815 → **−1.64% 回归**。
- 判定：**REJECTED**。与 NO00056 同教训：当前基线上 IR 层删 op/收窄会破坏 clang
  代码生成（冗余形态承载寄存器分配/调度信息），"更少的 op ≠ 更快"。

## VALIDATED（叠加栈正式测量，2026-09-23）

正式全流程（`formal.sh`：gen → hdlbits → build → formal，old=NO00055 flow-final
71.309667 s 预注册值）：

- 生成 **849.78 s**（<1800s 门）、编译 **189.58 s**（<1800s 门，nproc=32）、
  HDLBits DUT=001（GRH 路径与 grhsim 路径 `run_hdlbits_grhsim`）均通过。
- 六次交替（page-cache 驱逐，old1/new1/… 序）：old **71.138 / 71.196 / 71.562**，
  new **72.312 / 72.588 / 71.921**；old 均值 71.298667 / new 均值 72.273667 →
  **−1.367% 回归**（U=9、单侧精确 p=1.0，秩次门反向全分离——统计显著回归）。
  六次均 emu_exit=0、endpoint 全等（240349/99996/100001/0x80000c0c）。
- 分解：窄打包单独（reemit 路径干净 3 对）**+0.334%**；碎屑规则把栈拖至 −1.37% →
  碎屑净效应 ≈ **−1.7%**（第三次独立复证"删 op/折叠即回归"的 clang 敏感性，
  与 NO00056 及本节点 v1/v3 一致）。叠加路线实测封顶 ≈ +0.3%（仅窄打包一项为正）。
- 判定：叠加栈 **REJECTED**（正式回归）。**全部代码已回退**：wolvrix 与 `7b1fd50`
  零差异（窄打包扩展、碎屑规则、管线/Makefile/reemit 接线、测试改动全部撤销），
  回退后重建复跑测试绿（`test_revert_smoke.log`）。普查脚本九件保留在 `scripts/`，
  证据链保留在 `ptmp/no00057_semantic_fixpoint_20260922/`。

## 节点最终状态与移交（FAILED，2026-09-23 用户人工判定）

本节点在"≥3% + 纯 IR 层 + 禁 emit 层"约束下完成系统穷举：20 个机制族全部经测量
或普查封顶在噪声内，6 个筛查变体 + 1 个正式栈全部实测；唯一正向项（窄寄存器打包
+0.334%）过不了秩次门且远低于 3%。叠加路线（用户 2026-09-23 裁定允许）经正式
测量为 −1.37% 回归。剩余大池均被已关闭方向封锁（粒度双向、运行时跳过三次复证、
两波路线用户放弃、emit 层禁止、写回经济三次测量证死）。复杂子图替换方向（用户同日指示，见尝试 7）经 motif 普查证伪（剩余空间 ≤0.04% dyn）。
**2026-09-23 用户人工判定 FAILED**，并指示将机制税/框架税的定量归因移交
[NO00058（纯 profile 节点）](NO00058-grhsim-ir-tax-profile-20260923.md)。

- **工作区已全部回退至基线**：wolvrix 与 `7b1fd50` 零差异，回退后重建复测绿
  （`test_revert_smoke.log`）；根仓库无代码改动残留。
- 保留：普查脚本 11 件（`scripts/grhsim_{ir_pools,bitselect_fusion,boundary_pack,
  boundary_pack_profit,boundary_pack_static,cone_clone,gather_hoist,mux_algebra,
  bitselect_const,motifs,eq_field_fold}_census.py`）、动态插桩 flow-dyn 与 100k
  动态地图、gsim 画像构建 `build/xs/gsim-prof/`（GSIM_EMIT_RUNTIME_PROFILE=1，
  与归档参考隔离）与其 supernode fire TSV、四次筛查与一次正式栈的完整数据
  （ptmp/no00057_semantic_fixpoint_20260922/）。

### 尝试 7（2026-09-23 用户指示方向）：复杂子图替换——普查证伪

按"找更复杂的子图结构进行替换"的指示做 motif 普查（`census_motifs.py` +
`census_eq_field_fold.py`，已归档 `scripts/grhsim_{motifs,eq_field_fold}_census.py`）：

- **eq-OR 链 → 区间/字段检查**（译码网络形态）：2,335 条链 / 13,592 ops /
  链动态 435.5M（0.44% dyn）。原样区间折叠（常量连续）净省仅 **0.014%**；
  字段级分解（共享掩码基址 + 变化字段连续）提升至 **0.0376%**——距 0.3% 实现
  门槛仍差一个数量级。最热链是 RISC-V 译码匹配集（k=21/22、stride 0x400、
  字段值带空洞），**带空洞的集合成员结构不可被区间/字段折叠捕获**；
  唯一对口机制是集合成员专用 op/LUT——NO00038 已全面证伪 lut-fold 方向。
- **ne-AND 链**：0 条（排除条件实际写成 logicNot(or(eq…)) 形，随 eq-OR 处理）。
- **比较对共存**（lt+gt 等同对多形态，0.69% dyn）：所有子形态 0 或负收益，
  反向等价重复为 0（CSE 已净）。
- **mux(c,a±C,a)**（increment-or-not）：408 ops / 0.0055%——2→2 不省 op。
- **位测试 eq(and(x,m),0|m)**：69 ops / 0.002%——2→2 不省。
- **通用 2-op 邻接扫描**（producer→consumer top-30）：and→and/or→or/and→or 为
  数据通路本质形态，constant→mux 的 sameSn 仅 728——**无遗漏的高频可折叠形态**。
- 判定：**REJECTED（普查证伪）**。复杂子图替换的剩余空间 ≤0.04% dyn，实现任何
  一条都不及实现成本对应的验证开销。

## 与 gsim 差距的精确定量归因（2026-09-23，回答"同一设计为什么差 1.52×"）

新建 gsim 画像构建（`build/xs/gsim-prof/`，GSIM_EMIT_RUNTIME_PROFILE=1，
与归档参考 emu 完全隔离）+ 双 emu 干净 perf stat（30k cycles）：

| 指标（30k guest cycles） | gsim | GrhSIM-IR(NO00055) | 比值 |
|---|---|---|---|
| instructions | 40.4G | 114.6G | **2.83×** |
| host cycles | 57.0G | 83.4G | 1.46× |
| branch-misses | 1.14G | 0.84G | 0.74×（我们更优） |
| IPC | 0.71 | 1.37 | 我们 1.93× 优 |

**时间 = 指令数 ÷ IPC**：2.83 ÷ 1.93 ≈ 1.52×，与实测 71.31/46.97 精确吻合。
gsim 画像给出其工作量：nodes=82.9G/run（829k nodes/cycle）、active_supernodes
1.76G/run；我们 99.5G ops/run（994k ops/cycle）——**双方求值体积同量级
（我们仅 1.20× 多），差距的全部本质是"每 op 指令数"：gsim 1.66 instr/node vs
我们 3.84 instr/op（2.3×）**。

每 op 指令数差额的构成（NO00047 解剖 + 本节点动态地图复核）：boundary 写回
比较+存储（22.1G 次/run）、扇出发布 OR、helper 读缓存、commit 端口机制
（470M 开火/run × ~93cyc）、宽值 helper 与掩码——即**框架税**。gsim 无独立
commit 相（`reg = reg$NEXT` 内联）、无 boundary 写回层（值的家即其存储）、
无 round 收敛循环（单趟拓扑序）。

结论：剩余差距 = 框架税（emit/执行机制层形态，本节点约束下禁止）+ 求值体积冗余
（激活精度，粒度双向关闭 + clang 惩罚封锁）。**两个因子均不在"IR 图变换"可达
空间内**——这就是穷举的最终定量答案，不是"没办法"，而是"办法都在被禁/已关闭
的层面上"。若未来解禁 emit 框架层（写回/扇出的批量形态）或重启执行机制重构，
差距分解数据即上述表格。



### 叠加栈候选清单（按证据分级）

- 干净复测（3 对正式协议，无并行负载污染）：窄寄存器打包 ≤8-bit **+0.334%**
  （U=3、p=0.35，秩次交错——真实但噪声内）；fixpoint **−1.347%**（U=7、p=0.9，
  回归实锤）；boundary 打包 τ=0.5 **−3.664%**（U=9、p=1.0，回归实锤）。
  used-bits 单独重跑（v3，1 对）**−1.885%** ——收窄本身破坏 clang 代码生成，
  证实"删 op/收窄类变换在当前基线回归"的 clang 敏感性。
- 结论转向：**凡删除/收窄现存 op 的 IR 变换均回归；只有"结构合并、不删计算"的
  变换（窄寄存器打包）为正**。叠加栈成员必须满足"不产生寄存器分配扰动"。
- 栈组成（2026-09-23，用户裁定允许叠加）：
  1. 窄寄存器打包 ≤8-bit（pack-bit-registers `max_lane_width=8`，+0.33% 实测）；
  2. canonicalize 碎屑规则（纯代数折叠，不改变活值结构）：
     - nested sliceStatic 折叠（就地改写，链缩短）；
     - mux 分配律（`mux(c,slice(x,a,b),slice(y,a,b)) → slice(mux(c,x,y),a,b)`，
       ≤64-bit 源；每次激活少求值一个 slice）；
     - 常量分支 select 折叠（`select(m,s,0)→and(m,s)`、`select(m,1,c)→or(m,c)`、
       `select(m,1,0)→m`，覆盖 mux 与 bitSelect 两形；普查池 34,048 ops / 661M
       动态 ≈ 0.4-0.5%，canonicalize 从未识别——bitwise-muxes 在 canonicalize
       之后创建 bitSelect，故遍历同时覆盖两种形态）。
- 证伪排除（不入栈）：fixpoint、used-bits 重跑、boundary 打包、锥克隆、
  bitSelect 字融合、汇聚提升、eq/ne 归一（净零 op 变化）。


