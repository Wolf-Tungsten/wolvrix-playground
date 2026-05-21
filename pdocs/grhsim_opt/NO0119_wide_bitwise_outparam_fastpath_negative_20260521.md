# NO0119: wide bitwise out-param fast path negative result

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


实验目的：

- 针对 materialized wide `and/or/xor/not`，尝试用 out-param helper 直接写目标 slot，减少 `const auto = grhsim_*_words(...)` 返回临时。

结果：

- fresh emit 输出目录：`tmp/no0119_xs_emit_wide_bitwise_outparam/grhsim_emit`
- `activity-schedule`: `189360ms`
- `write_grhsim_cpp`: `40564ms`
- model build real: `255.13s`
- 生成代码覆盖：
  - `grhsim_assign_(and|or|xor|not)_words(`: `714`
  - `grhsim_store_(and|or|xor|not)_words(`: `0`
  - `const auto = grhsim_(and|or|xor|not)_words(` 从 NO0118 `28139` 降到 `27425`
- difftest emu build: 成功。
- CoreMark 50k 退出码：`0`
- 未出现 difftest mismatch。
- `Guest cycle spent`: `50001`
- `Host time spent`: `360273ms`
- 折算速度：约 `138.8 cycles/s`

NO0119 进度点：

| model cycles | host ms | cumulative cycles/s |
| ---: | ---: | ---: |
| `10000` | `32768` | `305` |
| `20000` | `108477` | `184` |
| `30000` | `187292` | `160` |
| `40000` | `267669` | `149` |
| `50000` | `360260` | `139` |

判断：

- 覆盖只有 `714` 处，且基本都是需要 change detect 的 materialized value，helper 内部仍需构造 `next` 做比较。
- 相比 NO0118，50k runtime 从 `358037ms` 退化到 `360273ms`，慢 `2236ms`，约 `0.62%`。
- 该 fast path 已回退，不纳入当前最佳代码。

