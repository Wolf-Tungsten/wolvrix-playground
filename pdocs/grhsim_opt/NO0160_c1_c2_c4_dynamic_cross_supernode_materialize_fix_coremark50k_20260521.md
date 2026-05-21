# NO0160: C1/C2/C4 dynamic cross-supernode materialize fix and coremark 50k

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


背景：

- C4 dynamic 下曾出现 emitted C++ 非法引用跨 schedule 局部变量的问题。
- NO0158 fresh emit 后 model build 失败，典型错误为 `grhsim_SimTop_sched_755.cpp` 引用未声明的 `grhsim_v3752435_0`。
- 修复点在 `wolvrix/lib/emit/grhsim_cpp.cpp`：
  - `ScheduleRefs` 引入最终 `op_to_supernode`。
  - persistent value 判定增加基于最终 schedule 的 result/operand 扫描。
  - `scalarAssignmentExpr` 的递归内联增加 context 可见性约束，跨 supernode value 改为 materialized storage 读取。

验证：

- `cmake --build wolvrix/build --target emit-grhsim-cpp -j32`：通过。
- `ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'`：通过。
- `python3 -m pip install --no-build-isolation -e wolvrix`：通过。

配置：

- fresh emit/build 目录：`tmp/no0160_xs_c4_dynamic_context_expr_guard`
- C1/C2/C4 dynamic 主体：
  - `ESSENT_MFFC_BUILD=1`
  - `ESSENT_COARSEN=1`
  - `SMALL_SIBLING_MERGE=1`
  - `SMALL_OVERLAP_MERGE=0`
  - `DOWN_MERGE=1`
  - `SMALL_SIBLING_MAX_PREDS=0`
  - `SMALL_SIBLING_CANDIDATE_BUDGET=0`
  - `SCHED_BATCH_TARGET_COUNT=800`

fresh emit：

- `/usr/bin/time`: `real 434.45s`
- 结构：
  - `compute_supernodes=76592`
  - `commit_supernodes=515`
  - `supernodes=77107`
  - `dag_edges=475522`
  - `boundary_values=1697807`
  - `boundary_activation_edges=2731106`
  - `compute_compute_value_pairs=2372992`
  - `compute_commit_value_pairs=358114`
- sched lines: `35388356`

build / relink：

- model archive 强制重编：
  - `real 1060.92s`
  - `user 16153.60s`
  - `sys 90.07s`
- `libgrhsim_SimTop.a`：`163M`
- `grhsim_emit` 目录：`3.3G`
- object text 汇总：`160150063`
- difftest emu：`154M`

CoreMark 50k：

- 命令口径：difftest enabled，`EMU_PROGRESS_EVERY_CYCLES=10000`。
- 进度：
  - 10k: `host_ms=48686`
  - 20k: `host_ms=165163`
  - 30k: `host_ms=282435`
  - 40k: `host_ms=401886`
  - 50k: `host_ms=539598`
- `Host time spent=539617ms`
- 约 `92.66 cycles/s`
- 退出码 `0`，退出原因是达到 `-C 50000` cycle limit，未出现 difftest mismatch。

判断：

- 修复后 C4 dynamic 的跨 supernode materialize 语义正确，model build 和 XiangShan difftest runtime 均可通过。
- 之前 C4 dynamic 的 `BAE=2146343` 是低估；修正最终 schedule fanout/materialization 后真实 `BAE=2731106`，显著高于 NO0151/NO0152/NO0154。
- 这版不是 runtime 收益方向：50k `92.66 cycles/s`，低于 NO0154 的 `136.12 cycles/s` 和早期约 `120 cycles/s` 基线。
- 当前 C1/C2/C4 dynamic with `DOWN_MERGE=1` 会显著增大 boundary/materialization 和 emitted code 体积；下一步应优先回退或重做 C4 dynamic 的收益函数/合法性约束，避免把低 activation edge 的局部 merge 变成更大的 boundary value 压力。

