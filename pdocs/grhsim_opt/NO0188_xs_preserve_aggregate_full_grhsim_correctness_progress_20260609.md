# NO0188 XiangShan Preserve-Aggregate Full GrhSIM Correctness Progress

日期：2026-06-09

## 背景

本轮从 `firtool --preserve-aggregate` 形态下的 XiangShan SV 输入开始，目标是修复
GrhSIM 对 aggregate SV、reset/fill、`comb-loop-elim` 和完整 XiangShan runtime 的支持。

当前调试口径固定为仓库内 XiangShan：

```text
testcase/xiangshan
```

不要再使用旧的外部路径 `/home/gaoruihao/wksp/gsim-playground/XiangShan`。完整 XiangShan
构建和运行时使用仓库内 ccache：

```sh
CCACHE_DIR=/home/gaoruihao/wksp/wolvrix-playground/build/xs/ccache
```

## 完整 XiangShan 构建状态

完整 GrhSIM 已从 SV 读取开始重新走通。关键日志：

```text
build/logs/xs/xs_wolf_grhsim_build_codex_20260609_grhsim_full.log
```

关键阶段结果：

```text
[wolvrix-xs-grhsim] read_sv done
comb-loop-elim graph=SimTop loops=44 true=0 false=44 false-unresolved=0 false-fixed=44
retargeted-slices=2969 split-values=3620 split-ops=152332 fix-iters=2
[wolvrix-xs-grhsim] pass comb-loop-elim done
[wolvrix-xs-grhsim] pass activity-schedule done
[wolvrix-xs-grhsim] write_grhsim_cpp done
```

当前结论：

- `read_sv` 已能吃当前完整 XiangShan preserve-aggregate SV。
- `comb-loop-elim` 没有留下 unresolved loop；44 个 loop 均被判定为 false loop 并修复。
- 当前完整 XiangShan preserve-aggregate 运行问题不再是 SV 读入失败或
  `comb-loop-elim` 直接失败；但 2026-06-10 从
  `build/xs-preserve-aggregate` 重建并复测 50k 后，旧的吞吐差异再次复现。
  之前 clean 50k 通过只适用于默认 lowered SV baseline，不能代表
  preserve-aggregate 路径。
- 明确状态：目前 preserve-aggregate 版本仍然有误。GrhSIM 50k 只提交
  `36573` 条指令，而 ref/lowered baseline 为 `73580` 条；这不是单纯性能波动，
  而是 preserve-aggregate 路径上的 correctness/吞吐分叉。

## Runtime 症状复验

最初的 CoreMark 50k 对比日志：

```text
build/logs/xs/xs_wolf_grhsim_codex_20260609_grhsim_50k.log
build/logs/xs/xs_ref_codex_20260609_ref_50k.log
```

50k 总结果：

| model | instrCnt | cycleCnt | IPC | final pc |
| --- | ---: | ---: | ---: | --- |
| GrhSIM | `36573` | `49996` | `0.731519` | `0x80000428` |
| Verilator ref | `73580` | `49996` | `1.471718` | `0x80001312` |

分段进度：

| cycle | GrhSIM instr / commit_pc | Verilator instr / commit_pc |
| ---: | --- | --- |
| 5k | `3 / 0x10000008` | `3 / 0x10000008` |
| 10k | `458 / 0x80001cdc` | `458 / 0x80001cdc` |
| 15k | `4505 / 0x80000116` | `5532 / 0x80000130` |
| 20k | `10424 / 0x80000a9c` | `14121 / 0x8000043a` |
| 50k | `36573 / 0x8000042a` | `73580 / 0x800012f8` |

当时现象不是 reset 后 assert 或 difftest mismatch，而是：

- 10k cycle 前后进度完全一致；
- 10k 到 15k 之间开始出现吞吐差异；
- 后续 GrhSIM 指令提交数量约为 Verilator 的一半；
- 从现有 progress 和无 assert/mismatch 现象看，更像是额外 stall / 气泡，而不是立即取错或执行错。

2026-06-10 先用当前最新 `build/xs/ref/emu` 和 `build/xs/grhsim/emu`、
关闭 waveform/commit trace 后重跑 50k：

```text
build/logs/xs/xs_ref_clean50k_ref_20260610.log
build/logs/xs/xs_wolf_grhsim_clean50k_grhsim_20260610.log
```

clean 50k 结果完全一致：

| cycle | ref instr / commit_pc | GrhSIM instr / commit_pc |
| ---: | --- | --- |
| 5k | `3 / 0x10000008` | `3 / 0x10000008` |
| 10k | `458 / 0x80001cdc` | `458 / 0x80001cdc` |
| 15k | `5532 / 0x80000130` | `5532 / 0x80000130` |
| 20k | `14121 / 0x8000043a` | `14121 / 0x8000043a` |
| 25k | `20048 / 0x8000043c` | `20048 / 0x8000043c` |
| 30k | `27809 / 0x8000043a` | `27809 / 0x8000043a` |
| 35k | `35570 / 0x80000442` | `35570 / 0x80000442` |
| 40k | `43350 / 0x80000432` | `43350 / 0x80000432` |
| 45k | `52481 / 0x80001236` | `52481 / 0x80001236` |
| 50k | `73580 / 0x800012f8` | `73580 / 0x800012f8` |

最终 summary 也完全一致：

| model | instrCnt | cycleCnt | IPC | final trap pc |
| --- | ---: | ---: | ---: | --- |
| Verilator ref | `73580` | `49996` | `1.471718` | `0x80001312` |
| GrhSIM | `73580` | `49996` | `1.471718` | `0x80001312` |

但事后校验发现，这一轮使用的是默认 `build/xs` SV：`build/xs/rtl/time.log`
没有 `--preserve-aggregate`。因此该结果只能说明 lowered/default SV 路径的
ref/GrhSIM correctness baseline 通过，不能用来推翻 preserve-aggregate 路径上的
旧 50k 吞吐差异。

2026-06-10 又执行了一次从 `read_sv` 开始的 GrhSIM emu 重建和 CoreMark 50k 性能复测。
这轮同样属于默认 lowered SV baseline，而不是 preserve-aggregate：

```text
build/logs/xs/xs_wolf_grhsim_build_perf50k_rebuild_grhsim_20260610.log
build/logs/xs/xs_wolf_grhsim_perf50k_rebuild_grhsim_20260610.log
```

本次重建命令关闭 waveform、GrhSIM perf 和 commit trace，并强制不从 stats JSON resume：

```sh
make xs_wolf_grhsim_emu \
  RUN_ID=perf50k_rebuild_grhsim_20260610 \
  XS_WOLF_GRHSIM_RESUME_FROM_STATS_JSON=0 \
  WOLVRIX_GRHSIM_WAVEFORM=0 \
  WOLVRIX_GRHSIM_PERF=0 \
  XS_WAVEFORM=0 \
  XS_COMMIT_TRACE=0
```

关键生成阶段耗时：

| stage | time |
| --- | ---: |
| `read_sv` | `64647ms` |
| `xmr-resolve` | `51306ms` |
| `memory-read-retime` | `1556ms` |
| `hier-flatten` | `36385ms` |
| `comb-lane-pack` | `171177ms` |
| `comb-loop-elim` | `64541ms` |
| simplify pass 1 / 2 | `223979ms` / `22494ms` |
| `stats` | `257099ms` |
| `activity-schedule` | `143054ms` |
| `write_grhsim_cpp` | `51069ms` |
| Python emit total | `1091154ms` |

本次 schedule 规模：

```text
top_total_ops=5268574 top_compute_ops=4376838 top_declaration_ops=287282 top_values=4677017
supernodes=72653 compute_supernodes=72138 commit_supernodes=515
ops_mean=92.831 ops_median=99 ops_p90=108 ops_p99=108 compute_ops_max=108 commit_ops_max=4096
```

新 emu 的 50k 结果仍与 clean correctness baseline 的 architectural summary 一致：

| cycle | instr / commit_pc | host_ms |
| ---: | --- | ---: |
| 5k | `3 / 0x10000008` | `13236` |
| 10k | `458 / 0x80001cdc` | `29205` |
| 15k | `5532 / 0x80000130` | `65758` |
| 20k | `14121 / 0x8000043a` | `112248` |
| 25k | `20048 / 0x8000043c` | `154650` |
| 30k | `27809 / 0x8000043a` | `198749` |
| 35k | `35570 / 0x80000442` | `242847` |
| 40k | `43350 / 0x80000432` | `287035` |
| 45k | `52481 / 0x80001236` | `332622` |
| 50k | `73580 / 0x800012f8` | `387776` |

最终 summary：

```text
Core-0 instrCnt = 73580, cycleCnt = 49996, IPC = 1.471718
Seed=0 Guest cycle spent: 50001
Host time spent: 387790ms
```

与上一轮 clean GrhSIM 50k 的 `483944ms` 相比，本次从 `read_sv` 重建后的 lowered-SV
GrhSIM 50k host time 下降约 `19.87%`，吞吐约 `1.248x`；按 final host time
计算约 `128.94 cycles/s`、`189.74 instr/s`。这次复测只更新 lowered-SV
性能基线，不代表 preserve-aggregate 版本。

### Preserve-Aggregate 50k 复测

按用户要求，随后从 `read_sv` 开始重新构建 preserve-aggregate 版本，独立工作目录为：

```text
build/xs-preserve-aggregate
```

构建命令：

```sh
make xs_wolf_grhsim_emu \
  RUN_ID=preserve_aggregate_perf50k_20260610 \
  XS_WORK_BASE=build/xs-preserve-aggregate \
  SIM_ARGS='--firtool-opt --preserve-aggregate=1d-vec' \
  XS_WOLF_GRHSIM_RESUME_FROM_STATS_JSON=0 \
  WOLVRIX_GRHSIM_WAVEFORM=0 \
  WOLVRIX_GRHSIM_PERF=0 \
  XS_WAVEFORM=0 \
  XS_COMMIT_TRACE=0
```

preserve-aggregate 证据：

```text
build/xs-preserve-aggregate/rtl/time.log
  --firtool-opt --preserve-aggregate=1d-vec

build/xs-preserve-aggregate/rtl/rtl/ExuBlock.sv
  input  [1:0][63:0] io_in_5_0_bits_data_src

build/xs-preserve-aggregate/rtl/rtl/ICacheMainPipe.sv
  input  [7:0][63:0] io_dataRead_resp_datas
```

关键日志：

```text
build/logs/xs/xs_wolf_grhsim_build_preserve_aggregate_perf50k_20260610.log
build/logs/xs/xs_wolf_grhsim_preserve_aggregate_perf50k_20260610.log
```

关键生成阶段耗时：

| stage | time |
| --- | ---: |
| `read_sv` | `58028ms` |
| `xmr-resolve` | `53159ms` |
| `memory-read-retime` | `1775ms` |
| `hier-flatten` | `47132ms` |
| `comb-lane-pack` | `97560ms` |
| `comb-loop-elim` | `86408ms` |
| simplify pass 1 / 2 | `302654ms` / `23719ms` |
| `memory-init-check` | `961ms` |
| `stats` | `230004ms` |
| `activity-schedule` | `135521ms` |
| `write_grhsim_cpp` | `48011ms` |
| Python emit total | `1088431ms` |

本次 preserve-aggregate schedule 规模：

```text
top_total_ops=5093469 top_compute_ops=4353759 top_declaration_ops=231749 top_values=4595567
supernodes=70652 compute_supernodes=70145 commit_supernodes=507
ops_mean=92.450 ops_median=99.0 ops_p90=108 ops_p99=108 compute_ops_max=108 commit_ops_max=4096
```

50k 运行命令：

