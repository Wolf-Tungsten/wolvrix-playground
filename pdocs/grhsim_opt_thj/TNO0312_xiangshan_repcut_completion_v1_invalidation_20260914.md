# TNO0312: XiangShan RepCut completion-v1 invalidation

日期：2026-09-14

状态：`V1 CORRECTNESS INVALID; RAW RUNS PRESERVED; NO PERFORMANCE SELECTION`。

前置：[TNO0310](./TNO0310_xiangshan_repcut_sync_probe_result_20260914.md)。
本篇记录 completion-only 首版实现、已发生的 AB/BA 以及随后正确性复核的否决。
所有产物位于 `build/repcut_nk32_opt_20260907/` 下；未覆盖旧文件或改生产默认。

## 1. 首版实现与缺陷

`completion_tail_20260914/generate_candidate.py` 从 frozen `runtime/generated-v1` 生成
`generated-v1`，仅把 completion 计数改为 release atomic fetch_add、Host acquire load，
最后一个 worker 直接 notify_one，不再锁住 Host 等待使用的 mutex。

这个写法存在漏唤醒：Host 持锁检查 completed 未满 → worker 完成计数并通知 → Host
进入 condition_variable wait。因为 worker 不受同一个 mutex 约束，通知可以落在检查与
实际入睡之间；之后没有新通知，Host 可永久等待。有限运行未挂住不能排除此交错。

- v1 header SHA：`973f67729a659e5e215a7f1dd7be41407d0396189c0d2bb7452621446662c62b`。
- v1 ELF：`builds/completion-tail-v1/emu`，SHA
  `cd31ae1fd61e3f680aa56a632ac3cb421947053efe0a1d88957ff4a46bfa6f16`。
- build manifest SHA：`cdd155be9196bd8a7dedc3678a5dfcd9f02c3a836fac42a13c83bc4fadf74575`。

## 2. 已发生运行，只保留事实

node031 CPU96-127、NUMA1、monitor35，A=frozen runtime-v1 legacy，B=completion-tail-v1
pipeline-workers。各序 C100 后 C10000；共8个首次 admission/launch，无重新抽取已启动样本。

| C10000 Host | A legacy (s) | B invalid v1 (s) | B/A−1 |
| --- | ---: | ---: | ---: |
| AB | 10.400 | 11.538 | +10.9423% |
| BA | 10.537 | 11.490 | +9.0443% |
| pooled | 10.4685 | 11.5140 | +9.9871% |

四个长样本功能、身份、page/worker 门通过；原 CPU residual 门 AB/A 拒绝
（unexplained 14.39578 s），其余通过。测量分析器输出 `balanced_diagnostic`、
`formal_acceptance=false`，但它没有同步算法正确性证明能力；**本篇新增的代码正确性否决
高于测量器 verdict，v1 不能用于候选选型或机制因果判断**。

- captures：`runs/stage1-completion-tail-20260914-node031-reserved96-{ab1,ba1}/captured.json`。
- summary：`measurement/stage1-completion-tail-20260914-node031-reserved96-pair1-analysis/summary.json`。
- summary SHA：`ba010d87a69dd6a5a379ba0b6f2d188271184f4f72997b9d1b32c975a5db62ec`。

## 3. 勘误与解释边界

1. 先前口头所称 candidate mock 已通过不准确：当时运行的是旧 `runtime/test_step_pipeline`
   二进制，仅生成器的3项结构测试针对首版；旧 mock 不能证明首版候选正确。
2. TNO0307 的 B=11.5355 s 与本次 B=11.5140 s 是不同 pair 的绝对值。相减得到的约0.19%
   不是 completion 改动的受控收益；撤销“去掉 mutex 确有一点作用”的表述。
3. 不能据此排除 completion mutex 是瓶颈，也不能断言主要成本一定在更早屏障。若要量化
   completion 改动自身，必须另设原 pipeline 与正确候选的直接机制对照；本轮按既定规则
   先与 legacy 比较，不无限增加实验。
4. 后续在新目录生成 v2，仅最后一个完成者锁 mutex 后通知，所有 v1 原始产物不动。

相关 probe CPU gate 与 critical-lane 条件统计解释已向 TNO0310 追加勘误。
