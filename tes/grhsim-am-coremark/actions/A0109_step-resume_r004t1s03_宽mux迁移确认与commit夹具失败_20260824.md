# A0109 step-resume：r004/t1/s03 宽 mux 迁移确认与 commit 夹具失败（2026-08-24）

对应本轮 `next` = `step-resume`，轨迹 `t1`，step 3/4，pending = `[1, 2]`。
Phi 选择 e00102（Host **171.233s**）与基线 e00085；最新动态证据来自
`build/tes/grhsim-am-coremark/recon/r004-t1-s02/report.md`。c1 占用本 step 唯一迁移席，
把 e00106 已确认的宽 ArrayBroadcast-to-ArrayMux 链融合叠加到 e00102；c2 保持本地
refinement，针对 commit 双峰的 chunk 共享 scratch 生命周期后移清零。

## 候选与结果

| 候选 | eval / commit | 来源 -> 动态病灶 -> 局部改动 -> 可证伪预期 | 正式结果 | 裁决 |
|---|---|---|---|---|
| c1 `--array-broadcast-mux-chain-fuse` | e00113 / `2768258` | e00102 + 迁移源 e00106 -> post-change recon 中 b69157/b69158/b69159 仍占总块 cycles **1.697%** -> 融合相邻、sole-use 的 64-bit lane broadcast/mux 链，只物化尾值 -> Host 较 e00102 至少改善 1% | **166.014s**（166.014/165.651/169.952s，CV 1.43%，单簇、非 noisy），`compile_s=644.5s`；17/17 ctest、三次 `73580/49996` difftest 全过；生产命中 **4 chains / 92 steps**；较父改善 **3.05%** | 越过 r004 3% 确认带；`migration_source=e00106`，winner，outcome=`win`，合入 t1/main |
| c2 `--commit-scratch-lazy-init` | e00114 / `fd68556` | e00102 -> b93159/b93141 占 **9.194%** cycles 且 commit 绝对时间未降 -> 将 oversized commit 的 `arrChgblk` / `wrChgblk` / `detGrpblk` 清零移入事件门 -> 该池降至少 15%、Host 降至少 1% | `ctest_fail`（16/17，`compile_s=233.4s`），未进入生产 emit、difftest 或 Host 计时 | 新 fixture 错误要求当前模型不存在的 `detGrpblk_3` reset；机制性能**未测**，不作性能证伪 |

两个候选的 `tes-candidate.json` 均声明完整生产表型：冻结 12 开关 + t1 父节点的
`--host-call-guard-cache --memory-read-pow2-index` + 各自新开关；`record-eval` 表型审计
通过。两次 evaluator 严格串行，c1 完成全部门和三次绑核计时，c2 在回归门提前停止。

## 裁决与机制分析

- `finish-step` 将 e00113 快移入 `tes/r004/t1/main`。它较父 e00102 快 **5.219s
  （3.05%）**，把 e00106 在 t3 的确认机制迁移到 host-call guard cache + 幂次索引
  基座后再次越过确认带，说明宽 mux 中间宽值物化与 memory-read 索引机械是可加的
  独立 compute 成本。生产 emit 的 4 链/92 steps 与迁移源覆盖一致。
- e00113 取代 e00106 成为全局 best：相对冻结 AM/e00085 改善 **14.16%**，冻结
  gsim/e00086 口径为 **7.307x**。本结果仍只证明整体 Host 可加性；1.697% 池的实际
  post-change 降幅需要下一次 t1 recon 才能核验，不能由整体收益反推。
- e00114 的失败来自候选测试断言而非生产语义或性能结果：fixture 没有 detector group，
  因而不应要求 `detGrpblk_3` reset。协议要求非 interference 的 `ctest_fail` 如实登记，
  本 step 不修改 commit 重跑；未来若 Phi 再选择该方向，须先修正 fixture，再验证
  生产命中和 9.194% commit 池降幅。
- 预算由 28/48 增至 **30/48**。c1 是确认 winner；c2 是失败信息，不把“未测”误记为
  commit scratch 生命周期机制的负证据。

## 后续建议

状态机下一 action 为 `recon`：对 t2 tip e00104 做非计时 profiling。应先核验幂次索引
在 t2 的池级降权及 commit/system-task 替代热点，再设计 t2/s03；本 action 未启动该
recon，也未开始任何后续 action。