```sh
make run_xs_wolf_grhsim_emu \
  RUN_ID=preserve_aggregate_perf50k_20260610 \
  XS_WORK_BASE=build/xs-preserve-aggregate \
  XS_SIM_MAX_CYCLE=50000 \
  XS_PROGRESS_EVERY_CYCLES=5000 \
  XS_WAVEFORM=0 \
  XS_COMMIT_TRACE=0 \
  XS_LOG_BEGIN=0 \
  XS_LOG_END=0
```

50k progress：

| cycle | instr / commit_pc | host_ms |
| ---: | --- | ---: |
| 5k | `3 / 0x10000008` | `14476` |
| 10k | `458 / 0x80001cdc` | `31391` |
| 15k | `4505 / 0x80000116` | `64675` |
| 20k | `10424 / 0x80000a9c` | `107098` |
| 25k | `14567 / 0x8000043c` | `145910` |
| 30k | `18590 / 0x8000043c` | `184254` |
| 35k | `23094 / 0x8000042c` | `223173` |
| 40k | `27583 / 0x8000042c` | `262231` |
| 45k | `32069 / 0x8000042e` | `301245` |
| 50k | `36573 / 0x8000042a` | `340388` |

最终 summary：

```text
Core-0 instrCnt = 36573, cycleCnt = 49996, IPC = 0.731519
Seed=0 Guest cycle spent: 50001
Host time spent: 340396ms
```

该结果与最初 2026-06-09 preserve-aggregate 50k 症状一致：10k 前后一致，
15k 开始落后，50k 时提交数约为 lowered-SV/ref baseline 的一半。它说明旧吞吐差异
不是已经整体消失，而是 preserve-aggregate 路径仍可复现；之前 clean 50k 通过的是
非 preserve/default lowered SV 路径。

因此当前结论必须写成：preserve-aggregate GrhSIM 版本仍然错误，尚未达到
full CoreMark 50k correctness 通过状态；后续所有 correctness 判断都应优先使用
preserve-aggregate 独立回归结果，而不能用 lowered-SV clean baseline 代替。

性能口径也要分开看：preserve-aggregate 这次 host time 为 `340396ms`，按 cycle
计算约 `146.89 cycles/s`，比 lowered-SV 新 emu 的 `387790ms` / `128.94 cycles/s`
更快；但 preserve-aggregate 只提交 `36573` 条指令，`instr/s` 约 `107.44`，
低于 lowered-SV 的 `189.74 instr/s`。因此这次 preserve-aggregate 结果不能视为
有效性能提升，当前首要问题仍是 correctness/吞吐分叉。

### Preserve-Aggregate 20k FST

2026-06-10 按用户要求抓取了一组 preserve-aggregate 的 Verilator ref 和 GrhSIM
波形，用于后续从 FST 入手分析 10k 到 15k 之间的有效消费链路分叉。所有本轮
artifact 均放在项目内：

```text
tmp/preserve_aggregate_wave20k_20260610/
```

关键文件：

```text
tmp/preserve_aggregate_wave20k_20260610/xs_ref_preserve_aggregate_wave20k_ref_20260610.fst
tmp/preserve_aggregate_wave20k_20260610/xs_wolf_grhsim_preserve_aggregate_wave20k_grhsim_20260610.fst
tmp/preserve_aggregate_wave20k_20260610/xs_ref_preserve_aggregate_wave20k_ref_20260610.log
tmp/preserve_aggregate_wave20k_20260610/xs_wolf_grhsim_preserve_aggregate_wave20k_grhsim_20260610.log
tmp/preserve_aggregate_wave20k_20260610/xs_preserve_aggregate_rtl_time.log
tmp/preserve_aggregate_wave20k_20260610/xs_ref_wave20k_build_time.log
tmp/preserve_aggregate_wave20k_20260610/xs_wolf_grhsim_build_preserve_aggregate_wave20k_grhsim_build_20260610.log
```

文件大小：

```text
xs_ref_preserve_aggregate_wave20k_ref_20260610.fst = 3.6M
xs_wolf_grhsim_preserve_aggregate_wave20k_grhsim_20260610.fst = 172M
```

构建证据：

- `xs_preserve_aggregate_rtl_time.log` 记录了
  `--firtool-opt --preserve-aggregate=1d-vec`；
- ref `time.log` 记录了 Verilator 使用 `--x-assign unique --trace-fst`；
- GrhSIM build log 记录了 `--waveform declared-symbols` 和
  `WOLVRIX_GRHSIM_WAVEFORM=1`。

ref waveform emu 构建：

```sh
CCACHE_DIR=/home/gaoruihao/wksp/wolvrix-playground/build/xs-preserve-aggregate/ccache \
make xs_ref_emu \
  RUN_ID=preserve_aggregate_wave20k_ref_build_20260610 \
  XS_WORK_BASE=build/xs-preserve-aggregate \
  XS_WAVEFORM=1 \
  XS_EMU_THREADS=1 \
  XS_VM_BUILD_JOBS=32
```

GrhSIM waveform emu 构建：

```sh
CCACHE_DIR=/home/gaoruihao/wksp/wolvrix-playground/build/xs-preserve-aggregate/ccache \
make xs_wolf_grhsim_emu \
  RUN_ID=preserve_aggregate_wave20k_grhsim_build_20260610 \
  XS_WORK_BASE=build/xs-preserve-aggregate \
  XS_WOLF_GRHSIM_RESUME_FROM_STATS_JSON=0 \
  WOLVRIX_GRHSIM_WAVEFORM=1 \
  WOLVRIX_GRHSIM_PERF=0 \
  XS_WAVEFORM=1 \
  XS_EMU_THREADS=1 \
  XS_VM_BUILD_JOBS=32
```

ref 20k 运行：

```sh
CCACHE_DIR=/home/gaoruihao/wksp/wolvrix-playground/build/xs-preserve-aggregate/ccache \
make run_xs_ref_emu \
  RUN_ID=preserve_aggregate_wave20k_ref_20260610 \
  XS_WORK_BASE=build/xs-preserve-aggregate \
  XS_SIM_MAX_CYCLE=20000 \
  XS_PROGRESS_EVERY_CYCLES=5000 \
  XS_WAVEFORM=1 \
  XS_WAVEFORM_FULL=0 \
  XS_WAVEFORM_DIR=tmp/preserve_aggregate_wave20k_20260610 \
  XS_COMMIT_TRACE=0 \
  XS_LOG_BEGIN=0 \
  XS_LOG_END=0
```

GrhSIM 20k 运行：

```sh
CCACHE_DIR=/home/gaoruihao/wksp/wolvrix-playground/build/xs-preserve-aggregate/ccache \
make run_xs_wolf_grhsim_emu \
  RUN_ID=preserve_aggregate_wave20k_grhsim_20260610 \
  XS_WORK_BASE=build/xs-preserve-aggregate \
  XS_SIM_MAX_CYCLE=20000 \
  XS_PROGRESS_EVERY_CYCLES=5000 \
  XS_WAVEFORM=1 \
  XS_WAVEFORM_FULL=0 \
  XS_WAVEFORM_DIR=tmp/preserve_aggregate_wave20k_20260610 \
  WOLVRIX_GRHSIM_WAVEFORM=1 \
  XS_COMMIT_TRACE=0 \
  XS_LOG_BEGIN=0 \
  XS_LOG_END=0
```

本轮 20k waveform run 已复现 preserve-aggregate 分叉：

| cycle | ref instr / commit_pc | GrhSIM instr / commit_pc |
| ---: | --- | --- |
| 5k | `3 / 0x10000008` | `3 / 0x10000008` |
| 10k | `458 / 0x80001cdc` | `458 / 0x80001cdc` |
| 15k | `5532 / 0x80000130` | `4505 / 0x80000116` |
| 20k | `14121 / 0x8000043a` | `10424 / 0x80000a9c` |

最终 summary：

```text
ref:
Core-0 instrCnt = 14121, cycleCnt = 19996, IPC = 0.706191
Host time spent: 148000ms

GrhSIM:
Core-0 instrCnt = 10424, cycleCnt = 19996, IPC = 0.521304
Host time spent: 987522ms
```

结论：这组 FST 是当前后续分析的首选输入。它明确使用 preserve-aggregate RTL，
且在 15k/20k 复现了 GrhSIM 提交量落后的真实分叉；后续应从这组 FST 中沿
`io_toIfu_fetchResp_valid`、fetch queue enqueue、decode valid 或 commit 进度相关
链路定位最早有效消费分叉点。

### Preserve-Aggregate 20k Event-Level FST Finding

2026-06-10 继续分析上述 FST 时发现最初的 ref FST 只记录到 time `3`，不能用于
波形对比。因此重新跑了一份 full waveform ref：

```text
tmp/preserve_aggregate_wave20k_20260610/xs_ref_preserve_aggregate_wave20k_ref_full_20260610.fst
tmp/preserve_aggregate_wave20k_20260610/xs_ref_preserve_aggregate_wave20k_ref_full_20260610.log
```

新的 ref FST 信息：

```text
ref full FST: start=0, end=40101, timescale=-12, size ~= 131M
GrhSIM FST:  start=1, end=40102, timescale=-9,  size ~= 172M
```

full ref 运行结果仍与 preserve-aggregate 20k 复现表一致：

```text
10k: 458 / 0x80001cdc
15k: 5532 / 0x80000130
20k: 14121 / 0x8000043a
```

为了消除 timestamp/valid 相位噪声，新增了 TSV/event 对齐脚本：

```text
tmp/preserve_aggregate_wave20k_20260610/dump_xs_roi_tsv.py
```

该脚本先 dump 六组优先观察信号，再将 valid pulse 抽象成事件流，并额外做
payload identity 对齐：

- `frontend_cfvec`: lane valid 上升/持续 pulse，payload 为 `pc/instr`；
- `dispatch_enqrob`: lane valid，payload 为 `pc/instr/robIdx/ftqPtr`；
- `lsqEnq`: lane valid，payload 为 `robIdx`；
- `lsu_violation`: valid，payload 为 `robIdx`，GrhSIM 当前缺 `ftqIdx` 映射；
- `backend_redirect`: valid，payload 为 `pc/target/ftqIdx/isMisPred/debugIsMemVio`；
- `rob_commit`: `commitValid` 每 lane 事件，payload 为 `robIdx/ftqIdx`，GrhSIM 当前缺 commit PC。

事件对齐命令示例：

```sh
.venv/bin/python tmp/preserve_aggregate_wave20k_20260610/dump_xs_roi_tsv.py event-compare \
  --ref-tsv tmp/preserve_aggregate_wave20k_20260610/roi_dump_full_1_40101.ref.tsv \
  --wolf-tsv tmp/preserve_aggregate_wave20k_20260610/roi_dump_full_1_40101.wolf.tsv \
  --prefix roi_events_full_1_40101.frontend_cfvec.id128 \
  --families frontend_cfvec \
  --limit 1000 \
  --collapse-window 1 \
  --identity-lookahead 128
```

相关输出：

```text
tmp/preserve_aggregate_wave20k_20260610/roi_events_full_1_40101.frontend_cfvec.id128.events.identity.diff.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_events_full_1_40101.dispatch_enqrob.id128.events.identity.diff.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_events_full_1_40101.backend_redirect.id128.events.identity.diff.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_events_full_1_40101.rob_commit.id128.events.identity.diff.tsv
```

分析过程中还修正了 `value_nonzero()` / `bit_is_set()` 的解析 bug：旧逻辑会把
`0x1` 中的 `x` 当成 unknown，导致十六进制 valid 被误判为 false。修正后保留了
新的 semantic compare 结果：

