# A0091 step：r004/t2/s01 scratch 后延与 host 谓词 run（2026-08-23）

对应 `next` = `step-resume`，轨迹 `t2`，step 1/4，K=2。`begin-step` 与 c1/e00091
已在恢复前完成；本次只补做 pending `[2]`，没有重复 begin-step、没有重跑已登记候选，
也没有手改 `run.json`。Phi 唯一来源为 r004 AM 基线 e00085（commit `1563c3d837fc`，
Host **193.403s**，完整 12 开关表型）。两项候选分别处理 A0090 recon 的 commit
scratch 主峰与 host-call compute 双峰，机制互异。

## 候选与结果

| 候选 | eval / commit | 来源 -> 动态病灶 -> 局部改动 -> 可证伪预期 | 正式结果 | 裁决 |
|---|---|---|---|---|
| c1 `--commit-scratch-after-gate` | e00091 / `8b4fe80` | e00085 -> b93159/b93141 各执行约 10 万次、合计占总块 cycles **8.599%**，事件前缀前无条件清零 2,742/4,227 个 scratch flag -> 前缀 chunk 只携带活跃的 `byteFlags`，把其余数组声明与清零延后到合并事件门内 -> 双峰至少下降 15%、Host 至少下降 1%，Host 低于 0.5% 则证伪 | **189.045s**（189.045/188.787/192.212s，CV 1.00%，单簇、非 noisy），`compile_s=640.9s`；17/17 ctest，3 rep difftest 均为 73580/49996；较 e00085 名义 **-2.25%** | 整体 Host 预期通过，但未越 3% 确认门；无 post-change recon，15% 池级预期尚未验证 |
| c2 `--host-call-predicate-run` | e00092 / `83c9e18` | e00085 -> b90656/b90657 执行 88,260/100,791 次、合计占总块 cycles **4.574%**，相邻 outlined fwrite/DPI 调用重复完全相同的 fire/event 谓词 -> 把每段精确同谓词 run 融合到单一分支，保持 pending/once/final 与参数物化语义 -> 双峰至少下降 20%、Host 至少下降 1%，Host 低于 0.5% 则证伪 | **188.662s**（188.662/187.240/190.890s，CV 0.97%，单簇、非 noisy），`compile_s=648.1s`；17/17 ctest，3 rep difftest 均为 73580/49996；较 e00085 名义 **-2.45%**，同窗较 c1 **-0.20%** | raw-score winner；`finish-step` outcome=`initial`，未越 3% 门；20% 池级预期尚未验证 |

两个 `tes-candidate.json` 都声明相对冻结父表型的单一增量；正式 evaluator 显式传入
12 项父开关再追加候选开关，两个 `result.json.emit_args` 均与声明逐项一致。生产
engagement 核对显示 c1 的 b93159/b93141 前缀 chunk 已只接收 `byteFlags`，并分别把
2,742/4,227 个 scratch flag 的清零移入事件门；c2 形成 **6,314** 个精确同谓词 run，
覆盖 **12,827** 个 host-call 成员，b90656/b90657 所在生成 chunk 均有命中。

## 裁决与机制分析

- 两次正式评估严格串行且只通过任务 evaluator；每项均完成全量构建、17 项回归、
  金标 difftest 和绑核 3 rep。两项都超过各自预注册的整体 Host 1% 门，但都没有越过
  r004 的 3% adjudication noise，不能据此确认相对 e00085 的因果收益。
- e00092 相对 e00091 只快 **0.20%**，远低于 3% 分辨率。两个候选修改的是不同热点池，
  raw 排名不能证明 host predicate run 优于 scratch 后延，也不能把两项效果相加。
- c1 已证明预期发射表型在生产模型中成立，但是否让 b93159/b93141 合计权重下降至少
  15% 仍缺 post-change recon；c2 同理，静态覆盖 6,314 个 run 不能替代 b90656/b90657
  池下降至少 20% 的动态证据。两项目前都只记弱正向信号。
- `finish-step` 按 raw score 将 e00092 快移到 `tes/r004/t2/main`，作为 t2 的首个
  `initial` 节点，并刷新 ledger `best_overall`。当前 AM/gsim =
  **188.662/22.720 = 8.304x**，预算 8/48；这不是 `outcome=win`，目标仍远未达到。

## 后续建议

t2 再次到期时先对 e00092 做新 recon，检查 b90656/b90657 是否降权；若双峰没有达到
预注册的 20% 降幅，则关闭当前 predicate-run 形态。c1 的 b93159/b93141 也只有在可比
画像中下降至少 15% 才能确认 scratch 后延命中预期。在此之前不把 e00092 当作已确认
migration source，也不沿 0.20% raw 差值继续语法级精修。状态机下一 action 为
**t3/e00085 recon**（非计时 profiling）；本 action 只预告，不启动它。
