# TES 性能看板

> 本文件由 `python3 tes/tools/tesctl.py dashboard` 生成；record-baseline / record-eval /
> finish-step / close-run / action-done 等状态变更后也会自动刷新。**请勿手改。**
> 生成于 2026-08-19T10:14:56+08:00

## 任务 `grhsim-am-coremark`

run **r001**（active）· C=3 L=8 K=2 · evals 32/48 · actions 20 · 下一步 `round-summary`：第 5 轮（全部 3 条轨迹各完成 1 步）已齐平，做跨轨迹小结

| 基准 | eval | Host 中位 | vs target |
|---|---|---|---|
| gsim（target） | e00002 | 24.7s | 1.00x |
| am（y0 基线） | e00001 | 273.1s | 11.06x |
| **当前 best** | e00027 | **222.7s** | **9.02x** |

基线→target 进度：`████░░░░░░░░░░░░░░░░` 20.3%（273.1s → 目标 24.7s，当前差距 9.02x）

| 轨迹 | 分支 | 步数 | best eval | best Host |
|---|---|---|---|---|
| t0 | `tes/r001/t0/main` | 5/8 | e00027 | 222.7s |
| t1 | `tes/r001/t1/main` | 5/8 | e00030 | 230.4s |
| t2 | `tes/r001/t2/main` | 5/8 | e00019 | 264.5s |

| eval | 类别 | 位置 | Host 中位 | vs target | 状态 | 假设 |
|---|---|---|---|---|---|---|
| e00001 | baseline-am | - | 273.1s | 11.06x | ok | am baseline |
| e00002 | baseline-gsim | - | 24.7s | 1.00x | ok | gsim baseline |
| e00003 | candidate | t0/s01c1 | 279.2s | 11.31x | ok | chunk 3000->12000 使更多窄值 chunk 内标量化、减少跨 chunk uint6… |
| e00004 | candidate | t0/s01c2 | 271.1s | 10.98x | ok | 标量 mux 全量 if/else 化（branchy-mux）：若显著恶化则量化分支误预测成本并关… |
| e00005 | candidate | t1/s01c1 | - | - | compile_timeout | 状态按块静态访问亲和性聚簇布局（标量成员+宽值池，stateLayout=affinity）后热块工… |
| e00006 | candidate | t1/s01c2 | 270.5s | 10.96x | ok | 消除同宽无符号resize_value胶（静态94.1%站点、占胶95%）后热块动态指令数/依赖链缩… |
| e00007 | candidate | t2/s01c1 | - | - | compile_timeout | 状态按块静态访问亲和聚簇布局（init宽池store按offset升序修复后）热块工作集局部性改善，… |
| e00008 | candidate | t2/s01c2 | 272.7s | 11.05x | ok | 对常量切片主导的宽状态做标量炸开（元素数组声明+直读/单元素写）后，计数器网络族的词提取+栈数组往返… |
| e00009 | candidate | t0/s02c1 | 274.4s | 11.12x | ok | init()字面量0死store发射期消除后：runtime.o编译瓶颈移除（全程compile_s… |
| e00010 | candidate | t0/s02c2 | 273.3s | 11.07x | ok | branchy-mux与resize-elision机制正交，组合收益近似可加（期望-1.3%~-1… |
| e00011 | candidate | t1/s02c1 | 289.2s | 11.71x | ok | 激活合并455K静态/4.77G动态条件分支若显著误预测，去分支化(恒写活动字mask&actMas… |
| e00012 | candidate | t1/s02c2 | - | - | difftest_fail | 被commit act.b再激活的compute块（含b83400族）round-1 preset求… |
| e00013 | candidate | t2/s02c1 | 309.6s | 12.54x | ok | commit写站wrNext输入在生产者compute块未触发时等于已提交状态（compare幂等失… |
| e00014 | candidate | t2/s02c2 | 269.7s | 10.93x | ok | b83400型纯守卫块（fatal/fwrite全以changedResults_时钟沿槽为事件条件… |
| e00015 | candidate | t0/s03c1 | 247.5s | 10.02x | ok | 精确 64-bit source-part activity 区间守卫可跳过静默 part 的函数调… |
| e00016 | candidate | t0/s03c2 | 257.4s | 10.43x | ok | 按调度块首次触及顺序重排宽 BitVector/Array 存储并叠加 init-zero-elis… |
| e00017 | candidate | t1/s03c1 | - | - | compile_timeout | 重建 stateLayout=affinity 并按物理 offset 排列字面量宽初始化，若恢复编… |
| e00018 | candidate | t1/s03c2 | 244.3s | 9.89x | ok | 将 slice_value、标量移位与 signed_value 定义移入生成头文件以消除跨 TU … |
| e00019 | candidate | t2/s03c1 | 264.5s | 10.71x | ok | commit块next锥的外部叶子在绝大多数时钟事件不脏；由compute生产块执行与ST00013… |
| e00020 | candidate | t2/s03c2 | 265.2s | 10.74x | ok | init-zero-elision消除98%+冗余init store后，affinity状态布局可… |
| e00021 | candidate | t0/s04c1 | 239.4s | 9.70x | ok | source-part guard消除空part扫描后，wide first-touch仍可通过收缩… |
| e00022 | candidate | t0/s04c2 | 230.6s | 9.34x | ok | e00015仍会在活跃source part内逐byte扫描；按64-block activity … |
| e00023 | candidate | t1/s04c1 | 256.4s | 10.39x | ok | 将同宽 signed/unsigned resize_value 胶统一消除；若 signed 胶仍… |
| e00024 | candidate | t1/s04c2 | 241.3s | 9.78x | ok | 将不可写且不超过 64 bit 的 InitKind::Constant 标量读取直接内联为掩码字面… |
| e00025 | candidate | t2/s04c1 | 271.0s | 10.98x | ok | 稀疏 commit-input gating 仅保留尾部工作量至少为 dirty edge 数 4 … |
| e00026 | candidate | t2/s04c2 | 271.3s | 10.99x | ok | wide-state explode 将 commit 输入门控的宽态传播边压缩，使剩余 gate … |
| e00027 | candidate | t0/s05c1 | 222.7s | 9.02x | ok | 在e00022的source-word activity guard上叠加wide-storage … |
| e00028 | candidate | t0/s05c2 | 235.6s | 9.54x | ok | e00022 的 source-word guard 仍逐 byte 从 activeWords_ … |
| e00029 | candidate | t1/s05c1 | 237.4s | 9.62x | ok | 将窄标量 divide_value/modulo_value 定义内联到生成头文件，使固定宽度、si… |
| e00030 | candidate | t1/s05c2 | 230.4s | 9.33x | ok | 在 inlineScalarConstants 的字面量读取基础上，按 escape/pin 分析删… |
| e00031 | candidate | t2/s05c1 | 265.2s | 10.74x | ok | c1: 每64个commit gate共用packed uint64 dirty位图，减少逐gate… |
| e00032 | candidate | t2/s05c2 | 285.6s | 11.57x | ok | c2: producer block结束后比较窄标量输出快照，仅在真实变化时传播commit-inp… |

最近 actions：A0016 step-resume；A0017 round-summary；A0018 step-resume；A0019 step；A0020 step-resume