```text
tmp/preserve_aggregate_wave20k_20260610/roi_dump_full_1_40101.semantic_fixed_offset_0.diff.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_dump_full_1_40101.semantic_fixed_offset_p1.diff.tsv
```

事件级结论如下。前 20 多个 `backend_redirect` payload 可对齐，只是 GrhSIM
整体晚 1 个 tick；因此早期差异主要是 timestamp/valid 相位噪声，不应作为根因。
去掉这类噪声后，第一处稳定分叉出现在 frontend cfVec：

| event family | side | index | time | lane | payload |
| --- | --- | ---: | ---: | ---: | --- |
| `frontend_cfvec` | ref | 1589 | 20828 | 4 | `pc=0x800027d0, instr=0x413` |
| `dispatch_enqrob` | ref | 1071 | 20832 | 4 | `pc=0x800027d0, instr=0x413, robIdx=0x70, ftqPtr=0x38` |
| `backend_redirect` | ref | 23 | 20852 | 0 | `pc=0x800027c2, target=0x800027b8, ftqIdx=0x38` |
| `rob_commit` | ref | 1016 | 20856 | 0 | `pc=0x80001f66, robIdx=0xb0, ftqIdx=0x24` |

分叉窗口内的 frontend cfVec 形态：

```text
ref:
20828: 0x800027c2, 0x800027c6, 0x800027ca, 0x800027cc,
       0x800027d0, 0x800027d2, 0x800027d6, 0x800027da
20830: 0x800027de, 0x800027e2

GrhSIM:
20829: 0x800027c2, 0x800027c6, 0x800027ca, 0x800027cc
20833: 0x800027b8, 0x800027ba, 0x800027bc, 0x800027be, 0x800027c0
20835: 0x8000276a
20837: 0x8000276e
20839: 0x80001c96
20841: 0x80001cd6, 0x80001cd8, 0x80001cdc, 0x80001ce0
```

即：两边在 `0x800027c2/0x800027c6/0x800027ca/0x800027cc` 之前仍可对齐；
随后 ref 继续 fall-through 到 `0x800027d0...`，而 GrhSIM 转到 `0x800027b8...`。
同一分叉随后进入 `dispatch_enqrob`，再往后体现为 `rob_commit.ftqIdx` 差异。
因此 ROB/commit 更像下游结果，不是当前首疑根因。

当前首疑模块族应从 ROB/LSU 下调，转向 frontend 的 FTQ / BPU 预测与 redirect
处理路径，重点关注 `20720..20860` 附近：

- FTQ entry 中 `pc=0x800027c2`、target `0x800027b8`、`ftqIdx=0x38/0x39`
  的生成和更新；
- backend redirect 到 frontend/FTQ 的消费时序；
- frontend 是否因 preserve-aggregate 后的状态/entry 更新差异，提前采用了 target；
- BPU/FTQ 对 `0x800027c2` 附近控制流的预测方向、target 和 entry 状态。

### FTQ Input Boundary Expansion

2026-06-10 进一步按 FTQ 输入边界扩展 dump，目标是判断前面看到的
`frontend_cfvec` 分叉是否是在 FTQ 内部相同输入下产生，还是 FTQ 输入流本身已经
分叉。新增观察组覆盖三类 FTQ 输入：

- BPU -> FTQ：`prediction.valid/ready/startPc/target/takenCfiOffset/s3Override`
  以及 `s3FtqPtr.flag/value`；
- IFU -> FTQ：`wbRedirect.valid/pc/target/ftqIdx/ftqOffset/taken/branchType/rasAction`；
- backend -> FTQ：`commit`、`ftqIdxAhead`、`resolve[0..2]`，以及共用的
  `backend_redirect`。

相关 full-window TSV 和事件输出如下：

```text
tmp/preserve_aggregate_wave20k_20260610/roi_ftq_input_full_1_40101.ref.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_ftq_input_full_1_40101.wolf.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_ftq_input_full_1_40101.manifest.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_ftq_input_full_1_40101.ftq_inputs.fire.events.identity.diff.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_ftq_input_full_1_40101.ftq_bpu.fire.events.identity.diff.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_ftq_input_full_1_40101.ftq_backend.fire.events.identity.diff.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_ftq_input_full_1_40101.ftq_ifu.fire.events.identity.diff.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_ftq_input_full_1_40101.semantic_fire_s3flag_offset_p1.diff.tsv
```

BPU -> FTQ 的事件提取已改为只在 `prediction.fire = valid && ready` 时记录，
避免把 `ready=0` 时的 payload 抖动当成 FTQ 输入交易。`s3FtqPtr.value` 的
逐列 semantic compare 也只在两边 `s3FtqPtr.flag` 同时有效时比较；否则
ref 侧 value 会在 flag 为 0 时变化，而 Wolf 侧为 0，容易形成无效噪声。

full-window 事件计数：

| event family | ref count | GrhSIM count |
| --- | ---: | ---: |
| `ftq_bpu_prediction` | 8344 | 8486 |
| `ftq_backend_commit` | 3593 | 2749 |
| `ftq_backend_redirect` | 308 | 408 |
| `ftq_backend_resolve` | 4421 | 4010 |
| `ftq_ifu_wbRedirect` | 159 | 145 |

端口级 raw 输入并非完全一致：例如 `ftq_bpu_input.s3FtqPtr_flag` 在 ref time
`17596` 已出现 ref `1` / GrhSIM `0`。但在这一段 `s3Override=0`，根据
`testcase/xiangshan/src/main/scala/xiangshan/frontend/ftq/Ftq.scala`，FTQ 只在
`prediction.bits.s3Override` 时用 `io.fromBpu.s3FtqPtr` 覆盖 `predictionPtr`，
因此该 raw flag 差异暂不作为第一功能根因。

只看 FTQ 真正消费的 BPU prediction 交易，最早可证明的语义不等价发生在
ref time `20820`，早于前面看到的 `frontend_cfvec` ref time `20828` 分叉：

| family | side | index | time | payload |
| --- | --- | ---: | ---: | --- |
| `ftq_bpu_prediction` | ref | 690 | 20820 | `startPc=0x400013f8, target=0x40001410, takenValid=0, takenOffset=0x17, s3Override=0` |
| nearest GrhSIM | wolf | 690 | 20821 | `startPc=0x400013dc, target=0x400013b5, takenValid=1, takenOffset=0x4, s3Override=0` |

后续 backend -> FTQ 输入也出现不等价，但时间更晚：

| family | side | index | time | payload |
| --- | --- | ---: | ---: | --- |
| `ftq_backend_resolve` | ref | 287 | 20848 | `pc=0x400013e1, ftqIdx=0x38, target=0x400013dc, taken=1, ftqOffset=0x6, isMisPred=1` |
| nearest GrhSIM | wolf | 286 | 20845 | `pc=0x400013dc, ftqIdx=0x39, target=0x400013b5, taken=1, ftqOffset=0x4, isMisPred=0` |
| `ftq_backend_redirect` | ref | 23 | 20852 | `pc=0x800027c2, ftqIdx=0x38, target=0x800027b8, isMisPred=1` |

IFU -> FTQ `wbRedirect` 在 20820 附近仍没有首个 unmatched identity 差异；单独
比较该 family 时，最早明显不匹配出现在 ref time `25658`，属于后续分叉结果。

因此当前结论应修正为：FTQ 的输入并不完全等价。更具体地说，在可见
`frontend_cfvec` 输出分叉前，BPU -> FTQ 的 `prediction.fire` 输入交易已经分叉；
backend -> FTQ 的 resolve/redirect 差异随后出现。当前证据不支持“FTQ 在相同输入下
产生不同输出”作为第一结论，下一步应沿 BPU 输入、BPU/FTQ feedback、redirect/train
更新路径继续往前追，优先窗口为 ref `20718..20824` / GrhSIM `20719..20825`。

暂不把 `lsu_mem.violation_valid` 作为首因证据：当前 GrhSIM 映射使用的是
`mem_redirect`，而 ref 使用 `fromMem_violation`，语义可能不完全等价；其早期差异
更适合作为二级排查信号。

### Frontend Input Boundary Expansion

2026-06-10 继续把观察边界上移到 `Frontend` 模块输入。目标是回答：
BPU -> FTQ 输入交易在 ref time `20820` 已分叉，是否可能是更上层
`FrontendIO` 输入从仿真起点开始就不一致导致。

本轮新增 `frontend_input` dump group，只比较 `Frontend` 边界输入，不混入
`cfVec/fromFtq/fromIfu/stallReason` 这些 Frontend 输出。主要覆盖：

- `reset_vector`、`fencei`、`sfence`；
- `tlbCsr`、`csrCtrl`；
- `backend.canAccept`、`backend.wfi.wfiReq`；
- `backend.toFtq.commit/ftqIdxAhead/redirect/resolve/callRetCommit`。

由于两边 FST 时间范围不同，ref full FST 是 `0..40101`，GrhSIM FST 是
`1..40102`，主比较采用 `wolf_time = ref_time + 1`。对应产物：

```text
tmp/preserve_aggregate_wave20k_20260610/roi_frontend_input_full_0_40102.ref.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_frontend_input_full_0_40102.wolf.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_frontend_input_full_0_40102.diff.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_frontend_input_full_0_40102.semantic_offset_p1.diff.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_frontend_input_full_0_40102.manifest.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_frontend_input_full_0_40102.missing.tsv
```

解析覆盖情况：

- ref 解析到 `144` 个 `frontend_input` 信号；
- GrhSIM 解析到 `126` 个 `frontend_input` 信号；
- 缺失的 `18` 个均为 Wolf 侧 direct `frontend.io_*` 边界网：
  `hartId`、`softPrefetch[0..2]`、`ptw.req(0).ready`、`ptw.resp.valid/bits`。

missing 信号对本次首因判断的影响有限：在 ref time `0..20820` 内，
`softPrefetch[0..2].valid` 和 `ptw_resp_valid` 一直为 `0`；
`ptw_req_0_ready` 一直为 `1`；`hartId` 是静态输入，Wolf FST 没有直接边界网。

`semantic-compare --wolf-time-offset 1` 的结果：

- ref time `0..20820` / GrhSIM time `1..20821` 内，已解析的 `Frontend`
  输入没有任何 semantic mismatch；
- 第一条 `Frontend` 输入边界差异出现在 ref time `20844` / GrhSIM time
  `20845`：

| ref time | GrhSIM time | signal | ref | GrhSIM |
| ---: | ---: | --- | --- | --- |
| `20844` | `20845` | `frontend_input.toFtq_resolve_1_valid` | `0x0` | `0x1` |
| `20845` | `20846` | `frontend_input.toFtq_resolve_1_valid` | `0x0` | `0x1` |
| `20848` | `20849` | `frontend_input.toFtq_resolve_2_mispredict` | `0x1` | `0x0` |
| `20850` | `20851` | `frontend_input.toFtq_ftqIdxAhead_0_valid` | `0x1` | `0x0` |
| `20852` | `20853` | `frontend_input.toFtq_redirect_valid` | `0x1` | `0x0` |

这说明可见的 `Frontend` 顶层输入并不是从仿真起点开始就不同。相反，在
BPU -> FTQ `prediction.fire` 分叉点 ref time `20820` 之前，已解析的
Frontend 输入保持一致；后续 `backend.toFtq.resolve/redirect` 的输入差异更晚，
应视为 frontend/BPU/FTQ 分叉进入 backend 后的反馈结果。

