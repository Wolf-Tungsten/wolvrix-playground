# NO0181 C2 Alias-Off Metrics Gate

日期：2026-05-21

## 目的

把 `NO0180` 的静态 code-shape 指标升级为机器可判定 gate，避免 latest default fresh emit 后只靠人工看 JSON。

本次不启动 XiangShan fresh emit/build/runtime，只扩展 `scripts/grhsim_opt_metrics.py` 并用历史产物验证：

- `NO0151` alias-off 快档必须通过；
- `NO0172` 同结构 alias-on 慢档必须失败。

## 改动

修改文件：

```text
scripts/grhsim_opt_metrics.py
```

新增参数：

```sh
--gate c2-alias-off
```

行为：

- 输出 JSON 中新增 `gate` 字段；
- gate 通过返回 `0`；
- gate 失败返回 `2`；
- 不传 `--gate` 时保持原来的指标汇总行为。

## Gate 定义

当前 gate 锁定 `NO0151/NO0171/NO0177` 对齐出的 C2 full + alias-off 快档。

| 指标 | 期望 | 容差 |
| --- | ---: | ---: |
| `compute_supernodes` | `74430` | `0` |
| `dag_edges` | `485905` | `0` |
| `boundary_values` | `1151073` | `0` |
| `boundary_activation_edges` | `2216514` | `0` |
| `sched_cpp_bytes` | `1788406953` | `100000000` |
| `storage_ref_alias_count` | `0` | `0` |
| `state_scalar_ref_alias_count` | `0` | `0` |
| `value_ref_alias_count` | `0` | `0` |

`sched_cpp_bytes` 给 `100MB` 容差，用于容纳无害格式漂移；这个容差仍远小于 `NO0172` 相对 `NO0151` 的 `908545149` 字节膨胀。

结构指标暂时使用零容差，因为当前 latest default structure-only gate 已精确恢复该档。若后续算法有意改变结构，需要新建文档调整 gate，而不是静默放宽。

## NO0151 通过验证

命令：

```sh
python3 scripts/grhsim_opt_metrics.py \
  --gate c2-alias-off \
  --emit-dir tmp/no0151_xs_no_storage_ref_aliases/grhsim_emit \
  --stats tmp/no0151_xs_no_storage_ref_aliases/grhsim_emit/activity_schedule_supernode_stats.json \
  --pretty
```

退出码：`0`。

关键输出：

```json
"gate": {
  "name": "c2-alias-off",
  "pass": true
}
```

核心 checks：

| 指标 | actual | pass |
| --- | ---: | --- |
| `compute_supernodes` | `74430` | true |
| `dag_edges` | `485905` | true |
| `boundary_activation_edges` | `2216514` | true |
| `sched_cpp_bytes` | `1788406953` | true |
| `storage_ref_alias_count` | `0` | true |
| `state_scalar_ref_alias_count` | `0` | true |
| `value_ref_alias_count` | `0` | true |

## NO0172 失败验证

命令：

```sh
python3 scripts/grhsim_opt_metrics.py \
  --gate c2-alias-off \
  --emit-dir tmp/no0172_xs_c2_full_valuefanout_fix_full/grhsim_emit \
  --stats tmp/no0172_xs_c2_full_valuefanout_fix_full/grhsim_emit/activity_schedule_supernode_stats.json \
  --pretty
```

退出码：`2`。

关键输出：

```json
"gate": {
  "name": "c2-alias-off",
  "pass": false
}
```

失败项：

| 指标 | actual | expected | delta |
| --- | ---: | ---: | ---: |
| `sched_cpp_bytes` | `2696952102` | `1788406953` | `908545149` |
| `storage_ref_alias_count` | `4509798` | `0` | `4509798` |
| `state_scalar_ref_alias_count` | `1318475` | `0` | `1318475` |
| `value_ref_alias_count` | `3184814` | `0` | `3184814` |

结构项全部通过：

| 指标 | actual |
| --- | ---: |
| `compute_supernodes` | `74430` |
| `dag_edges` | `485905` |
| `boundary_values` | `1151073` |
| `boundary_activation_edges` | `2216514` |

这正好复现 `NO0173` 的结论：`NO0172` 不是结构错，而是同结构下 code-shape/alias 回退。

## 最新默认验收用法

下次 fresh emit 后，先跑：

```sh
python3 scripts/grhsim_opt_metrics.py \
  --gate c2-alias-off \
  --emit-dir <fresh>/grhsim_emit \
  --stats <fresh>/grhsim_emit/activity_schedule_supernode_stats.json \
  --out <fresh>/c2_alias_off_gate.json \
  --pretty
```

若返回非零，不进入 50k；先看 `gate.checks` 的失败项。

若通过，再继续：

1. build difftest emu；
2. CoreMark 20k with difftest；
3. 20k 接近 `~99-101s` 后再跑 50k。

## 结论

现在 latest default full emit 后具备可自动化的结构 + code-shape 前置验收。

这个 gate 不替代 runtime gate；它只防止“结构恢复但 alias/code-size 回退”的 `NO0172` 类问题再次混入 runtime 判断。
