# TNO0310: XiangShan RepCut sync probe result

日期：2026-09-14

状态：`DIAGNOSTIC PROBE VALID; REGRESSION ATTRIBUTED TO CRITICAL COMPLETION TAIL; NO CANDIDATE YET`。

前置：[TNO0308](./TNO0308_xiangshan_repcut_nk32_sync_diagnosis_plan_20260914.md)、
[TNO0309](./TNO0309_xiangshan_repcut_sync_probe_build_gate_20260914.md)。

## 1. 证据范围

node031 NUMA1 CPU96-127、SMT288-319、monitor35 上完成独立诊断 AB/BA。两臂同一
syncdiag-v1 ELF，A=legacy、B=pipeline-workers，N=K=32、identity 映射、push。8 个
预定 C100/C10000 slot 全部启动；四个长样本功能、身份、页归属和 worker 门通过，
唯一原 runtime 拒绝仍为 BA/A 的 unexplained target busy。probe 本身四条长样本均有
1257 个采样记录（每16 step，覆盖 C=10000 的 20102 steps），事件计数和时间顺序
全部通过。插桩会改变 timing，因此以下只用于机制归因，不用于 Host 选型。

## 2. 核心分解（C=10000 长样本 pooled）

定义每个采样 step 的 `E=max(eval_end)`，选择实际最晚 `update_end` 的 lane 为 critical；
跨 AB/BA 对每步均值算术平均。单位 us：

| 区间/指标 | legacy A | pipeline-workers B | B-A |
| --- | ---: | ---: | ---: |
| 首个 lane 放行延迟 | 35.696 | 31.964 | −3.731 |
| 全 lane 平均放行延迟 | 72.267 | 62.621 | −9.646 |
| 最后完成 lane 的放行延迟 | 63.648 | 78.355 | +14.707 |
| critical update 本体 | 116.732 | 119.139 | +2.407 |
| 最后 update 完成 → Host 返回 | 13.093 | 25.245 | +12.151 |
| E → 最后 update 完成 | 180.380 | 197.495 | +17.114 |
| E → Host 返回 | 193.473 | 222.739 | +29.266 |
| dispatch → Host 返回 | 625.578 | 670.900 | +45.321 |

AB 与 BA 的方向一致：critical release 分别 +15.401/+14.013 us，completion tail
分别 +12.739/+11.564 us；E→Host 分别 +30.793/+27.738 us。全 lane 平均放行下降
而 critical lane 放行上升，说明平均值掩盖了决定墙钟的尾部线程，不能只优化平均 barrier。

## 3. 解释边界

当前 probe 支持“回退主要来自关键 lane 的屏障/唤醒竞争及完成通知尾部”的假设：
`StepPipeline::execute_lane` 在 eval 汇聚和 completed 汇聚处都使用同一共享 mutex；
最后到达者唤醒等待者，等待者需重新竞争该 mutex。B 的 critical body 只增加2.407 us，
不能解释29.266 us 的 E→Host 增量；但 probe 没有 futex 调度事件或逐锁等待 profile，
不能给出共享 mutex、notify_all、notify_one 各自的因果比例，也不能把 E→Host 全称为
纯 barrier/通信时间。probe 本体包含原 callback/wrapper 边界，不是裸 memcpy。

## 4. 阶段决策

不直接实现“只替换 eval→update barrier”候选，因为全 lane 平均 eval 放行已下降，
而 critical release 和完成尾部才是主要差异。下一项应是**只针对 completion/critical
tail 的最小同步变体**：保持全体 eval 完成后才能 update、所有 update 完成后才能下一
step 的语义，单独减少 completed 共享锁竞争或 host 完成通知的 convoy。若实现前需要
进一步区分 eval barrier 与 completion barrier，先加一次无性能选型用途的 futex/调度
等待诊断；不能把带 probe 的结果与 TNO0307 的无 probe Host 数值相减。

候选必须先通过 C++17 mock、异常/取消、ABI/源码/1422对象身份和 C100；关闭 probe 后
再按同一 CPU96-127、C10000 AB/BA 复测。只有两序 Host 都改善且 pooled 中心至少2%
才暂选 control；否则立即保留 legacy。本轮未进入 pipeline-host、CCD 映射、pull 或
solver 后处理。

## 5. 产物与复核

- AB：`build/repcut_nk32_opt_20260907/runs/stage1-syncdiag-20260914-node031-reserved96-ab1/captured.json`。
- BA：`build/repcut_nk32_opt_20260907/runs/stage1-syncdiag-20260914-node031-reserved96-ba1/captured.json`。
- Probe summary：`measurement/stage1-syncdiag-20260914-node031-reserved96-pair1-analysis/summary.json`。
- summary SHA-256：`e6add566bc8d9c8eb12663d72d7cf3a14e7b794f40dc49d09e25b6bd2192c0f4`。
- AB/BA captured SHA-256：`1932ddb2e9c9626ecd2b28620519ef15d364a73249e04f0ef501c8944c7bb59d` /
  `e7e0f0f04227d3df3a261db27409270f245fd57d0ce2668fc952849be978240a`。

生成器/collector 5 项、probe analyzer 5 项及原 measurement/calibration 47 项单测均通过。

## 6. 勘误 2026-09-14：CPU verdict 与归因边界

重新检查原 summary 的 baseline_capture_analysis.gate_evidence，原 CPU residual 门拒绝
实际包括 AB/A（unexplained 10.64098 s）和 BA/A（8.03212 s），不是第1节所称“唯一 BA/A”。
两侧 B 均通过；全部原始样本保留，仍为 balanced diagnostic 而非全 strict。

critical lane 是每步按最晚 update_end 条件选择的，会因运行方式改变身份；因此 critical
release 增加14.707 us不是“同一线程的放行延迟必然增加14.707 us”。事件分解定位时间落点，
支持同步尾部假设，但不足以证明某把mutex的因果份额。全lane平均延迟下降也不排除 eval
barrier 的尾部优化价值。第3、4节应在这些边界内理解。

completion 首版实现发现漏唤醒并被否决，见
[TNO0312](./TNO0312_xiangshan_repcut_completion_v1_invalidation_20260914.md)；
修正版构建门见 [TNO0313](./TNO0313_xiangshan_repcut_completion_v2_build_gate_20260914.md)。