因此当前怀疑边界应收窄到 `Frontend` 内部，尤其是 BPU 自身输入/状态、
BPU 从 FTQ 收到的 feedback、以及 BPU pipeline 内部预测状态。下一步不应只看
FTQ/BPU 输出，而应从 BPU 输入侧继续扩展，验证 `Bpu.io.fromFtq`、CSR control
延迟后的 BPU 输入、redirect/train/update 相关 internal state 在
ref `20718..20824` / GrhSIM `20719..20825` 是否一致。

### BPU Boundary Recheck

2026-06-10 继续把边界收窄到 `Bpu` 模块可见端口，复核“BPU 输入未分叉时，
BPU 输出是否已经先分叉”。新增 `bpu_boundary` dump group，主比较仍采用
`wolf_time = ref_time + 1`，对应产物：

```text
tmp/preserve_aggregate_wave20k_20260610/roi_bpu_boundary_full_0_40102.ref.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_bpu_boundary_full_0_40102.wolf.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_bpu_boundary_full_0_40102.diff.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_bpu_boundary_full_0_40102.semantic_offset_p1.diff.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_bpu_boundary_full_0_40102.manifest.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_bpu_boundary_full_0_40102.missing.tsv
```

解析覆盖情况：

- ref 解析到 `233` 个 `bpu_boundary` 信号；
- GrhSIM 解析到 `228` 个 `bpu_boundary` 信号；
- 缺失映射共 `9` 条：两边均缺 `input_ctrl_rasEnable`、
  `input_fromFtq_redirectFromIFU`；Wolf 侧缺
  `input_fromFtq_train_meta_sc_scGlobalResp_[0..1]`、
  `input_fromFtq_train_meta_sc_scBWResp_[0..1]`、
  `input_fromFtq_train_meta_sc_debug_predBWIdx`。

这些缺口需要保留为限制条件：本节结论只覆盖当前 FST 已解析的 BPU 可见边界，
并不证明 BPU 内部 predictor SRAM/table/register state 完全一致。不过从
`Bpu.scala` 的使用看，`redirectFromIFU` 未被 BPU 主逻辑直接引用；SC meta 缺失
只影响 train feedback 侧的部分字段，且 train feedback 的首个有效分叉晚于
本节关注的首个 consumed prediction 分叉。

raw-wire 口径下，首个 BPU 输出 bus 差异出现在 ref time `20722` /
GrhSIM time `20723`：

| ref time | GrhSIM time | signal | ref | GrhSIM |
| ---: | ---: | --- | --- | --- |
| `20722` | `20723` | `bpu_boundary.output_toFtq_prediction_s3Override` | `0x1` | `0x0` |
| `20722` | `20723` | `bpu_boundary.output_toFtq_prediction_startPc_addr` | `0x400013e1` | `0x400013dc` |
| `20722` | `20723` | `bpu_boundary.output_toFtq_prediction_takenCfiOffset_bits` | `0x11` | `0x4` |
| `20722` | `20723` | `bpu_boundary.output_toFtq_prediction_target_addr` | `0x400013f8` | `0x400013b5` |

在这个 raw 输出差异之前，已解析 BPU input/output raw diff 计数为：

```text
input_pre20722=0
output_pre20722=0
```

但 ref `20722` / GrhSIM `20723` 时，两边
`output_toFtq_prediction_valid=1`、`input_prediction_ready=0`，FTQ 没有消费
这条 prediction payload。因此该点只能说明 BPU 输出线上已经出现不同值，不能直接
作为 FTQ 输入交易分叉。

semantic/fire 口径只在 `prediction.fire = valid && ready` 时比较
`output_toFtq_prediction_*` payload，并对 redirect/train/commit 等 payload 做
valid/fire gating。该口径下，首个已消费 BPU prediction 输出分叉出现在
ref time `20820` / GrhSIM time `20821`：

| ref time | GrhSIM time | signal | ref | GrhSIM |
| ---: | ---: | --- | --- | --- |
| `20820` | `20821` | `bpu_boundary.output_toFtq_prediction_startPc_addr` | `0x400013f8` | `0x400013dc` |
| `20820` | `20821` | `bpu_boundary.output_toFtq_prediction_takenCfiOffset_bits` | `0x17` | `0x4` |
| `20820` | `20821` | `bpu_boundary.output_toFtq_prediction_takenCfiOffset_valid` | `0x0` | `0x1` |
| `20820` | `20821` | `bpu_boundary.output_toFtq_prediction_target_addr` | `0x40001410` | `0x400013b5` |

到 ref time `20820` 为止的 semantic diff 计数为：

```text
total_le_20820=4
input_le_20820=0
output_le_20820=4
prediction_output_le_20820=4
```

也就是说，在首个 consumed prediction 输出分叉之前，已解析的 BPU 输入边界没有
semantic mismatch。第一条 BPU 输入边界 semantic mismatch 更晚，出现在
ref time `20832` / GrhSIM time `20833`：

| ref time | GrhSIM time | signal | ref | GrhSIM |
| ---: | ---: | --- | --- | --- |
| `20832` | `20833` | `bpu_boundary.input_prediction_ready` | `0x1` | `0x0` |

结论：当前证据支持“在已解析/可见 BPU 输入未分叉的前提下，BPU 输出先分叉”。
更精确地说，BPU raw 输出 bus 在 ref `20722` / GrhSIM `20723` 已先出现不同，
但当时未被 FTQ 消费；第一条被 FTQ 消费的 BPU prediction 交易在
ref `20820` / GrhSIM `20821` 分叉，而首个已解析 BPU 输入 semantic mismatch
晚到 ref `20832` / GrhSIM `20833`。因此当前首疑应继续收敛到 BPU 内部状态或
BPU 内部 predictor/update 逻辑在 preserve-aggregate/GrhSIM 路径下的语义差异，
而不是 FTQ 在相同 BPU 输入交易下自行产生不同输出。

### TAGE Train/Write SetIdx Divergence

2026-06-10 继续从 BPU 内部往子模块卡差异。此前已把 BPU raw 输出最早分叉压到
TAGE lane3：

| ref time | GrhSIM time | signal | ref | GrhSIM |
| ---: | ---: | --- | --- | --- |
| `20720` | `20721` | `bpu_top_state.s2_takenMask` | `0x80` | `0x88` |
| `20720` | `20721` | `tage_io_prediction_3_useProvider` | `1` | `0` |
| `20720` | `20721` | `s2_branch_3_table_0_result_hit` | `1` | `0` |
| `20720` | `20721` | `s2_readResp_0_entries_0_valid/tag/takenCtr` | `1/0x9/0x3` | `0/0/0` |

进一步看 `TageTable(0)` 后，ref/Wolf 在预测读地址上是等价的：

```text
ref 20718 / GrhSIM 20719:
predictReadBankMaskNext = 0x2
predictReadSetIdxNext   = 0xfc
```

但 table0 bank1 way0 的读响应不同：ref 读出 `{valid=1, tag=0x9, takenCtr=0x3}`，
GrhSIM 读出 invalid/0。继续回溯 table0 写历史后发现，正确 entry 在 ref 侧写到了
`setIdx=0xfc`，而 GrhSIM 侧同一 entry 写到了 `setIdx=0x0`：

```text
ref 19474..19479:
  table0.writeReq setIdx=0xfc bankMask=0x2 wayMask=0x1
  entry0 valid=1 tag=0x9 takenCtr=0x3
  final SRAM write b1/w0 addr=0xfc wdata=0x1004b

GrhSIM 19475..19480:
  table0.writeReq setIdx=0x0 bankMask=0x2 wayMask=0x1
  entry0 valid=1 tag=0x9 takenCtr=0x3
  final SRAM write b1/w0 addr=0x0 wdata=0x1004b
```

本轮新增 `bpu_tage_train_top` dump group，把 `Bpu.io.fromFtq.train`、TAGE train
pipeline 顶层状态、allocation/update 决策、8 张 TAGE table 的写口 setIdx 放到
同一张 TSV 中。产物：

```text
tmp/preserve_aggregate_wave20k_20260610/roi_bpu_tage_train_top_19468_19482.ref.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_bpu_tage_train_top_19468_19482.wolf.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_bpu_tage_train_top_19468_19482.semantic_offset_p1.diff.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_bpu_tage_train_top_tables_19468_19482.ref.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_bpu_tage_train_top_tables_19468_19482.wolf.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_bpu_tage_train_top_tables_19468_19482.semantic_offset_p1.diff.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_bpu_tage_train_top_deep_19468_19482.ref.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_bpu_tage_train_top_deep_19468_19482.wolf.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_bpu_tage_train_top_deep_19468_19482.semantic_offset_p1.diff.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_bpu_tage_train_top_deep_19468_19482.manifest.tsv
tmp/preserve_aggregate_wave20k_20260610/roi_bpu_tage_train_top_deep_19468_19482.missing.tsv
```

随后又把 `bpu_tage_train_top` 扩展到更完整的 TAGE 顶层状态：`t1/t2` branch/meta、
`t2_readResp`、所有 branch x table 的 trainInfoVec、8 张 table 的 `io.writeReq`
和 table 内部寄存后的 `writeReq` payload。该 deep dump 在窗口 `19468..19482`
内解析到 ref `925` 列、GrhSIM `890` 列；raw mismatch `118` 条，但按
`t2_fire`、`writeWayMask_tableN`、table write valid 做 semantic gating 后只剩
4 条有效差异：

```text
ref_time  wolf_time  signal                                             ref   GrhSIM
19474     19475      table0_io_writeReq_bits_setIdx                     0xfc  0x0
19475     19476      table0_io_writeReq_bits_setIdx                     0xfc  0x0
19476     19477      table0_writeReq_setIdx                             0xfc  0x0
19477     19478      table0_writeReq_setIdx                             0xfc  0x0
```

关键对齐结果如下，仍使用 `wolf_time = ref_time + 1`：

| ref time | GrhSIM time | field | ref | GrhSIM |
| ---: | ---: | --- | --- | --- |
| `19474` | `19475` | `t2_fire` | `1` | `1` |
| `19474` | `19475` | `t2_startPc_addr` | `0x400013e1` | `0x400013e1` |
| `19474` | `19475` | `t2_bankMask` | `0x2` | `0x2` |
| `19474` | `19475` | `t2_needAllocate/t2_allocate` | `1/1` | `1/1` |
| `19474` | `19475` | `t2_allocateTableOH/t2_allocateWayOH` | `0x1/0x1` | `0x1/0x1` |
| `19474` | `19475` | `writeWayMask_table0` | `0x1` | `0x1` |
| `19474` | `19475` | `table0.io_writeReq.bits.setIdx` | `0xfc` | `0x0` |
| `19474` | `19475` | `table0.io_writeReq.bits.bankMask` | `0x2` | `0x2` |
| `19474` | `19475` | `table0.entry0 valid/tag/takenCtr` | `1/0x9/0x3` | `1/0x9/0x3` |
| `19476` | `19477` | `table0.writeReqValid` | `1` | `1` |
| `19476` | `19477` | `table0.writeReq_setIdx` | `0xfc` | `0x0` |
| `19476` | `19477` | `table0.writeReq entry0 valid/tag/takenCtr` | `1/0x9/0x3` | `1/0x9/0x3` |

同一窗口中，TAGE `t0_setIdx` 在 ref/Wolf 对齐后完全一致。例如 ref `19474` /
GrhSIM `19475`：

```text
t0_setIdx packed = 0xf52021ac82b9df2f9
unpacked table[0..7] = 0xf9,0xf9,0xe7,0x105,0x1ac,0x10,0x148,0x1e
```

对应的 `table.io_writeReq.bits.setIdx` 在 ref 侧为下一条 train/update pipeline
已经推到 t2 的 setIdx：

```text
ref table[0..7].io_writeReq.bits.setIdx =
  0xfc,0x1c,0x59,0x160,0x1cb,0xa4,0x1f6,0x133

GrhSIM table[0..7].io_writeReq.bits.setIdx =
  0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0
```

