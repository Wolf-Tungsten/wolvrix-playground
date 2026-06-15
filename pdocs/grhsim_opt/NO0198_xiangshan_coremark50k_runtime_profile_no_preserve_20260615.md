# NO0198 XiangShan CoreMark 50k runtime profile no-preserve-aggregate

记录日期：2026-06-15

目的：按最新工作区重新记录 XiangShan `coremark-2-iteration.bin` 50k cycle 下 `gsim` / `grhsim` 的 runtime profile。本文口径明确不启用 firtool `preserve-aggregate`，并尽量沿用仓库标准 make target。

关联：

- [`NO0190`](./NO0190_grhsim_gsim_unified_cost_model_comp_src_sink_plan_20260612.md)：统一 `n_comp/n_src/n_sink/n_const/a_succ` profile 口径。
- [`NO0195`](./NO0195_xiangshan_coremark50k_no_runtime_profile_speed_20260614.md)：同 workload 的 no-runtime-profile 裸跑速度快照。
- [`NO0196`](./NO0196_two_eval_vs_xiangshan_sink_succ_inconsistency_20260614.md)：此前对 XiangShan sink/succ 计数异常的诊断。
- [`NO0197`](./NO0197_ftq_vec_of_bundle_sv_scalarization_rootcause_20260614.md)：FTQ Vec-of-Bundle 在 SV 层被 firtool 标量化的根因定位。

## 1. 运行口径

共同 workload：

- top：`SimTop`
- workload：`testcase/xiangshan/ready-to-run/coremark-2-iteration.bin`
- difftest：on，reference 为 `testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`
- cycle bound：`XS_SIM_MAX_CYCLE=50000`
- waveform：off
- commit trace：off
- progress interval：`25000` cycles
- runtime profile：`EMU_RUNTIME_PROFILE=1`

本轮产物：

- `build/logs/xs/xs_gsim_simverilog_rtprof50k_gsim_build_20260615.log`
- `build/logs/xs/xs_gsim_build_rtprof50k_gsim_build_20260615.log`
- `build/logs/xs/xs_gsim_rtprof50k_gsim_run_20260615.log`
- `build/logs/xs/xs_wolf_grhsim_build_rtprof50k_grhsim_build_20260615.log`
- `build/logs/xs/xs_wolf_grhsim_rtprofile50k_grhsim_run_20260615.log`
- `tmp/xs_coremark50k_rtprofile_no_preserve_20260615/`

`tmp/xs_coremark50k_rtprofile_no_preserve_20260615/` 中保留了本次分析直接使用的 TSV：

- `gsim_supernode_static.tsv`
- `gsim_supernode_fire.tsv`
- `grhsim_supernode_static.tsv`
- `grhsim_supernode_fire.tsv`

本次运行使用仓库现有 make target。运行日志中记录的顶层命令为：

```bash
make run_xs_gsim_emu \
  RUN_ID=rtprof50k_gsim_run_20260615 \
  XS_SIM_MAX_CYCLE=50000 \
  XS_PROGRESS_EVERY_CYCLES=25000 \
  XS_COMMIT_TRACE=0 \
  XS_WAVEFORM=0 \
  XS_WAVEFORM_FULL=0 \
  XS_LOG_BEGIN=0 \
  XS_LOG_END=0

make run_xs_wolf_grhsim_emu \
  RUN_ID=rtprofile50k_grhsim_run_20260615 \
  XS_SIM_MAX_CYCLE=50000 \
  XS_PROGRESS_EVERY_CYCLES=25000 \
  XS_COMMIT_TRACE=0 \
  XS_WAVEFORM=0 \
  XS_WAVEFORM_FULL=0 \
  XS_LOG_BEGIN=0 \
  XS_LOG_END=0
```

`gsim` / `grhsim` 的 build 也通过 `xs_gsim_emu` / `xs_wolf_grhsim_emu` 路径进入 `testcase/xiangshan/difftest` make flow；本文不把手写 `clang++` 或手写 emu 命令作为复现主路径。

## 2. preserve-aggregate 口径确认

本轮没有启用 firtool `preserve-aggregate`。

证据：

