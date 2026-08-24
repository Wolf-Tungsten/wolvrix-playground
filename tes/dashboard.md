# TES 性能看板

> 本文件由 `python3 tes/tools/tesctl.py dashboard` 生成；record-baseline / record-eval /
> finish-step / close-run / action-done 等状态变更后也会自动刷新。**请勿手改。**
> 生成于 2026-08-24T11:15:00+08:00

## 任务 `grhsim-am-coremark`

run **r004**（active）· C=6 L=4 K=2 · evals 28/48 · actions 24 · 下一步 `step`：推进轨迹 t1 到第 3 步（round-robin 最少步数优先）

| 基准 | eval | Host 中位 | vs target |
|---|---|---|---|
| gsim（target） | e00086 | 22.7s | 1.00x |
| am（y0 基线） | e00085 | 193.4s | 8.51x |
| **当前 best** | e00106 | **166.9s** | **7.35x** |

基线→target 进度：`███░░░░░░░░░░░░░░░░░` 15.5%（193.4s → 目标 22.7s，当前差距 7.35x）

| 轨迹 | 分支 | 步数 | best eval | best Host |
|---|---|---|---|---|
| t0 | `tes/r004/t0/main` | 3/4 | e00100 | 172.8s |
| t1 | `tes/r004/t1/main` | 2/4 | e00102 | 171.2s |
| t2 | `tes/r004/t2/main` | 2/4 | e00104 | 169.6s |
| t3 | `tes/r004/t3/main` | 2/4 | e00106 | 166.9s |
| t4 | `tes/r004/t4/main` | 2/4 | e00108 | 189.3s |
| t5 | `tes/r004/t5/main` | 2/4 | e00110 | 173.1s |