上面 table[0..7] 的 `io_writeReq.bits.setIdx` 是 raw payload 口径。deep semantic
compare 进一步确认，在这个窗口真正被 `writeWayMask` 选中的有效写入只有 table0；
table1..7 的 raw setIdx 为 0 暂不能作为消费差异，只能说明未选中 table 的 payload
也暴露了同一类边界症状。有效根因链路仍以 table0 为准。

因此当前证据链已经收敛为：

1. BPU 边界输入在首个 consumed prediction 分叉前没有已解析 semantic mismatch；
2. BPU 输出先分叉，首个可见根因落在 TAGE lane3 `useProvider`；
3. lane3 `useProvider` 分叉来自 table0 prediction read response 不同；
4. table0 prediction read request 地址相同，差异来自 table 内容；
5. table 内容差异来自更早的 train/write：正确 entry 的 payload 相同，但 GrhSIM
   写到了错误 setIdx `0x0`；
6. TAGE 顶层 train control/allocate/writeWayMask/entry payload 对齐，`t0_setIdx`
   也对齐；有效差异集中在 `tables_0.io_writeReq.bits.setIdx` 以及随后
   `TageTable(0).writeReq.setIdx`，GrhSIM 侧均为 `0x0`。

当前最可疑的实现形态是 `testcase/xiangshan/src/main/scala/xiangshan/frontend/bpu/tage/Tage.scala`
里的 train setIdx pipeline 和 table writeReq 连接：

```scala
private val t1_setIdx = RegEnable(t0_setIdx, t0_fire)
private val t2_setIdx = RegEnable(t1_setIdx, t1_fire)

table.io.writeReq.bits.setIdx := t2_setIdx(tableIdx)
```

需要注意的是，Wolf FST 没有直接保留 `t1_setIdx` / `t2_setIdx` / `t2_rawTag`，
所以目前还不能区分是 `t1/t2_setIdx` aggregate register 本身被错误更新为 0，
还是 `t2_setIdx(tableIdx)` 连接到各 `TageTable.writeReq.bits.setIdx` 时被错误展开。
但已经可以排除 TAGE 顶层 train 输入、allocation 选择、bankMask、writeWayMask 和 entry
payload 作为第一差异；下一步应围绕 `RegEnable(Vec[UInt])`、packed aggregate
寄存器/索引、以及 preserve-aggregate 下跨模块 bundle field 连接生成最小 case。

2026-06-10 继续沿 `t2_setIdx -> tables_N.io_writeReq.bits.setIdx` 复核 RTL、
post-transform IR 和 GrhSIM emit。结论进一步收敛：问题不是运行时 table 索引跑偏，
而是承载 `t2_setIdx[0..7]` 的 8x9 状态在 GrhSIM/post-transform 产物中没有写端。

RTL 侧连接是正确的：

```text
build/xs-preserve-aggregate/rtl/rtl/Tage.sv

line 4917: reg [7:0][8:0] t1_setIdx;
line 5012: reg [7:0][8:0] t2_setIdx;
line 25139: t1_setIdx <= t0_setIdx;
line 25900: t2_setIdx <= t1_setIdx;
line 26808: .io_writeReq_bits_setIdx (t2_setIdx[3'h0])
```

GrhSIM emit 中 table0 的 `io_writeReq_bits_setIdx` 被实现为匿名 memory
`_op_551990` 的 read port：

```text
build/xs-preserve-aggregate/grhsim/grhsim_emit/grhsim_SimTop_sched_8.cpp:310967

// op _op_551992 [kMemoryReadPort] mem=_op_551990
// value ...$tage$tables_0$io_writeReq_bits_setIdx -> value_u16_slots_[3845]
const auto next_value =
  state_mem__op_551990_264313_[(value_u8_slots_[1584] & 7u)];
```

对应索引槽是初始化常量，不是动态误更新：

```text
value_u8_slots_[1584] = 0  -> table0
value_u8_slots_[1844] = 1  -> table1
value_u8_slots_[1845] = 2  -> table2
value_u8_slots_[1846] = 3  -> table3
value_u8_slots_[2975] = 4  -> table4
value_u8_slots_[1847] = 5  -> table5
value_u8_slots_[1886] = 6  -> table6
value_u8_slots_[146]  = 7  -> table7
```

关键异常是 `_op_551990` 只有声明、初始化和 8 个 read port，没有任何 runtime write/fill：

```text
grhsim_SimTop.hpp:1091
  std::array<std::uint16_t, 8> state_mem__op_551990_264313_ = {};

grhsim_SimTop_state_init_7.cpp:4761
  state_mem__op_551990_264313_ = {};

rg 'state_mem__op_551990_264313_'
  only 8 read sites + init + declaration
```

post-transform stats 也显示 `_op_551990` 已经缺写端，而不是 C++ emit 单独漏写：

```text
build/xs-preserve-aggregate/grhsim/wolvrix_xs_post_stats.json

_op_551990 kind=kMemory row=8 width=9 loc=Tage.sv:26808
_op_551992 kind=kMemoryReadPort mem=_op_551990 -> tables_0.io_writeReq_bits_setIdx
_op_628281 kind=kMemoryReadPort mem=_op_551990 -> tables_1.io_writeReq_bits_setIdx
...
_op_1086015 kind=kMemoryReadPort mem=_op_551990 -> tables_7.io_writeReq_bits_setIdx

no kMemoryFillPort/kMemoryWritePort for _op_551990
```

另外，post-stats 中 `t0_setIdx` 仍作为 72-bit logic 存在，并直接驱动
`tables_0.io_trainReadReq_bits_setIdx`；但 `t1_setIdx` / `t2_setIdx` 名称已经不存在。
这说明 preserve-aggregate 路径把 `t2_setIdx(tableIdx)` 选择降成了匿名 8-row memory
read，却没有保留 `t2_setIdx <= t1_setIdx` 的时序更新。由此可以直接解释 GrhSIM
在有效 train write 时把 table0 写到 `setIdx=0x0`：`_op_551990[0]` 从复位后一直保持
初始化值 0。

当前怀疑点应从 BPU/FTQ 功能逻辑转移到 Wolvrix preserve-aggregate transform/IR
阶段：`RegEnable(Vec[UInt])` 或 packed aggregate reg 被跨模块 indexed field 使用时，
read port 保留下来了，但对应 register update/write port 被 DCE、aggregate lowering
或 memory materialization 阶段丢失。下一步最小验证建议是提取一个
`Vec[8] UInt(9.W)` 的两级 `RegEnable`，同时包含 `trainReadReq` 组合 slice 和
`writeReq := t2_vec(idx)` 跨实例连接，检查 post-stats 是否复现“anonymous memory
only-read no-write”。

## 已提取和验证的 xs-bugcase

本轮围绕完整 XiangShan 问题提取了多个局部 case。`CASE_009` 到 `CASE_019`
均未复现完整 50k 的吞吐差异；`CASE_020` 已复现一个更局部的 ICache data
response 差异，且该差异与完整 FST 中 cycle `8313` 附近看到的 bank data 分叉形态一致。
后续 response consumption FST 已确认该差异没有进入有效 IFU response，因此
`CASE_020` 目前只证明 GrhSIM 与 Verilator `--x-assign unique` 在 invalid/X read
data 上存在语义差异，不能作为完整 CoreMark 吞吐差异根因。

| case | RTL / 模块 | 覆盖点 | 当前结论 |
| --- | --- | --- | --- |
| `CASE_009` | `OldestArbiterResetCase009.sv` | reset/fill 相关调度 | 已通过，支持 reset/fill 方向修复 |
| `CASE_010` | `PackedWideMemoryFillCase010.sv` | packed aggregate memory fill | 已通过，支持 aggregate fill 修复 |
| `CASE_011` | `PackedAggregateBitSelectCase011.sv` | packed aggregate bit select | 已通过 |
| `CASE_012` | `PackedAggregateMixedSelectCase012.sv` | mixed aggregate select | 已通过 |
| `CASE_013` | 完整 `OldestArbiter.sv` | 完整 OldestArbiter，而非小模块 | 已通过，OldestArbiter 单体不再可疑 |
| `CASE_014` | `RenameTableWrapper.sv` 及依赖 | rename table aggregate/reset/write 交互 | 已通过，对 ingest aggregate 修复有指导意义 |
| `CASE_015` | 完整 `ICacheReplacer.sv` | PLRU state packed array、动态索引、整数组赋值 | 已通过 |
| `CASE_016` | 完整 `ICacheWayLookup.sv` | queue entry、read/write ready-valid、bypass、flush、updateStall、exception entry | 已通过 |
| `CASE_017` | 完整 `ICacheMainPipe.sv` + `Arbiter2_MissReqBundle.sv` | `s0_canGo`、`io_req_ready`、`io_wayLookupRead_ready`、data read ready、respStall、flush、missReq | 已通过 |
| `CASE_018` | 完整 `ICacheMainPipe.sv` + 完整 `ICacheWayLookup.sv` + `Arbiter2_MissReqBundle.sv` | 真实 `MainPipe <-> WayLookup` read/ready 闭环、WayLookup bypass/queue/write/update、data/miss stub | 已通过 |
| `CASE_019` | 完整 `ICacheMissUnit.sv` + 完整 `ICacheWayLookup.sv` + MSHR/arbiter 依赖 | fetch miss、MSHR acquire、两拍 grant、refill response、meta/data write、WayLookup update/read | 已通过 |
| `CASE_020` | `ICacheDataBank_5.sv` + `SRAMTemplate_16` / `array_256x66` | bank5 way0 read response，reset scrub 后读 set `0x73`，`--x-assign unique` 下 SRAM invalid/X 输出选择 | 已复现 X policy 差异：ready 控制一致，但 `resp_data` ref 非零、GrhSIM 为 0；完整 FST 显示未进入有效 IFU response，已降级为兼容性问题 |

`CASE_015` 的 `ICacheReplacer.sv` 与完整 XiangShan 输入文件完全一致：

```text
testcase/xs-bugcase/CASE_015/rtl/ICacheReplacer.sv
build/xs/rtl/rtl/ICacheReplacer.sv
sha256 = 4a3132f45f9d83c017f21b7f7a0fa309a4b1fe143d7958e10fb0047663cc5862
```

`CASE_015` 覆盖的是内部 aggregate：

```systemverilog
reg  [127:0][2:0] state_vec;
reg  [127:0][2:0] state_vec_1;
```

它不是 aggregate port case，但能覆盖 ICacheReplacer 本体里的 packed array state、dynamic
index、assignment pattern 和 whole-array assignment。该 case 通过后，当前没有证据支持
“ICacheReplacer 状态错导致 ICache 退化成只有 1 个 way”。

`CASE_016` 是本轮新增的完整 `ICacheWayLookup` 单测：

```sh
make -C testcase/xs-bugcase/CASE_016 run
```

结果：

```text
[PASS] CASE_016 ICacheWayLookup ref == grhsim
```

这说明 `ICacheWayLookup` 单体的 aggregate entry、queue 指针、bypass、flush、update
和 read payload 在当前 testbench 下没有暴露 GrhSIM / Verilator 差异。

`CASE_017` 是完整 `ICacheMainPipe` 单测：

```sh
make -C testcase/xs-bugcase/CASE_017 run
```

结果：

```text
[PASS] CASE_017 ICacheMainPipe ref == grhsim
```

