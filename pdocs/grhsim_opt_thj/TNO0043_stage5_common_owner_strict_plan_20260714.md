# TNO0043 Stage 5 common-owner strict plan

记录日期：2026-07-14

状态：启动 Stage 5；基于 [TNO0042](./TNO0042_stage4_simtop_common_owner_probe_20260714.md) 的 691 个单项上界，实现 conflict-aware common-owner strict true clone，并保持 Stage 3 local-owner clone 关闭以隔离变量。

## 1. 独立配置与预算

`localSharedComputeCommonOwnerPolicy` 扩展为：

```text
off / probe / strict
```

common-owner 使用独立预算：

| Option | Default | 含义 |
| --- | ---: | --- |
| `localSharedComputeCommonOwnerMaxClones` | `4096` | common-owner clone hard limit |
| `localSharedComputeCommonOwnerMaxClonedOpPpm` | `5000` | 相对 baseline compute ops 的 PPM limit |

Stage 5 SimTop 显式配置：

```text
enable_local_shared_compute=true
local_shared_compute_max_clones=0
local_shared_compute_common_owner_policy=strict
local_shared_compute_common_owner_max_clones=4096
local_shared_compute_common_owner_max_cloned_op_ppm=5000
post_dp_refine_policy=off
kahn_level_pack_policy=off
```

strict 要求总开关为 true 且现有 local-owner `maxClones=0`；不满足时直接诊断失败。这样结果只包含 common-owner clone，不混入 [TNO0039](./TNO0039_stage3_quiet_aba_and_default_decision_20260714.md) 已判 neutral 的 108 个 local-owner candidate。

## 2. Candidate 与稳定选择

raw candidate 必须通过 Stage 4 exact gate：cheap pure、single Logic result、exactly two distinct compute user/two node、source 为第三个 singleton common node、result 是两侧 exact boundary、三节点非 intent/indivisible、所有 source operands 对两侧均 local/existing-boundary、两侧单项 cap 成立。

稳定排序优先级：

```text
estimated op cost
operand total bits
result width
source topo position / op id
retained / clone target stable key
```

较早 target 保留 original，较晚 target 改用 clone。selection 必须在 mutation 前处理：

- clone hard/PPM budget；
- 两个 target 分别累计预留 `+1` cap；common source node 的预计删除不抵扣；
- selected source node 不得作为任何 selected target，反向亦然；
- candidate source op 不得是已选 user op，candidate user op 不得是已选 source op；
- source/target role 或直接依赖冲突稳定 reject。

691 是上述冲突处理前上界，selected 数可能更低。

## 3. Transaction 与验证

所有 selected candidate 先 deep-copy kind、operands、attrs、op/result srcLoc、result width/signed/type 和两组 exact uses；任何 mutation 后不得再读取旧 span。每次 replace 前确认 `(user, operandIndex)` 仍指向 source value。

每个 candidate 只创建一个 clone op/value，改写 later target 的全部 exact uses；original 保留给 earlier target。apply 后统一 refreeze并从头重建 op data/classes/compute rewrite，禁止改 baseline node/DAG 或 canonical map。

除 Stage 3 validator 外，strict 还要验证：

- graph op/value 增量都精确等于 selected clone 数；
- original/clone result user 集分别等于 retained/rewritten plan；
- clone kind/operands/attrs/result metadata 与 snapshot 一致；
- original/clone 分别与两个 consumer local，result 不再跨 compute node；
- commit ops/inputs、intent map、cycle split、cap、topology 与 final schedule coverage闭合。

## 4. Tests 与 SimTop

focused tests覆盖 strict positive、zero hard/PPM budget、共享 target累计 cap、source-target role/依赖冲突、重复确定性、metadata/users/no-cross-fanout、invalid option组合、probe/off identity和Kahn/post-DP shape。

SimTop 先 stop-after-activity-schedule，报告 raw/selected/reject、graph ops/values、SN、BAE、DAG、boundary values与耗时。只要没有明显功能/结构失败，即使 selected 数或 BAE 收益较小也继续 full emit/O3、fixed-ASLR 100/10k/50k；最终仍由 atomic quiet A/B/A 裁决，默认保持 off 直到超过可信线。

阶段完成后先提交 Wolvrix，再提交父仓指针、XS options和增量文档。

## 5. 增量修正：冲突测试口径

实现 review 证明，在首版 `singleton common owner + exactly two user ops/two nodes + 双边 operand locality` 的严格资格下，selected source op 与另一 candidate user op、source node 与另一 target node 的直接角色冲突在合法 GRH 上结构不可达。实现仍保留 node/op role guards，作为未来放宽资格时的纵深保护；focused tests 不通过内部 hook 强造不可达状态。

因此 §4 的测试口径修正为：实际覆盖 zero budget、共享 target累计 cap、determinism、metadata/users/no-cross-fanout、invalid配置和Kahn/post-DP shape；role/dependency guard 由代码 review 与 SimTop计数 sanity 验证，不声称已有独立可达 fixture。
