# TNO0425 恒零表回退的动态执行计数

承接 [TNO0424](./TNO0424_decode_constant_schedule_divergence_20261104.md)。本轮使用隔离的诊断二进制，只记录行为，不把诊断 walltime 当作正式性能结果。C/E 均用相同输入窗口，seed0、seed1，并重复 seed0；两次 seed0 的计数文件逐字节一致，四项有效 Difftest trace 全部通过。

## 原始计数

| 计数 | C | E | E 相对 C |
| --- | ---: | ---: | ---: |
| supernode fire | 1,785,229,319 | 1,774,800,898 | −0.584% |
| 结果/宽值检查 | 19,449,014,903 | 19,370,319,632 | −0.405% |
| 变化结果 | 1,121,996,051 | 1,121,822,571 | −0.015% |
| 活动写入语句 | 10,757,210,971 | 10,646,806,128 | −1.026% |
| 写入非零 mask | 3,444,878,175 | 3,440,449,439 | −0.129% |
| 新增活动位 | 1,868,155,831 | 1,861,447,500 | −0.359% |
| batch 调用 | 38,109,535 | 37,708,382 | −1.053% |
| batch 空调用 | 16,428,710 | 16,319,879 | −0.663% |

`fixed-point round` 和 eval 次数相同；dirty word 计数器在这两个构建中没有匹配到可归因语句，因此不用于结论。变化检测本身几乎相同，差异主要来自 batch/supernode 调度和活动传播。

## 跨版本对齐

使用最终 supernode 的完整操作成员集合做 fingerprint，拒绝用 raw supernode ID 对齐。49,349 个成员集合相同，另有 27,454 个 hash 只在一侧出现或发生重组。公共组的变化检测次数完全相同；公共组的 fire 和 active write 仍分别多出约 0.38% 和 0.16%，其余差异来自重组组，不能强行分配给某个 RTL 源。

这与四对独立 PMU 一致：E 的进程 instructions 平均少 0.5713%，cycles 少 0.6154%，branches 少 0.0307%，branch-misses 增加 0.3241%。因此当前证据支持“C 执行了更多后端工作”，不支持“主要只是 branch predictor 退化”。

计数产物：[count-runs/summary.json](../../build/xs/decode_constant_investigation_20261104_v1/count-runs/summary.json)、[dynamic-group-diff.json](../../build/xs/decode_constant_investigation_20261104_v1/dynamic-group-diff.json)。
