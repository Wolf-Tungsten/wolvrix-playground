# TES 性能看板

> 本文件由 `python3 tes/tools/tesctl.py dashboard` 生成；record-baseline / record-eval /
> finish-step / close-run / action-done 等状态变更后也会自动刷新。**请勿手改。**
> 生成于 2026-08-20T22:04:09+08:00

## 任务 `grhsim-am-coremark`

run **r002**（active）· C=2 L=8 K=2 · evals 8/32 · actions 5 · 下一步 `step`：推进轨迹 t1 到第 2 步（round-robin 最少步数优先）

| 基准 | eval | Host 中位 | vs target |
|---|---|---|---|
| gsim（target） | e00002 | 46.8s | 1.00x |
| am（y0 基线） | e00001 | 619.0s | 13.23x |
| **当前 best** | e00007 | **261.5s** | **5.59x** |

基线→target 进度：`████████████░░░░░░░░` 62.5%（619.0s → 目标 46.8s，当前差距 5.59x）

| 轨迹 | 分支 | 步数 | best eval | best Host |
|---|---|---|---|---|
| t0 | `tes/r002/t0/main` | 2/8 | e00007 | 261.5s |
| t1 | `tes/r002/t1/main` | 1/8 | e00006 | 443.9s |

| eval | 类别 | 位置 | Host 中位 | vs target | 状态 | 假设 |
|---|---|---|---|---|---|---|
| e00001 | baseline-am | - | 273.1s | 5.84x | ok | am baseline |
| e00002 | baseline-gsim | - | 24.7s | 0.53x | ok | gsim baseline |
| e00003 | candidate | t0/s01c1 | 279.2s | 5.97x | ok | chunk 3000->12000 使更多窄值 chunk 内标量化、减少跨 chunk uint6… |
| e00004 | candidate | t0/s01c2 | 271.1s | 5.79x | ok | 标量 mux 全量 if/else 化（branchy-mux）：若显著恶化则量化分支误预测成本并关… |
| e00005 | candidate | t1/s01c1 | - | - | compile_timeout | 状态按块静态访问亲和性聚簇布局（标量成员+宽值池，stateLayout=affinity）后热块工… |
| e00006 | candidate | t1/s01c2 | 270.5s | 5.78x | ok | 消除同宽无符号resize_value胶（静态94.1%站点、占胶95%）后热块动态指令数/依赖链缩… |
| e00007 | candidate | t2/s01c1 | - | - | compile_timeout | 状态按块静态访问亲和聚簇布局（init宽池store按offset升序修复后）热块工作集局部性改善，… |
| e00008 | candidate | t2/s01c2 | 272.7s | 5.83x | ok | 对常量切片主导的宽状态做标量炸开（元素数组声明+直读/单元素写）后，计数器网络族的词提取+栈数组往返… |
| e00009 | candidate | t0/s02c1 | 274.4s | 5.86x | ok | init()字面量0死store发射期消除后：runtime.o编译瓶颈移除（全程compile_s… |
| e00010 | candidate | t0/s02c2 | 273.3s | 5.84x | ok | branchy-mux与resize-elision机制正交，组合收益近似可加（期望-1.3%~-1… |
| e00011 | candidate | t1/s02c1 | 289.2s | 6.18x | ok | 激活合并455K静态/4.77G动态条件分支若显著误预测，去分支化(恒写活动字mask&actMas… |
| e00012 | candidate | t1/s02c2 | - | - | difftest_fail | 被commit act.b再激活的compute块（含b83400族）round-1 preset求… |
| e00013 | candidate | t2/s02c1 | 309.6s | 6.62x | ok | commit写站wrNext输入在生产者compute块未触发时等于已提交状态（compare幂等失… |
| e00014 | candidate | t2/s02c2 | 269.7s | 5.76x | ok | b83400型纯守卫块（fatal/fwrite全以changedResults_时钟沿槽为事件条件… |
| e00015 | candidate | t0/s03c1 | 247.5s | 5.29x | ok | 精确 64-bit source-part activity 区间守卫可跳过静默 part 的函数调… |
| e00016 | candidate | t0/s03c2 | 257.4s | 5.50x | ok | 按调度块首次触及顺序重排宽 BitVector/Array 存储并叠加 init-zero-elis… |
| e00017 | candidate | t1/s03c1 | - | - | compile_timeout | 重建 stateLayout=affinity 并按物理 offset 排列字面量宽初始化，若恢复编… |
| e00018 | candidate | t1/s03c2 | 244.3s | 5.22x | ok | 将 slice_value、标量移位与 signed_value 定义移入生成头文件以消除跨 TU … |
| e00019 | candidate | t2/s03c1 | 264.5s | 5.65x | ok | commit块next锥的外部叶子在绝大多数时钟事件不脏；由compute生产块执行与ST00013… |
| e00020 | candidate | t2/s03c2 | 265.2s | 5.67x | ok | init-zero-elision消除98%+冗余init store后，affinity状态布局可… |
| e00021 | candidate | t0/s04c1 | 239.4s | 5.12x | ok | source-part guard消除空part扫描后，wide first-touch仍可通过收缩… |
| e00022 | candidate | t0/s04c2 | 230.6s | 4.93x | ok | e00015仍会在活跃source part内逐byte扫描；按64-block activity … |
| e00023 | candidate | t1/s04c1 | 256.4s | 5.48x | ok | 将同宽 signed/unsigned resize_value 胶统一消除；若 signed 胶仍… |
| e00024 | candidate | t1/s04c2 | 241.3s | 5.16x | ok | 将不可写且不超过 64 bit 的 InitKind::Constant 标量读取直接内联为掩码字面… |
| e00025 | candidate | t2/s04c1 | 271.0s | 5.79x | ok | 稀疏 commit-input gating 仅保留尾部工作量至少为 dirty edge 数 4 … |
| e00026 | candidate | t2/s04c2 | 271.3s | 5.80x | ok | wide-state explode 将 commit 输入门控的宽态传播边压缩，使剩余 gate … |
| e00027 | candidate | t0/s05c1 | 222.7s | 4.76x | ok | 在e00022的source-word activity guard上叠加wide-storage … |
| e00028 | candidate | t0/s05c2 | 235.6s | 5.04x | ok | e00022 的 source-word guard 仍逐 byte 从 activeWords_ … |
| e00029 | candidate | t1/s05c1 | 237.4s | 5.07x | ok | 将窄标量 divide_value/modulo_value 定义内联到生成头文件，使固定宽度、si… |
| e00030 | candidate | t1/s05c2 | 230.4s | 4.92x | ok | 在 inlineScalarConstants 的字面量读取基础上，按 escape/pin 分析删… |
| e00031 | candidate | t2/s05c1 | 265.2s | 5.67x | ok | c1: 每64个commit gate共用packed uint64 dirty位图，减少逐gate… |
| e00032 | candidate | t2/s05c2 | 285.6s | 6.10x | ok | c2: producer block结束后比较窄标量输出快照，仅在真实变化时传播commit-inp… |
| e00033 | candidate | t0/s06c1 | 216.5s | 4.63x | ok | concat/replicate/window-chain 的单字退化拼接（静态 56% 的 ins… |
| e00034 | candidate | t0/s06c2 | 229.8s | 4.91x | ok | 窄标量 v<K> 成员（1,263,224 个/约 10.1MB）按 scheduled Block… |
| e00035 | candidate | t1/s06c1 | 228.9s | 4.89x | ok | 若 t1 tip 约 23.5 万个宽 word-helper 跨 TU 调用边界是一阶适配成本，-… |
| e00036 | candidate | t1/s06c2 | 232.9s | 4.98x | ok | 若宽常量占用的 6.8% 可变宽池与 1.64M 行 init store 是可收的状态/初始化成本… |
| e00037 | candidate | t2/s06c1 | 257.3s | 5.50x | ok | c1: t2 仅有的两个独立正收益机制（commit 输入门控 e00019 -1.95%、affi… |
| e00038 | candidate | t2/s06c2 | 257.6s | 5.51x | ok | c2: atom 折叠上限 2->8 加粗 atom 粒度、减少逐 atom 边界适配胶，若 ato… |
| e00039 | candidate | t0/s07c1 | 212.4s | 4.54x | ok | 残余跨 word 拼接（静态 56,759 站、动态 6.89 亿次 outlined 调用）按对齐… |
| e00040 | candidate | t0/s07c2 | 194.8s | 4.16x | ok | t0 主线 5 个窄标量 helper（slice_value/shift_left/shift_r… |
| e00041 | candidate | t1/s07c1 | 224.0s | 4.79x | ok | 若宽池约 65.7% 未引用 word（约 122MB 死宽态）摊薄状态 gather 局部性，--… |
| e00042 | candidate | t1/s07c2 | 232.1s | 4.96x | ok | 若残余 1,267 站 divide_value 调用边界在常量存储瘦身后基线上仍是 >=1.5% … |
| e00043 | candidate | t2/s07c1 | 257.4s | 5.50x | ok | c1: 逐 gate 动态证据筛选 commit-input gate——recon 实测每个 ga… |
| e00044 | candidate | t2/s07c2 | 255.1s | 5.45x | ok | c2: 按 t2 自有 recon 块执行频次（880M execs，top 6.65% 块=50%… |
| e00045 | candidate | t0/s08c1 | 194.2s | 4.15x | ok | 残余跨 word 拼接三形内联（concat-insert-unroll，静态 56,762 站、动… |
| e00046 | candidate | t0/s08c2 | 200.3s | 4.28x | ok | commit 写侧 5 个 detect helper（masked/dynlane/assign/… |
| e00047 | candidate | t1/s08c1 | 219.0s | 4.68x | ok | 若 ~35.1 万个从未被引用的窄成员（~2.68MB，窄区 28.0%）摊薄状态对象局部性，--d… |
| e00048 | candidate | t1/s08c2 | 222.0s | 4.74x | ok | t1 tip 原样重测（emit_args 同 e00041）应落在 e00041 的 224.03… |
| e00049 | candidate | t2/s08c1 | 254.5s | 5.44x | ok | c1: t2/main 现行 emit 配置（guard-event-gating + commit… |
| e00050 | candidate | t2/s08c2 | 261.1s | 5.58x | ok | c2: e00019 配置（guard-event-gating + commit-input-ga… |
| e00001 | baseline-am | - | 619.0s | 13.23x | ok | am baseline |
| e00002 | baseline-gsim | - | 46.8s | 1.00x | ok | gsim baseline |
| e00003 | candidate | t0/s01c1 | 362.9s | 7.75x | ok | r001 t0 winner 机制链（branchy-mux/resize-elision/init… |
| e00004 | candidate | t0/s01c2 | 452.8s | 9.68x | ok | 新输入图宽池死变量占比与 r001 旧图相当（r001：-65.66% words），重实现 dea… |
| e00005 | candidate | t1/s01c1 | 607.8s | 12.99x | ok | r001 t1 winner 链幸存旋钮（resize-elision + inline-scala… |
| e00006 | candidate | t1/s01c2 | 443.9s | 9.49x | ok | inline-scalar-constants（只读窄标量常量读取发射为掩码字面量，r001 e00… |
| e00007 | candidate | t0/s02c1 | 261.5s | 5.59x | ok | commit 相 32.4% 集中于每 eval 触发的宽站巨块（43 块独占 31.7% 块周期）… |
| e00008 | candidate | t0/s02c2 | 358.5s | 7.66x | ok | 守卫双块（b90656/90657，各 ~7000 atom 的 system.task 条件评估，… |

最近 actions：A0001 run-init；A0002 step；A0003 step；A0004 round-summary；A0005 step