- `xs_gsim_simverilog_rtprof50k_gsim_build_20260615.log` 中记录的 RTL 生成命令为标准 `make -C testcase/xiangshan sim-verilog ... GSIM=1`，没有额外 `SIM_ARGS='--firtool-opt --preserve-aggregate=...'`。
- `testcase/xiangshan/Makefile` 当前默认 `MFC_ARGS` 只有 `-O=release`、`--disable-annotation-unknown` 和 `--lowering-options=explicitBitcast,disallowLocalVariables,disallowPortDeclSharing,locationInfoStyle=none`，以及 release/debug 的 layer specialization 选项，没有 `--preserve-aggregate`。
- 对 `Makefile`、`scripts`、`testcase/xiangshan` 做精确搜索，没有发现默认开启的 `preserve-aggregate` 配置需要删除。
- `testcase/xiangshan/rocket-chip/build.sc` 中存在 `--preserve-values=named`，这是 `preserve-values`，不是 `preserve-aggregate`，且不属于本次 XiangShan `sim-verilog` 主路径。

因此本次没有修改脚本来删除默认 `preserve-aggregate`：仓库标准 XiangShan make flow 当前并未默认开启它。

## 3. 运行结果

两边都跑到 50k cycle limit，且 difftest enabled。

| sim | compiled at | instrCnt | cycleCnt | IPC | host time | `/usr/bin/time` elapsed | throughput |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `gsim` | `Jun 15 2026, 10:35:27` | 73584 | 49998 | 1.471739 | 47952 ms | 47.96 s | 1042.73 cycles/s |
| `grhsim` | `Jun 15 2026, 11:05:32` | 73580 | 49996 | 1.471718 | 351592 ms | 351.61 s | 142.21 cycles/s |

速度差：

```text
grhsim / gsim = 351592 / 47952 = 7.33x
```

进度点：

| sim | 25k host_ms | 50k host_ms |
| --- | ---: | ---: |
| `gsim` | 19195 | 47950 |
| `grhsim` | 138037 | 351580 |

本轮 `gsim` stdout profile 行：

```text
[GSIM_RUNTIME_PROFILE] active_supernodes=766629270 nodes=35103020811 ref_enodes=114467111527 non_ref_enodes=66559770868 total_enodes=181026882395
```

本轮 `grhsim` stdout profile 行：

```text
[GRHSIM_RUNTIME_PROFILE] supernode_fire_tsv=tmp/xs_coremark50k_rtprofile_no_preserve_20260615/grhsim_supernode_fire.tsv rows=72653
```

## 4. 动态加权 profile

下面数据由 `*_supernode_static.tsv` 和 `*_supernode_fire.tsv` 组合得到，口径为 `sum(f(supernode) * static_count(supernode))`。

| metric | `gsim` | `grhsim` | `grhsim / gsim` | `gsim` / cycle | `grhsim` / cycle |
| --- | ---: | ---: | ---: | ---: | ---: |
| fire rows | 84714 | 72653 | 0.858x | - | - |
| supernode fires | 766629270 | 922720709 | 1.204x | 15332.28 | 18454.05 |
| `n_comp * f` | 40527723663 | 52113202979 | 1.286x | 810538.26 | 1042243.21 |
| `n_src * f` | 18856787184 | 15096768815 | 0.801x | 377128.20 | 301929.34 |
| `n_sink * f` | 1843388719 | 14155094220 | 7.679x | 36867.04 | 283096.22 |
| `n_const * f` | 17074612833 | 16006237564 | 0.937x | 341485.43 | 320118.35 |
| `a_succ * f` | 3762489186 | 25543160471 | 6.789x | 75248.28 | 510852.99 |
| feature sum | 82065001585 | 122914464049 | 1.498x | 1641267.20 | 2458240.13 |

把 7.33x host gap 拆成两个粗因子：

| item | `gsim` | `grhsim` | ratio |
| --- | ---: | ---: | ---: |
| feature sum | 82065001585 | 122914464049 | 1.498x |
| host ns / weighted feature | 0.584 | 2.860 | 4.895x |

