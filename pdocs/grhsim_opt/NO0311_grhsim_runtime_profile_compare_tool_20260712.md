# NO0311 GrhSIM runtime-profile comparison tool

日期：2026-07-12

## 1. 目的

[NO0309](./NO0309_no0286_no0300_dynamic_work_plan_20260712.md) 需要把 emit 期 static TSV 与运行期
fire TSV 严格连接。此前 NO0216 的汇总过程没有保留仓库内可复用工具，继续使用临时脚本或 awk 容易漏行、
重复计数，或把不同 phase 的同号 ID 错连。本轮新增：

```text
scripts/grhsim_runtime_profile_compare.py
```

## 2. 输入与校验

命令支持一个或多个三元组：

```text
--variant NAME STATIC_TSV FIRE_TSV
```

第一组作为 baseline，后续各组分别与它比较。工具执行以下硬校验：

- static TSV 必须包含 `supernode_id, phase, n_comp, n_src, n_sink, n_const, a_succ`；
- fire TSV 必须包含 `supernode_id, phase, f`；
- `phase` 只能为 `compute` 或 `commit`，全部计数字段必须是非负整数；
- 每张表的 `(supernode_id, phase)` 不允许重复；
- static/fire 的 key 集合必须完全相等，缺任意一行即失败。

工具不跨 variant 连接 supernode ID；不同 graph 中相同数值 ID 不被视为同一实体。

## 3. 输出口径

每个 variant 分 compute、commit 和 total 汇总：

```text
work_comp  = f * n_comp
work_src   = f * n_src
work_sink  = f * n_sink
work_const = f * n_const
work_total = work_comp + work_src + work_sink + work_const
a_succ_work = f * a_succ
```

同时输出 row/nonzero-row/fire、top-by-fire、top-by-work，以及 candidate 相对 baseline 的绝对 delta 和
百分比。文本报告用于人工检查，JSON 保留同一份 machine-readable 数据。

## 4. 验证

执行：

```text
source env.sh
python3 -m py_compile scripts/grhsim_runtime_profile_compare.py
python3 scripts/grhsim_runtime_profile_compare.py \
  --variant no0286 <strict-static.tsv> <strict-fire.tsv> \
  --variant no0300 <ordered-static.tsv> <ordered-fire.tsv> \
  --top 20 --output <report> --json <summary.json>
```

工具成功完成两组全量一一连接：

| Variant | Static/fire rows | Result |
| --- | ---: | --- |
| strict NO0286 | 67,934 | exact key match |
| ordered NO0300 | 63,726 | exact key match |

输出产物：

```text
build/logs/xs_perf/no0311/no0286_vs_no0300_dynamic_work.report
build/logs/xs_perf/no0311/no0286_vs_no0300_dynamic_work.json
```

动态数据结论作为独立 runtime gate 记录，不写入本文。

