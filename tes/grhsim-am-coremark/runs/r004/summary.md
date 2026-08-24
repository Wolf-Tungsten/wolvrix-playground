# run r004 总结（grhsim-am-coremark）

收口日期：2026-08-25。C=6, L=4, K=2，24/24 步全部走满；候选 evals 48/48
耗尽（另含基线 e00085/e00086，总计 50 eval）。base/y0 = r003/e00057 完整解
`1563c3d837fc`（12 个冻结 emit 开关，分支 `tes/r004/base`）。输入为 wolvrix
自解析 post-stats JSON（sha256 `c82ed454...b70c7`）。

## 结果总览

- 同协议冻结基线：AM y0 = **193.403s**（e00085），gsim target = **22.720s**
  （e00086），起跑差距 **8.512x**。
- ledger raw best_overall = t1/e00125 **164.729s**，commit
  `2420901f8343cfc5c407af92d7f0ec5a97cd5566`；相对 AM y0 改善 **14.83%**，
  但仍为 gsim 的 **7.250x**，剩余绝对差距 142.009s，目标未达成。
- 3% 裁决带下的确认 best 为 t1/e00113 **166.014s**（较 AM y0 改善 14.16%，
  gsim 比值 7.307x）；e00125 的 lazy commit-scratch 增量仅改善 0.77%，所以只更新
  raw best_overall，不替代轨迹的确认 best。
- 健康度：48 个候选中 42 个 `ok`、4 个 `ctest_fail`、1 个 `difftest_fail`、
  1 个 `emit_fail`。42 个 ok 候选均通过 17/17 ctest 和三次 nemu difftest，全部
  unimodal 且 non-noisy；失败候选均在对应功能/表型门停止，没有带分数越门。

## 轨迹分数曲线（step raw winner 中位，秒）

| step | t0 | t1 | t2 | t3 | t4 | t5 |
|---|---|---|---|---|---|---|
| y0 | 193.403 (e00085) | 193.403 (e00085) | 193.403 (e00085) | 193.403 (e00085) | 193.403 (e00085) | 193.403 (e00085) |
| s01 | 189.829 (e00088) | 190.827 (e00089) | 188.662 (e00092) | 172.530 (e00093) | 无 winner（e00095/e00096 `ctest_fail`） | 191.116 (e00097) |
| s02 | **172.832 (e00100，t0 best)** | 171.233 (e00102) | **169.577 (e00104，t2 best)** | **166.947 (e00106，t3 best)** | 189.263 (e00108) | **173.058 (e00110，t5 best)** |
| s03 | 170.564 (e00111) | **166.014 (e00113，t1 confirmed best)** | 166.561 (e00115) | 168.540 (e00118) | 173.624 (e00119) | 168.198 (e00121) |
| s04 | 169.236 (e00124) | **164.729 (e00125，raw global best)** | 167.795 (e00128) | 168.759 (e00130) | **166.837 (e00131，t4 best)** | 167.917 (e00133) |

表中为状态机每 step 的 raw-score winner；粗体轨迹 best 取 `run.json` 的 3% 裁决带
语义。neutral winner 会机械推进 tip，但不会把不足以分辨的 raw 改善升级为确认收益。

## 机制族裁决

**保留的有效解材料**：

1. **幂次 memory-read 索引专化**：e00093 相对 y0 改善 10.79%，随后在 t0/t1/t2/t5
   四条迁移轨迹相对父节点稳定改善 8.95%-10.27%。post-change recon 显示六个
   512-depth memory-read 热块 cycles 下降 93.08%-94.67%，形成跨轨迹、动态池和 Host
   三重闭环，是 r004 最稳定的一阶机制。
2. **宽 ArrayBroadcast-to-ArrayMux 链融合**：生产固定命中 4 chains/92 steps；在
   pow2-index + guard-cache 基座 e00113 上改善 3.05%，在 pow2-index + predicate-run
   基座 e00131 上改善 3.91%，确认中间宽值物化消除可与两类基座相加。其他基座只给
   1.31%-2.81%，其收益具有基座依赖，不能按静态命中数无条件外推。
3. **guard-cache / predicate-run / commit scratch 生命周期**：各自及其组合多为
   0.6%-2.5% 弱正。e00125 的完整组合给出全局 raw best，但相对 e00113 仅 0.77%，
   因此可作为下次 y0 的完整工程解，不把其中任一弱机制升级为独立确认收益。

**关闭或要求新动态证据后才能重开**：

- commit 双峰在 recon 中长期占约 8.4%-9.3%，但 chunk 6000、source 256KiB 分片、
  lazy/after-gate 清零、64-bit bitpack、state operand locality 都没有稳定越过 3%；
  bitpack 还回退 5.29%。后续须先把 commit 墙钟拆成清零、flag scan、call 与 DPI，
  再做生产者/消费者联合批处理，停止容器和边界参数的表面微调。
- host-call guard/predicate/common-event/operand-locality 的高静态覆盖没有转化为确认
  收益；重开须动态拆分 scan、参数准备、格式化和 DPI，而不是继续叠加外层条件。
- 短 wide-mux 链、Replicate 乘法、Concat 平衡 OR、commit atom 拆分、局部存储形态
  均被干净回退或低 engagement 证伪。e00105/e00114 的 fixture 失败和 e00134 的 CLI
  缺失仅说明性能未测，未来重开必须先修契约/实现，不能把失败状态当性能负证据。

## 测量与预算裁决

- r004 的自适应分簇协议消除了 r003 的跨态误裁风险：42 个有 Host 结果的候选全部
  unimodal、non-noisy，3% `adjudicate_noise` 只把可分辨改善升级为 `win`。
- round 2 最终重锚为 AM/e00085 **194.019s**（冻结值 +0.32%）和 gsim/e00086
  **24.226s**（+6.63%）。gsim 水位漂移超过 3%，故 ledger 仍用冻结 target
  22.720s；即使用最新重锚诊断值，e00125 仍为 **6.800x**，不改变目标未达结论。
- 收益主要来自 s02 的 pow2-index 广泛迁移与少数 s03/s04 宽 mux 组合；第四轮只有
  t4/e00131 形成新确认 win，其余五条轨迹均为 neutral 或失败。当前局部微结构邻域
  已明显饱和。

## restart 建议

**当前不建议 restart。** r004 未达目标，且 `restart.max=3` 已由 r001->r002、
r002->r003、r003->r004 三次 restart 用尽，`auto=false`。更重要的是剩余 7.250x
差距不可能由已饱和的 commit/host-call 表面微调闭合；run 收口后应停在无活跃 run，
等待用户决定结束搜索，或批准新的机制范围与 restart 预算。

若用户之后明确扩大 `restart.max` 并批准更大粒度的 AM pass/调度改写，预备 y0 为
**r004/e00125**：commit `2420901f8343cfc5c407af92d7f0ec5a97cd5566`，完整 16 项
emit 表型以 ledger 为准。建议新 **C=4, L=3, K=2（N=24）**：保留四条独立机制轨迹，
但缩减已显示饱和的深度与总预算。启动前先对 e00125 做新 recon，并把 commit 与
host-call 热点拆成可证伪的动态分量；届时由新的 goal 执行
`init-run --base-eval r004/e00125 --C 4 --L 3 --K 2`，本 action 不启动它。
