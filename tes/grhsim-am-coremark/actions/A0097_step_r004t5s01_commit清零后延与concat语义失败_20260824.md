# A0097 step：r004/t5/s01 commit 清零后延与 Concat 语义失败（2026-08-24）

类型：step。run：**r004**；轨迹：**t5**；step：**s01**；K=2；来源 Phi 节点：
**e00085**。两个候选只使用 A0096 的 t5/e00085 recon 动态证据，没有引用其他轨迹
结果或使用迁移席位。

## 候选与结果

| 候选 | 来源病灶与可证伪假设 | commit / 表型 | 正式结果 | 裁决 |
|---|---|---|---|---|
| c1 / e00097 `--commit-scratch-after-gate` | b93159/b93141 合计占总块 cycles **8.421%**；chunked commit Block 的 write/array/detector scratch 只在合并事件门命中后清零，预期该池降至少 15%、Host 降至少 1% | `64f6a5fd7216`；完整 12 项冻结表型 + 候选开关 | **191.116s**（191.253/187.011/191.116s，CV 1.27%，单簇、非 noisy），`compile_s=573.7s`；17/17 ctest，3 rep difftest 均为 `73580/49996` | 较 e00085 **改善 1.18%**，达到 Host 下限但未越 3% 确认带；唯一 ok、raw-score winner，outcome=`initial` 入 t5/main |
| c2 / e00098 `--concat-position-pack` | b83835/b93085 合计占总块 cycles **2.325%**，含密集 scalar `concat_value` 前缀链；按最终位位置直接掩码/shift/OR，预期该池降至少 20%、Host 降至少 0.5% | `fa77e39c0e32`；完整 12 项冻结表型 + 候选开关 | **difftest_fail**；`compile_s=641.2s`、17/17 ctest 通过，但首 rep 在 guest cycle 2 触发 OldestArbiter `priorityRegVec` 非 one-hot，`instrCnt/cycleCnt=0/0` | 功能门一票否决，无 score，不进入 t5/main |

两次正式评估严格串行，只通过任务 evaluator 完成。c1 第一次调用未显式传新增 emit
参数，产生了基线表型的 191.270s 无效测量；`record-eval` 表型审计拒绝登记。随后以同一
eval-id、完整 13 项声明表型覆盖重跑并登记上表 191.116s，未登记的测量不作为机制证据。
c2 从首次调用起即显式传完整表型。

## 机制分析

c1 保留 gate-head detector 的无条件执行，只把三个大型 bool scratch 数组从 Block
入口的零初始化改为 gate 内固定大小 `__builtin_memset`。gate-head chunk 不读写这些
数组；事件触发时仍在任何 commit chunk 之前恢复零初态。完整 difftest 说明该局部
时序保持语义，1.18% Host 改善也达到预注册下限；但小于 r004 的 3% adjudication
带，且没有 post-change recon，不能宣称 8.421% 热点池已下降 15%。它是弱正的初始
节点，不是已确认的一阶收益。

c2 的失败来自实现语义错误，而不是噪声或计时异常。原 `concat_value` 按 operand
序列逐次把既有前缀左移再加入新 operand；候选却把首 operand 放在低位，错误地把
operand 顺序解释为低位到高位。启动后大量 one-hot 断言立即失败，证明直接位置装配
必须按总宽度递减计算最终 offset。该候选不修补、不重跑；若未来 Phi 再选此邻域，
应先用多 operand、非对称位型的 emitter/runtime fixture 证明位序，再占用新席位。

## 裁决与后续建议

`finish-step` 选择 e00097，并将 `64f6a5f` 快移到 `tes/r004/t5/main`。t5 首节点
Host/gsim = **8.412x**；全局 best 仍是 t3/e00093 **172.530s**（7.594x），预算由
12/48 增至 **14/48**。第一轮六条轨迹已齐平。

下一 action 是第 1 轮 **round-summary**。届时应跨轨迹比较六个 s01 winner，并把
c1 的 scratch 后延弱正与 t2 同病灶证据、t3 的已确认幂次索引收益分开定级；本 action
只预告，不启动 round-summary。
