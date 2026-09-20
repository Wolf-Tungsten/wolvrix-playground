# TNO0314: XiangShan RepCut completion-v2 AB/BA result

日期：2026-09-14

状态：`COMPLETE BALANCED DIAGNOSTIC; CANDIDATE NOT SELECTED; LEGACY RETAINED`。

前置：[TNO0313](./TNO0313_xiangshan_repcut_completion_v2_build_gate_20260914.md)。
本篇只使用修正漏唤醒后的 v2，不混入被
[TNO0312](./TNO0312_xiangshan_repcut_completion_v1_invalidation_20260914.md) 否决的 v1。

## 1. 固定运行与质量门

2026-09-14 13:42–13:44（Asia/Shanghai），node031 CPU96-127、NUMA1、SMT288-319、
monitor35。A=runtime-v1 legacy，B=completion-tail-v2 pipeline-workers，N=K=32、
identity mapping、push、无新增probe。先AB后BA，每序先C100再C10000。8个slot均首次
admission即launch，四个canary通过；四个预定长样本全部保留，没有按残差/性能重抽。

四个长样本功能、source/ELF/protocol身份、page、worker门全部通过；每条EMU/NEMU
各3份合格page采样、worker各3份完整采样，本地驻留比例均100%。12个staging inode
互不重复，结束时身份复核通过。

| 顺序/臂 | 原 runtime verdict | raw busy−task-clock (CPU s) | raw total−32×workload wall (CPU s) |
| --- | --- | ---: | ---: |
| AB/A | unexplained target busy 拒绝 | +10.72378 | −6.37150 |
| AB/B | 通过 | −5.08924 | −25.96920 |
| BA/A | unexplained target busy 拒绝 | +12.40271 | −4.51921 |
| BA/B | 通过 | −5.58609 | −26.49927 |

计账差额按原门保存，不能自动等同外来用户CPU用量，也不能据此宣称环境完全无污染。
沿用 `balanced_diagnostic` / `formal_acceptance=false`，不是全strict或生产性能承诺。

## 2. Host 结果

| C10000 Host | A legacy (s) | B corrected completion-v2 (s) | B/A−1 |
| --- | ---: | ---: | ---: |
| AB | 10.652 | 11.533 | +8.2707% |
| BA | 10.443 | 11.494 | +10.0642% |
| pooled | 10.5475 | 11.5135 | +9.1586% |

两序都回退，pooled增加0.9660 s；不满足“两序改善且pooled减少至少2%”的事前选择条件。
保留legacy，不改变实验control或生产默认。

## 3. 辅助指标与可说/不可说的结论

| pooled 指标 | A | B | B/A−1 |
| --- | ---: | ---: | ---: |
| step总时间 (s) | 10.438665 | 11.357939 | +8.8064% |
| eval part max (us/step) | 277.8393 | 278.3661 | +0.1896% |
| eval phase wall (us/step) | 324.1883 | 327.7918 | +1.1115% |
| global update phase wall (us/step) | 180.8116 | 219.6295 | +21.4687% |
| instructions | 303,444,462,761 | 305,229,663,448 | +0.5883% |
| cycles | 200,800,654,492.5 | 225,334,600,242 | +12.2181% |
| context switches | 1,394,836.5 | 1,644,416.5 | +17.8931% |
| aggregate IPC | 1.51117 | 1.35456 | −10.3635% |

eval part max是各partition平均eval耗时的最大值，不是逐step最大值的均值。
global update wall包含阶段释放/拷贝callback/完成同步，不能全部称为纯通信拷贝代价；
本实验未改变通信端点或字节数，也没有加probe进一步拆分修正版的尾部。

数据支持“这个completion-only变体不足以让pipeline-workers胜过legacy”。它不支持
“completion修改本身没任何收益”或“已经排除completion mutex是瓶颈”：A/B同时包含原
pipeline整体结构差异。量化该改动本身需要原pipeline与v2直接配对；不拿TNO0307、v1或
probe的绝对值跨轮相减。本轮按一次定位、一个最小候选原则收尾，不继续无限调锁。

## 4. 证据路径与身份

以下路径以 `build/repcut_nk32_opt_20260907/` 为根：

- spec：`specs/stage1_completion_tail_v2.json`，SHA
  `db143fbc61be8c39a714367a21c365229b95831dfee7f194c8438ab36b72abd3`。
- AB：`runs/stage1-completion-tail-v2-20260914-node031-reserved96-ab1/captured.json`，SHA
  `5bb6e00aa38b1bb8ae658f806c132b24d47c836b1f58bdd1c332734b019570fd`。
- BA：`runs/stage1-completion-tail-v2-20260914-node031-reserved96-ba1/captured.json`，SHA
  `fd022412d05c502cf01be8f3f5c9d7c62eee0541eb9f8072bc9a070ba32f4b9a`。
- summary：`measurement/stage1-completion-tail-v2-20260914-node031-reserved96-pair1-analysis/summary.json`，
  SHA `08c43269bbc0d918c24c56e58d1ada5180a549af043229fe5255a1cb3f81e6ff`。
- v2 ELF SHA `69792905bdee89cbe516e76b3f5236c63f2522810a434b16b2af81de4c1e3739`；
  构建门、源码hash、独立并发回归见TNO0313。

## 5. 下一步边界

本轮completion候选已闭环且不采用。后续回到
[TNO0280](./TNO0280_xiangshan_repcut_nk32_four_stage_experiment_plan_20260907.md) 原计划，
优先补齐独立的pipeline-host（Host承担1个partition，31个后台worker承担其余partition）
对legacy无probe AB/BA；应冻结具体ELF/同步实现，不能默认叠加本轮未选中的v2。若仍无益，
保持legacy继续CCD映射，再评估pull/通信后处理。本篇未启动这些后续运行或ASC实验。
