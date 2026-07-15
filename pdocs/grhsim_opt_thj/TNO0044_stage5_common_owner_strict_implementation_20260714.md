# TNO0044 Stage 5 common-owner strict implementation

记录日期：2026-07-14

状态：Stage 5 conflict-aware common-owner strict true clone 已实现；focused build/tests、Python/XS runtime binding、diff-check 与独立 review 通过，进入 standalone SimTop structure scan。

## 1. Options 与隔离

`localSharedComputeCommonOwnerPolicy` 现支持 `off / probe / strict`。新增独立预算：

```text
localSharedComputeCommonOwnerMaxClones = 4096
localSharedComputeCommonOwnerMaxClonedOpPpm = 5000
```

CLI/Python 分别为：

```text
-local-shared-compute-common-owner-max-clones
local_shared_compute_common_owner_max_clones

-local-shared-compute-common-owner-max-cloned-op-ppm
local_shared_compute_common_owner_max_cloned_op_ppm
```

XS 环境变量使用同名大写前缀。strict 入口强制 `enableLocalSharedCompute=true` 且普通 local-owner `maxClones=0`；否则 pass 失败。strict 分支显式跳过 Stage 3 local-owner apply，保持 standalone变量。

common PPM 以 baseline compute ops 为分母，乘法有 overflow保护；PPM限制 `<=1,000,000`。editable `.venv` 已重装，runtime kwargs smoke 产生完整 strict参数。

## 2. Candidate selection

strict 与 Stage 4 probe 调用同一 exact candidate函数。每个 candidate记录 source op/value/node、两组 exact uses、两个 consumer node、estimated cost、operand bits、result width与source topo位置。

稳定排序：

```text
estimated cost
operand bits
result width
source topo position
source op id
ordered target node keys
```

在 mutation 前完成 selection：

- 独立 clone hard/PPM limit；
- 两个 target 分别累计预留一个 op；
- selected source node不能成为 target，target不能是selected source node；
- selected source/user op role互斥；
- 较早 target保留 original，较晚 target使用 clone。

选中后立即 deep-copy source kind/operands/attrs/op+result srcLoc、result width/signed/type和两组 exact uses。所有 plan snapshot 完成后才进入 mutation。

## 3. Apply 与 full validation

每个 plan 创建一个 internal op/value；逐 use replace 前重新检查 operand index仍指向 source value，stale即失败。clone不进入 source canonical map。

统一 apply 后 refreeze并从头重建 op data/classes/compute rewrite。共享 validator先验证 commit partition、intent map、cycle-split不增、owner locality和compute-node cap；common validator再验证：

- graph op/value增量精确等于 applied数；
- original/clone kind、operands、attrs、op/result srcLoc、width/signed/type与snapshot一致；
- original/clone result的 exact user set与plan一致；
- compute topo是完整 permutation且每条DAG edge向前。

日志报告 raw/selected/applied/limit、budget/cap/role/dependency/stale rejects、projected pairs、validated localized pairs和graph ops/values before/after/delta。localized pairs是compute-node owner验证后的 `2*N`，不是最终 supernode BAE delta；最终结构仍只看stats recount。

## 4. Tests 与 review

focused target重编PASS，`transform-activity-schedule 1/1 PASS`（约 `0.04..0.13 s`）。覆盖：

- strict singleton positive、metadata/exact users、original/clone分别local且result无跨supernode fanout；
- hard/PPM zero budget；
- shared target累计 cap；
- repeated deterministic schedule；
- invalid policy、PPM与strict/local-owner混用诊断；
- Kahn/post-DP同时启用后的完整shape。

两仓 `diff --check` 与Python `py_compile`通过。独立最终review无P0/P1。

## 5. Residual risk

role/dependency guards在当前严格资格下结构不可达，未用内部测试hook伪造；计数在SimTop应为0。`actual_localized_pairs`在compute-node rebuild后统计；若非SimTop配置把oversize split阈值设得低于compute-node cap，后续split可能再次分开producer/user，因此该字段不应替代final BAE。当前SimTop两项均为108且candidate双边预留cap，不受此项影响。

canonical map不变由构造保证：strict不写map，两次rewrite接收同一个map；validator未额外复制比较。后续若重构canonical逻辑，需要补显式断言。