该 case 覆盖 `s0_canGo = data_ready & way_valid & s1_ready`、`io_req_ready`、
`io_wayLookupRead_ready = s0_fire`、data read request、resp stall、flush、
miss request/backpressure 和受控 miss response。它没有接入真实 `ICacheWayLookup`
queue，因此通过后只能排除 `ICacheMainPipe` 单体逻辑/emit 的明显差异，不能排除
`MainPipe <-> WayLookup` 跨模块 ready-valid 固定点调度差异。

`CASE_018` 是 `ICacheMainPipe + ICacheWayLookup` 组合单测：

```sh
make -C testcase/xs-bugcase/CASE_018 run
```

结果：

```text
[PASS] CASE_018 ICacheMainPipe+ICacheWayLookup ref == grhsim
```

该 case 将真实 `WayLookup.io_read_*` 接到真实 `MainPipe.io_wayLookupRead_*`，
外部只 stub data read response、miss response 和 frontend request。TB 用 Verilator
低电平采样的 `way_read_ready/read_valid/write_ready` 更新本地 pending 队列，覆盖
empty+bypass、队列蓄积、data_ready/respStall 造成的 read backpressure、write/update
和 flush。组合 case 通过后，`MainPipe <-> WayLookup` read/ready 闭环不再是第一怀疑点。

`CASE_019` 是 `ICacheMissUnit + ICacheWayLookup` 组合单测：

```sh
make -C testcase/xs-bugcase/CASE_019 run
```

结果：

```text
[PASS] CASE_019 ICacheMissUnit+ICacheWayLookup ref == grhsim
```

该 case 将真实 `MissUnit.io_resp_*` 接到真实 `WayLookup.io_update_*`，
外部 TB 驱动 fetch miss、victim way、`memAcquire.ready`，捕获 `memAcquire.source`
后回灌两拍 TileLink grant，并比较 refill response、meta/data write、WayLookup
read payload 和关键 ready/valid。该组合 case 通过后，受控 `MissUnit` refill/update
到 `WayLookup` 的闭环不再是第一怀疑点。

`CASE_020` 是本轮按 FST 分叉点提取的 `ICacheDataBank_5` 单测：

```sh
make -C testcase/xs-bugcase/CASE_020 run
```

结果：

```text
[MISMATCH] cycle=279 phase=low rv=1 rs=0x73 rwm=0x1 wv=0 ws=0x00 wwm=0x0 wd=0x0000000000000000 wc=0 read_ready ref=1 grhsim=1 write_ready ref=1 grhsim=1 resp_data ref=0xb3203c9bd08fe8e2 grhsim=0x0000000000000000 resp_code ref=0 grhsim=0
```

该 case 的关键点是 Verilator ref 使用完整仿真一致的 `--x-assign unique`。在没有
该选项时，单独下钻到 SRAM 层可能无法复现完整仿真的 ref 行为；加上该选项后，
Verilator 会把 invalid/X 路径选择成确定的非零值，而当前 GrhSIM 在同一路径上输出 0。
反向验证也成立：使用 `EXTRA_VFLAGS="--x-assign 0"` 运行 `CASE_020` 时，该 case 通过，
说明 mismatch 的直接原因是 X assignment policy，而不是 bank ready/valid 控制或
SRAM 地址控制不同。

## 2026-06-10 FST/CASE_020 新发现

当前 FST 结论不应理解为“FST 不可信”。GrhSIM 和 Verilator 的 FST 都是有效证据；
差别主要在于两个仿真器导出的可见信号范围、层级命名和 X 展示方式不同。因此后续
应继续以 waveform 为主，而不是再侵入式修改 XiangShan 或 difftest 打印。

本轮对完整 20k CoreMark FST 做了 ICache data read 方向下钻，相关 artifact：

```text
build/logs/xs/roi_icache_dataread_ref_20260610.ai.md
build/logs/xs/roi_icache_dataread_grh_20260610.ai.md
build/logs/xs/fst_dataread_ref_8311_8315.csv
build/logs/xs/fst_dataread_grh_8311_8315.csv
build/logs/xs/fst_icache_bank45_ref_8309_8315.csv
build/logs/xs/fst_icache_bank45_grh_8309_8315.csv
build/logs/xs/fst_icache_sram_way0_ref_8298_8315.csv
build/logs/xs/fst_icache_sram_way0_grh_8298_8315.csv
build/logs/xs/fst_icache_dataarray_write_ref_0_8315.csv
build/logs/xs/fst_icache_dataarray_write_grh_0_8315.csv
build/logs/xs/fst_icache_resp_consumption_ref_8311_8325.csv
build/logs/xs/fst_icache_resp_consumption_grh_8311_8325.csv
build/logs/xs/fst_icache_resp_consumption_ref_8311_8400.csv
build/logs/xs/fst_icache_resp_consumption_grh_8311_8400.csv
```

FST 显示，cycle `8313` 附近 `ICacheMainPipe`、`ICacheDataArray`、bank4/5 的
request/ready/control 基本一致，分叉集中在 bank4/5 way0 的 read data：ref 为
非零值，GrhSIM 为 0。继续沿层级下钻后，最可疑路径落在
`ICacheDataBank_5 -> SRAMTemplate_16 -> array_256x66`。

`array_256x66` 的 read data 由如下逻辑产生：

```systemverilog
assign RW0_rdata = _RW0_ren_d0 & ~_RW0_rmode_d0 ? Memory[_RW0_raddr_d0] : 66'bx;
```

也就是说，当上一拍不是有效 read，或上一拍处于 write mode 时，`RW0_rdata`
语义上是 invalid/X。完整 Verilator ref 构建带有 `--x-assign unique`，因此这个
invalid/X 在波形和下游 mux 中表现为确定的非零值；当前 GrhSIM 对同一路径更像是
把 invalid/X 折叠成了 0。`ICacheDataBank_5` 又会按 `readReqReg_waymask` 选择
way response，因此该 invalid/X 差异能向上表现为 bank data response 差异。

`CASE_020` 正是把这个路径提取为 xs-bugcase：在 reset scrub 后读 set `0x73`、
waymask `0x1`，ready 信号一致，但 `resp_data` 出现 ref 非零、GrhSIM 为 0 的差异。
这与完整 FST 的 cycle `8313` 分叉形态一致，但还不能直接等价为完整 CoreMark 根因：
cycle `8313` 附近还需要确认 `s1_fire/io_resp_valid/io_toIfu_fetchResp_valid` 是否有效，
以及差异所在 bank lane 是否进入 IFU 实际消费的数据窗口。

因此当前结论应表述为：

- `CASE_020` 已闭环证明 X assignment policy 差异；
- 完整 FST 的 bank4/5 data 分叉与该差异形态一致；
- 但若这些 bank4/5 数据只落在 invalid/don't-care 路径，或没有被有效 response
  消费，则 `CASE_020` 只能作为二级语义问题，不能作为完整 CoreMark 吞吐差异根因。

继续抽取 `8311..8400` 的 response consumption 链路后，`CASE_020` 已降级：

- cycle `8313..8333`：ref 的 `s1_datas_4/5` 和 `io_resp_bits_data` lane4/5 为非零，
  GrhSIM 为 0，但两边 `s1_fire=0`、`io_resp_valid=0`、`io_toIfu_fetchResp_valid=0`；
- cycle `8334` 首次重新 `s1_fire/io_resp_valid/io_toIfu_fetchResp_valid=1` 时，
  `io_toIfu_fetchResp_bits_data` lane4/5 两边已经一致：
  lane4 `0x02d3f0000253f000`，lane5 `0x03d3f0000353f000`；
- 后续有效 response 周期 `8336/8337/8338/8339/8371/8377/8383` 的 lane4/5 也一致；
- 差异仍会停留在 `s1_datas_r_4/5` 这种内部寄存器残留上，但没有伴随有效
  `io_toIfu_fetchResp_valid` 输出。

因此，`CASE_020` 证明的是 GrhSIM 对 invalid/X branch 的兼容性语义差异；在当前
完整 20k FST 证据下，它不是 CoreMark 吞吐差异的有效消费分叉点。

另外，这对 20k wave 日志本身没有复现旧的 GrhSIM 20k 吞吐落后现象。当前
`xs_ref_wave20k_ref_20260609.log` 和 `xs_wolf_grhsim_wave20k_grhsim_20260609.log`
的 progress 完全一致：

| cycle | ref instr / commit_pc | GrhSIM instr / commit_pc |
| ---: | --- | --- |
| 10k | `458 / 0x80001cdc` | `458 / 0x80001cdc` |
| 15k | `5532 / 0x80000130` | `5532 / 0x80000130` |
| 20k | `14121 / 0x8000043a` | `14121 / 0x8000043a` |

这说明当前这对 FST 不存在需要继续定位的 ref/GrhSIM 行为分叉；但它后续被确认属于
默认 lowered SV 对照路径，不能覆盖 preserve-aggregate 路径。最新
`build/xs-preserve-aggregate` 50k 复测已经重新复现 `GrhSIM 20k = 10424`、
`ref/lowered baseline 20k = 14121` 这一类吞吐差异。

## 当前排除项

基于当前证据，以下方向不应继续作为第一怀疑点：

1. `ICacheReplacer` 单体逻辑错误。
   - 完整 RTL 字节级一致；
   - Verilator-vs-GrhSIM bugcase 通过；
   - xs-components `XsIcacheReplacerLarge` 也已通过较大向量验证。

2. `ICacheWayLookup` 单体 aggregate ingest/emit 错误。
   - 完整 RTL 单测通过；
   - queue / bypass / flush / updateStall 路径已被 case 覆盖。

3. `ICacheMainPipe` 单体逻辑错误。
   - 完整 RTL + `Arbiter2_MissReqBundle` 单测通过；
   - `s0_canGo`、`io_req_ready`、`io_wayLookupRead_ready`、respStall、flush 和 missReq 路径已被受控激励覆盖；
   - 但该 case 没有真实 `WayLookup` queue，不排除跨模块活动调度差异。

4. `ICacheMainPipe <-> ICacheWayLookup` read/ready 组合错误。
   - `CASE_018` 真实连接两者并通过；
   - empty+bypass、queue 蓄积、write/update、read backpressure 和 flush 均被覆盖。

5. `ICacheMissUnit` refill/update 到 `ICacheWayLookup.update` 的受控组合错误。
   - `CASE_019` 真实连接 `MissUnit.io_resp_*` 到 `WayLookup.io_update_*` 并通过；
   - fetch miss、MSHR acquire、两拍 grant、refill response、meta/data write 和 update 后 read 均被覆盖；
   - 但该 case 没有接入真实 `ICacheDataArray` / `ICacheMetaArray`，也没有覆盖完整 TileLink/runtime 活动调度。

   注意：`CASE_020` 证明了 `ICacheDataBank_5` / `SRAMTemplate_16` / `array_256x66`
   的 invalid/X data response policy 差异，但完整 FST 已显示该差异没有进入有效
   IFU response，因此它不再是 full CoreMark 第一怀疑点。

6. `OldestArbiter` 单体 reset/fill 错误。
   - 小 case 和完整 `OldestArbiter.sv` case 均已通过。

7. 当前完整 XiangShan 失败不是 reset 后 assertion。
   - 最新 50k 是 cycle limit 正常结束；
   - 问题表现为提交数量偏少。

## 旧 Trace 分叉定位（已复验修正）

本节记录的是插入 ROBDBG 之前的旧 15k commit trace 现象。后续固定窗口 ROBDBG
全量重新生成 RTL、重新 emit GrhSIM、重新编译并运行后，该分叉点没有复现；最新
复验结果见下一节。

按用户要求继续查看分叉 trace 后，已生成当前 2026-06-09 版本的 15k commit trace：

