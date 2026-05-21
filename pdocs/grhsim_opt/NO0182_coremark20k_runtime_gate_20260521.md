# NO0182 CoreMark 20k Runtime Gate

日期：2026-05-21

## 目的

补齐 latest default full emit/build 后的 runtime 前置验收工具：

- 解析 XiangShan CoreMark 20k difftest 日志；
- 判断是否真的跑到 20k cycle limit；
- 判断 difftest 是否启用；
- 判断 host time 是否回到 `NO0151/NO0162` 快档。

本次不启动 XiangShan fresh emit/build/runtime，只扩展 `scripts/grhsim_opt_metrics.py` 并用历史 20k 日志验证。

## 改动

修改文件：

```text
scripts/grhsim_opt_metrics.py
```

新增/增强字段：

| 字段 | 来源 |
| --- | --- |
| `max_cycles` | `max cycles: ...` |
| `guest_cycle_spent` | `Guest cycle spent: ...` |
| `difftest_enabled` | 日志包含 `Difftest enabled` |
| `cycle_limit_reached` | 日志包含 `EXCEEDING CYCLE/INSTR LIMIT` |
| `guest_cycles_per_s` | `guest_cycle_spent * 1000 / emu_host_time_ms` |

新增 gate：

```sh
--gate coremark20k-fast
```

## Gate 定义

| 指标 | 期望 |
| --- | --- |
| `emu_host_time_ms` | `<= 105000` |
| `difftest_enabled` | `true` |
| `cycle_limit_reached` | `true` |
| `max_cycles` | `20000` |
| `guest_cycle_spent` | `20001` |
| `guest_instr_cnt` | `14121` |
| `guest_cycle_cnt` | `19996` |

`emu_host_time_ms <= 105000` 基于 `NO0151/NO0162` 的 `~99-101s` 快档，留出约数秒运行波动空间。

`guest_cycle_spent=20001` 是当前 difftest 20k 日志稳定输出；虽然命令 max cycles 为 `20000`，日志中的 guest spent 会多 1。

## NO0162 快档通过验证

命令：

```sh
python3 scripts/grhsim_opt_metrics.py \
  --gate coremark20k-fast \
  --perf-log tmp/no0162_lto_ab/coremark_20k_lto.log \
  --pretty
```

退出码：`0`。

关键输出：

| 指标 | actual | pass |
| --- | ---: | --- |
| `emu_host_time_ms` | `99151` | true |
| `guest_cycles_per_s` | `201.72` | true |
| `difftest_enabled` | `true` | true |
| `cycle_limit_reached` | `true` | true |
| `max_cycles` | `20000` | true |
| `guest_cycle_spent` | `20001` | true |
| `guest_instr_cnt` | `14121` | true |
| `guest_cycle_cnt` | `19996` | true |

## NO0172 慢档失败验证

命令：

```sh
python3 scripts/grhsim_opt_metrics.py \
  --gate coremark20k-fast \
  --perf-log tmp/no0172_xs_c2_full_valuefanout_fix_full/build/coremark20k.log \
  --pretty
```

退出码：`2`。

关键输出：

| 指标 | actual | expected | pass |
| --- | ---: | --- | --- |
| `emu_host_time_ms` | `129095` | `<= 105000` | false |
| `guest_cycles_per_s` | `154.93` | - | - |
| `difftest_enabled` | `true` | `true` | true |
| `cycle_limit_reached` | `true` | `true` | true |
| `max_cycles` | `20000` | `20000` | true |
| `guest_cycle_spent` | `20001` | `20001` | true |
| `guest_instr_cnt` | `14121` | `14121` | true |
| `guest_cycle_cnt` | `19996` | `19996` | true |

这说明 `NO0172` 功能和 workload 对齐，但 runtime 明显慢，和 `NO0173` 的 code-shape 诊断一致。

## 最新默认验收顺序

latest default fresh emit/build 后，建议 gate 顺序固定为：

1. 静态 code-shape gate：

```sh
python3 scripts/grhsim_opt_metrics.py \
  --gate c2-alias-off \
  --emit-dir <fresh>/grhsim_emit \
  --stats <fresh>/grhsim_emit/activity_schedule_supernode_stats.json \
  --out <fresh>/c2_alias_off_gate.json \
  --pretty
```

2. build difftest emu。

3. 20k runtime gate：

```sh
python3 scripts/grhsim_opt_metrics.py \
  --gate coremark20k-fast \
  --perf-log <fresh>/build/coremark20k.log \
  --out <fresh>/coremark20k_gate.json \
  --pretty
```

4. 只有 20k gate 通过，才跑 50k。

若 `c2-alias-off` 失败，先查结构或 generated-code 形态；若 `coremark20k-fast` 失败但静态 gate 通过，再进入 hot batch/perf 诊断。

## 结论

现在 latest default 的前置验收具备两级自动 gate：

- `c2-alias-off`：结构 + code-shape；
- `coremark20k-fast`：difftest 20k runtime。

主目标仍不能标记完成，因为还没有 latest default 的 fresh emit/build/20k/50k 实测闭环。
