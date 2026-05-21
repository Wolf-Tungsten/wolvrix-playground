# NO0154: current improved coremark 50k full test

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


背景：

- 用户要求测试“改进后的 coremark 50k 性能”。
- 使用当前工作区代码 fresh emit/build/link/run，未复用 NO0153 二进制。
- 运行前验证：
  - `cmake --build wolvrix/build --target emit-grhsim-cpp -j32`：通过。
  - `ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'`：通过，`56.85s`。
  - `python3 -m pip install --no-build-isolation -e wolvrix`：通过。

配置：

- fresh emit/build 目录：`tmp/no0154_xs_current_coremark50k`
- C1/C2/C4 dynamic 主体，`small_sibling_merge=1`，`small_overlap_merge=0`，`down_merge=0`
- `WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_MAX_PREDS=2`
- `WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_CANDIDATE_BUDGET=250000`
- `WOLVRIX_XS_GRHSIM_SCHED_BATCH_TARGET_COUNT=800`

fresh emit：

- `read_json_file done 22275ms`
- `activity-schedule done 189672ms`
- `write_grhsim_cpp done 43263ms`
- `total done 255211ms`
- `/usr/bin/time`: `real 256.78s`
- 结构：
  - `supernodes=74171`
  - `compute_supernodes=73656`
  - `commit_supernodes=515`
  - `dag_edges=670160`
  - `boundary_values=1276942`
  - `boundary_activation_edges=2462201`
  - `clusters_after_essent_coarsen=3323371`
  - `compute_node_boundary_values=4221447`
  - `commit_input_root_values=358187`

静态代码形态：

- sched lines: `21643616`
- `libgrhsim_SimTop.a` object text 汇总：`122443585`

build / relink：

- model archive 强制重编：
  - `real 266.46s`
  - `user 6029.80s`
  - `sys 63.72s`
- difftest emu relink：
  - `real 1.23s`

CoreMark 50k：

- 命令口径：difftest enabled，`EMU_PROGRESS_EVERY_CYCLES=10000`。
- 进度：
  - 10k: `host_ms=24299`
  - 20k: `host_ms=103348`
  - 30k: `host_ms=185380`
  - 40k: `host_ms=269714`
  - 50k: `host_ms=367319`
- `Host time spent=367333ms`
- 约 `136.12 cycles/s`
- 退出码 `0`，未出现 difftest mismatch。

对比：

- NO0137 50k: `346589ms`，约 `144.3 cycles/s`
- NO0151 50k: `347835ms`，约 `143.75 cycles/s`
- NO0152 50k: `348563ms`，约 `143.45 cycles/s`
- NO0153 50k: `368129ms`，约 `135.82 cycles/s`
- NO0154 50k: `367333ms`，约 `136.12 cycles/s`

判断：

- 当前“改进后”代码没有带来 runtime 收益，50k 仍处于 NO0153 慢档，比 NO0137 慢约 `20744ms`。
- NO0154 结构与 NO0153 基本一致，尤其 `dag_edges=670160`、`BAE=2462201`、sched lines `21643616`、`.text` 约 `122.4M`，明显大于 NO0151/NO0152 的较小结构。
- 这说明当前瓶颈更像是结构漂移导致的前端压力/dispatch 压力，而不是单个 helper 微优化问题。下一步应先恢复或解释 NO0151/NO0152 的较小 DAG/BAE 结构，再谈 helper 级优化收益。

