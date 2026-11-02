# TNO0396：移除优先编码调用中的显式 Vec.asUInt

日期：2026-11-02。本文记录在 [TNO0395](./TNO0395_priority_intrinsic_input_layout_policy_20261102.md)
之后，对实际 XiangShan 调用点显式 gather 的进一步处理。

## 修改范围

确认并修改了三个 utility 覆盖范围内的调用：

| 文件 | 原表达式 | 新表达式 |
| --- | --- | --- |
| `huancun/RequestBuffer.scala:67` | `PriorityEncoder(~valids.asUInt)` | `PriorityEncoder(valids.map(v => !v))` |
| `frontend/ifu/PredChecker.scala:133` | `ParallelPriorityEncoder(remaskFault.asUInt)` | `ParallelPriorityEncoder(remaskFault)` |
| `frontend/ifu/Ifu.scala:621` | `PriorityEncoder(enq & s3_alignRvcIll.asUInt)` | 对每个 lane 构造 `enq(i) && s3_alignRvcIll(i)` 的 Seq 输入 |

这些修改保持最低位优先、位序、全零行为和硬件语义，只让 utility 看见分散输入。
Rocket Chip 的第三方 `uncachedInFlight.asUInt` 暂未修改；`MainBtbAlignBank` 的
`t1_entryWayMask.asUInt` 本身已经是 UInt，不是 Vec gather。

## v7 生成和布局判定

v7 已从修改后的源码分别生成 A（原语关闭）和 B（`priority-encode` 开启），两版都通过
Chisel/FIRRTL、Wolvrix emit 和 emu 编译。manifest 中的调用统计如下：

| 版本 | 总调用记录 | packed intrinsic | distributed 保留硬件 |
| --- | ---: | ---: | ---: |
| A（关闭） | 469 | 0 | 342（另有 127 个 packed 但模式关闭） |
| B（开启） | 466 | 127 | 339 |

三个修改点在 B 中都记录为 `distributed-keeps-hardware`：

- `huancun/RequestBuffer.scala:69`：`PriorityEncoder.Seq`，宽度 4；
- `frontend/ifu/PredChecker.scala:133`：`ParallelPriorityEncoder.Vec`，宽度 36；
- `frontend/ifu/Ifu.scala:621`：`PriorityEncoder.Seq`，宽度 36。

这说明显式 `asUInt` 已经从这三处输入布局中移除，但布局门控没有把它们错误地替换成
Wolvrix intrinsic；它们仍使用原有硬件优先编码结构。

### 后端形态

| 指标 | A | B | B 相对 A |
| --- | ---: | ---: | ---: |
| graph ops | 7,204,064 | 7,200,616 | -0.04786% |
| graph values | 6,832,965 | 6,829,517 | -0.05047% |
| compute nodes | 1,081,731 | 1,080,953 | -0.07192% |
| compute supernodes | 63,293 | 63,179 | -0.18012% |
| DAG edges | 519,747 | 521,006 | +0.24224% |
| topo edges | 10,141,532 | 10,137,474 | -0.03999% |
| boundary values | 996,513 | 996,545 | +0.00321% |
| boundary activation edges | 1,977,511 | 1,977,413 | -0.00496% |
| compute-node ops | 5,625,074 | 5,621,615 | -0.06149% |

后端没有出现规模爆炸；compute node 数略少，DAG 边略多，说明这次改动确实改变了少量
结构，但没有形成明显的软件工作量优势。

## 单线程 walltime

使用 Wolvrix 专用单线程流程，A/B 在 node030 上编译，测量固定 CPU96；每版先做 smoke、
两组 100,000 周期 Difftest trace 和 warmup，再做 8 对 AB/BA。所有正式样本的
`locality_pass`、CPU 亲和性、SMT sibling 检查均通过。

| 指标 | 结果 |
| --- | ---: |
| A 平均 Host time | 111.738750 s |
| B 平均 Host time | 112.276000 s |
| B 相对 A（均值） | **+0.482634%** |
| 配对差中位数 | +1.005639% |
| 固定种子 paired bootstrap 95% CI | [-0.158560%, +1.023038%] |
| B 更快的配对数 | 2 / 8 |

两组 trace 各有 100,000 条记录，A/B 哈希完全一致；功能签名为 PC `0x80000c0c`、
`instr_count=240349`、`cycle_count=99996`、`guest_cycles=100001`。历史 v4 A 的
前后 anchor 也与该签名一致。

结论是：移除三个显式 `Vec.asUInt` 没有带来可复现的 walltime 改善。本次均值方向略慢，
但置信区间跨过零，不能据此宣称有统计显著的回退。结合 TNO0395 的结果，当前仍应保持
“packed 输入才启用 intrinsic、分布式输入保留硬件结构”的默认策略；这三个源码改动可以
保留为布局清晰化，但不作为性能优化证据。

## 复现产物

- [v7 A/B 生成目录](../../build/xs/priority_intrinsic_20261102_v7/)
- [单线程 comparison-v1 summary](../../build/xs/priority_intrinsic_20261102_v7/comparison-v1/summary.json)
- [配对 CSV](../../build/xs/priority_intrinsic_20261102_v7/comparison-v1/pairs.csv)
- [机器可读本次报告](../../wolvrix/build/artifacts/priority-intrinsic/priority-intrinsic-explicit-asUInt-report.json)

复现命令（编译可在 node030 任意核，测量脚本会固定 CPU96）：

```bash
python3 wolvrix/build/artifacts/priority-intrinsic/xs_generate_v7.py
python3 wolvrix/build/artifacts/priority-intrinsic/xs_finish_v7.py
python3 wolvrix/build/artifacts/priority-intrinsic/xs_compare_v7_wait.py
```
