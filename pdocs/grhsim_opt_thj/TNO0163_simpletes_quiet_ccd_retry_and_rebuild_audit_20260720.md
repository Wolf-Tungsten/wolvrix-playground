# TNO0163 SimpleTES quiet-CCD retry and rebuild audit

记录日期：2026-07-20

状态：continuation instance `4269c986` 的第一次 initial seed runtime 没有产生性能样本，
原因是严格的空闲 CCD admission gate 未通过；SimpleTES 将该结果正确标为 retryable
infrastructure，而不是候选无效或性能回退。engine 随后重新提交同一 seed，当前已进入第二次
unpatched emit/build。性能和默认决策仍未形成。

启动与输入快照见
[TNO0162](./TNO0162_simpletes_best_seed_continuation_launch_20260720.md)。

## 1. First runtime attempt

初始 seed 的 emit、disabled、enabled build 以及小负载 gate 均通过后，第一次 50k runtime
在 `2026-07-20 19:46:41 +08:00` 返回：

```json
{
  "candidate_walltime_ms": null,
  "control_walltime_ms": null,
  "infrastructure_retry": true,
  "retryable_infra": true,
  "valid": false,
  "diagnostics": {
    "ccd_count": 24,
    "error": "no dynamically discovered CCD passed the strict quiet-window gate",
    "gate": "3s whole-CCD count=16 mean>=98 min>=95 target+sibling>=98"
  }
}
```

本次 evaluator manifest 的 `eval_time` 为 `4,986.4233756661415 s`，但这是包含构建和
runtime admission 的尝试耗时，不是 SimTop walltime，不能作为性能数据。`samples` 为空，
因此本次不计入 ABBA、BAAB、score 或 valid-candidate budget。

## 2. Retry behavior observed

SimpleTES engine 收到 `infrastructure_retry=1` 后等待 `30 s`，重新调用 evaluator。当前
实现中 evaluator worker 是新进程，candidate checkout 和 artifact preparation 也会重新执行；
因此第二次尝试在 `19:47:31` 重新 clone，并重新进入 unpatched same-options emit。第一轮已付出
的构建时间约为：

| phase | absolute duration |
| --- | ---: |
| unpatched emit | `1,366,917 ms` |
| disabled build | `1,371,162 ms` |
| enabled build | `1,357,903 ms` |

这些数值只描述 infrastructure retry 的成本，不描述候选性能。第二次尝试在本记录形成时仍
未到达新的 50k runtime，不能引用 slot 中旧的 `12:52` evaluation/runtime JSON。

## 3. Gate interpretation

该 gate 的意图是确保整个 16-logical-CPU CCD 在 3 秒窗口内保持足够空闲，并同时审计 target
与 sibling；它不是可放宽的性能筛选。一次瞬时外部负载导致全体 CCD 不通过时，正确行为是
等待并重试，而不是在繁忙节点上取得不可复现的 walltime。独立只读 survey 在稍后窗口曾观测
到若干 CCD 满足相同阈值，说明第一次失败是时间窗口的外部负载状态，而非拓扑发现为空或
candidate build 失败。

本轮没有改变 gate 阈值、CPU 绑定、ASLR、NUMA 或 PMU 契约，也没有修改 wolvrix source。
后续仍等待完整 quiet CCD，再执行 control/candidate ABBA，只有正向且可信的 50k walltime
才允许进入 SimpleTES 的候选排序。

## 4. Follow-up

当前实例继续运行第二次尝试；若外部负载反复阻断 admission，后续可在不放宽 gate 的前提下
提高 runtime 内部的 infrastructure retry 次数，以减少重复构建，但这属于独立的 SimpleTES
运行器改进，不能回写为本轮性能结果。任何新 walltime、worker generation 或停止原因另立
后续 TNO。