```sh
EMU_PROGRESS_EVERY_CYCLES=1000 build/xs/ref/verilator-compile/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 15000 --dump-commit-trace \
  > build/logs/xs/xs_ref_codex_20260609_ref_15k_commit_trace.log 2>&1

EMU_PROGRESS_EVERY_CYCLES=1000 build/xs/grhsim/grhsim-compile/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 15000 --dump-commit-trace \
  > build/logs/xs/xs_wolf_grhsim_codex_20260609_grhsim_15k_commit_trace.log 2>&1
```

结果：

| model | 15k instrCnt | final progress pc | commit trace events |
| --- | ---: | --- | ---: |
| Verilator ref | `5532` | `0x80000130` / trap `0x8000014e` | `2681` (`[0]..[2680]`) |
| GrhSIM | `4505` | `0x80000116` / trap `0x80000142` | `2181` (`[0]..[2180]`) |

逐 commit index 比较显示：

- `[0]..[1180]` 的 `pc/inst/wen/dst/data/robIdx` 完全一致；
- 第一条分叉在 commit index `[1181]`，model cycle `12729` 附近；
- 这不是之前假设的“同一 commit stream 只是中间多 idle”，而是退役事件本身开始缺失/错位。

第一分叉原始片段：

```text
ref:
[1180] commit cycle 12725 pc 00000000800003b8 inst f8099ce3 wen 0 dst 25 data 0000000080003ae0 idx 015
[1181] commit cycle 12729 pc 0000000080000350 inst 001c8c9b wen 1 dst 25 data 0000000000000003 idx 016
[1182] commit cycle 12729 pc 0000000080000352 inst 00098793 wen 1 dst 15 data 0000000080003ae0 idx 017
[1183] commit cycle 12733 pc 000000008000035e inst fe079ce3 wen 0 dst 25 data 0000000080003ad0 idx 01c

GrhSIM:
[1180] commit cycle 12725 pc 00000000800003b8 inst f8099ce3 wen 0 dst 25 data 0000000080003ae0 idx 015
[1181] commit cycle 12733 pc 0000000080000354 inst 00000413 wen 1 dst 08 data 0000000000000000 idx 018
[1182] commit cycle 12733 pc 0000000080000356 inst 01545563 wen 0 dst 10 data 0000000080003ae0 idx 019
[1183] commit cycle 12745 pc 000000008000035e inst fe079ce3 wen 0 dst 25 data 0000000080003ad0 idx 01c
```

Cycle 分组比较进一步确认，在 cycle `12729`：

```text
ref-only:
  pc 0x80000350 inst 0x001c8c9b robIdx 0x016
  pc 0x80000352 inst 0x00098793 robIdx 0x017
grh-only:
  <none>
```

反汇编该窗口可知这是 CoreMark list sort 代码：

```text
0x80000350: addiw s9, s9, 1
0x80000352: mv    a5, s3
0x80000354: li    s0, 0
0x80000356: bge   s0, s5, 0x80000360
...
0x800003b8: bnez  s3, 0x80000350
```

因此，最新 trace 将首要怀疑点从 ICache 前端气泡转移到 backend ROB/commit 退役侧：

- `0x800003b8` 两边都已提交且 payload 一致；
- ref 下一轮退役 `0x80000350/0x80000352`；
- GrhSIM 下一轮从 `0x80000354/0x80000356` 开始，少了两条真实 commit event；
- Difftest `--dump-commit-trace` 是在每个 `InstrCommitChecker` 看到 `probe.valid` 时记录，
  所以这不是普通打印排序问题。

已用 `fst-roi-discovery` 做 RTL-only ROI，artifact：

```text
build/logs/xs/no0188_commit_diverge_20260609.metadata.json
build/logs/xs/no0188_commit_diverge_20260609.signals.tsv
build/logs/xs/no0188_commit_diverge_20260609.ai.md
```

ROI 结果指向 `Rob.sv` 中的 `iretireCommit_*` / difftest commit 相关路径，例如：

```text
build/xs/rtl/rtl/Rob.sv:89907 _iretireCommit_0_andMatrixOutputs_T_3
build/xs/rtl/rtl/Rob.sv:90068 _iretireCommit_1_andMatrixOutputs_T_3
build/xs/rtl/rtl/Rob.sv:183582 difftest_commit_nFused
```

为排除 `nFused` 造成的 trace 误导，已临时扩展 Difftest commit trace 打印：

```text
testcase/xiangshan/difftest/src/test/csrc/difftest/diffstate.h
testcase/xiangshan/difftest/src/test/csrc/difftest/checkers/instructions.cpp
```

新增字段：

```text
nfused <N>
```

重编并重跑 15k：

```text
build/logs/xs/xs_ref_codex_20260609_ref_15k_commit_trace_nfused.log
build/logs/xs/xs_wolf_grhsim_codex_20260609_grhsim_15k_commit_trace_nfused.log
```

结论：

- 两边 15k trace 中 `nfused != 0` 的 event 均为 `13` 个；
- 第一分叉窗口 `[1176]..[1190]` 全部 `nfused 0`；
- 第一分叉仍在 `[1181]`，且不是 fused commit event 合并多条指令导致。

带 `nfused` 的第一分叉片段：

```text
ref:
[1180] commit cycle 12725 pc 00000000800003b8 inst f8099ce3 wen 0 dst 25 data 0000000080003ae0 idx 015 nfused 0
[1181] commit cycle 12729 pc 0000000080000350 inst 001c8c9b wen 1 dst 25 data 0000000000000003 idx 016 nfused 0
[1182] commit cycle 12729 pc 0000000080000352 inst 00098793 wen 1 dst 15 data 0000000080003ae0 idx 017 nfused 0

GrhSIM:
[1180] commit cycle 12725 pc 00000000800003b8 inst f8099ce3 wen 0 dst 25 data 0000000080003ae0 idx 015 nfused 0
[1181] commit cycle 12733 pc 0000000080000354 inst 00000413 wen 1 dst 08 data 0000000000000000 idx 018 nfused 0
[1182] commit cycle 12733 pc 0000000080000356 inst 01545563 wen 0 dst 10 data 0000000080003ae0 idx 019 nfused 0
```

进一步按 `nFused + 1` 将 commit event 展开为实际指令计数 slot 后，第一分叉窗口
仍然一致落在同一个位置。该窗口内所有 event 的 `nfused` 都是 `0`，因此没有隐藏的
fused 指令 slot：

```text
ref:
E1180 S0004 cycle 12725 pc 00000000800003b8 inst f8099ce3 robIdx 015 nfused 0
E1181 S0005 cycle 12729 pc 0000000080000350 inst 001c8c9b robIdx 016 nfused 0
E1182 S0006 cycle 12729 pc 0000000080000352 inst 00098793 robIdx 017 nfused 0
E1183 S0007 cycle 12733 pc 000000008000035e inst fe079ce3 robIdx 01c nfused 0
E1184 S0008 cycle 12733 pc 0000000080000356 inst 01545563 robIdx 01d nfused 0

GrhSIM:
E1180 S0004 cycle 12725 pc 00000000800003b8 inst f8099ce3 robIdx 015 nfused 0
E1181 S0005 cycle 12733 pc 0000000080000354 inst 00000413 robIdx 018 nfused 0
E1182 S0006 cycle 12733 pc 0000000080000356 inst 01545563 robIdx 019 nfused 0
E1183 S0007 cycle 12745 pc 000000008000035e inst fe079ce3 robIdx 01c nfused 0
E1184 S0008 cycle 12745 pc 0000000080000356 inst 01545563 robIdx 01d nfused 0
```

同时确认 `DiffInstrCommit` payload 本身只有一组 `pc` / `instr` 字段和一个
`nFused` 计数：

```text
testcase/xiangshan/difftest/src/main/scala/Bundles.scala:
  val pc = UInt(64.W)
  val instr = UInt(32.W)
  val nFused = UInt(8.W)
```

也就是说，当 `nfused > 0` 时，Difftest commit trace 只能说明该 event 代表
`nFused + 1` 条参考模型步进；后续 fused 指令的真实 opcode 并不在
`DiffInstrCommit` payload 中。因此这份 trace 不能被理解成 Verilator trace 的
简单 prefix。当前窗口缺失的是两条 `nfused 0` 的真实 commit event：
`0x80000350` 和 `0x80000352`，不是 fused event 展开方式造成的显示误导。

## ROBDBG 复验更新

按 ROB/commit 方向插入固定窗口打印后，已完整重跑 ref 和 GrhSIM。最初尝试用
`PlusArg` 控制打印窗口，但 GrhSIM ingest 生成的 `plusarg_reader.v` 时遇到
`$value$plusargs` 支持问题，因此改为固定窗口：

```scala
timer >= 12720.U && timer <= 12740.U
```

本轮执行：

```text
make -C testcase/xiangshan comp
make -B xs_rtl RUN_ID=robdbg_fixed_rtl_20260609
make xs_ref_emu RUN_ID=robdbg_fixed_ref_20260609
make xs_wolf_grhsim_emu RUN_ID=robdbg_fixed_grhsim_20260609 XS_WOLF_GRHSIM_RESUME_FROM_STATS_JSON=0
```

运行日志：

```text
build/logs/xs/xs_ref_robdbg_fixed_20260609.log
build/logs/xs/xs_grhsim_robdbg_fixed_20260609.log
```

提取完整 commit record 后，ref 与 GrhSIM 在 15k 内均为 `2681` 条 event，且抽取后的
commit record `cmp` 完全一致。原先可疑窗口现在两边一致：

```text
[1178] commit cycle 12717 pc 000000008000037c inst fe8047e3 wen 0 dst 15 data 0000000000000000 idx 013 nfused 0
[1179] commit cycle 12717 pc 0000000080000380 inst 03405c63 wen 0 dst 24 data 0000000080003af0 idx 014 nfused 0
[1180] commit cycle 12725 pc 00000000800003b8 inst f8099ce3 wen 0 dst 25 data 0000000080003ae0 idx 015 nfused 0
[1181] commit cycle 12729 pc 0000000080000350 inst 001c8c9b wen 1 dst 25 data 0000000000000003 idx 016 nfused 0
[1182] commit cycle 12729 pc 0000000080000352 inst 00098793 wen 1 dst 15 data 0000000080003ae0 idx 017 nfused 0
[1183] commit cycle 12733 pc 000000008000035e inst fe079ce3 wen 0 dst 25 data 0000000080003ad0 idx 01c nfused 0
[1184] commit cycle 12733 pc 0000000080000356 inst 01545563 wen 0 dst 10 data 0000000000000001 idx 01d nfused 0
```

ref 的 ROBDBG 也验证了原先怀疑点的 ROB commit 语义：

- cycle `12726`：`ioCommitValid 00000011`，lane 0/1 分别输出 deq `016` / `017`；
- lane 0：pc `0x80000350`，instr `0x001c8c9b`，`cvOut 1`；
- lane 1：pc `0x80000352`，instr `0x00098793`，`cvOut 1`；
- cycle `12727` 后 deqPtr 前进到 `018/019`。

GrhSIM 日志没有出现 `[ROBDBG]` 行，但 `strings build/xs/grhsim/grhsim-compile/emu`
能看到 ROBDBG format string，说明生成 binary 中包含这一路 system task 字符串；
当前更像是 GrhSIM `$fwrite` / `printf` runtime 输出路径没有真正落到 stdout/stderr。
这不影响本轮用 commit trace 验证原始症状。

当前复验结论：旧日志中的 “GrhSIM 跳过 ROB idx `016/017`，从 `018/019` 继续”
没有被复现；“ROB commit 退役逻辑在当前代码下必然丢两条 event”这个猜测不成立。
更可能的解释是旧日志来自 stale RTL/emu、旧 GrhSIM emit 结果，或中间某次代码生成状态。

