# NO0124: 2-word shift overload clean A/B positive result

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


实验目的：

- NO0118 中高频 wide helper 计数显示：
  - `grhsim_shl_words(`: `3388`
  - `grhsim_lshr_words(`: `2207`
- 针对 65-128 bit 的 shift，增加 `std::array<std::uint64_t, 2>` overload，避免 generic `N` 版本中的循环与分支。
- 该优化不改变 schedule，不改变调用点；由 C++ overload resolution 在 `N=2` 时自动选择专门化。

实现与验证：

- 代码改动：
  - `wolvrix/lib/emit/grhsim_cpp.cpp`
    - 新增 2-word `grhsim_shl_words` overload。
    - 新增 2-word `grhsim_lshr_words` overload。
  - `wolvrix/tests/emit/test_emit_grhsim_cpp.cpp`
    - 检查 runtime 模板包含 2-word shift overload。
    - 复用已有 wide shift harness 做语义覆盖。
- 局部验证：
  - `cmake --build wolvrix/build --target emit-grhsim-cpp -j$(nproc)`：通过。
  - `ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'`：通过，`61.88s`。
  - `python3 -m pip install --no-build-isolation -e wolvrix`：通过。

NO0124 prototype：

- 在 NO0118 生成目录上临时只替换 `grhsim_SimTop_runtime.hpp`，不重跑 emit，验证 helper 本身是否值得回填。
- model build：
  - `real 256.47s`
- difftest emu build：
  - `real 8.04s`
- CoreMark 20k：
  - 退出码：`0`
  - 未出现 difftest mismatch。
  - `Host time spent`: `108043ms`
- CoreMark 50k：
  - 退出码：`0`
  - 未出现 difftest mismatch。
  - `Host time spent`: `347343ms`
  - 折算速度：约 `144.0 cycles/s`
- prototype 后已恢复 NO0118 生成目录的 runtime header，避免污染基准目录。

NO0124 fresh emit：

- 输出目录：`tmp/no0124_xs_emit_shift2_overload/grhsim_emit`
- 配置对齐 NO0118 的 C2 full cap128：
  - `WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD=1`
  - `WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN=1`
  - `WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_SIBLING_MERGE=1`
  - `WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE=0`
  - `WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE=0`
  - `WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_MAX_PREDS=0`
  - `WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_CANDIDATE_BUDGET=0`
- `activity-schedule`: `193989ms`
- `write_grhsim_cpp`: `39962ms`
- total wall time: `259541ms`
- `compute_supernodes`: `74430`
- `commit_supernodes`: `515`
- `dag_edges`: `485905`
- `boundary_values`: `1151073`
- `boundary_activation_edges`: `2216514`
- `grhsim_(shl|lshr)_words(` generated calls: `5595`
- runtime helper 确认：
  - `std::array<std::uint64_t, 2> grhsim_shl_words`
  - `std::array<std::uint64_t, 2> grhsim_lshr_words`

NO0124 build/runtime：

- model build：
  - `real 256.32s`
  - `user 5707.46s`
  - `sys 58.62s`
- difftest emu build：
  - `real 7.46s`
  - 成功链接 `tmp/no0124_xs_emit_shift2_overload_emu/grhsim-compile/emu`
- CoreMark 20k：
  - 命令包含 `--diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`
  - 退出码：`0`
  - 未出现 difftest mismatch。
  - `Guest cycle spent`: `20001`
  - `Host time spent`: `110258ms`
  - 折算速度：约 `181.4 cycles/s`
- CoreMark 50k：
  - 命令包含 `--diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`
  - 退出码：`0`
  - 未出现 difftest mismatch。
  - `Guest cycle spent`: `50001`
  - `Host time spent`: `349396ms`
  - 折算速度：约 `143.1 cycles/s`

NO0124 50k 进度点：

| model cycles | host ms | cumulative cycles/s |
| ---: | ---: | ---: |
| `10000` | `23964` | `417` |
| `20000` | `99122` | `202` |
| `30000` | `177434` | `169` |
| `40000` | `257576` | `155` |
| `50000` | `349384` | `143` |

对比 NO0118：

| 指标 | NO0118 | NO0124 |
| --- | ---: | ---: |
| `activity-schedule` | `191465ms` | `193989ms` |
| `write_grhsim_cpp` | `40062ms` | `39962ms` |
| `compute_supernodes` | `74430` | `74430` |
| `dag_edges` | `485905` | `485905` |
| `boundary_activation_edges` | `2216514` | `2216514` |
| model build real | `255.51s` | `256.32s` |
| 50k `Host time spent` | `358037ms` | `349396ms` |
| 50k throughput | `139.7 cycles/s` | `143.1 cycles/s` |

判断：

- NO0124 是 clean A/B：schedule 结构与 NO0118 完全一致，差异只在 runtime helper 代码形态。
- 2-word shift overload 对 CoreMark 50k 有真实收益：相比 NO0118 快 `8641ms`，约 `2.41%`。
- model build 基本不变：`256.32s` 对 `255.51s`，慢 `0.81s`，约 `0.32%`。
- 当前已测最佳更新为 NO0124：CoreMark 50k 约 `143.1 cycles/s`。
- 该优化离 5x 目标仍很远，但给出一个有效方向：优先针对高频 `N=2` wide helper 做 overload，而不是展开生成代码或引入 batch-level runtime guard。

