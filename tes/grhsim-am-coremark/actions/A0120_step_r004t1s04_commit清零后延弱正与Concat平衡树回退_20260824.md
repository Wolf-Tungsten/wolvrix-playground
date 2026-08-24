# A0120 step：r004/t1/s04 commit 清零后延弱正与 Concat 平衡树回退（2026-08-24）

对应当前 `next` = `step`，轨迹 `t1`，step 4/4，K=2。Phi 选择 e00113（Host
**166.014s**）与 e00089；最新动态证据来自
`build/tes/grhsim-am-coremark/recon/r004-t1-s02/report.md`（基于 e00102）。该 recon
中 b93159/b93141 commit 双峰占总 block cycles **9.194%**，b83835/b93085 compute
池占 **2.522%**。两个候选都从 t1 当前三机制 tip 出发，不使用迁移席位，分别处理
commit scratch 生命周期与标量 Concat 数据流。

## 候选与结果

| 候选 | eval / commit | 来源 -> 动态病灶 -> 局部改动 -> 可证伪预期 | 正式结果 | 裁决 |
|---|---|---|---|---|
| c1 `--commit-scratch-lazy-init` 夹具修正后组合 | e00125 / `2420901` | e00113 + e00114 回归反馈 -> b93159/b93141 占 **9.194%**，e00114 仅因 fixture 错要不存在的 `detGrpblk_3` reset 而未测 -> 修正夹具并将 chunked commit scratch 清零后移到事件门内，同时保留 guard cache、幂次索引和宽 mux 融合 -> Host 较 e00113 至少改善 1% | **164.729s**（164.729/164.376/167.388s，CV 0.99%，单簇、非 noisy），`compile_s=642.8s`；17/17 ctest、三次 `73580/49996` difftest 全过 | 较父改善 **0.77%**，未达 1% 预期且低于 3% 确认带；raw winner，outcome=`neutral` |
| c2 `--concat-position-pack` 平衡单表达式 | e00126 / `74e1a3c` | e00113 + e00090 -> b83835/b93085 占 **2.522%**；e00090 命中 699,997 个最终位置 term 但仍发射显式 accumulator RMW -> 将 term 组织为平衡 OR 树并一次 const 赋值 -> Host 至少改善 0.5% | **168.646s**（168.646/166.046/169.913s，CV 1.17%，单簇、非 noisy），`compile_s=575.3s`；17/17 ctest、三次 `73580/49996` difftest 全过 | 较父回退 **1.59%**，未达预期；平衡表达式策略证伪，不合入 |

两个正式终态均以冻结 12 项表型加父节点的
`--host-call-guard-cache --memory-read-pow2-index --array-broadcast-mux-chain-fuse`，
再分别增加自己的候选开关；`tes-candidate.json` 与 `result.json.emit_args` 通过硬审计。
评估严格串行，e00125 登记并释放全局锁后才启动 e00126。

## 恢复说明

- c1 在实施时直接修正 e00114 已知的错误 fixture：模型没有 detector group，不能要求
  `detGrpblk_3` 清零。正式 e00125 一次通过全部门，没有把 e00114 的历史失败重记为
  当前候选失败。
- c2 的前两次 e00126 均在 ctest 门停止，未进入生产 emit、difftest 或 Host 计时：
  第一次文本断言仍要求每个最终 shift 后立刻有分号，第二次把 operand 的 `<< 32`
  与 32-bit mask 内的 `UINT64_C(1) << 32` 同时计数。两次都只修正形态夹具，不改
  机制；随后以同一 eval-id 从完整流水线重跑。ledger 只登记最终全门通过结果。

## 裁决与机制分析

- `finish-step` 按 raw score 选择 e00125，并将 `2420901` 快移到
  `tes/r004/t1/main`。它比 e00126 快 **3.917s（2.32%）**，但相对父 e00113 仅快
  **1.285s（0.77%）**，因此 outcome=`neutral`。e00125 以 **164.729s** 刷新 raw
  `best_overall`；t1 的统计确认 best 仍是 e00113 **166.014s**，不能把本次弱正升级
  为确认收益。
- lazy scratch 在 t4/e00107 曾给 1.84% 弱正，在 t2/e00116 回退 0.36%，本次组合为
  0.77% 弱正；三种基座都没有越过 3% 带。修正夹具证明其功能与三机制 tip 可组合，
  但“静默轮清零”不是 9.194% commit 双峰的一阶主成本。后续不再以清零位置细化该池。
- c2 确实把最终位置 term 收敛为单个平衡 OR 表达式，功能门逐位一致，但整体回退
  1.59%。e00090 的逐条 `|=` 版本本就只有 0.98% 弱信号；进一步消除源码 accumulator
  没有兑现，说明 O3 已能处理原链，或更大的表达式树带来前端、寄存器分配或代码布局
  成本。标量 Concat 语法形态轴关闭。
- e00125 相对冻结 AM/e00085 改善 **14.83%**，冻结 gsim/e00086 口径仍为
  **7.250x**，目标差距仍大。预算由 40/48 增至 **42/48**。

## 对下一步的建议

t1 已完成 4/4。剩余轨迹若继续处理 commit 双峰，应先取得清零、逐 flag 访问、尾部
fanout 的动态分量，设计生产者与消费者联合的 word-at-a-time 批处理；不再重试 scratch
清零位置、仅容器位压缩或标量 Concat 源码重排。状态机下一 action 为
**r004/t2/s04 step（K=2）**；本 action 只作预告，未启动下一 step。
