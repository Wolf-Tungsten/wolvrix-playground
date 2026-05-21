# NO0109: C2 full cap128 + emitted activation merge 的 CoreMark 50k 复测

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


目的：在第 32 节 runtime 最佳配置 `C2 full cap128` 上，只叠加 GrhSIM C++ emit 的 successor activation 合并优化，观察重复 activation 写出减少能否转成 CoreMark 50k runtime 收益。

配置：

```text
WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1
WOLVRIX_XS_GRHSIM_POST_STATS_JSON=build/xs/grhsim/wolvrix_xs_post_stats.json
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_SIBLING_MERGE=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE=0
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE=0
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_MAX_PREDS=0
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_CANDIDATE_BUDGET=0
```

fresh emit 输出目录：

```text
tmp/no0109_xs_emit_activation_merge_c2_full_emit/grhsim_emit
```

emit 结果：

- `activity-schedule done`: `187654ms`
- `write_grhsim_cpp done`: `40499ms`
- script total: `249345ms`
- `supernodes`: `74945`
- `compute_supernodes`: `74430`
- `commit_supernodes`: `515`
- `dag_edges`: `485905`
- `boundary_values`: `1151073`
- `boundary_activation_edges`: `2216514`

model build：

```text
timeout 3600 /usr/bin/time -p make -B -C tmp/no0109_xs_emit_activation_merge_c2_full_emit/grhsim_emit -j$(nproc) CXX=clang++
```

结果：

- `real`: `303.60s`
- `user`: `6737.02s`
- `sys`: `59.72s`
- `libgrhsim_SimTop.a`: `122M`
- `grhsim_SimTop_sched_*.cpp`: `994`

XiangShan difftest emu build：

```text
timeout 3600 make -C testcase/xiangshan/difftest emu
  BUILD_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/no0109_xs_emit_activation_merge_c2_full_emu
  GEN_CSRC_DIR=/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/build/generated-src
  GEN_VSRC_DIR=/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/build/generated-src
  NUM_CORES=1
  WITH_CHISELDB=0
  WITH_CONSTANTIN=0
  GRHSIM=1
  GRHSIM_MODEL_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/no0109_xs_emit_activation_merge_c2_full_emit/grhsim_emit
  WOLVRIX_GRHSIM_WAVEFORM=0
  VM_BUILD_JOBS=$(nproc)
  CXX=clang++
  CC=clang
```

结果：成功生成 `tmp/no0109_xs_emit_activation_merge_c2_full_emu/grhsim-compile/emu`，大小 `111M`。

CoreMark 50k bounded run：

```text
timeout 1800 env EMU_PROGRESS_EVERY_CYCLES=10000 stdbuf -oL -eL
  tmp/no0109_xs_emit_activation_merge_c2_full_emu/grhsim-compile/emu
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so
  -b 0 -e 0 -C 50000
```

结果：

- 退出码：`0`
- 未出现 difftest mismatch。
- `Guest cycle spent: 50001`
- `Host time spent: 369976ms`
- 折算 host 侧仿真速度：约 `135.1 cycles/s`

50k 进度点：

| model cycles | host ms | cumulative cycles/s |
| ---: | ---: | ---: |
| `10000` | `26249` | `381` |
| `20000` | `105701` | `189` |
| `30000` | `188617` | `159` |
| `40000` | `273452` | `146` |
| `50000` | `369963` | `135` |

与旧 C2 full cap128 基线对比：

| 指标 | C2 full cap128 | C2 full cap128 + activation merge |
| --- | ---: | ---: |
| `activity-schedule` | `128098ms` | `187654ms` |
| `write_grhsim_cpp` | `41058ms` | `40499ms` |
| `libgrhsim_SimTop.a` build real | `302.35s` | `303.60s` |
| 10k progress | `27089ms` | `26249ms` |
| 20k progress | `108648ms` | `105701ms` |
| 30k progress | `193188ms` | `188617ms` |
| 40k progress | `279432ms` | `273452ms` |
| 50k `Host time spent` | `378558ms` | `369976ms` |
| 50k throughput | `132.1 cycles/s` | `135.1 cycles/s` |

判断：

- runtime 有可测收益：50k 从 `378558ms` 降到 `369976ms`，减少 `8582ms`，约 `2.27%`。
- build 基本不变：model archive build 从 `302.35s` 到 `303.60s`，差异约 `0.4%`，说明 activation merge 没有明显增加 C++ 编译成本。
- 当前已测组合中，`C2 full cap128 + activation merge` 暂时成为新的 runtime 最佳点；它比 `C1+C2+C4 dynamic` 的 `386258ms` 快 `16282ms`，约 `4.22%`。
- 这次收益来自 emit 代码形态，而不是调度结构变化。后续 C4 仍需继续解释结构收益没有转化为 runtime 的原因。

