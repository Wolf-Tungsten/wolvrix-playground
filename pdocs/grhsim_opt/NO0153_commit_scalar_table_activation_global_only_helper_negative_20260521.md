# NO0153: commit scalar table activation global-only helper negative result

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


背景：

- NO0150 perf 指向 `eval_commit_batch_*` 和 `apply_commit_scalar_state_write_table`。
- 对 NO0152 生成物做静态统计后发现，commit scalar table/range 调用的 activation masks 均不指向当前 active word：
  - table 调用：`3732`
  - table `globalOnly=true`：`3732`
  - table `globalOnly=false`：`0`
  - table+range 调用：`4645`
  - activation entry 分布：`1:342, 2:2093, 3:1824, 4:233, 5:56, 6:32, 7:27, 8:7, 9:2, 10:3, 12:6, 13:4, 15:16`
- 因此尝试在 emit 期判断 activation masks 是否全局化，table helper 走 `apply_commit_activation_masks_global()`，去掉 helper 内 `word_index == currentActiveWordIndex` 分支。

实现与验证：

- 实验改动只影响 commit scalar table helper，range helper 保持原路径。
- 局部验证：
  - `cmake --build wolvrix/build --target emit-grhsim-cpp -j32`：通过。
  - `ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'`：通过。
  - `python3 -m pip install --no-build-isolation -e wolvrix`：通过。
- 由于 50k 结果明显负向，实验代码已从默认 generator 路径撤回；本文仅保留实测记录。

配置：

- fresh emit/build 目录：`tmp/no0153_xs_commit_activation_global_only`
- C1/C2/C4 dynamic 主体，`small_sibling_merge=1`，`small_overlap_merge=0`，`down_merge=0`
- `WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_MAX_PREDS=2`
- `WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_CANDIDATE_BUDGET=250000`

fresh emit：

- `read_json_file done 22323ms`
- `activity-schedule done 188246ms`
- `write_grhsim_cpp done 42403ms`
- `total done 253960ms`
- `/usr/bin/time`: `real 255.51s`
- 结构：
  - `supernodes=74171`
  - `compute_supernodes=73656`
  - `commit_supernodes=515`
  - `dag_edges=670160`
  - `boundary_values=1276942`
  - `boundary_activation_edges=2462201`
  - `clusters_after_essent_coarsen=3323371`

注意：

- NO0153 的 schedule 结构与 NO0148/NO0151/NO0152 不完全一致：
  - NO0152: `compute_supernodes=74430`, `dag_edges=485905`, `BAE=2216514`
  - NO0153: `compute_supernodes=73656`, `dag_edges=670160`, `BAE=2462201`
- 因此 NO0153 不是严格 clean A/B，只能作为当前工作区真实路径下的完整负向实验。

静态代码形态：

- table 调用：`3723`
- table `globalOnly=true`：`3723`
- table `globalOnly=false`：`0`
- sched lines: `21643616`
- 目录大小：`2.0G`
- `libgrhsim_SimTop.a` text 汇总：`122495887`

build / relink：

- model archive 强制重编：
  - `real 267.08s`
  - `user 6011.83s`
  - `sys 63.21s`
- difftest emu relink：
  - `real 1.23s`

CoreMark：

- 命令口径：difftest enabled，`EMU_PROGRESS_EVERY_CYCLES=10000`。
- 20k gate:
  - 10k: `host_ms=24324`
  - 20k: `host_ms=103362`
  - `Host time spent=103369ms`
- 50k:
  - 10k: `host_ms=24477`
  - 20k: `host_ms=103516`
  - 30k: `host_ms=186073`
  - 40k: `host_ms=270544`
  - 50k: `host_ms=368115`
  - `Host time spent=368129ms`
  - 约 `135.82 cycles/s`
  - 退出码 `0`，未出现 difftest mismatch。

对比：

- NO0137 50k: `346589ms`，约 `144.3 cycles/s`
- NO0151 50k: `347835ms`，约 `143.75 cycles/s`
- NO0152 50k: `348563ms`，约 `143.45 cycles/s`
- NO0153 50k: `368129ms`，约 `135.82 cycles/s`

判断：

- 尽管静态分析显示 activation masks 全是 global-only，单独抽出 global-only helper 没有转成 runtime 收益。
- 负向主因很可能不是 `word_index == currentActiveWordIndex` 分支本身，而是本轮 schedule 结构漂移带来的 `.text` 增长、边数/BAE 增长和 frontend 压力增加。
- 该方向不应作为默认优化；若未来复查，必须先固定 schedule 结构做 clean A/B，并优先处理能显著减少 `.text` / batch dispatch / commit table 调用次数的结构性策略。

