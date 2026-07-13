# NO0325 Stable-op origin-density tool plan

日期：2026-07-12

## 1. 目的

[NO0324](./NO0324_batch_dynamic_work_profile_tool_plan_20260712.md) 已得到每版 batch 的 full-empty
samples/work，但 NO0303 已证明 old/new 同编号 batch 逻辑不同。本阶段扩展：

```text
scripts/grhsim_compute_batch_overlap.py
```

让它可选读取 NO0324 的 profile JSON，并按 stable `_op_<id>` overlap 估算每个 new batch 的 old-origin
sample density。

## 2. 指标

对 new batch 中每个可映射到 old 的 op，以 overlap op 数加权其 old batch 的 samples-per-billion-work：

```text
op_weighted_origin_density = sum(overlap_ops * old_batch_density) / common_ops
density_ratio = new_batch_density / op_weighted_origin_density
relative_to_global = density_ratio / (new_compute_density / old_compute_density)
```

同时用 origin density 和 new batch work 估算 expected/excess samples，并报告 common ops 占 new static ops 的
coverage。输出 density-ratio 与 excess-samples 两种 top 排名，默认要求 new batch 至少 100 samples。

## 3. 边界

该指标是筛选启发式，不是因果分解：

- overlap 权重是 static op count，不含逐 op fire、复杂度和 sample；
- new-only/removed ops 只能通过 common coverage 暴露，不能被 old-origin density 解释；
- non-precise frontend event 有 skid；
- 候选必须继续检查 dynamic batch work、coverage、generated source 和 annotate，不能只按 ratio 排名改代码。

原有不带 profile JSON 的 overlap 命令和报告保持兼容。

## 4. 验证计划

- 原命令输出结构统计成功；
- profile 增强命令严格连接 `no0286/no0300` 的 66 个 compute batches；
- global density ratio 必须复现 NO0324 的 `+21.1677%`；
- profile variant 缺失、batch 集合不闭合、负值和参数不完整均应报错。

