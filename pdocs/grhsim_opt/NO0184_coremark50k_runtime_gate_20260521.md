# NO0184 CoreMark 50k Runtime Gate

日期：2026-05-21

## 目的

补齐 latest default 进入最终 XiangShan CoreMark 50k 验收时的机器 gate。

本次不启动 fresh emit/build/runtime，只扩展 `scripts/grhsim_opt_metrics.py` 并用已有快档/慢档日志验证：

- 50k runtime 必须带 difftest；
- workload 必须对齐当前 CoreMark 2-iteration 50k 口径；
- host time 必须回到 `NO0151/NO0162` 的快档；
- 可与 `c2-alias-off` 静态 gate 合成 latest default 50k gate。

## 改动

修改文件：

```text
scripts/grhsim_opt_metrics.py
```

新增 gate：

```sh
--gate coremark50k-fast
--gate latest-default-50k
```

同时增强 summary log 解析：

- 若日志没有 `max cycles:` banner，但命令行包含 `-C 50000`，从 command line 解析 `max_cycles`；
- 若日志没有 `Difftest enabled` banner，但命令行包含 `--diff`，判定为 difftest enabled。

这是为了让 `NO0162` 的 50k summary log 可以作为快档校准样本；该 summary 明确记录了 `--diff ... -C 50000`，但没有保存完整 emu 启动 banner。

## Gate 定义

| 指标 | 期望 |
| --- | --- |
| `emu_host_time_ms` | `<= 355000` |
| `difftest_enabled` | `true` |
| `cycle_limit_reached` | `true` |
| `max_cycles` | `50000` |
| `guest_cycle_spent` | `50001` |
| `guest_instr_cnt` | `73580` |
| `guest_cycle_cnt` | `49996` |

`emu_host_time_ms <= 355000` 基于 `NO0151/NO0162` 的 `~348-350s` 快档，留出约数秒运行波动空间。

`guest_instr_cnt=73580` / `guest_cycle_cnt=49996` 固定当前正确 CoreMark 2-iteration 50k 口径，避免误把旧 workload 的 `instrCnt=22484` 快日志当作当前验收样本。

## NO0162 50k 快档通过验证

命令：

```sh
python3 scripts/grhsim_opt_metrics.py \
  --gate coremark50k-fast \
  --perf-log build/logs/xs/xs_wolf_grhsim_20260521_no0162_fullword_fastpath_50k.summary.log \
  --pretty
```

退出码：`0`。

关键输出：

| 指标 | actual | pass |
| --- | ---: | --- |
| `emu_host_time_ms` | `350265` | true |
| `guest_cycles_per_s` | `142.75` | true |
| `difftest_enabled` | `true` | true |
| `cycle_limit_reached` | `true` | true |
| `max_cycles` | `50000` | true |
| `guest_cycle_spent` | `50001` | true |
| `guest_instr_cnt` | `73580` | true |
| `guest_cycle_cnt` | `49996` | true |

## 当前 improved 50k 慢档失败验证

命令：

```sh
python3 scripts/grhsim_opt_metrics.py \
  --gate coremark50k-fast \
  --perf-log build/logs/xs/xs_wolf_grhsim_20260521_codex_current_improved_50k.log \
  --pretty
```

退出码：`2`。

关键输出：

| 指标 | actual | expected | pass |
| --- | ---: | --- | --- |
| `emu_host_time_ms` | `432935` | `<= 355000` | false |
| `guest_cycles_per_s` | `115.49` | - | - |
| `difftest_enabled` | `true` | `true` | true |
| `cycle_limit_reached` | `true` | `true` | true |
| `max_cycles` | `50000` | `50000` | true |
| `guest_cycle_spent` | `50001` | `50001` | true |
| `guest_instr_cnt` | `73580` | `73580` | true |
| `guest_cycle_cnt` | `49996` | `49996` | true |

这说明该慢档 workload 与 difftest 口径是对齐的，失败原因是 runtime 速度本身。

## Latest Default 50k Composite Gate

快档组合验证：

```sh
python3 scripts/grhsim_opt_metrics.py \
  --gate latest-default-50k \
  --emit-dir tmp/no0151_xs_no_storage_ref_aliases/grhsim_emit \
  --stats tmp/no0151_xs_no_storage_ref_aliases/grhsim_emit/activity_schedule_supernode_stats.json \
  --perf-log build/logs/xs/xs_wolf_grhsim_20260521_no0162_fullword_fastpath_50k.summary.log \
  --pretty
```

退出码：`0`。

关键结果：

| 子 gate | pass |
| --- | --- |
| `c2-alias-off` | true |
| `coremark50k-fast` | true |
| `latest-default-50k` | true |

慢档组合验证：

```sh
python3 scripts/grhsim_opt_metrics.py \
  --gate latest-default-50k \
  --emit-dir tmp/no0172_xs_c2_full_valuefanout_fix_full/grhsim_emit \
  --stats tmp/no0172_xs_c2_full_valuefanout_fix_full/grhsim_emit/activity_schedule_supernode_stats.json \
  --perf-log build/logs/xs/xs_wolf_grhsim_20260521_codex_current_improved_50k.log \
  --pretty
```

退出码：`2`。

失败项：

| 指标 | actual | expected |
| --- | ---: | --- |
| `sched_cpp_bytes` | `2696952102` | `1788406953 +/- 100000000` |
| `storage_ref_alias_count` | `4509798` | `0` |
| `state_scalar_ref_alias_count` | `1318475` | `0` |
| `value_ref_alias_count` | `3184814` | `0` |
| `emu_host_time_ms` | `432935` | `<= 355000` |

结构项仍通过：

| 指标 | actual |
| --- | ---: |
| `compute_supernodes` | `74430` |
| `dag_edges` | `485905` |
| `boundary_values` | `1151073` |
| `boundary_activation_edges` | `2216514` |

这和当前根因链条一致：C2 full 结构恢复是必要条件，但 per-supernode storage-ref alias code-shape 回退会把同结构产物拖回慢档。

## 最新默认验收顺序

latest default fresh emit/build 后，建议固定为：

1. `latest-default-20k` gate 通过；
2. 只在 20k gate 通过后运行 50k；
3. 对 50k 产物运行：

```sh
python3 scripts/grhsim_opt_metrics.py \
  --gate latest-default-50k \
  --emit-dir <fresh>/grhsim_emit \
  --stats <fresh>/grhsim_emit/activity_schedule_supernode_stats.json \
  --perf-log <fresh>/build/coremark50k.log \
  --out <fresh>/latest_default_50k_gate.json \
  --pretty
```

若 `latest-default-50k` 失败：

- `c2-alias-off` 失败：先查 activity-schedule 或 generated-code alias code-shape；
- `c2-alias-off` 通过但 `coremark50k-fast` 失败：进入 hot batch/perf 诊断，不再重复 fresh emit。

## 结论

现在 latest default 具备 20k 和 50k 两级机器验收 gate：

- `latest-default-20k`：前置 runtime gate，决定是否值得跑 50k；
- `latest-default-50k`：最终 runtime gate，要求结构、code-shape、difftest 和 50k host time 同时达标。

主目标仍不能标记完成，因为还没有 latest default 的实际 fresh emit/build/20k/50k 闭环数据。
