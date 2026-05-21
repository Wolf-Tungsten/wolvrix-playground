# NO0120: static 1-bit slice inline negative result

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


实验目的：

- 针对 static `kSliceStatic` 和 const-index `kSliceDynamic` 的 1-bit scalar 结果，尝试将 `grhsim_get_bit_words(src, index)` 展开为直接 word load/shift/mask 表达式。
- 预期减少 helper 调用与生成源码体积，验证结构收益是否转成 CoreMark runtime 收益。

结果：

- fresh emit 输出目录：`tmp/no0120_xs_emit_static_bit_inline/grhsim_emit`
- `activity-schedule`: `194499ms`
- `write_grhsim_cpp`: `42571ms`
- total real: `265.82s`
- `compute_supernodes`: `74430`
- `commit_supernodes`: `515`
- supernodes: `74945`
- 源码目录体积：`2.0G`，NO0118 为 `2.2G`
- `grhsim_get_bit_words(` 计数：`0`，NO0118 为 `39142`
- `apply_commit_scalar_state_write_table(`：`3733`
- `apply_commit_scalar_state_write_*_range(`：`918`
- model build real: `260.72s`
- model build user/sys: `5701.68s` / `59.13s`
- difftest emu build: 成功。
- CoreMark 50k 退出码：`0`
- 未出现 difftest mismatch。
- `Guest cycle spent`: `50001`
- `Host time spent`: `360761ms`
- 折算速度：约 `138.6 cycles/s`

NO0120 进度点：

| model cycles | host ms | cumulative cycles/s |
| ---: | ---: | ---: |
| `10000` | `24372` | `410` |
| `20000` | `111348` | `180` |
| `30000` | `189338` | `158` |
| `40000` | `269246` | `149` |
| `50000` | `360749` | `139` |

对比 NO0118：

| 指标 | NO0118 | NO0120 |
| --- | ---: | ---: |
| `activity-schedule` | `191465ms` | `194499ms` |
| `write_grhsim_cpp` | `40062ms` | `42571ms` |
| model build real | `255.51s` | `260.72s` |
| 50k `Host time spent` | `358037ms` | `360761ms` |
| 50k throughput | `139.7 cycles/s` | `138.6 cycles/s` |

判断：

- NO0120 的结构指标改善真实存在：`grhsim_get_bit_words` 调用归零，源码体积减少约 `0.2G`。
- 但 emit、model build 和 50k runtime 都变慢；50k 相比 NO0118 慢 `2724ms`，约 `0.76%`。
- 该 static bit inline fast path 已回退，不纳入当前最佳代码；当前最佳仍为 NO0118。

