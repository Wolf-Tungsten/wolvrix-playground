# NO0183 Latest Default 20k Composite Gate

日期：2026-05-21

## 目的

把 `NO0181` 的静态 `c2-alias-off` gate 和 `NO0182` 的 runtime `coremark20k-fast` gate 合成一个 latest default 20k 闭环前置验收命令。

本次不启动 XiangShan fresh emit/build/runtime，只扩展 `scripts/grhsim_opt_metrics.py` 并用历史产物验证：

- 快档组合应通过；
- `NO0172` 同结构 alias-on 慢档应失败，并同时指出 code-shape 和 runtime 问题。

## 改动

修改文件：

```text
scripts/grhsim_opt_metrics.py
```

新增 gate：

```sh
--gate latest-default-20k
```

输出结构：

```json
"gate": {
  "name": "latest-default-20k",
  "pass": true,
  "gates": {
    "c2-alias-off": { "...": "..." },
    "coremark20k-fast": { "...": "..." }
  }
}
```

返回码：

- 所有子 gate 通过：`0`
- 任一子 gate 失败：`2`

保留已有单 gate：

- `--gate c2-alias-off`
- `--gate coremark20k-fast`

## 快档组合通过验证

命令：

```sh
python3 scripts/grhsim_opt_metrics.py \
  --gate latest-default-20k \
  --emit-dir tmp/no0151_xs_no_storage_ref_aliases/grhsim_emit \
  --stats tmp/no0151_xs_no_storage_ref_aliases/grhsim_emit/activity_schedule_supernode_stats.json \
  --perf-log tmp/no0162_lto_ab/coremark_20k_lto.log \
  --pretty
```

退出码：`0`。

关键结果：

| 子 gate | pass |
| --- | --- |
| `c2-alias-off` | true |
| `coremark20k-fast` | true |
| `latest-default-20k` | true |

核心指标：

| 指标 | 数值 |
| --- | ---: |
| `compute_supernodes` | `74430` |
| `dag_edges` | `485905` |
| `boundary_activation_edges` | `2216514` |
| `sched_cpp_bytes` | `1788406953` |
| `storage_ref_alias_count` | `0` |
| `emu_host_time_ms` | `99151` |
| `guest_cycles_per_s` | `201.72` |

注：该验证组合使用 `NO0151` 的 alias-off 静态产物和 `NO0162` 的 20k runtime 快档日志，目的是验证 gate 行为，不代表一个新 fresh 产物。

## NO0172 慢档失败验证

命令：

```sh
python3 scripts/grhsim_opt_metrics.py \
  --gate latest-default-20k \
  --emit-dir tmp/no0172_xs_c2_full_valuefanout_fix_full/grhsim_emit \
  --stats tmp/no0172_xs_c2_full_valuefanout_fix_full/grhsim_emit/activity_schedule_supernode_stats.json \
  --perf-log tmp/no0172_xs_c2_full_valuefanout_fix_full/build/coremark20k.log \
  --pretty
```

退出码：`2`。

关键结果：

| 子 gate | pass | 失败原因 |
| --- | --- | --- |
| `c2-alias-off` | false | sched 源码体积和 storage-ref alias 计数回退 |
| `coremark20k-fast` | false | 20k host time 超过快档阈值 |
| `latest-default-20k` | false | 任一子 gate 失败即失败 |

失败项：

| 指标 | actual | expected |
| --- | ---: | --- |
| `sched_cpp_bytes` | `2696952102` | `1788406953 +/- 100000000` |
| `storage_ref_alias_count` | `4509798` | `0` |
| `state_scalar_ref_alias_count` | `1318475` | `0` |
| `value_ref_alias_count` | `3184814` | `0` |
| `emu_host_time_ms` | `129095` | `<= 105000` |

结构项仍通过：

| 指标 | actual |
| --- | ---: |
| `compute_supernodes` | `74430` |
| `dag_edges` | `485905` |
| `boundary_values` | `1151073` |
| `boundary_activation_edges` | `2216514` |

这说明合成 gate 能准确表达当前根因链条：结构恢复不是充分条件，code-shape 和 runtime 都必须过。

## Latest Default 使用方式

latest default fresh emit/build/20k 后，运行：

```sh
python3 scripts/grhsim_opt_metrics.py \
  --gate latest-default-20k \
  --emit-dir <fresh>/grhsim_emit \
  --stats <fresh>/grhsim_emit/activity_schedule_supernode_stats.json \
  --perf-log <fresh>/build/coremark20k.log \
  --out <fresh>/latest_default_20k_gate.json \
  --pretty
```

判定：

- `latest-default-20k` 通过：可以进入 50k runtime。
- `c2-alias-off` 失败：先查 activity-schedule 或 emitter code-shape。
- `c2-alias-off` 通过但 `coremark20k-fast` 失败：先查 runtime hot batch/perf，不直接跑 50k。

## 结论

latest default 20k 闭环现在具备单命令自动验收。它仍不能替代实际 fresh emit/build/20k，但可以在 fresh 之后明确给出是否进入 50k 的机器判定。

主目标仍不能标记完成，因为还没有 latest default 的实际 fresh emit/build/20k/50k 数据。