即本轮 profile 下，`grhsim` 不是只多做了 7.33x 的动态工作量；动态加权 feature 总量约为 `1.50x`，剩余差距主要来自单位 feature 执行成本约 `4.90x`。

## 5. GrhSIM phase split

`grhsim` TSV 区分了 `compute` 和 `commit`：

| phase | rows | supernode fires | `n_comp * f` | `n_src * f` | `n_sink * f` | `n_const * f` | `a_succ * f` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `compute` | 72138 | 913127559 | 52113202979 | 15096768815 | 0 | 16006237564 | 11388066251 |
| `commit` | 515 | 9593150 | 0 | 0 | 14155094220 | 0 | 14155094220 |

观察：

- `commit` 只有 515 行，占 supernode fire 约 `1.04%`，但贡献了全部 `n_sink`。
- `commit` 同时贡献 `55.42%` 的 `a_succ`。
- `compute` fire 很多，但单个 compute supernode 的热点不集中；top `n_comp * f` 单点只占 `0.03%` 左右。

`grhsim` `n_sink * f` 前几名全部是 4096 sink 的 commit supernode：

| supernode | phase | f | n_sink | `n_sink * f` | 占 GrhSIM `n_sink * f` |
| ---: | --- | ---: | ---: | ---: | ---: |
| 72138 | `commit` | 50050 | 4096 | 205004800 | 1.45% |
| 72141 | `commit` | 50050 | 4096 | 205004800 | 1.45% |
| 72142 | `commit` | 50050 | 4096 | 205004800 | 1.45% |
| 72143 | `commit` | 50050 | 4096 | 205004800 | 1.45% |
| 72144 | `commit` | 50050 | 4096 | 205004800 | 1.45% |

这与 `NO0196` 的判断一致：XiangShan full 50k 的 grhsim gap 里，少量大 commit supernode 的 per-field sink/succ 压力仍是核心候选，而不是 compute 侧某个单点热点。

## 6. GSim 对照热点

`gsim` 的热点形态不同：

- `n_src * f` 有一个明显单点：supernode `7532`，`f=50101`，`n_src=47996`，贡献 `2404647596`，占 `gsim n_src * f` 的 `12.75%`。
- `n_comp * f` 前几名每个约占 `0.8% - 1.0%`，比 `grhsim` compute 热点集中。
- `n_sink * f` 和 `a_succ * f` 绝对量明显小于 `grhsim`，分别只有 `grhsim` 的 `13.02%` 和 `14.73%`。

这说明两边的 runtime profile 差异不是简单的“某一边所有项都大”；`grhsim` 的突出异常仍集中在 sink/succ，`gsim` 则有较大的 source-heavy supernode。

## 7. 结论

本轮最新 no-preserve-aggregate、标准 make flow 的 XiangShan CoreMark 50k runtime profile 结论：

```text
gsim   host 47.952 s, profile enabled, 1042.73 cycles/s
grhsim host 351.592 s, profile enabled, 142.21 cycles/s
gap    7.33x
```

动态 profile 的主结论：

1. `grhsim` 动态 feature 总量约为 `gsim` 的 `1.50x`，不足以单独解释 `7.33x` host gap。
2. `grhsim` 单位 weighted feature 成本约为 `gsim` 的 `4.90x`，这是 runtime gap 的另一半主因。
3. `grhsim` 的 `n_sink` 和 `a_succ` 仍分别是 `gsim` 的 `7.68x` 和 `6.79x`，并且集中在少量 `4096` sink commit supernode。
4. 这组结果继续支持 `NO0196/NO0197` 的方向：优先减少 SV lowered 后的 array-register / Vec-of-Bundle 标量化带来的 per-field commit/succ 压力，或让 grhsim 恢复 indexed store / 聚合提交形态；仅优化 compute supernode 内部算子不太可能直接回收主差距。

后续建议单独开新记录推进两件事：

- 用 profile TSV 反查 top commit supernode 对应的具体 state/register family，确认是否仍主要来自 FTQ / BPU / array-register 展平。
- 在不启用 `preserve-aggregate` 的前提下尝试 re-aggregation 或 commit indexed-store lowering；preserve-aggregate 路径当前仍是独立 correctness 议题，不能和本文 no-preserve profile 混用。
