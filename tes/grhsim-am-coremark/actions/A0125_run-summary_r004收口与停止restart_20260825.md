# A0125 run-summary：r004 收口与停止 restart 建议（2026-08-25）

对应 `next` = `run-summary`（全部 6 条轨迹已达 L=4 步）。本 action 无评估开销。

## 做了什么

汇总 r004 台账 e00085-e00134、24 个 step、3 个 round-summary 与 12 次 recon，写
[runs/r004/summary.md](../runs/r004/summary.md)（分数曲线、机制族裁决、测量口径和
restart 建议），并更新 insights.md 与两处 README。随后仅执行本 action 的
`close-run`、`action-done` 和 playground 提交，不初始化新 run。

## 量化结果

- C=6/L=4/K=2，24/24 步走满；候选 48/48，总 eval 50（含双基线）。42 个候选
  `ok`，4 个 `ctest_fail`、1 个 `difftest_fail`、1 个 `emit_fail`；全部 ok 候选
  通过 17/17 ctest 与三次 difftest，且均 unimodal、non-noisy。
- AM y0 e00085 = **193.403s**，gsim e00086 = **22.720s**，起跑差距 8.512x。
- raw best_overall = t1/e00125 **164.729s**，commit `2420901f8343`；较 AM y0
  改善 **14.83%**，但仍为 gsim 的 **7.250x**，目标未达成。3% 裁决带下的确认
  best 为 e00113 **166.014s**；e00125 相对它仅弱正 0.77%。
- 六条轨迹确认 best 分别为 t0/e00100 172.832s、t1/e00113 166.014s、
  t2/e00104 169.577s、t3/e00106 166.947s、t4/e00131 166.837s、
  t5/e00110 173.058s。

## 裁决与机制分析

- 幂次 memory-read 索引是唯一稳定的一阶机制：原始轨迹与四次迁移相对父节点改善
  8.95%-10.27%，recon 同时确认六个热块 cycles 下降 93.08%-94.67%。
- 宽 mux 的 4-chain/92-step 融合在 e00113/e00131 两个基座分别给出 3.05%/3.91%
  确认增量，但其他基座只有 1.31%-2.81%，确认结论限于完整组合实测。
- commit 与 host-call 表面微调大多落在 neutral 或回退区；第四轮除 e00131 外没有
  新确认收益。后续若扩大机制范围，必须先动态拆分 commit 的清零/scan/call/DPI 和
  host-call 的参数准备/格式化成本，再设计联合批处理或调度级 pass。
- round 2 重锚的 AM 194.019s 与冻结值一致，gsim 24.226s 则漂移 +6.63%；冻结裁决
  口径保持不变。即使用重锚 target，e00125 仍为 6.800x，不影响目标未达成判断。

## restart 裁决

**当前不建议 restart，也不在本 action 自动执行。** `restart.max=3` 已耗尽且
`auto=false`，剩余 7.250x 差距远超当前局部候选的效应量。run 收口后停止，等待用户
决定结束搜索，或另行批准 restart 预算和更大粒度的 AM pass/调度改写。

若用户之后明确批准，候选 y0 = `r004/e00125`，commit
`2420901f8343cfc5c407af92d7f0ec5a97cd5566`，完整 16 项 emit 表型按 ledger 冻结；
建议 **C=4/L=3/K=2（N=24）**，并以前置 e00125 recon 的动态分解约束候选。
届时由新的 goal 执行 init-run，本 action 不启动下一 action。
