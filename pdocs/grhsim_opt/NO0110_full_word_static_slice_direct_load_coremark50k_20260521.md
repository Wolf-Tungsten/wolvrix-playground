# NO0110: full-word static slice direct load emit 的 CoreMark 50k 测试

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


实验目的：

- 在 NO0109 的当前最佳调度组合上，仅改变 emit 代码形态。
- 将 64-bit 对齐整字 slice 从 `grhsim_slice_words<1>(...)[0]` 优化为直接 word load，例如 `(wide_in)[1]`。
- 判断减少临时 `std::array<1>` 是否能转化为 XiangShan CoreMark runtime 收益。

改动范围：

- `wolvrix/lib/emit/grhsim_cpp.cpp`
  - 新增 full-word static slice scalar fast path。
  - 条件：结果为 scalar logic，结果宽度为 `64`，输入为 wide logic，且 `sliceStart` 为 64-bit 对齐。
- `wolvrix/tests/emit/test_emit_grhsim_cpp.cpp`
  - 增加 `wide_full_word_slice_y` 覆盖 `[127:64]` slice。
  - 检查生成代码包含直接 `(wide_in)[1]` 形态。

局部验证：

```text
cmake --build wolvrix/build --target emit-grhsim-cpp -j$(nproc)
ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'
```

结果：通过。

XiangShan fresh emit：

```text
tmp/no0110_xs_emit_fullword_slice_c2_full_emit/grhsim_emit
```

配置沿用 NO0109：

```text
WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1
WOLVRIX_XS_GRHSIM_POST_STATS_JSON=/home/gaoruihao/wksp/wolvrix-playground/build/xs/grhsim/wolvrix_xs_post_stats.json
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_SIBLING_MERGE=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE=0
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE=0
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_MAX_PREDS=0
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_CANDIDATE_BUDGET=0
```

emit 结果：

- `activity-schedule done`: `200081ms`
- `write_grhsim_cpp done`: `42296ms`
- total wall time: `274.11s`
- `supernodes`: `74945`
- `compute_supernodes`: `74430`
- `commit_supernodes`: `515`
- `dag_edges`: `485905`
- `boundary_values`: `1151073`
- `boundary_activation_edges`: `2216514`

生成代码形态变化：

| 指标 | NO0109 | NO0110 |
| --- | ---: | ---: |
| 对齐 64-bit `grhsim_slice_words<1>(...)[0]` 模式数量 | `34934` | `485` |

model build：

```text
timeout 3600 /usr/bin/time -p make -B -C tmp/no0110_xs_emit_fullword_slice_c2_full_emit/grhsim_emit -j$(nproc) CXX=clang++
```

结果：

- `real`: `318.08s`
- `user`: `6869.56s`
- `sys`: `62.46s`
- `libgrhsim_SimTop.a`: `122M`
- `grhsim_SimTop.hpp.pch`: `15M`
- `grhsim_SimTop_sched_*.cpp`: `994`

XiangShan difftest emu build：

```text
timeout 3600 make -C testcase/xiangshan/difftest emu
  BUILD_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/no0110_xs_emit_fullword_slice_c2_full_emu
  GEN_CSRC_DIR=/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/build/generated-src
  GEN_VSRC_DIR=/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/build/generated-src
  NUM_CORES=1
  WITH_CHISELDB=0
  WITH_CONSTANTIN=0
  GRHSIM=1
  GRHSIM_MODEL_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/no0110_xs_emit_fullword_slice_c2_full_emit/grhsim_emit
  WOLVRIX_GRHSIM_WAVEFORM=0
  VM_BUILD_JOBS=$(nproc)
  CXX=clang++
  CC=clang
```

结果：成功生成 `tmp/no0110_xs_emit_fullword_slice_c2_full_emu/grhsim-compile/emu`。

CoreMark 50k bounded run：

```text
timeout 1800 env EMU_PROGRESS_EVERY_CYCLES=10000 stdbuf -oL -eL
  tmp/no0110_xs_emit_fullword_slice_c2_full_emu/grhsim-compile/emu
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so
  -b 0 -e 0 -C 50000
```

结果：

- 退出码：`0`
- 未出现 difftest mismatch。
- `Guest cycle spent: 50001`
- `Host time spent: 397559ms`
- 折算 host 侧仿真速度：约 `125.8 cycles/s`

50k 进度点：

| model cycles | host ms | cumulative cycles/s |
| ---: | ---: | ---: |
| `10000` | `44203` | `226` |
| `20000` | `133918` | `149` |
| `30000` | `216875` | `138` |
| `40000` | `301413` | `133` |
| `50000` | `397547` | `126` |

与 NO0109 对比：

| 指标 | NO0109 activation merge | NO0110 full-word slice direct load |
| --- | ---: | ---: |
| `activity-schedule` | `187654ms` | `200081ms` |
| `write_grhsim_cpp` | `40499ms` | `42296ms` |
| `libgrhsim_SimTop.a` build real | `303.60s` | `318.08s` |
| 10k progress | `26249ms` | `44203ms` |
| 20k progress | `105701ms` | `133918ms` |
| 30k progress | `188617ms` | `216875ms` |
| 40k progress | `273452ms` | `301413ms` |
| 50k `Host time spent` | `369976ms` | `397559ms` |
| 50k throughput | `135.1 cycles/s` | `125.8 cycles/s` |

判断：

- 该 emit 形态清理显著减少了 aligned 64-bit slice helper 临时对象数量，但没有转化为 runtime 收益。
- 相比 NO0109，50k runtime 从 `369976ms` 退化到 `397559ms`，慢 `27583ms`，约 `7.46%`。
- model build 从 `303.60s` 增加到 `318.08s`，约 `4.77%`。
- NO0110 不能作为当前最佳点；当前 runtime 最佳仍是 NO0109：`C2 full cap128 + activation merge`。
- 后续优化应优先回到已确认有效的方向：activation path、C4 dynamic 结构收益为何未变成 runtime，以及更高频的宽值赋值/bit access/commit path 代码形态。

