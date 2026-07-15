# TNO0041 Stage 4 common-owner probe implementation

记录日期：2026-07-14

状态：Stage 4 no-mutation probe 已实现；C++ option/CLI/Python/XS wiring、focused correctness、editable runtime smoke 与独立只读 review 通过，进入 SimTop opportunity scan。

## 1. Option 与入口

新增：

| Layer | Name | Default |
| --- | --- | --- |
| C++ | `localSharedComputeCommonOwnerPolicy` | `off` |
| CLI | `-local-shared-compute-common-owner-policy` | `off` |
| Python | `local_shared_compute_common_owner_policy` | unset/off |
| XS env | `WOLVRIX_XS_GRHSIM_LOCAL_SHARED_COMPUTE_COMMON_OWNER_POLICY` | `off` |

当前只接受 `off / probe`，invalid policy 在 pass 入口报错。Python/XS 参数 smoke：

```text
['-local-shared-compute-common-owner-policy', 'probe',
 '-local-shared-compute-max-clones', '0',
 '-enable-local-shared-compute', 'true']
```

`.venv` 已重新 editable install，父脚本同时打印 common-owner policy 并透传到 activity-schedule kwargs。

## 2. 只读实现边界

probe helper 的 graph、op classes、op data 与 baseline rewrite 参数全部为 `const`。唯一调用点位于第一次完整 compute rewrite 之后、现有 conservative clone apply 之前；输出只进入局部 stats 和 info log。

probe diff 不包含 `createOperation/createValue/replaceOperand/freeze`、session store、summary schema 或 `graphChanged` 写入。`off` 不进入 helper；`probe + maxClones=0` 时 conservative clone scanner 即使发现机会也不 apply，最终不触发二次 rebuild。

## 3. 统计漏斗

扫描复用 Stage 3 的 cheap-pure、single Logic result、width、declared/port、side-effect/intent attribute 与 distinct user fanout基础 guard，并记录：

- 首层 `scanned` 与 kind/shape/width/side-effect/declared/intent/pre-user rejects；
- valid users 下 consumer-node count `0/1/2/>2`，以及 exactly-two distinct user op；
- source owner invalid / is consumer / third common / third non-common；
- third common singleton/multi-op 与 source/left/right intent-or-indivisible；
- result 是否同时为 A/B exact boundary input；
- 每个 source operand 对 A/B 是否 local 或 exact existing boundary，分 `both/left/right/neither`；
- A/B 分别增加一个 op 后的 cap，分 `both-pass/left-fail/right-fail/both-fail`；
- exact eligible、projected removed pairs、kind/result-width/operand-bits/left-right headroom buckets。

独立 review 对漏斗逐层复核：各分支互斥且闭合，complexity 近似线性于 topo ops 与 value users，没有 candidate pair 笛卡尔展开。

## 4. Focused correctness

`transform-activity-schedule` `1/1 PASS`，约 `0.04..0.06 s`。测试覆盖：

- default、显式 off 与 probe 的 graph connectivity/size、session size、全部 schedule 字段及 raw summary identity；
- singleton third-common positive：`exactEligible=1`、`projectedRemovedPairs=2`；
- multi-op common owner、non-common consumer-owner、双边 locality 与双边 cap reject；
- invalid policy。

父/子仓 `git diff --check`、Python AST 与 `py_compile` 均通过；独立 review 无 P0/P1。

## 5. 口径限制

`exact_eligible` 是逐 candidate 的 opportunity upper bound。probe 尚未做：

- 多 candidate 共享 target 时的累计 headroom；
- source node 与 target node 角色冲突；
- candidate 直接依赖冲突；
- hard clone/PPM budget 后的稳定 selection。

因此 SimTop probe 只能回答“有多少严格单项候选及其形态”，不能把全部 exact eligible 直接写成 strict 可应用数。只有机会量成立后，Stage 5 selection 才处理冲突、预算、snapshot/mutation 和 full rebuild。
