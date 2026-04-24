# NO0027 GrhSIM Emit Real Compile Time Snapshot 20260424

## 背景

- 目标：把 `sink supernode` 默认上限从 `1024` 压到 `768`，然后对 XiangShan `grhsim` 做一次 fresh `emit -> build`，并记录每个编译单元的真实编译耗时。
- fresh re-emit 日志：[`build/logs/xs/xs_wolf_grhsim_build_20260424_132042.log`](../../build/logs/xs/xs_wolf_grhsim_build_20260424_132042.log)
- 真实编译耗时日志：[`build/logs/xs/grhsim_emit_compile_times_20260424.tsv`](../../build/logs/xs/grhsim_emit_compile_times_20260424.tsv)
- 按耗时降序排序后的全量清单：[`build/logs/xs/grhsim_emit_compile_times_20260424.sorted.tsv`](../../build/logs/xs/grhsim_emit_compile_times_20260424.sorted.tsv)

## 本轮口径

- `emit` 参数已改为 `-max-sink-supernode-op 768`，对应脚本见 [`scripts/wolvrix_xs_grhsim.py`](../../scripts/wolvrix_xs_grhsim.py)。
- re-emit 日志确认：
  - `activity-schedule supernode-max-size=72 max_sink_supernode_op=768`
  - `sink_chunk_limit=768`
  - `sink_supernodes=430`
- `build` 目录：[`build/xs/grhsim/grhsim_emit`](../../build/xs/grhsim/grhsim_emit)
- `Makefile` 仍走 `-include-pch`，因此本轮显式用 `clang++`：
  - `/home/gaoruihao/download/LLVM-21.1.8-Linux-X64/bin/clang++`
- 为了拿到每个 `.cpp -> .o` 的真实耗时，使用了计时 wrapper：
  - [`scripts/grhsim_compile_time_wrapper.sh`](../../scripts/grhsim_compile_time_wrapper.sh)
- 实际 build 命令等价于：

```bash
make -C build/xs/grhsim/grhsim_emit clean
GRHSIM_COMPILE_TIME_LOG=build/logs/xs/grhsim_emit_compile_times_20260424.tsv \
GRHSIM_REAL_CXX=/home/gaoruihao/download/LLVM-21.1.8-Linux-X64/bin/clang++ \
make -C build/xs/grhsim/grhsim_emit -j$(nproc) \
  CXX=/workspace/gaoruihao-dev-gpu/wolvrix-playground/scripts/grhsim_compile_time_wrapper.sh
```

## 结果摘要

- build 成功，产物：[`build/xs/grhsim/grhsim_emit/libgrhsim_SimTop.a`](../../build/xs/grhsim/grhsim_emit/libgrhsim_SimTop.a)
- 记录条数：`1450`
  - `1449` 个 `.cpp -> .o`
  - `1` 个 `PCH`
- `status != 0` 的失败条数：`0`
- `PCH` 生成耗时：`17.281180s`
- 全量样本统计：
  - `median = 25.575141s`
  - `mean = 174.256511s`
  - `p90 = 793.781812s`
  - `p95 = 1228.528531s`
  - `p99 = 1577.162805s`

## 关键观察

- `sched_945.cpp` 仍然慢，但已经不是最顶层的 outlier。
  - `grhsim_SimTop_sched_945.cpp = 535.979880s`
  - 全部成功条目中排名 `179 / 1450`
- 当前最慢文件已经扩散成一整个重尾区，而不是单点集中在 `sched_945.cpp`。
- `state_init_2.cpp` 这一轮并不突出：
  - `grhsim_SimTop_state_init_2.cpp = 31.297015s`
  - 排名 `500 / 1450`
- `state.cpp` 和 `eval.cpp` 也不是主拖尾：
  - `grhsim_SimTop_state.cpp = 57.327364s`，排名 `305`
  - `grhsim_SimTop_eval.cpp = 34.200380s`，排名 `385`

## Top 20 慢文件

| 排名 | 耗时(s) | 文件 |
| --- | ---: | --- |
| 1 | 1914.321563 | `grhsim_SimTop_sched_1230.cpp` |
| 2 | 1877.251265 | `grhsim_SimTop_sched_1146.cpp` |
| 3 | 1877.041025 | `grhsim_SimTop_sched_964.cpp` |
| 4 | 1773.435945 | `grhsim_SimTop_sched_1309.cpp` |
| 5 | 1730.373846 | `grhsim_SimTop_sched_1026.cpp` |
| 6 | 1709.107171 | `grhsim_SimTop_sched_1304.cpp` |
| 7 | 1692.796810 | `grhsim_SimTop_sched_1252.cpp` |
| 8 | 1672.149741 | `grhsim_SimTop_sched_1224.cpp` |
| 9 | 1645.273204 | `grhsim_SimTop_sched_1257.cpp` |
| 10 | 1642.058855 | `grhsim_SimTop_sched_1290.cpp` |
| 11 | 1623.789120 | `grhsim_SimTop_sched_1145.cpp` |
| 12 | 1620.516363 | `grhsim_SimTop_sched_1044.cpp` |
| 13 | 1616.463715 | `grhsim_SimTop_sched_954.cpp` |
| 14 | 1615.202343 | `grhsim_SimTop_sched_1139.cpp` |
| 15 | 1579.429215 | `grhsim_SimTop_sched_1012.cpp` |
| 16 | 1577.162805 | `grhsim_SimTop_sched_994.cpp` |
| 17 | 1569.510449 | `grhsim_SimTop_sched_1068.cpp` |
| 18 | 1565.027921 | `grhsim_SimTop_sched_1272.cpp` |
| 19 | 1561.747311 | `grhsim_SimTop_sched_1075.cpp` |
| 20 | 1559.760979 | `grhsim_SimTop_sched_1245.cpp` |

## 结论

- 把 `sink supernode` 默认上限从 `1024` 降到 `768` 以后，`sched_945.cpp` 不再是最突出的编译热点，但整体仍然存在很长的 `sched_9xx~13xx` 编译重尾。
- `PCH` 已经生效，但它解决的主要是前端 parse / include 成本；当前拖尾主因依然是大量超大 `sched` 编译单元在 `-O3` 下的优化与后端耗时。
- 下一步如果要继续压编译时间，重点不该放在 `state_init` 或 `PCH` 上，而应该继续处理这批大 `sched` 文件的函数体规模与 chunking 策略。
