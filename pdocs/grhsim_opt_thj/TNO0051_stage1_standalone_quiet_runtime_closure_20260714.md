# TNO0051 Stage 1 standalone quiet runtime closure

记录日期：2026-07-14

状态：补齐 [TNO0027](./TNO0027_stage1_quiet_gate_block_and_default_decision_20260714.md) 当时被外部负载阻断的 Stage 1 standalone formal gate；strict、balanced、bae-budget 均在有效 quiet 包夹中回退 `8.22%..8.87%` cycles，整个 static post-DP refinement policy family 明确停止。

## 1. 为什么必须补测

Stage 1 三个 policy 都已通过 full build 和 fixed-ASLR 50k 功能门禁，且 total BAE 下降约 `1.12%..1.20%`、DAG 下降约 `3.49%..3.81%`。但 [TNO0027](./TNO0027_stage1_quiet_gate_block_and_default_decision_20260714.md) 只得到持续 high-load rejection，没有正式 candidate 样本。

[TNO0033](./TNO0033_stage2_combination_runtime_and_default_decision_20260714.md) 的 `+8.713%` 是 Stage 1 strict 与 Stage 2 Kahn packing 的组合，不能证明回退来自哪一项。本轮机器已能稳定通过 atomic quiet gate，因此直接复用原有、功能正确的三个 standalone binary 补齐缺口，不重建、不改变配置。

## 2. 多候选包夹

运行顺序：

```text
current-default / strict / balanced / bae-budget / current-default
```

统一使用 CPU142/sibling334、NUMA1、`setarch x86_64 -R` 和五事件 `perf stat`。双 sibling 三秒平均 idle 均 `>=99%` 才在同一 helper 内立即启动 50k。

| Run | Accepted gate idle | gate-to-run | Endpoint |
| --- | --- | ---: | --- |
| control1 | `100.00% / 99.67%` | `6 ms` | `50001/49996/73580/0x80001312` |
| strict | `99.67% / 100.00%` | `6 ms` | same |
| balanced | `99.67% / 99.33%` | `6 ms` | same |
| bae-budget | `99.00% / 99.00%` | `6 ms` | same |
| control2 | `99.00% / 99.00%` | `8 ms` | same |

所有运行的五事件均为 `100%` scheduled，difftest 正常，负向关键词为 0。两侧 control cycles spread 为 `0.563304%`，小于 1%，多候选包夹有效。

## 3. PMU 结果

| Metric | control1 | strict | balanced | bae-budget | control2 |
| --- | ---: | ---: | ---: | ---: | ---: |
| cycles | `284,734,545,533` | `309,118,099,108` | `308,227,387,914` | `307,281,422,348` | `283,135,128,312` |
| instructions | `172,881,406,660` | `171,833,785,716` | `171,770,088,663` | `171,938,966,444` | `172,881,406,453` |
| frontend empty | `1,303,355,001,205` | `1,453,336,536,732` | `1,446,058,900,124` | `1,441,499,571,335` | `1,295,667,096,480` |
| frontend cmask6 | `169,335,099,380` | `194,194,377,598` | `192,940,289,559` | `192,219,818,230` | `168,068,723,390` |
| backend stalls | `95,044,280,750` | `92,547,046,801` | `94,113,689,172` | `93,253,687,994` | `93,205,861,480` |
| host wall | `77,694 ms` | `84,773 ms` | `84,565 ms` | `84,283 ms` | `77,423 ms` |

相对 control 均值：

| Policy | cycles | instructions | frontend empty | cmask6 | backend | wall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| strict | `+8.869%` | `-0.606%` | `+11.837%` | `+15.111%` | `-1.677%` | `+9.302%` |
| balanced | `+8.556%` | `-0.643%` | `+11.277%` | `+14.368%` | `-0.012%` | `+9.034%` |
| bae-budget | `+8.223%` | `-0.545%` | `+10.926%` | `+13.941%` | `-0.926%` | `+8.670%` |

三者都减少约 `0.55%..0.64%` retired instructions 和约 `0.2%` `.text`，但 frontend empty/cmask6 大幅增加，最终 cycles/wall 一致回退约 `8%..9%`。这证明 Stage 2 组合不是回退根因；仅改变 final segment 成员和生成代码布局的 Stage 1 standalone 已足以触发同一 cliff。

## 4. 结论

可信阈值为 `max(1%, control spread 0.563304%) = 1%`。三个 policy 都远超回退线，且相互复现相同 PMU 形态。因此：

- `post_dp_refine_policy` 默认继续为 `off`；
- 不扫描 rounds `2/4`，因为 moved-cluster budget 在 round1 已耗尽且会复现同一结果；
- 不再用 raw BAE/DAG/source size 作为该 family 的继续调参理由；
- 后续 activity-schedule 实验必须限制 code/order blast radius，或直接以动态/生成机器成本为目标。

当前下一候选优先考虑 [TNO0020](./TNO0020_sparse_pure_event_codegen_and_legal_packing_20260713.md) 留下的 targeted pure-event final active-word packing：它只移动约 `0.405%` compute SN，保持 partition/BAE/DAG/batch membership 不变，和本轮 broad segment membership 改写正交。

## 5. 原始数据

```text
build/logs/xs_perf/activity_stage6_stage1_standalone_20260714/control1_*
build/logs/xs_perf/activity_stage6_stage1_standalone_20260714/strict_*
build/logs/xs_perf/activity_stage6_stage1_standalone_20260714/balanced_*
build/logs/xs_perf/activity_stage6_stage1_standalone_20260714/bae_budget_*
build/logs/xs_perf/activity_stage6_stage1_standalone_20260714/control2_*
build/logs/xs_perf/activity_stage6_stage1_standalone_20260714/run_atomic.sh
```
