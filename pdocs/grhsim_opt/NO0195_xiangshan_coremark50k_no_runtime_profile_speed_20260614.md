# NO0195 XiangShan CoreMark 50k no-runtime-profile speed snapshot

记录日期：2026-06-14

目的：补充 NO0190 XiangShan full-profile 结果的裸跑对照，确认不启用 `EMU_RUNTIME_PROFILE` 时 `gsim` / `grhsim` 的实际 host-time 差距。

关联：

- [`NO0190`](./NO0190_grhsim_gsim_unified_cost_model_comp_src_sink_plan_20260612.md)：统一 runtime profile 口径与 XiangShan 50k profile 输出。
- `tmp/no0190_xs_gsim_grhsim_runtime_profile_20260613_131543/README.md`：2026-06-13 带 `EMU_RUNTIME_PROFILE=1` 的同 workload 对照。

## 1. 口径

本次没有重新 build emu，复用 2026-06-13 的现有二进制：

- `build/xs/gsim/emu`，compiled at `Jun 13 2026, 11:51:29`
- `build/xs/grhsim/emu`，compiled at `Jun 13 2026, 13:21:48`

运行时显式取消 runtime profile 相关环境变量：

```bash
unset EMU_RUNTIME_PROFILE GSIM_SUPERNODE_TSV WOLVRIX_GRHSIM_SUPERNODE_TSV
```

因此这次测的是“同一批已构建 emu，运行时不启用 runtime profile”的速度；不是“重新 build 时完全去掉 profile 编译支持”的速度。

共同 workload：

- XiangShan `SimTop`
- `coremark-2-iteration.bin`
- difftest on
- `XS_SIM_MAX_CYCLE=50000`
- `XS_COMMIT_TRACE=0`
- waveform off
- progress interval `25000` cycles

## 2. 复现命令

```bash
source env.sh
unset EMU_RUNTIME_PROFILE GSIM_SUPERNODE_TSV WOLVRIX_GRHSIM_SUPERNODE_TSV
/usr/bin/time -v make run_xs_gsim_emu \
  RUN_ID=no0190_nortprof_gsim_20260614 \
  XS_SIM_MAX_CYCLE=50000 \
  XS_PROGRESS_EVERY_CYCLES=25000 \
  XS_COMMIT_TRACE=0 \
  XS_WAVEFORM=0 \
  XS_WAVEFORM_FULL=0 \
  XS_LOG_BEGIN=0 \
  XS_LOG_END=0

source env.sh
unset EMU_RUNTIME_PROFILE GSIM_SUPERNODE_TSV WOLVRIX_GRHSIM_SUPERNODE_TSV
/usr/bin/time -v make run_xs_wolf_grhsim_emu \
  RUN_ID=no0190_nortprof_grhsim_20260614 \
  XS_SIM_MAX_CYCLE=50000 \
  XS_PROGRESS_EVERY_CYCLES=25000 \
  XS_COMMIT_TRACE=0 \
  XS_WAVEFORM=0 \
  XS_WAVEFORM_FULL=0 \
  XS_LOG_BEGIN=0 \
  XS_LOG_END=0
```

日志：

- `build/logs/xs/xs_gsim_no0190_nortprof_gsim_20260614.log`
- `build/logs/xs/xs_wolf_grhsim_no0190_nortprof_grhsim_20260614.log`

## 3. 裸跑结果

| sim | instrCnt | cycleCnt | IPC | host time | `/usr/bin/time` elapsed | throughput |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `gsim` | 73584 | 49998 | 1.471739 | 47296 ms | 47.30 s | 1057.17 cycles/s |
| `grhsim` | 73580 | 49996 | 1.471718 | 374975 ms | 374.98 s | 133.34 cycles/s |

速度差：

```text
grhsim / gsim = 374975 / 47296 = 7.93x
```

即在不启用 runtime profile 的这次 50k bounded run 中，`grhsim` 比 `gsim` 慢约 `7.93x`，绝对差值为 `327679 ms`。

进度点：

| sim | 25k host_ms | 50k host_ms |
| --- | ---: | ---: |
| `gsim` | 19126 | 47294 |
| `grhsim` | 147134 | 374962 |

## 4. 与 runtime-profile run 对照

2026-06-13 的 profile run 数据来自 `tmp/no0190_xs_gsim_grhsim_runtime_profile_20260613_131543/{gsim_run.log,grhsim_run.log}`：

| mode | `gsim` host time | `grhsim` host time | `grhsim / gsim` |
| --- | ---: | ---: | ---: |
| `EMU_RUNTIME_PROFILE=1` | 68012 ms | 392355 ms | 5.77x |
| runtime profile disabled | 47296 ms | 374975 ms | 7.93x |

runtime profile overhead in this specific run:

| sim | no-profile | profile | delta | factor |
| --- | ---: | ---: | ---: | ---: |
| `gsim` | 47296 ms | 68012 ms | +20716 ms | 1.438x |
| `grhsim` | 374975 ms | 392355 ms | +17380 ms | 1.046x |

观察：

- `EMU_RUNTIME_PROFILE=1` 对 `gsim` 的相对开销更大，约 `+43.8%`。
- `EMU_RUNTIME_PROFILE=1` 对 `grhsim` 的相对开销较小，约 `+4.6%`。
- 因此带 profile 时看到的 `5.77x` 会低估裸跑口径下的速度差；本次裸跑差距是 `7.93x`。

## 5. 结论

当前同 workload、同已构建 emu、关闭 runtime profile 环境变量后，XiangShan CoreMark 50k 的可引用速度基线应记为：

```text
gsim   47.296 s, ~1057 cycles/s
grhsim 374.975 s, ~133 cycles/s
gap    7.93x
```

后续若要评估“完全不编译 runtime profile 支持”的纯净 binary，需要重新 build 一组不带 profile emit/runtime 支持的 `gsim` / `grhsim` emu，再独立记录；不要与本文口径混用。
