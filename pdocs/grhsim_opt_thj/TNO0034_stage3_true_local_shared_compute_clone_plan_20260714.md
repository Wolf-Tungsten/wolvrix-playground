# TNO0034 Stage 3 true local shared compute clone plan

记录日期：2026-07-14

状态：启动 Stage 3；在 current-default NO0300、fixed-ASLR 基线上实现 bounded true local-shared-compute cloning，目标是用极少量便宜组合计算复制减少跨 compute node 的 boundary activation edge。本文只定义实现契约、门禁与停止条件，不预写结构或性能收益。

## 1. 基线与历史边界

唯一基线固定为父仓 `33e7d3c`、Wolvrix `0204c1e` 的默认生成配置：

```text
NO0300
ASLR disabled / fixed-ASLR
post_dp_refine_policy=off
kahn_level_pack_policy=off
enable_local_shared_compute=false
```

[NO0086](../grhsim_opt/NO0086_grhsim_runtime_aware_coarsen_ordering_experiments_20260511.md) 曾启用旧 `local_shared_compute` 吸收模型，把共享 def 重新归属到 consumer node，最终使 SimTop compute-node DAG 出环；增加“不依赖其他 compute op” guard 后仍失败。该方案已经停止，本阶段不得恢复。

本阶段采用真正的 graph clone：保留原 op/value 与 ownership，新建语义相同的 op/value，只把一个远端 consumer node 中的 uses 改到 clone。候选必须在 mutation 后重新 freeze、重建 topo/op class/compute rewrite，不能手工修改旧 compute-node DAG 或 canonical value map。

## 2. 插入点与事务边界

计划流程：

```text
source clone + refreeze
  -> baseline buildComputeNodeRewrite
  -> discover/validate bounded local clone plan
  -> create cloned op/value + replace one consumer-node uses
  -> refreeze
  -> rebuild ActivityOpData / op classes / compute rewrite from scratch
  -> export/materialize unchanged activity schedule pipeline
```

关闭 feature 时不进入发现、mutation 或二次 rebuild，default 与显式 `false` 必须保持完整 session identity。

开启 feature 后若 clone/rewrite/topology/cap 任一验证失败，pass 必须失败并给出诊断，不能继续使用 stale baseline rewrite。Graph mutation API 只使用正式 `createOperation/createValue/addOperand/addResult/replaceOperand/setAttr` 等接口；在新增 op/value 前复制所有需要的 operands、attrs 和 source location，避免持有 mutation 后失效的 span。

## 3. 首版保守资格

首版只考虑同时满足以下条件的 source op：

- class 为 compute，单结果，结果是 `Logic`，width 在 `1..64`；
- 结果不是 declared value、graph output/inout、sink/commit 输入，也没有任何非 compute semantic user；
- 恰好有两个 distinct compute user op，且分属两个不同 compute node；保留原 op 服务其当前 owner/consumer，只为另一个 consumer node 建一个 clone；
- op 无 `hasSideEffects`，不属于 storage/read/write、intent、system/DPI、instance/blackbox/XMR；
- kind 使用显式 cheap-pure whitelist，包括 assign、bit/logical、compare、reduce、shift、mux、concat/replicate/slice、add/sub；首版排除 mul/div/mod 和不明确 operation；
- clone 的所有 operands 对目标 consumer node 已是 local 或既有 boundary，不能因复制引入新的 compute-node dependency；
- clone 吸收后目标 compute node 不超过 `maxOpInComputeNode`，且不能进入 indivisible/intent node。

所有 uses 在 discovery 时按 `(consumer node, user topo position, operand index)` 稳定排序；只改目标 consumer node 内匹配原 value 的 operands。原 op/value 不删除、不改 declared/canonical 身份。

## 4. 预算与诊断

计划新增或收紧显式参数：

| Option | Planned default | 含义 |
| --- | ---: | --- |
| `enableLocalSharedCompute` | `false` | feature 总开关 |
| `localSharedComputeMaxFanout` | `2` | 按 distinct compute user op 计数，首版只允许两个且分属两个 node |
| `localSharedComputeMaxWidth` | `64` | 首版结果位宽上限 |
| `localSharedComputeMaxClones` | `4096` | graph clone 硬上限 |
| `localSharedComputeMaxClonedOpPpm` | `5000` | clone 数不超过 baseline compute ops 的 `0.5%` |

实现日志与 summary stats 至少记录 eligible、planned、applied clones、rewritten uses、cloned ops ppm，以及 width/fanout/kind/declared/noncompute-user/operand-locality/cap/intent/budget 各类 reject 数。结构对照必须同时报告 graph ops/values、compute/commit SN、BAE、DAG、boundary values、code size，不能只报告 BAE。

## 5. Correctness 与 SimTop gate

focused tests 至少覆盖：

- unspecified 与 explicit `false` 完整 schedule identity；
- 一个 cheap shared op 的 true clone、目标 uses 重写、原 uses 保留，clone op/value attrs/type/source location 一致；
- max clones 与 cloned-op ppm 为零时 identity；
- width、fanout、declared/output、non-compute user、side effect、expensive/unknown kind、operand locality、cap、intent guard；
- repeated run deterministic，第二次 activity-schedule 不应继续 clone 已本地化结果；
- refreeze/rebuild 后 topo、compute-to-commit fanout、cap、coverage 与 full schedule shape 成立；
- 与 Stage 1/Stage 2 显式开启时不破坏 exact recount。

SimTop standalone 首轮保持 Stage 1/2 为 `off`，从 fresh current-default checkpoint 做 structure scan。只要功能/结构不明显失败，即使 BAE/DAG 有轻微退化也继续 fresh emit/O3 build 和 fixed-ASLR 100、10k、50k；正式性能仍使用同 CPU/NUMA quiet `control / candidate / control`、双 sibling idle `>=99%`、五事件 `100% scheduled`。

同时直接比较 current-default 与 candidate 的 generated sched C++、compute function/TU 数、ELF `.text` 和五事件，判断复制节省的 boundary work 是否被重复计算或代码布局抵消。

## 6. Stop 与提交条件

满足任一条件停止或收紧本阶段候选：

- true-clone 语义、default-off identity、topology、cap、intent、commit remap 或 final recount 不闭合；
- clone 数/graph ops/code size 无界增长，或 activity-schedule/build 成本显著超过预算；
- 结构明显退化超过 `10%` 且没有可解释反向收益；
- fixed-ASLR quiet 50k 稳定回退超过 `max(1%, baseline spread)`；
- 候选机会太少，不足以改变 SimTop 静态或动态工作。

阶段完成后先提交 Wolvrix 子模块，再由父仓提交子模块指针、XS 参数与增量文档。没有可信 50k 正收益时，`enableLocalSharedCompute` 必须继续默认 `false`。