注意：上述 ROBDBG 和 difftest `nfused` 打印属于侵入式调试改动，已从
`testcase/xiangshan` 与其 `difftest` 子仓库撤回。后续若需要验证类似怀疑，应开启
waveform 并在波形中定位，不再修改 XiangShan / difftest 源码插打印。

## 当前最可能方向

当前不应继续把 `Rob.sv` intrinsic commit/drop 当作第一结论。经过固定窗口插桩和
全量重建，ref 与 GrhSIM 的 15k commit record 已完全一致，说明原先分叉点不再是
稳定可复现故障。最新 FST 又进一步确认 `CASE_020` 的 bank4/5 X policy 差异没有进入
有效 `io_toIfu` response，因此它也不能直接作为完整 CoreMark 根因。

不过，2026-06-10 的 preserve-aggregate 50k 复测已经重新复现
`36573 vs 73580` 的提交量差异；之前 clean 50k 通过的是默认 lowered SV 路径。
因此当前 full CoreMark 问题不是已经消失，而是被限定在 preserve-aggregate 路径。

新的优先方向：

1. 重新生成 preserve-aggregate 的 ref/GrhSIM FST，定位新的有效消费分叉点。
   - 必须使用 `build/xs-preserve-aggregate` 或等价 preserve-aggregate 工作目录；
   - lowered/default SV 的 clean 50k 只能作为对照组；
   - 第一目标是确认 10k 到 15k 之间哪条 valid/ready 或 commit-visible 链路开始分叉。

2. `ICacheDataBank_5` 选择 `SRAMTemplate_16/array_256x66` invalid/X `RW0_rdata`
   的语义差异。
   - 完整 FST 在 cycle `8313` 附近显示 request/ready/control 一致，bank way0
     data 分叉；
   - `array_256x66` 在非有效 read 或 write mode 后输出 `66'bx`；
   - Verilator ref 的 `--x-assign unique` 会把该 X 路径固化为非零值；
   - 当前 GrhSIM 在 `CASE_020` 中表现为同一路径输出 0；
   - 但完整 FST 已显示该差异在 `8311..8400` 内没有进入有效 IFU response，因此降为
     二级兼容性问题。

3. 检查 GrhSIM 生成代码中对 `x` literal、ternary invalid branch、memory read
   data 和后续 mux/select 的处理。
   - 该项目前仍不能直接解释 full CoreMark 吞吐差异；
   - 但 preserve-aggregate 路径重新复现后，应在新 FST 中确认是否存在新的
     valid data 消费点，而不是沿用 cycle `8313` 的 invalid response 结论。

已降级但仍可能作为二级方向：

1. 旧分叉日志来源和 clean 长跑基线。
   - 旧 ROB trace 的分叉没有在固定窗口复验中复现；
   - lowered-SV clean 长跑基线仍有价值，但它不能替代 preserve-aggregate 回归。

2. `ICacheMainPipe` / `ICacheDataArray` / `ICacheMetaArray` 之间的 ready 和完整
   frontend retry 调度。

   当前 FST 显示 control 基本一致，差异更像 data/X 语义而不是 ready 固定点；
   如果修复 X 语义后仍有长跑吞吐差异，再回到更大组合环境。

3. 完整系统中 `MissUnit`、Data/Meta array、WayLookup update、MainPipe retry 的相对调度。

   `CASE_019` 覆盖了受控 `MissUnit -> WayLookup.update` 闭环，但没有真实 SRAM array
   和完整 frontend retry 环境；如果长跑吞吐差异稳定复现，仍需要 trace 或更大组合 case。

## 已降级方向

1. `ICacheMainPipe` 与 `ICacheWayLookup` 的 read/ready 组合交互。

   Chisel 中 `ICacheMainPipe` 的推进条件是：

   ```scala
   s0_canGo = toData.ready && fromWayLookup.valid && s1_ready
   fromFtq.ready := s0_canGo
   fromWayLookup.ready := s0_fire
   ```

   `CASE_017` 已排除 `ICacheMainPipe` 单体明显差异，但没有真实 `WayLookup`
   queue；`CASE_018` 已进一步覆盖真实 `WayLookup` queue。因此该方向不再作为第一怀疑点。

2. `ICacheMissUnit` refill/update 与 `ICacheWayLookup.update` 的受控组合交互。

   `CASE_019` 已覆盖 fetch miss、MSHR acquire、两拍 grant、refill response、meta/data write
   和 update 后 WayLookup read。因此不应继续在该受控闭环上扩展单点测试，除非 trace
   指向真实 Data/Meta array 或完整 TileLink 时序参与后的差异。

## 下一步建议

下一步不应继续基于旧日志直接提取 ROB commit/drop bugcase，也不应继续沿
`CASE_020` 直接修 full CoreMark。当前 20k wave ref/GrhSIM progress 完全一致，
但那组 wave/clean baseline 属于默认 lowered SV 对照；最新 preserve-aggregate
50k 已重新复现吞吐差异，应切回 preserve-aggregate FST 定位。

建议执行：

1. 保留 lowered-SV clean 50k baseline 作为对照组。
   - 它证明默认 lowered SV 路径当前 ref/GrhSIM 一致；
   - 但 preserve-aggregate 路径仍需独立回归，不能用该 baseline 替代。

2. 保留 `CASE_020` 作为 X policy 兼容性回归。
   - 它不再阻塞 full CoreMark 根因分析；
   - 后续若要修，应补最小化 `cond ? value : 66'bx` / SRAM invalid read 单测，
     并明确 ref 侧使用 `--x-assign unique`。

3. 重新跑 preserve-aggregate ref/GrhSIM waveform，并从 10k 到 15k 定位分叉。
   - `CASE_017` / `CASE_018` / `CASE_019` 用于确认 ready-valid 和 MissUnit/WayLookup
     组合路径未回退；
   - 优先选择影响 `io_toIfu_fetchResp_valid`、fetch queue enqueue、decode valid
     或 commit 进度的信号链路。

4. 后续若还有新怀疑点，继续按 waveform 定位。
   - 不再修改 XiangShan / difftest 源码插打印；
   - 如需 GrhSIM waveform，模型需用 `WOLVRIX_GRHSIM_WAVEFORM=1` 重新生成。

## 当前状态一句话

SV ingest 和 `comb-loop-elim` 已经能支持当前完整 XiangShan preserve-aggregate 输入；
reset/assert、`ICacheMainPipe`、`WayLookup`、`MissUnit` 相关受控 case 均未复现控制
路径问题。固定窗口 ROBDBG 全量重建复跑后，旧 trace 中 `idx 016/017` 缺失的分叉点
没有复现；最新 FST 与 `CASE_020` 已复现并定位到 `ICacheDataBank_5` 选择
`SRAMTemplate_16/array_256x66` invalid/X read data 时 ref 非零而 GrhSIM 为 0，
该点已证明为 X assignment policy 差异，但完整 FST 显示它没有进入有效
`io_toIfu_fetchResp` 消费路径；同时 lowered/default SV 的 20k wave 和 clean 50k
non-wave ref/GrhSIM progress 均完全一致。最新 preserve-aggregate 50k 复测则重新
复现 `36573 vs 73580` 的提交量差异，因此当前 full CoreMark 问题应限定为
preserve-aggregate 路径上的吞吐/提交分叉，下一步应重跑 preserve-aggregate FST
并从 10k 到 15k 的有效消费链路定位。

## 增量更新 2026-06-10：CASE_021 packed aggregate lowering 修复完成

后续继续沿 preserve-aggregate / packed aggregate 方向缩小问题，已提取独立复现用例：

```text
testcase/xs-bugcase/CASE_021
```

该用例模拟 XiangShan TAGE 中 `t0_setIdx -> t1_setIdx -> t2_setIdx` 的 1D packed
aggregate register pipeline，并只通过子模块 `table.write_set_idx(t2_setIdx[...])`
观察输出。修复前，GrhSIM 会把 `t1_setIdx/t2_setIdx` 这类 packed aggregate register
错误 lowering 成 anonymous `kMemory`，且只生成 `kMemoryReadPort`，没有运行时
write/fill port；生成 C++ 中对应 state memory 只有初始化和读取，导致子模块看到的
lane 输出保持 0。

已在 ingest / graph assembly 中修复该问题：

- packed aggregate variable 不再因为 `memoryRows > 0` 就按普通 memory-backed
  state 处理；
- whole aggregate register 读写按 flattened register 语义建模；
- packed aggregate element/range select 生成正确 lane slice；
- instance port sink 侧的 `t2[addr]` 观察路径不再触发 anonymous `kMemory`；
- 新增 `graph_assembly_packed_aggregate_instance_sink` 回归，明确检查 `t1/t2`
  为 72-bit `kRegister`，存在 register write port，且不生成 `kMemory`。

本次验证：

```sh
ctest --test-dir wolvrix/build --output-on-failure -R '^ingest-graph-assembly-memory$'

make -C testcase/xs-bugcase/CASE_021 run \
  WOLVRIX_PY=/home/gaoruihao/wksp/wolvrix-playground/.venv/bin/python
```

结果：

```text
ingest-graph-assembly-memory ..... Passed
[PASS] CASE_021 ref == grhsim
```

随后使用包含该修复的 `.venv` Python package，从 `read_sv` 开始重新构建默认 lowered-SV
XiangShan GrhSIM emu，并跑 CoreMark 50k：

```sh
make xs_wolf_grhsim_emu \
  RUN_ID=20260610_220021_readsv50k \
  PYTHON=/home/gaoruihao/wksp/wolvrix-playground/.venv/bin/python \
  XS_WOLF_GRHSIM_RESUME_FROM_STATS_JSON=0

make run_xs_wolf_grhsim_emu \
  RUN_ID=20260610_220021_readsv50k \
  PYTHON=/home/gaoruihao/wksp/wolvrix-playground/.venv/bin/python \
  XS_SIM_MAX_CYCLE=50000
```

关键日志：

```text
build/logs/xs/xs_wolf_grhsim_build_20260610_220021_readsv50k.log
build/logs/xs/xs_wolf_grhsim_20260610_220021_readsv50k.log
```

构建证据：

```text
WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=0
[wolvrix-xs-grhsim] read_sv start
[wolvrix-xs-grhsim] read_sv done 62141ms
[wolvrix-xs-grhsim] total done 1058514ms
[EXIT] xs_wolf_grhsim_emit 0
+ LD /home/gaoruihao/wksp/wolvrix-playground/build/xs/grhsim/grhsim-compile/emu
```

CoreMark 50k 结果：

```text
[CYCLE_LIMIT] cycles=50000 max_cycles=50000
Core 0: EXCEEDING CYCLE/INSTR LIMIT at pc = 0x80001312
Core-0 instrCnt = 73580, cycleCnt = 49996, IPC = 1.471718
Seed=0 Guest cycle spent: 50001
Host time spent: 363749ms
```

本次结论：

- `CASE_021` 覆盖的 packed aggregate register lowering bug 已修复。
- 默认 lowered-SV XiangShan GrhSIM 在包含该修复的版本上可从 `read_sv` 全量重建并跑满
  CoreMark 50k，未出现 mismatch/abort。
- 这次 50k 仍是默认 lowered-SV 工作目录 `build/xs` 的 correctness gate，不替代
  preserve-aggregate 工作目录 `build/xs-preserve-aggregate` 的独立 closure。
- preserve-aggregate 50k 的历史吞吐分叉需要在后续用同样修复后的版本重新单独复测；
  若复测通过，再把本文前面 “preserve-aggregate 仍有误” 的历史结论以新的增量更新
  形式关闭。