| eval | 类别 | 位置 | Host 中位 | vs target | 簇 | 状态 | 假设 |
|---|---|---|---|---|---|---|---|
| e00001 | baseline-am | - | 273.1s | 12.02x | - | ok | am baseline |
| e00002 | baseline-gsim | - | 24.7s | 1.09x | - | ok | gsim baseline |
| e00003 | candidate | t0/s01c1 | 279.2s | 12.29x | - | ok | chunk 3000->12000 使更多窄值 chunk 内标量化、减少跨 chunk uint6… |
| e00004 | candidate | t0/s01c2 | 271.1s | 11.93x | - | ok | 标量 mux 全量 if/else 化（branchy-mux）：若显著恶化则量化分支误预测成本并关… |
| e00005 | candidate | t1/s01c1 | - | - | - | compile_timeout | 状态按块静态访问亲和性聚簇布局（标量成员+宽值池，stateLayout=affinity）后热块工… |
| e00006 | candidate | t1/s01c2 | 270.5s | 11.91x | - | ok | 消除同宽无符号resize_value胶（静态94.1%站点、占胶95%）后热块动态指令数/依赖链缩… |
| e00007 | candidate | t2/s01c1 | - | - | - | compile_timeout | 状态按块静态访问亲和聚簇布局（init宽池store按offset升序修复后）热块工作集局部性改善，… |
| e00008 | candidate | t2/s01c2 | 272.7s | 12.00x | - | ok | 对常量切片主导的宽状态做标量炸开（元素数组声明+直读/单元素写）后，计数器网络族的词提取+栈数组往返… |
| e00009 | candidate | t0/s02c1 | 274.4s | 12.08x | - | ok | init()字面量0死store发射期消除后：runtime.o编译瓶颈移除（全程compile_s… |
| e00010 | candidate | t0/s02c2 | 273.3s | 12.03x | - | ok | branchy-mux与resize-elision机制正交，组合收益近似可加（期望-1.3%~-1… |
| e00011 | candidate | t1/s02c1 | 289.2s | 12.73x | - | ok | 激活合并455K静态/4.77G动态条件分支若显著误预测，去分支化(恒写活动字mask&actMas… |
| e00012 | candidate | t1/s02c2 | - | - | - | difftest_fail | 被commit act.b再激活的compute块（含b83400族）round-1 preset求… |
| e00013 | candidate | t2/s02c1 | 309.6s | 13.63x | - | ok | commit写站wrNext输入在生产者compute块未触发时等于已提交状态（compare幂等失… |
| e00014 | candidate | t2/s02c2 | 269.7s | 11.87x | - | ok | b83400型纯守卫块（fatal/fwrite全以changedResults_时钟沿槽为事件条件… |
| e00015 | candidate | t0/s03c1 | 247.5s | 10.89x | - | ok | 精确 64-bit source-part activity 区间守卫可跳过静默 part 的函数调… |
| e00016 | candidate | t0/s03c2 | 257.4s | 11.33x | - | ok | 按调度块首次触及顺序重排宽 BitVector/Array 存储并叠加 init-zero-elis… |
| e00017 | candidate | t1/s03c1 | - | - | - | compile_timeout | 重建 stateLayout=affinity 并按物理 offset 排列字面量宽初始化，若恢复编… |
| e00018 | candidate | t1/s03c2 | 244.3s | 10.75x | - | ok | 将 slice_value、标量移位与 signed_value 定义移入生成头文件以消除跨 TU … |
| e00019 | candidate | t2/s03c1 | 264.5s | 11.64x | - | ok | commit块next锥的外部叶子在绝大多数时钟事件不脏；由compute生产块执行与ST00013… |
| e00020 | candidate | t2/s03c2 | 265.2s | 11.67x | - | ok | init-zero-elision消除98%+冗余init store后，affinity状态布局可… |
| e00021 | candidate | t0/s04c1 | 239.4s | 10.53x | - | ok | source-part guard消除空part扫描后，wide first-touch仍可通过收缩… |
| e00022 | candidate | t0/s04c2 | 230.6s | 10.15x | - | ok | e00015仍会在活跃source part内逐byte扫描；按64-block activity … |
| e00023 | candidate | t1/s04c1 | 256.4s | 11.29x | - | ok | 将同宽 signed/unsigned resize_value 胶统一消除；若 signed 胶仍… |
| e00024 | candidate | t1/s04c2 | 241.3s | 10.62x | - | ok | 将不可写且不超过 64 bit 的 InitKind::Constant 标量读取直接内联为掩码字面… |
| e00025 | candidate | t2/s04c1 | 271.0s | 11.93x | - | ok | 稀疏 commit-input gating 仅保留尾部工作量至少为 dirty edge 数 4 … |
| e00026 | candidate | t2/s04c2 | 271.3s | 11.94x | - | ok | wide-state explode 将 commit 输入门控的宽态传播边压缩，使剩余 gate … |
| e00027 | candidate | t0/s05c1 | 222.7s | 9.80x | - | ok | 在e00022的source-word activity guard上叠加wide-storage … |
| e00028 | candidate | t0/s05c2 | 235.6s | 10.37x | - | ok | e00022 的 source-word guard 仍逐 byte 从 activeWords_ … |
| e00029 | candidate | t1/s05c1 | 237.4s | 10.45x | - | ok | 将窄标量 divide_value/modulo_value 定义内联到生成头文件，使固定宽度、si… |
| e00030 | candidate | t1/s05c2 | 230.4s | 10.14x | - | ok | 在 inlineScalarConstants 的字面量读取基础上，按 escape/pin 分析删… |
| e00031 | candidate | t2/s05c1 | 265.2s | 11.67x | - | ok | c1: 每64个commit gate共用packed uint64 dirty位图，减少逐gate… |
| e00032 | candidate | t2/s05c2 | 285.6s | 12.57x | - | ok | c2: producer block结束后比较窄标量输出快照，仅在真实变化时传播commit-inp… |
| e00033 | candidate | t0/s06c1 | 216.5s | 9.53x | - | ok | concat/replicate/window-chain 的单字退化拼接（静态 56% 的 ins… |
| e00034 | candidate | t0/s06c2 | 229.8s | 10.12x | - | ok | 窄标量 v<K> 成员（1,263,224 个/约 10.1MB）按 scheduled Block… |
| e00035 | candidate | t1/s06c1 | 228.9s | 10.08x | - | ok | 若 t1 tip 约 23.5 万个宽 word-helper 跨 TU 调用边界是一阶适配成本，-… |
| e00036 | candidate | t1/s06c2 | 232.9s | 10.25x | - | ok | 若宽常量占用的 6.8% 可变宽池与 1.64M 行 init store 是可收的状态/初始化成本… |
| e00037 | candidate | t2/s06c1 | 257.3s | 11.32x | - | ok | c1: t2 仅有的两个独立正收益机制（commit 输入门控 e00019 -1.95%、affi… |
| e00038 | candidate | t2/s06c2 | 257.6s | 11.34x | - | ok | c2: atom 折叠上限 2->8 加粗 atom 粒度、减少逐 atom 边界适配胶，若 ato… |
| e00039 | candidate | t0/s07c1 | 212.4s | 9.35x | - | ok | 残余跨 word 拼接（静态 56,759 站、动态 6.89 亿次 outlined 调用）按对齐… |
| e00040 | candidate | t0/s07c2 | 194.8s | 8.57x | - | ok | t0 主线 5 个窄标量 helper（slice_value/shift_left/shift_r… |
| e00041 | candidate | t1/s07c1 | 224.0s | 9.86x | - | ok | 若宽池约 65.7% 未引用 word（约 122MB 死宽态）摊薄状态 gather 局部性，--… |
| e00042 | candidate | t1/s07c2 | 232.1s | 10.22x | - | ok | 若残余 1,267 站 divide_value 调用边界在常量存储瘦身后基线上仍是 >=1.5% … |
| e00043 | candidate | t2/s07c1 | 257.4s | 11.33x | - | ok | c1: 逐 gate 动态证据筛选 commit-input gate——recon 实测每个 ga… |
| e00044 | candidate | t2/s07c2 | 255.1s | 11.23x | - | ok | c2: 按 t2 自有 recon 块执行频次（880M execs，top 6.65% 块=50%… |
| e00045 | candidate | t0/s08c1 | 194.2s | 8.55x | - | ok | 残余跨 word 拼接三形内联（concat-insert-unroll，静态 56,762 站、动… |
| e00046 | candidate | t0/s08c2 | 200.3s | 8.81x | - | ok | commit 写侧 5 个 detect helper（masked/dynlane/assign/… |
| e00047 | candidate | t1/s08c1 | 219.0s | 9.64x | - | ok | 若 ~35.1 万个从未被引用的窄成员（~2.68MB，窄区 28.0%）摊薄状态对象局部性，--d… |
| e00048 | candidate | t1/s08c2 | 222.0s | 9.77x | - | ok | t1 tip 原样重测（emit_args 同 e00041）应落在 e00041 的 224.03… |
| e00049 | candidate | t2/s08c1 | 254.5s | 11.20x | - | ok | c1: t2/main 现行 emit 配置（guard-event-gating + commit… |
| e00050 | candidate | t2/s08c2 | 261.1s | 11.49x | - | ok | c2: e00019 配置（guard-event-gating + commit-input-ga… |
| e00001 | baseline-am | - | 619.0s | 27.25x | - | ok | am baseline |
| e00002 | baseline-gsim | - | 46.8s | 2.06x | - | ok | gsim baseline |
| e00003 | candidate | t0/s01c1 | 362.9s | 15.97x | - | ok | r001 t0 winner 机制链（branchy-mux/resize-elision/init… |
| e00004 | candidate | t0/s01c2 | 452.8s | 19.93x | - | ok | 新输入图宽池死变量占比与 r001 旧图相当（r001：-65.66% words），重实现 dea… |
| e00005 | candidate | t1/s01c1 | 607.8s | 26.75x | - | ok | r001 t1 winner 链幸存旋钮（resize-elision + inline-scala… |
| e00006 | candidate | t1/s01c2 | 443.9s | 19.54x | - | ok | inline-scalar-constants（只读窄标量常量读取发射为掩码字面量，r001 e00… |
| e00007 | candidate | t0/s02c1 | 261.5s | 11.51x | - | ok | commit 相 32.4% 集中于每 eval 触发的宽站巨块（43 块独占 31.7% 块周期）… |
| e00008 | candidate | t0/s02c2 | 358.5s | 15.78x | - | ok | 守卫双块（b90656/90657，各 ~7000 atom 的 system.task 条件评估，… |
| e00009 | candidate | t1/s02c1 | 414.9s | 18.26x | - | ok | 二级活动摘要扫描(摘要位图镜像 activeWords_、每处全局激活同址镜像、扫描按摘要 bit … |
| e00010 | candidate | t1/s02c2 | 574.6s | 25.29x | - | ok | 同窗安慰剂锚点(机制多样性妥协,先例 A0031/e00048):t1 tip c8b4a2c 原样… |
| e00011 | candidate | t0/s03c1 | 370.5s | 16.31x | - | ok | 守卫池 9.3%（b90656/90657，65.3G ticks，每 eval 触发的 ~7000… |
| e00012 | candidate | t0/s03c2 | 363.4s | 16.00x | - | ok | 安慰剂锚点：t0 tip（e00007 代码 + 同 10 旋钮）原样重测，把 ledger bes… |
| e00013 | candidate | t1/s03c1 | 375.7s | 16.53x | - | ok | task-body-outline:b116236 型守卫密集块的冷 task 体(TaskForm… |
| e00014 | candidate | t1/s03c2 | 421.7s | 18.56x | - | ok | 同窗安慰剂锚点(机制多样性妥协,先例 A0031/e00048、A0041/e00012):t1 t… |
| e00015 | candidate | t0/s04c1 | 339.7s | 14.95x | - | ok | 守卫块 b90656/90657（9.3% 块周期，per-atom ~50cyc 前端流式嫌疑）每… |
| e00016 | candidate | t0/s04c2 | 361.1s | 15.89x | - | ok | 安慰剂锚点：t0 tip（48916f2 + 同 10 旋钮）原样重测，为 c1（sys-task-… |
| e00017 | candidate | t1/s04c1 | 369.0s | 16.24x | - | ok | 调度点单变量：摘除 config 调度点全参数回落 CLI 默认 gsim-aligned 点（15… |
| e00018 | candidate | t1/s04c2 | 403.0s | 17.74x | - | ok | 同窗安慰剂锚点：t1 tip b9a888c 原样重测、emit_args 与 e00013 相同（… |
| e00019 | candidate | t0/s05c1 | 335.1s | 14.75x | - | ok | 22528-bit broadcast→mux 链（b69159 族，含链块池 33.35G tic… |
| e00020 | candidate | t0/s05c2 | 342.6s | 15.08x | - | ok | 安慰剂锚点（无机制假设）：t0 tip e43ff4d 原样重测，同 11 旋钮，为 c1 提供同窗… |
| e00021 | candidate | t1/s05c1 | 365.4s | 16.08x | - | ok | commit-write-branchless：b93159 族 43 commit 块（31.1%… |
| e00022 | candidate | t1/s05c2 | 359.3s | 15.81x | - | ok | 同窗安慰剂锚点：t1 tip 520b017 原样重测（CLI 默认调度点 + 5 旋钮），为 c1… |
| e00023 | candidate | t0/s06c1 | 338.2s | 14.89x | - | ok | b93131 族 CommitEvent 动态索引位 RMW（同 index/行基址/word、逐位… |
| e00024 | candidate | t0/s06c2 | 327.6s | 14.42x | - | ok | 安慰剂锚点（无机制假设）：t0 tip 61b5fd6 原样 + 同 12 旋钮重测，为 c1（co… |
| e00025 | candidate | t1/s06c1 | 364.5s | 16.04x | - | ok | wide-mux-chain-fuse 跨轨迹迁移（t0 A0047 -2.19% 机制移植到 t1… |
| e00026 | candidate | t1/s06c2 | 368.8s | 16.23x | - | ok | 同窗安慰剂锚点：t1 tip f167ae7 原样重测（CLI 默认调度点 + 5 旋钮），为 c1… |
| e00027 | candidate | t0/s07c1 | 301.1s | 13.25x | - | ok | 每 round 全模型扫描 93,199 个 compute 块活动位测试与其后 ~945B 块体交… |
| e00028 | candidate | t0/s07c2 | 339.8s | 14.96x | - | ok | 同窗安慰剂锚点（连续第五轮锚点席位）：t0 tip ab20b29 原样重测、emit_args 与… |
| e00029 | candidate | t1/s07c1 | 322.8s | 14.21x | - | ok | scan-branch-hints 跨轨迹迁移（t0 A0053 -11.41% 机制移植到 t1 … |
| e00030 | candidate | t1/s07c2 | 342.2s | 15.06x | - | ok | 同窗安慰剂锚点：t1 tip 4471846 原样重测（CLI 默认调度点 + 5 旋钮 + --w… |
| e00031 | candidate | t0/s08c1 | 321.9s | 14.17x | - | ok | commit 相 MemoryFill 逐元素 detect 扫描在写口使能为假时为可证 no-op… |
| e00032 | candidate | t0/s08c2 | 343.7s | 15.13x | - | ok | 安慰剂锚点：t0 tip（b9a671a + 13 旋钮）原样重测，为 c1（memory-fill… |
| e00033 | candidate | t1/s08c1 | 338.4s | 14.89x | - | ok | concat-insert-inline 跨轨迹迁移到 t1 链：单字退化 concat/windo… |
| e00034 | candidate | t1/s08c2 | 361.0s | 15.89x | - | ok | 同窗安慰剂锚点：t1 tip 74b6d1e 原样重测（CLI 默认调度点 + 7 旋钮），为 c1… |
| e00051 | baseline-am | - | 364.0s | 16.02x | - | ok | am baseline |
| e00052 | baseline-gsim | - | 45.9s | 2.02x | - | ok | gsim baseline |
| e00053 | candidate | t0/s01c1 | 334.7s | 14.73x | - | ok | e00051 -> 同输入 recon 显示每轮约 93199 个 Block 的稀疏活动测试与约 … |
| e00054 | candidate | t0/s01c2 | 247.6s | 10.90x | - | ok | e00051 -> 同输入 recon 显示 b90656/b90657 守卫池约占 9.3% 块周… |
| e00055 | candidate | t1/s01c1 | 270.0s | 11.88x | - | ok | e00051 -> r002 frozen-input recon found 30324 byte… |
| e00056 | candidate | t1/s01c2 | 242.0s | 10.65x | - | ok | e00051 -> r002 frozen-input recon measured the 225… |
| e00057 | candidate | t0/s02c1 | 229.4s | 10.10x | - | ok | Φ e00054 -> c1：在 sysTaskBodyOutline 基座上给 byte/Bloc… |
| e00058 | candidate | t0/s02c2 | 252.4s | 11.11x | - | ok | Φ e00054 -> c2：在 sysTaskBodyOutline 基座上将无参数非 final… |
| e00059 | candidate | t1/s02c1 | 257.2s | 11.32x | - | ok | e00056 -> four 23-level and one 4-level fused chai… |
| e00060 | candidate | t1/s02c2 | 358.3s | 15.77x | - | ok | e00056 -> 151 of 156 fused chains are single-level… |
| e00061 | candidate | t0/s03c1 | 251.7s | 11.08x | - | ok | Phi e00057 -> scanBranchHints 已捕获约一半 75-80s 扫描骨架、残… |
| e00062 | candidate | t0/s03c2 | 300.2s | 13.21x | - | ok | Phi e00057 -> 7,235 个 outlined fwrite body 极少 fire… |
| e00063 | candidate | t1/s03c1 | 495.5s | 21.81x | - | ok | e00059 -> recon 显示 23-level 链 99.57% lane 取 base，而… |
| e00064 | candidate | t1/s03c2 | 409.7s | 18.03x | - | ok | e00056/e00059 -> recon 显示 23-level selector 机会密度仅0… |
| e00065 | candidate | t0/s04c1 | 409.9s | 18.04x | - | ok | Phi e00061 -> ctz 已减少活跃 byte 测试，但 93,599 个 switch … |
| e00066 | candidate | t0/s04c2 | 412.8s | 18.17x | - | ok | Phi e00057/e00061 -> branch-hinted线性扫描优于ctz+switch… |
| corr-e00065-e00066 | correction | - | - | - | - | correction | 勘误：e00065/e00066 登记 insight 的 compile_s 手误 |
| e00067 | candidate | t1/s04c1 | 382.2s | 16.82x | - | ok | e00064 -> recon showed only 0.0188% selector oppor… |
| e00068 | candidate | t1/s04c2 | 427.1s | 18.80x | - | ok | e00064 -> zero-tile helper still receives dynamic … |
| e00069 | candidate | t0/s05c1 | - | - | - | ctest_fail | Phi e00061/e00065 -> per-set-bit ctz dispatch lost… |
| e00070 | candidate | t0/s05c2 | - | - | - | ctest_fail | Phi e00054 -> 7235 outlined fwrite bodies are rare… |
| e00071 | candidate | t1/s05c1 | 339.9s | 14.96x | - | ok | e00067 -> active-tile sparse helper rescans all 4/… |
| e00072 | candidate | t1/s05c2 | 356.8s | 15.70x | - | ok | e00067/e00059 -> active-tile sparse writes a lane … |
| e00073 | candidate | t0/s06c1 | 370.6s | 16.31x | - | ok | Phi e00057/e00065 -> direct-tree active-byte dispa… |
| e00074 | candidate | t0/s06c2 | 346.7s | 15.26x | - | ok | Phi e00054/e00065 -> 7235 outlined fwrite bodies a… |
| corr-e00073-e00074-phenotype | correction | t0/s06c0 | - | - | - | correction | 勘误：e00073/e00074 正式评估遗漏候选专属 emit_args，两个机制均未在生产模型启… |
| e00075 | candidate | t1/s06c1 | 363.8s | 16.01x | - | ok | e00071 -> active-tile sparse union already loads e… |
| e00076 | candidate | t1/s06c2 | 354.5s | 15.60x | - | ok | e00056/e00071 -> 151 of 156 fused chains are singl… |
| e00077 | candidate | t0/s07c1 | 312.0s | 13.73x | - | ok | Phi e00057/e00073 -> e00057 proved branch-hinted s… |
| e00078 | candidate | t0/s07c2 | 299.7s | 13.19x | - | ok | Phi e00054/e00074 -> sys-task-body-outline removes… |
| e00079 | candidate | t1/s07c1 | 359.9s | 15.84x | - | ok | Phi e00067/e00071 -> four production 23-level chai… |
| e00080 | candidate | t1/s07c2 | 345.2s | 15.19x | - | ok | Phi e00051/e00067/e00071 -> active-tile sparse sti… |
| corr-e00075-e00076-phenotype | correction | t1/s06c0 | - | - | - | correction | 勘误：e00075/e00076 缺少 wideMuxChainActiveTileSparse 的… |
| e00081 | candidate | t0/s08c1 | - | - | - | ctest_fail | Phi e00054/e00078 -> outlined fwrite still materia… |
| e00082 | candidate | t0/s08c2 | 327.7s | 14.42x | - | ok | Phi e00057/e00061/e00078 -> source-word activity g… |
| e00083 | candidate | t1/s08c1 | 419.5s | 18.47x | - | ok | Phi e00080/e00071 -> active-tile sparse scans each… |
| e00084 | candidate | t1/s08c2 | 378.1s | 16.64x | - | ok | Phi e00080/e00071 -> e00080 idempotent suppression… |
| e00085 | baseline-am | - | 193.4s | 8.51x | unimodal | ok | am baseline |
| e00086 | baseline-gsim | - | 22.7s | 1.00x | unimodal | ok | gsim baseline |
| e00085 | recon | - | - | - | - | - |  |
| e00087 | candidate | t0/s01c1 | 191.7s | 8.44x | unimodal | ok | Testing sparse system-task events before fire will… |
| e00088 | candidate | t0/s01c2 | 189.8s | 8.36x | unimodal | ok | Inlining guarded unsigned 64-bit division will rem… |
| e00085 | recon | - | - | - | - | - |  |
| e00089 | candidate | t1/s01c1 | 190.8s | 8.40x | unimodal | ok | e00085 的 b90656/b90657 合计占动态块 cycles 4.629%，相邻 fwr… |
| e00090 | candidate | t1/s01c2 | 191.5s | 8.43x | unimodal | ok | e00085 的 b83835/b93085 合计占动态块 cycles 2.354%，其中密集 s… |
| e00085 | recon | - | - | - | - | - |  |
| e00091 | candidate | t2/s01c1 | 189.0s | 8.32x | unimodal | ok | e00085 recon shows commit blocks 93159/93141 consu… |
| e00092 | candidate | t2/s01c2 | 188.7s | 8.30x | unimodal | ok | e00085 recon shows b90656/b90657 account for 4.574… |
| e00085 | recon | - | - | - | - | - |  |
| e00093 | candidate | t3/s01c1 | 172.5s | 7.59x | unimodal | ok | e00085 recon 的六个 512-depth memory-read 块占总块 cycles… |
| e00094 | candidate | t3/s01c2 | 187.5s | 8.25x | unimodal | ok | e00085 recon shows b69157/b69158/b69159 execute 14… |
| e00085 | recon | - | - | - | - | - |  |
| e00095 | candidate | t4/s01c1 | - | - | - | ctest_fail | Defer chunked commit scratch clearing until the ev… |
| e00096 | candidate | t4/s01c2 | - | - | - | ctest_fail | Merge adjacent outlined fwrite calls with identica… |
| e00085 | recon | - | - | - | - | - |  |
| e00097 | candidate | t5/s01c1 | 191.1s | 8.41x | unimodal | ok | e00085 recon 中 b93159/b93141 合计占 8.421% 块周期；将 chun… |
| e00098 | candidate | t5/s01c2 | - | - | - | difftest_fail | e00085 recon 中 b83835/b93085 合计占 2.325% 块周期且生成代码含密… |
| e00099 | candidate | t0/s02c1 | 194.2s | 8.55x | unimodal | ok | The e00088 division specialization plus event-firs… |
| e00100 | candidate | t0/s02c2 | 172.8s | 7.61x | unimodal | ok | Migrating confirmed e00093 power-of-two memory-rea… |
| e00101 | candidate | t1/s02c1 | 189.6s | 8.35x | unimodal | ok | Starting from e00089, whose adjacent host-call gua… |
| e00102 | candidate | t1/s02c2 | 171.2s | 7.54x | unimodal | ok | Migrating confirmed e00093 power-of-two memory-rea… |
| e00103 | candidate | t2/s02c1 | 188.8s | 8.31x | unimodal | ok | Starting from e00092, exact-predicate host-call ru… |
| e00104 | candidate | t2/s02c2 | 169.6s | 7.46x | unimodal | ok | Migrating confirmed e00093 power-of-two memory-rea… |
| e00105 | candidate | t3/s02c1 | - | - | - | ctest_fail | Starting from e00093, six 512-read blocks still ca… |
| e00106 | candidate | t3/s02c2 | 166.9s | 7.35x | unimodal | ok | Starting from e00093, e00085 recon assigns 1.567% … |
| e00107 | candidate | t4/s02c1 | 189.9s | 8.36x | unimodal | ok | Phi e00085 and t4/s01 c1 ctest feedback -> recon b… |
| e00108 | candidate | t4/s02c2 | 189.3s | 8.33x | unimodal | ok | Phi e00085 and t4/s01 c2 ctest feedback -> recon b… |
| e00109 | candidate | t5/s02c1 | 189.8s | 8.35x | unimodal | ok | 来源 e00097 与本轨迹 e00098 失败反馈：e00085 recon 中 b83835/b… |
| e00110 | candidate | t5/s02c2 | 173.1s | 7.62x | unimodal | ok | 迁移来源 e00093：e00085 recon 的六个 512-depth memory-read… |
| e00100 | recon | - | - | - | - | - |  |
| e00111 | candidate | t0/s03c1 | 170.6s | 7.51x | unimodal | ok | Migrating e00106's confirmed wide ArrayBroadcast-t… |
| e00112 | candidate | t0/s03c2 | 174.3s | 7.67x | unimodal | ok | On e00100, b93159 and b93141 execute about 100k ti… |
| e00102 | recon | - | - | - | - | - |  |

最近 actions：A0020 step；A0021 round-summary；A0022 recon；A0023 step；A0024 recon

