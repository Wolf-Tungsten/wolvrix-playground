# A0082 - r003/t1/s08 mask 缓存与 direct 写回

对应 `next` = `step`，轨迹 `t1`，step 8/8，K=2。Phi 选择 e00080、e00056、
e00071：分别覆盖 active-tile sparse 的幂等写回退、wide-mux chain fuse 起点和
nonzero-level bitmap 正向节点。A0079 的 append-only 勘误确认 e00075/e00076
漏传 `--wide-mux-chain-fuse`，其候选机制当时未进入生产表型；本 step 从 e00080
主线出发，以完整 13 开关表型首次真实评估 mask/value 缓存，并以移除幂等比较作为
互异的写回策略候选。两项评估严格串行。

`begin-step` 首次在 sandbox 内因无权写 submodule Git 元数据而失败；现场无同名分支/
worktree 冲突，受控权限重入后由 `tesctl` 幂等补齐 c1/c2、proposal 和 current_step，
没有手改 `run.json`。起始状态虽显示 evals 32/32，`next` 仍明确给出 t1/s08 step 并
分配 e00083/e00084；本 action 只执行这两个状态机分配的候选，完成后显示 34/32。

## 候选与结果

| 候选 | eval / commit | 来源 -> 病灶 -> 改动 -> 可证伪预期 | 量化结果 | 裁决 |
|---|---|---|---|---|
| c1 `active-mux-mask-cache-live` | e00083 / `b68a06a` | e00080/e00071 -> active-tile sparse 在 union 与 overlay 两次读取非零 selector mask/tval -> union 时紧凑缓存最多 64 项 mask/value，保留 e00080 幂等写 -> 预期较 e00080 至少 -1.5%，低于 0.5% 或回退证伪 | **419.534s**（419.534/419.535/419.530s，CV 0，非 noisy），`compile_s=2063.6s`；17/17 ctest、3 rep difftest 73580/49996；完整 13 开关与生产 `cachedMasks/cachedValues` 命中已审计。较 e00080 名义 +21.53%，loadavg 50.53 | 未达收益门；1 KiB 栈缓存与缓存写流无正向证据 |
| c2 `active-mux-direct-store` | e00084 / `64b2b93` | e00080/e00071 -> 幂等写为每个 base/selector lane 增加目标回读、比较和数据相关分支，e00080 较 e00071 回退 1.56% -> 恢复连续 copy/fill 与直接 sparse store，保留 active-tile sparse 和 single-level direct -> 预期较 e00080 至少 -1.5%，低于 0.5% 或回退证伪 | **378.064s**（378.065/378.064/378.063s，CV 0，非 noisy），`compile_s=2164.5s`；17/17 ctest、3 rep difftest 73580/49996；完整 13 开关与生产 direct store 命中已审计。较 e00083 名义 -9.89%，较 e00080 名义 +9.52%，loadavg 11.58 | raw-score winner，入 `t1/main`；跨窗未确认达到父节点收益门 |

## 裁决与机制分析

- 两候选机制互异：c1 改 selector/tval 的读取与暂存策略，c2 改 target base/overlay 的
  写回策略。两者都继承 e00080 的 fuse + zero-tile + active-tile sparse 完整表型，
  不以空提交、原样重测或固定对照占用席位。
- c1 的 64 项 mask/value 数组形成约 1 KiB 栈框，并在 union 时增加缓存写流。虽然它
  消除了 overlay 的指针数组重读，生产 Host 没有正向信号；这与 A0076 的“机制未启用”
  勘误区分开，本次才是该形态的有效生产评估。
- c2/e00083 = **0.9011x**，raw score 明显胜出，但两次起跑 loadavg 为 11.58 vs
  50.53，不能把 9.89% 全归因于 direct store。相对 e00080（345.215s，loadavg 3.18）
  和 e00071（339.910s，loadavg 1.92），c2 仍名义慢 9.52%/11.23%；因此稳健结论是
  direct store 在本 step 机械胜出，未确认相对父节点的一阶收益。
- 两项均在 2400s 编译预算内，但只余 236-336s；wide-mux helper 继续扩张已经接近
  编译门。mask 栈缓存、target 幂等比较、静态 selector 共享度和 base lane 比例均不能
  再作为收益代理，重开前需要 helper 动态 Host 权重或 target 实际变化率直接证据。

## winner 与后续建议

`tes/r003/t1/main` 已快移到 e00084 commit `64b2b93`；t0/t1 均完成 8/8。
历史 t1 best 仍为 e00056 **241.956s**，全局 best 仍为 e00057 **229.429s**，
gsim 基线为 **45.864s**。

对后续的建议：run-summary 应把 r003 的跨批快慢态作为主要测量风险，按轨迹报告
机械 tip 与历史 best，不把跨 loadavg 百分比解释为纯机制收益；restart 前优先解决
进程态分簇/同窗锚定。状态机下一 action 是 `run-summary`；本 action 不启动它。
