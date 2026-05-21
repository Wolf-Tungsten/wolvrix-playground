# NO0118: wide masked state write in-place emit

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


实验目的：

- 针对 wide state masked write 的高频临时对象。
- 将普通 wide state direct commit 从 `grhsim_merge_words_masked(...)` 生成临时 `std::array` 后再 `grhsim_assign_words_N(...)`，改为直接复用已有 `grhsim_apply_masked_words_inplace(state, data, mask, width)`。
- memory wide masked write 已经使用该 helper，本实验把普通 state write 对齐到同一代码形态。

改动范围：

- `wolvrix/lib/emit/grhsim_cpp.cpp`
  - 普通 wide state masked write emit 改为 in-place helper。
- `wolvrix/tests/emit/test_emit_grhsim_cpp.cpp`
  - 单测期望从 `grhsim_merge_words_masked` 更新为 `grhsim_apply_masked_words_inplace`。

局部验证：

```text
cmake --build wolvrix/build --target emit-grhsim-cpp -j$(nproc)
ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'
```

结果：通过。

NO0118 fresh emit：

- 输出目录：`tmp/no0118_xs_emit_wide_masked_inplace/grhsim_emit`
- `activity-schedule`: `191465ms`
- `write_grhsim_cpp`: `40062ms`
- total real: `264.39s`
- `compute_supernodes`: `74430`
- `commit_supernodes`: `515`
- supernodes: `74945`
- DAG edges: `485905`
- boundary values: `1151073`
- boundary activation edges: `2216514`
- commit scalar table 诊断：
  - `candidates=1238762`
  - `accepted=1231479`
  - `reject_memory=4889`
  - `reject_wide=2380`
  - `reject_next_slot=14`

生成代码计数：

| 指标 | NO0117 | NO0118 |
| --- | ---: | ---: |
| `grhsim_merge_words_masked(` | `1640` | `0` |
| `grhsim_apply_masked_words_inplace(` | 未记录 | `4736` |
| state wide `assign_words_*<...>(grhsim_state_words...)` | `821` | `0` |
| `apply_commit_scalar_state_write_table(` | `3733` | `3733` |
| `apply_commit_scalar_state_write_*_range(` | `918` | `918` |

NO0118 build/runtime：

- model build real: `255.51s`
- model build user/sys: `5717.37s` / `57.63s`
- difftest emu build: 成功。
- CoreMark 50k 退出码：`0`
- 未出现 difftest mismatch。
- `Guest cycle spent`: `50001`
- `Host time spent`: `358037ms`
- 折算速度：约 `139.7 cycles/s`

NO0118 进度点：

| model cycles | host ms | cumulative cycles/s |
| ---: | ---: | ---: |
| `10000` | `31789` | `315` |
| `20000` | `107531` | `186` |
| `30000` | `185791` | `161` |
| `40000` | `266091` | `150` |
| `50000` | `358025` | `140` |

对比：

| 指标 | NO0116 | NO0117 | NO0118 |
| --- | ---: | ---: | ---: |
| `activity-schedule` | `191458ms` | `192934ms` | `191465ms` |
| `write_grhsim_cpp` | `40819ms` | `41266ms` | `40062ms` |
| model build real | `256.84s` | `258.75s` | `255.51s` |
| 50k `Host time spent` | `363258ms` | `358605ms` | `358037ms` |
| 50k throughput | `137.6 cycles/s` | `139.4 cycles/s` | `139.7 cycles/s` |

判断：

- NO0118 成功消除了 `grhsim_merge_words_masked` 产生的 wide temporary，build 和 runtime 都小幅改善。
- 相比 NO0117，model build 快 `3.24s`，约 `1.25%`；CoreMark 50k 快 `568ms`，约 `0.16%`。
- NO0118 是当前已测最佳 CoreMark 50k 点：约 `139.7 cycles/s`。
- 后续更高收益方向应转向 wide compute 高频 helper。NO0118 生成代码中高频 wide helper 计数为：`grhsim_get_bit_words(` `39142`、`grhsim_and_words(` `13167`、`grhsim_or_words(` `9410`、`grhsim_not_words(` `4813`、`grhsim_shl_words(` `3388`、`grhsim_lshr_words(` `2207`。

