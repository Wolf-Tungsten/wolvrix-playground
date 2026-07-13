# TNO0001 Small-load baseline and analysis method

记录日期：2026-07-13

来源范围：`NO0221..NO0223`，原始记录见 [NO0221](../grhsim_opt/NO0221_no0217_plain_bae_artifact_rebuild_20260707.md) 至 [NO0223](../grhsim_opt/NO0223_small_load_codegen_perf_findings_20260709.md)。

状态：基线与分析方法已建立，后续优化从“大 SimTop 统计猜测”切换为“小负载代码与机器行为直接对照”。

## 1. 背景

仓库重置后先恢复 NO0217 的 plain 路径构件，再选择 `BigComb` 和 4 个 `xs-components` 小负载，直接比较 GSim/GrhSIM 的：

- generated C++ 与 hot function；
- runtime profile TSV；
- `perf stat/report/annotate`；
- O3 object、反汇编与 helper 调用形态。

这套口径避免继续只在完整 SimTop 上观察聚合数据而无法定位具体代码形态。

## 2. 恢复后的结构基线

| Metric | GSim | plain GrhSIM | Ratio |
| --- | ---: | ---: | ---: |
| strict BAE | 1,367,268 | 2,446,334 | `1.789x` |
| compute-to-commit | - | 350,523 | 固定项 |

恢复结果没有带回 CBAW/iteration 变体。新增差异主体仍是 compute-to-compute value-target multiplicity，而不是 commit split。

## 3. 小负载结果

`BigComb` 这类纯组合 case 中，GrhSIM 可以接近甚至快于 GSim；明显差距集中在 FTQ、Tage 和 VtypeBuffer 等带宽状态与多阶段 settle 的负载，GrhSIM 慢约 `1.62x..2.20x`。

首轮直接证据为：

- 热点集中在少数 `eval_*_batch_*`；
- `grhsim_*_words<16>` 宽字 helper 占有可见比例；
- 简单比较 generated source 总字节无法解释差距；
- 必须同时看 helper、临时值、fixed-point round 和 active propagation。

## 4. 固化的分析口径

后续小负载实验统一遵循：

1. GSim/GrhSIM 使用同一输入和等价 workload；
2. 先做单模型长窗口，避免两模型互相污染 PMU；
3. 先验证功能，再看 wall time、instructions、cycles 与 IPC；
4. hot symbol 必须回到 generated C++ 和汇编；
5. probe 只在确实改变 object machine code 后才有解释力；
6. 小负载结论必须再经 SimTop 功能与相邻 A/B/A 验收。

## 5. 阶段判断

本阶段建立了后续工作的基本方法：先用小负载把“慢在哪里”落到具体 C++/object，再回到 SimTop。第一个明确主线是 VtypeBuffer 宽字 helper 与 active/change 框架，而不是继续盲调 partition/topology。

## 6. 规则审计与关键数据

记录类型：历史 root-cause 阶段总结。单一议题边界是“如何建立能够解释 GSim/GrhSIM 差距的小负载基线与分析口径”。下表只补充既有实验的复核信息；本篇不再承载后续独立实现或性能 gate，后续结果必须新建 TNO。

### 6.1 Raw no-profile 基线

`xs-components` 的 `--vectors 200000` 实际执行 `200002` 个 component cycles，其中多出的 2 个来自 seed vectors：

| Workload | Component cycles | GSim wall (ms) | GrhSIM wall (ms) | GrhSIM / GSim |
| --- | ---: | ---: | ---: | ---: |
| NfmappedSmall | 200,002 | 8.851 | 7.937 | `0.897x` |
| FTQ | 200,002 | 382.939 | 621.988 | `1.624x` |
| Tage | 200,002 | 311.882 | 519.662 | `1.666x` |
| VtypeBuffer | 200,002 | 210.040 | 462.889 | `2.204x` |

BigComb 是无时钟组合负载，执行 `1,000,000` 次 eval，GSim/GrhSIM 分别为 `18,412.182/18,423.966ms`；它没有可报告的 guest cycle。

### 6.2 Perf 长窗口口径

- 大负载 timed region 为 `2,000,002` 个 component cycles；含 warmup 的进程总量为 `4,000,004` 个 component cycles。
- GrhSIM 每个 component cycle 调用 low/high 两次 eval，因此进程总计 `8,000,008` 次 eval；不能把 eval 次数误写成 guest cycles。
- VtypeBuffer 同一长窗口 stdout 为 GSim `2,125.737ms`、GrhSIM `4,695.578ms`。

详细命令和产物见 [NO0223](../grhsim_opt/NO0223_small_load_codegen_perf_findings_20260709.md)。
