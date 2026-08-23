# TES 性能看板

> 本文件由 `python3 tes/tools/tesctl.py dashboard` 生成；record-baseline / record-eval /
> finish-step / close-run / action-done 等状态变更后也会自动刷新。**请勿手改。**
> 生成于 2026-08-23T08:14:29+08:00

## 任务 `grhsim-am-coremark`

run **r003**（completed）· C=2 L=8 K=2 · evals 34/32 · actions 25 · 下一步 `run-closed`：r003 已收口；可开新 run（restart）

| 基准 | eval | Host 中位 | vs target |
|---|---|---|---|
| gsim（target） | e00052 | 45.9s | 1.00x |
| am（y0 基线） | e00051 | 364.0s | 7.94x |
| **当前 best** | e00057 | **229.4s** | **5.00x** |

基线→target 进度：`████████░░░░░░░░░░░░` 42.3%（364.0s → 目标 45.9s，当前差距 5.00x）

| 轨迹 | 分支 | 步数 | best eval | best Host |
|---|---|---|---|---|
| t0 | `tes/r003/t0/main` | 8/8 | e00057 | 229.4s |
| t1 | `tes/r003/t1/main` | 8/8 | e00056 | 242.0s |

| eval | 类别 | 位置 | Host 中位 | vs target | 状态 | 假设 |
|---|---|---|---|---|---|---|
| e00001 | baseline-am | - | 273.1s | 5.95x | ok | am baseline |
| e00002 | baseline-gsim | - | 24.7s | 0.54x | ok | gsim baseline |
| e00003 | candidate | t0/s01c1 | 279.2s | 6.09x | ok | chunk 3000->12000 使更多窄值 chunk 内标量化、减少跨 chunk uint6… |
| e00004 | candidate | t0/s01c2 | 271.1s | 5.91x | ok | 标量 mux 全量 if/else 化（branchy-mux）：若显著恶化则量化分支误预测成本并关… |
| e00005 | candidate | t1/s01c1 | - | - | compile_timeout | 状态按块静态访问亲和性聚簇布局（标量成员+宽值池，stateLayout=affinity）后热块工… |
| e00006 | candidate | t1/s01c2 | 270.5s | 5.90x | ok | 消除同宽无符号resize_value胶（静态94.1%站点、占胶95%）后热块动态指令数/依赖链缩… |
| e00007 | candidate | t2/s01c1 | - | - | compile_timeout | 状态按块静态访问亲和聚簇布局（init宽池store按offset升序修复后）热块工作集局部性改善，… |
| e00008 | candidate | t2/s01c2 | 272.7s | 5.95x | ok | 对常量切片主导的宽状态做标量炸开（元素数组声明+直读/单元素写）后，计数器网络族的词提取+栈数组往返… |
| e00009 | candidate | t0/s02c1 | 274.4s | 5.98x | ok | init()字面量0死store发射期消除后：runtime.o编译瓶颈移除（全程compile_s… |
| e00010 | candidate | t0/s02c2 | 273.3s | 5.96x | ok | branchy-mux与resize-elision机制正交，组合收益近似可加（期望-1.3%~-1… |
| e00011 | candidate | t1/s02c1 | 289.2s | 6.30x | ok | 激活合并455K静态/4.77G动态条件分支若显著误预测，去分支化(恒写活动字mask&actMas… |
| e00012 | candidate | t1/s02c2 | - | - | difftest_fail | 被commit act.b再激活的compute块（含b83400族）round-1 preset求… |
| e00013 | candidate | t2/s02c1 | 309.6s | 6.75x | ok | commit写站wrNext输入在生产者compute块未触发时等于已提交状态（compare幂等失… |
| e00014 | candidate | t2/s02c2 | 269.7s | 5.88x | ok | b83400型纯守卫块（fatal/fwrite全以changedResults_时钟沿槽为事件条件… |
| e00015 | candidate | t0/s03c1 | 247.5s | 5.40x | ok | 精确 64-bit source-part activity 区间守卫可跳过静默 part 的函数调… |
| e00016 | candidate | t0/s03c2 | 257.4s | 5.61x | ok | 按调度块首次触及顺序重排宽 BitVector/Array 存储并叠加 init-zero-elis… |
| e00017 | candidate | t1/s03c1 | - | - | compile_timeout | 重建 stateLayout=affinity 并按物理 offset 排列字面量宽初始化，若恢复编… |
| e00018 | candidate | t1/s03c2 | 244.3s | 5.33x | ok | 将 slice_value、标量移位与 signed_value 定义移入生成头文件以消除跨 TU … |
| e00019 | candidate | t2/s03c1 | 264.5s | 5.77x | ok | commit块next锥的外部叶子在绝大多数时钟事件不脏；由compute生产块执行与ST00013… |
| e00020 | candidate | t2/s03c2 | 265.2s | 5.78x | ok | init-zero-elision消除98%+冗余init store后，affinity状态布局可… |
| e00021 | candidate | t0/s04c1 | 239.4s | 5.22x | ok | source-part guard消除空part扫描后，wide first-touch仍可通过收缩… |
| e00022 | candidate | t0/s04c2 | 230.6s | 5.03x | ok | e00015仍会在活跃source part内逐byte扫描；按64-block activity … |
| e00023 | candidate | t1/s04c1 | 256.4s | 5.59x | ok | 将同宽 signed/unsigned resize_value 胶统一消除；若 signed 胶仍… |
| e00024 | candidate | t1/s04c2 | 241.3s | 5.26x | ok | 将不可写且不超过 64 bit 的 InitKind::Constant 标量读取直接内联为掩码字面… |
| e00025 | candidate | t2/s04c1 | 271.0s | 5.91x | ok | 稀疏 commit-input gating 仅保留尾部工作量至少为 dirty edge 数 4 … |
| e00026 | candidate | t2/s04c2 | 271.3s | 5.91x | ok | wide-state explode 将 commit 输入门控的宽态传播边压缩，使剩余 gate … |
| e00027 | candidate | t0/s05c1 | 222.7s | 4.85x | ok | 在e00022的source-word activity guard上叠加wide-storage … |
| e00028 | candidate | t0/s05c2 | 235.6s | 5.14x | ok | e00022 的 source-word guard 仍逐 byte 从 activeWords_ … |
| e00029 | candidate | t1/s05c1 | 237.4s | 5.18x | ok | 将窄标量 divide_value/modulo_value 定义内联到生成头文件，使固定宽度、si… |
| e00030 | candidate | t1/s05c2 | 230.4s | 5.02x | ok | 在 inlineScalarConstants 的字面量读取基础上，按 escape/pin 分析删… |
| e00031 | candidate | t2/s05c1 | 265.2s | 5.78x | ok | c1: 每64个commit gate共用packed uint64 dirty位图，减少逐gate… |
| e00032 | candidate | t2/s05c2 | 285.6s | 6.23x | ok | c2: producer block结束后比较窄标量输出快照，仅在真实变化时传播commit-inp… |
| e00033 | candidate | t0/s06c1 | 216.5s | 4.72x | ok | concat/replicate/window-chain 的单字退化拼接（静态 56% 的 ins… |
| e00034 | candidate | t0/s06c2 | 229.8s | 5.01x | ok | 窄标量 v<K> 成员（1,263,224 个/约 10.1MB）按 scheduled Block… |
| e00035 | candidate | t1/s06c1 | 228.9s | 4.99x | ok | 若 t1 tip 约 23.5 万个宽 word-helper 跨 TU 调用边界是一阶适配成本，-… |
| e00036 | candidate | t1/s06c2 | 232.9s | 5.08x | ok | 若宽常量占用的 6.8% 可变宽池与 1.64M 行 init store 是可收的状态/初始化成本… |
| e00037 | candidate | t2/s06c1 | 257.3s | 5.61x | ok | c1: t2 仅有的两个独立正收益机制（commit 输入门控 e00019 -1.95%、affi… |
| e00038 | candidate | t2/s06c2 | 257.6s | 5.62x | ok | c2: atom 折叠上限 2->8 加粗 atom 粒度、减少逐 atom 边界适配胶，若 ato… |
| e00039 | candidate | t0/s07c1 | 212.4s | 4.63x | ok | 残余跨 word 拼接（静态 56,759 站、动态 6.89 亿次 outlined 调用）按对齐… |
| e00040 | candidate | t0/s07c2 | 194.8s | 4.25x | ok | t0 主线 5 个窄标量 helper（slice_value/shift_left/shift_r… |
| e00041 | candidate | t1/s07c1 | 224.0s | 4.88x | ok | 若宽池约 65.7% 未引用 word（约 122MB 死宽态）摊薄状态 gather 局部性，--… |
| e00042 | candidate | t1/s07c2 | 232.1s | 5.06x | ok | 若残余 1,267 站 divide_value 调用边界在常量存储瘦身后基线上仍是 >=1.5% … |
| e00043 | candidate | t2/s07c1 | 257.4s | 5.61x | ok | c1: 逐 gate 动态证据筛选 commit-input gate——recon 实测每个 ga… |
| e00044 | candidate | t2/s07c2 | 255.1s | 5.56x | ok | c2: 按 t2 自有 recon 块执行频次（880M execs，top 6.65% 块=50%… |
| e00045 | candidate | t0/s08c1 | 194.2s | 4.24x | ok | 残余跨 word 拼接三形内联（concat-insert-unroll，静态 56,762 站、动… |
| e00046 | candidate | t0/s08c2 | 200.3s | 4.37x | ok | commit 写侧 5 个 detect helper（masked/dynlane/assign/… |
| e00047 | candidate | t1/s08c1 | 219.0s | 4.77x | ok | 若 ~35.1 万个从未被引用的窄成员（~2.68MB，窄区 28.0%）摊薄状态对象局部性，--d… |
| e00048 | candidate | t1/s08c2 | 222.0s | 4.84x | ok | t1 tip 原样重测（emit_args 同 e00041）应落在 e00041 的 224.03… |
| e00049 | candidate | t2/s08c1 | 254.5s | 5.55x | ok | c1: t2/main 现行 emit 配置（guard-event-gating + commit… |
| e00050 | candidate | t2/s08c2 | 261.1s | 5.69x | ok | c2: e00019 配置（guard-event-gating + commit-input-ga… |
| e00001 | baseline-am | - | 619.0s | 13.50x | ok | am baseline |
| e00002 | baseline-gsim | - | 46.8s | 1.02x | ok | gsim baseline |
| e00003 | candidate | t0/s01c1 | 362.9s | 7.91x | ok | r001 t0 winner 机制链（branchy-mux/resize-elision/init… |
| e00004 | candidate | t0/s01c2 | 452.8s | 9.87x | ok | 新输入图宽池死变量占比与 r001 旧图相当（r001：-65.66% words），重实现 dea… |
| e00005 | candidate | t1/s01c1 | 607.8s | 13.25x | ok | r001 t1 winner 链幸存旋钮（resize-elision + inline-scala… |
| e00006 | candidate | t1/s01c2 | 443.9s | 9.68x | ok | inline-scalar-constants（只读窄标量常量读取发射为掩码字面量，r001 e00… |
| e00007 | candidate | t0/s02c1 | 261.5s | 5.70x | ok | commit 相 32.4% 集中于每 eval 触发的宽站巨块（43 块独占 31.7% 块周期）… |
| e00008 | candidate | t0/s02c2 | 358.5s | 7.82x | ok | 守卫双块（b90656/90657，各 ~7000 atom 的 system.task 条件评估，… |
| e00009 | candidate | t1/s02c1 | 414.9s | 9.05x | ok | 二级活动摘要扫描(摘要位图镜像 activeWords_、每处全局激活同址镜像、扫描按摘要 bit … |
| e00010 | candidate | t1/s02c2 | 574.6s | 12.53x | ok | 同窗安慰剂锚点(机制多样性妥协,先例 A0031/e00048):t1 tip c8b4a2c 原样… |
| e00011 | candidate | t0/s03c1 | 370.5s | 8.08x | ok | 守卫池 9.3%（b90656/90657，65.3G ticks，每 eval 触发的 ~7000… |
| e00012 | candidate | t0/s03c2 | 363.4s | 7.92x | ok | 安慰剂锚点：t0 tip（e00007 代码 + 同 10 旋钮）原样重测，把 ledger bes… |
| e00013 | candidate | t1/s03c1 | 375.7s | 8.19x | ok | task-body-outline:b116236 型守卫密集块的冷 task 体(TaskForm… |
| e00014 | candidate | t1/s03c2 | 421.7s | 9.19x | ok | 同窗安慰剂锚点(机制多样性妥协,先例 A0031/e00048、A0041/e00012):t1 t… |
| e00015 | candidate | t0/s04c1 | 339.7s | 7.41x | ok | 守卫块 b90656/90657（9.3% 块周期，per-atom ~50cyc 前端流式嫌疑）每… |
| e00016 | candidate | t0/s04c2 | 361.1s | 7.87x | ok | 安慰剂锚点：t0 tip（48916f2 + 同 10 旋钮）原样重测，为 c1（sys-task-… |
| e00017 | candidate | t1/s04c1 | 369.0s | 8.04x | ok | 调度点单变量：摘除 config 调度点全参数回落 CLI 默认 gsim-aligned 点（15… |
| e00018 | candidate | t1/s04c2 | 403.0s | 8.79x | ok | 同窗安慰剂锚点：t1 tip b9a888c 原样重测、emit_args 与 e00013 相同（… |
| e00019 | candidate | t0/s05c1 | 335.1s | 7.31x | ok | 22528-bit broadcast→mux 链（b69159 族，含链块池 33.35G tic… |
| e00020 | candidate | t0/s05c2 | 342.6s | 7.47x | ok | 安慰剂锚点（无机制假设）：t0 tip e43ff4d 原样重测，同 11 旋钮，为 c1 提供同窗… |
| e00021 | candidate | t1/s05c1 | 365.4s | 7.97x | ok | commit-write-branchless：b93159 族 43 commit 块（31.1%… |
| e00022 | candidate | t1/s05c2 | 359.3s | 7.83x | ok | 同窗安慰剂锚点：t1 tip 520b017 原样重测（CLI 默认调度点 + 5 旋钮），为 c1… |
| e00023 | candidate | t0/s06c1 | 338.2s | 7.38x | ok | b93131 族 CommitEvent 动态索引位 RMW（同 index/行基址/word、逐位… |
| e00024 | candidate | t0/s06c2 | 327.6s | 7.14x | ok | 安慰剂锚点（无机制假设）：t0 tip 61b5fd6 原样 + 同 12 旋钮重测，为 c1（co… |
| e00025 | candidate | t1/s06c1 | 364.5s | 7.95x | ok | wide-mux-chain-fuse 跨轨迹迁移（t0 A0047 -2.19% 机制移植到 t1… |
| e00026 | candidate | t1/s06c2 | 368.8s | 8.04x | ok | 同窗安慰剂锚点：t1 tip f167ae7 原样重测（CLI 默认调度点 + 5 旋钮），为 c1… |
| e00027 | candidate | t0/s07c1 | 301.1s | 6.56x | ok | 每 round 全模型扫描 93,199 个 compute 块活动位测试与其后 ~945B 块体交… |
| e00028 | candidate | t0/s07c2 | 339.8s | 7.41x | ok | 同窗安慰剂锚点（连续第五轮锚点席位）：t0 tip ab20b29 原样重测、emit_args 与… |
| e00029 | candidate | t1/s07c1 | 322.8s | 7.04x | ok | scan-branch-hints 跨轨迹迁移（t0 A0053 -11.41% 机制移植到 t1 … |
| e00030 | candidate | t1/s07c2 | 342.2s | 7.46x | ok | 同窗安慰剂锚点：t1 tip 4471846 原样重测（CLI 默认调度点 + 5 旋钮 + --w… |
| e00031 | candidate | t0/s08c1 | 321.9s | 7.02x | ok | commit 相 MemoryFill 逐元素 detect 扫描在写口使能为假时为可证 no-op… |
| e00032 | candidate | t0/s08c2 | 343.7s | 7.49x | ok | 安慰剂锚点：t0 tip（b9a671a + 13 旋钮）原样重测，为 c1（memory-fill… |
| e00033 | candidate | t1/s08c1 | 338.4s | 7.38x | ok | concat-insert-inline 跨轨迹迁移到 t1 链：单字退化 concat/windo… |
| e00034 | candidate | t1/s08c2 | 361.0s | 7.87x | ok | 同窗安慰剂锚点：t1 tip 74b6d1e 原样重测（CLI 默认调度点 + 7 旋钮），为 c1… |
| e00051 | baseline-am | - | 364.0s | 7.94x | ok | am baseline |
| e00052 | baseline-gsim | - | 45.9s | 1.00x | ok | gsim baseline |
| e00053 | candidate | t0/s01c1 | 334.7s | 7.30x | ok | e00051 -> 同输入 recon 显示每轮约 93199 个 Block 的稀疏活动测试与约 … |
| e00054 | candidate | t0/s01c2 | 247.6s | 5.40x | ok | e00051 -> 同输入 recon 显示 b90656/b90657 守卫池约占 9.3% 块周… |
| e00055 | candidate | t1/s01c1 | 270.0s | 5.89x | ok | e00051 -> r002 frozen-input recon found 30324 byte… |
| e00056 | candidate | t1/s01c2 | 242.0s | 5.28x | ok | e00051 -> r002 frozen-input recon measured the 225… |
| e00057 | candidate | t0/s02c1 | 229.4s | 5.00x | ok | Φ e00054 -> c1：在 sysTaskBodyOutline 基座上给 byte/Bloc… |
| e00058 | candidate | t0/s02c2 | 252.4s | 5.50x | ok | Φ e00054 -> c2：在 sysTaskBodyOutline 基座上将无参数非 final… |
| e00059 | candidate | t1/s02c1 | 257.2s | 5.61x | ok | e00056 -> four 23-level and one 4-level fused chai… |
| e00060 | candidate | t1/s02c2 | 358.3s | 7.81x | ok | e00056 -> 151 of 156 fused chains are single-level… |
| e00061 | candidate | t0/s03c1 | 251.7s | 5.49x | ok | Phi e00057 -> scanBranchHints 已捕获约一半 75-80s 扫描骨架、残… |
| e00062 | candidate | t0/s03c2 | 300.2s | 6.55x | ok | Phi e00057 -> 7,235 个 outlined fwrite body 极少 fire… |
| e00063 | candidate | t1/s03c1 | 495.5s | 10.80x | ok | e00059 -> recon 显示 23-level 链 99.57% lane 取 base，而… |
| e00064 | candidate | t1/s03c2 | 409.7s | 8.93x | ok | e00056/e00059 -> recon 显示 23-level selector 机会密度仅0… |
| e00065 | candidate | t0/s04c1 | 409.9s | 8.94x | ok | Phi e00061 -> ctz 已减少活跃 byte 测试，但 93,599 个 switch … |
| e00066 | candidate | t0/s04c2 | 412.8s | 9.00x | ok | Phi e00057/e00061 -> branch-hinted线性扫描优于ctz+switch… |
| corr-e00065-e00066 | correction | - | - | - | correction | 勘误：e00065/e00066 登记 insight 的 compile_s 手误 |
| e00067 | candidate | t1/s04c1 | 382.2s | 8.33x | ok | e00064 -> recon showed only 0.0188% selector oppor… |
| e00068 | candidate | t1/s04c2 | 427.1s | 9.31x | ok | e00064 -> zero-tile helper still receives dynamic … |
| e00069 | candidate | t0/s05c1 | - | - | ctest_fail | Phi e00061/e00065 -> per-set-bit ctz dispatch lost… |
| e00070 | candidate | t0/s05c2 | - | - | ctest_fail | Phi e00054 -> 7235 outlined fwrite bodies are rare… |
| e00071 | candidate | t1/s05c1 | 339.9s | 7.41x | ok | e00067 -> active-tile sparse helper rescans all 4/… |
| e00072 | candidate | t1/s05c2 | 356.8s | 7.78x | ok | e00067/e00059 -> active-tile sparse writes a lane … |
| e00073 | candidate | t0/s06c1 | 370.6s | 8.08x | ok | Phi e00057/e00065 -> direct-tree active-byte dispa… |
| e00074 | candidate | t0/s06c2 | 346.7s | 7.56x | ok | Phi e00054/e00065 -> 7235 outlined fwrite bodies a… |
| corr-e00073-e00074-phenotype | correction | t0/s06c0 | - | - | correction | 勘误：e00073/e00074 正式评估遗漏候选专属 emit_args，两个机制均未在生产模型启… |
| e00075 | candidate | t1/s06c1 | 363.8s | 7.93x | ok | e00071 -> active-tile sparse union already loads e… |
| e00076 | candidate | t1/s06c2 | 354.5s | 7.73x | ok | e00056/e00071 -> 151 of 156 fused chains are singl… |
| e00077 | candidate | t0/s07c1 | 312.0s | 6.80x | ok | Phi e00057/e00073 -> e00057 proved branch-hinted s… |
| e00078 | candidate | t0/s07c2 | 299.7s | 6.53x | ok | Phi e00054/e00074 -> sys-task-body-outline removes… |
| e00079 | candidate | t1/s07c1 | 359.9s | 7.85x | ok | Phi e00067/e00071 -> four production 23-level chai… |
| e00080 | candidate | t1/s07c2 | 345.2s | 7.53x | ok | Phi e00051/e00067/e00071 -> active-tile sparse sti… |
| corr-e00075-e00076-phenotype | correction | t1/s06c0 | - | - | correction | 勘误：e00075/e00076 缺少 wideMuxChainActiveTileSparse 的… |
| e00081 | candidate | t0/s08c1 | - | - | ctest_fail | Phi e00054/e00078 -> outlined fwrite still materia… |
| e00082 | candidate | t0/s08c2 | 327.7s | 7.14x | ok | Phi e00057/e00061/e00078 -> source-word activity g… |
| e00083 | candidate | t1/s08c1 | 419.5s | 9.15x | ok | Phi e00080/e00071 -> active-tile sparse scans each… |
| e00084 | candidate | t1/s08c2 | 378.1s | 8.24x | ok | Phi e00080/e00071 -> e00080 idempotent suppression… |

最近 actions：A0021 step；A0022 round-summary；A0023 step；A0024 step；A0025 run-summary

