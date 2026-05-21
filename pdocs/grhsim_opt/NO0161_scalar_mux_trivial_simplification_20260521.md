# NO0161: scalar mux trivial simplification

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


背景：

- NO0137 好档位生成物中 `grhsim_mux_u64(` 调用约 `776456` 个，是静态最高频 scalar helper。
- 之前 `emit_scalar_mux_ternary` 全局改三目表达式是负向；本轮不改变普通 mux 形态，只删除语义上无效的 trivial mux。
- 对 NO0137 生成物做静态扫描，至少存在约 `3075` 个 `grhsim_mux_u64(cond, 0, 0)` 形态；另有常量 true 条件形态，例如 `static_cast<bool>(((UINT64_C(1)) & UINT64_C(1)))`。

实现：

- 修改 `wolvrix/lib/emit/grhsim_cpp.cpp` 的 scalar `kMux` emit：
  - 条件表达式可静态判定为 true/false 时，直接选择对应 arm。
  - IR operand 的 true/false arm 相同，或生成表达式相同，直接输出共享 arm。
  - 两个 arm 都可静态判定为 unsigned zero，直接输出 `UINT64_C(0)`。
  - 两个 IR arm 都是 const zero 时，直接输出 `UINT64_C(0)`。
- 普通未知条件 mux 仍默认生成 `grhsim_mux_u64`，不引入 `?:`。

验证：

- `cmake --build wolvrix/build --target emit-grhsim-cpp -j32`：通过。
- `ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'`：通过，`56.45s`。
- 单测新增 `scalar_mux_const_true_op`、`scalar_mux_const_false_op`、`scalar_mux_same_arm_op`、`scalar_mux_zero_arm_op`，并检查这些 op block 中不再出现 `grhsim_mux_u64(`。
- 单测保留 `scalar_mux_op` 默认 `grhsim_mux_u64(` 检查，确认没有把普通 mux 改成全局三目表达式。

判断：

- 这是低风险代码形态清理，能减少一部分无效 scalar mux helper 调用和生成代码，但预期收益小于 1%。
- XiangShan fresh emit/build/CoreMark 50k 已完成，未看到 runtime 收益。
- 当前 C1/C2 主体结构的 `BAE`、`boundary_values` 与 build/runtime 都显著变重，因此本轮不能把 scalar mux trivial simplification 作为有效提速方向；它只能作为低风险清理保留或后续随主线结构优化一起复测。

XiangShan fresh emit/build/CoreMark 50k 验收：

- 目录：`tmp/no0161_xs_scalar_mux_trivial`
- 输入修正：
  - `build/xs/rtl/rtl/filelist.f` 内为相对 `.sv` 路径，直接从 repo 根调用会失败。
  - 本轮生成实验专用绝对路径 filelist：`tmp/no0161_xs_scalar_mux_trivial/xs_wolf_abs.f`。
  - read args：`-I build/xs/rtl/rtl`、`-I testcase/xiangshan/difftest/src/test/vsrc/common`、`-I testcase/xiangshan/build/generated-src`、`-D DIFFTEST`。
- 配置：
  - `ESSENT_MFFC_BUILD=1`
  - `ESSENT_COARSEN=1`
  - `SMALL_SIBLING_MERGE=1`
  - `SMALL_OVERLAP_MERGE=0`
  - `DOWN_MERGE=0`
  - `SMALL_SIBLING_MAX_PREDS=2`
  - `SMALL_SIBLING_CANDIDATE_BUDGET=250000`
  - `SCHED_BATCH_TARGET_COUNT=800`

fresh emit：

- `/usr/bin/time`: `real 1199.48s`
- 关键阶段：
  - `read_sv`: `41336ms`
  - `comb-lane-pack`: `181516ms`
  - first `simplify`: `234667ms`
  - `stats`: `269843ms`
  - `activity-schedule`: `220451ms`
  - `write_grhsim_cpp`: `78393ms`
- post-stats:
  - `top_total_ops=5284053`
  - `top_compute_ops=4390655`
  - `top_values=4692495`
- activity schedule:
  - `compute_nodes=3720195`
  - `essent_single_parent_merges=305822`
  - `essent_small_sibling_merges=91002`
  - `compute_supernodes=73656`
  - `commit_supernodes=515`
  - `supernodes=74171`
  - `dag_edges=670160`
  - `boundary_values=1905504`
  - `boundary_activation_edges=3090763`
  - `compute_compute_value_pairs=2732649`
  - `compute_commit_value_pairs=358114`
  - `ops_mean=123.213`
  - `ops_p90=128`
  - `ops_p99=482`
  - `ops_max=8192`
  - `outdeg_p99=95`
  - `outdeg_max=8478`
- generated shape:
  - `grhsim_emit` 文件数：`1112`
  - `grhsim_emit` 目录：`6.1G`
  - `grhsim_mux_u64(` 静态匹配：`768875` matches，`616` files contained matches

build / relink：

- model archive 强制重编：
  - `real 910.93s`
  - `user 14909.27s`
  - `sys 104.63s`
- 尾部瓶颈：`grhsim_SimTop_state_init_12.cpp` 最后单独拖尾，该文件约 `1.9M`、`16391` 行。
- `libgrhsim_SimTop.a`：`175M`
- difftest emu relink：
  - `real 1.25s`
  - 未触发 model archive 重编。

CoreMark 50k：

- 命令口径：difftest enabled，`EMU_PROGRESS_EVERY_CYCLES=10000`。
- 进度：
  - 10k: `host_ms=43489`
  - 20k: `host_ms=168711`
  - 30k: `host_ms=296961`
  - 40k: `host_ms=428203`
  - 50k: `host_ms=577683`
- `Host time spent=577703ms`
- 约 `86.55 cycles/s`
- 退出码 `0`，退出原因是达到 `-C 50000` cycle limit，未出现 difftest mismatch。

对比与结论：

- NO0137 好档 50k：`346589ms`，约 `144.3 cycles/s`。
- NO0160 C4 dynamic 负向 50k：`539617ms`，约 `92.66 cycles/s`。
- NO0161 fresh 50k：`577703ms`，约 `86.55 cycles/s`。
- NO0161 的 scalar mux trivial simplification 没有转成 XiangShan runtime 收益；当前 C1/C2 主体的结构代价更大，尤其 `BAE=3090763` 明显高于 NO0137 的 `2216514`。
- 下一步主线应先修 C1/C2 的 boundary/materialization 成本，让 `compute_supernodes` 维持 70k 量级的同时，把 `BAE` 拉回 NO0137 附近或更低；在这个基础上再评估 scalar mux/helper 微优化。
