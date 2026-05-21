# NO0141: scalar LogicAnd/LogicOr constant absorb 50k check

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


背景：

- 观察到生成代码中仍有大量标量逻辑形态：
  - `x && UINT64_C(1)`
  - `x || UINT64_C(0)`
- 在 `scalarAssignmentExpr` 中加入 `kLogicAnd/kLogicOr` 常量吸收：
  - `x && 0 -> false`
  - `x && 1 -> x`
  - `x || 0 -> x`
  - `x || 1 -> true`

验证：

- `cmake --build wolvrix/build --target emit-grhsim-cpp -j32`：通过。
- `ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'`：通过，`56.62s`。
- `python3 -m py_compile scripts/wolvrix_xs_grhsim.py`：通过。
- `python3 -m pip install --no-build-isolation -e wolvrix`：通过。

XiangShan emit/build/runtime：

- emit dir：
  - `tmp/no0141_xs_logic_const_absorb/grhsim_emit`
- schedule 结构：
  - `supernodes=82676`
  - `compute_supernodes=82143`
  - `commit_supernodes=533`
  - `dag_edges=1294877`
  - `boundary_values=1418765`
  - `boundary_activation_edges=2791790`
  - `compute_compute_value_pairs=2411498`
  - `compute_commit_value_pairs=380292`
  - `ops_mean=91.896`
  - `ops_p99=108`
  - `outdeg_p99=185`
- emit timing：
  - `read_json_file=27057ms`
  - `activity-schedule=436916ms`
  - `write_grhsim_cpp=41787ms`
  - `total=505760ms`
- model + emu build：
  - 初次 build 未设置 `WITH_CONSTANTIN=0`，失败于缺少 `tmp/no0141_xs_logic_const_absorb/build/constantin.cpp`。
  - 使用 `WITH_CONSTANTIN=0` 重跑成功。
  - `real 312.81s`
  - `user 7873.39s`
  - `sys 77.87s`
- CoreMark 50k：
  - 10k: `host_ms=39605`
  - 20k: `host_ms=134943`
  - 30k: `host_ms=232082`
  - 40k: `host_ms=331145`
  - 50k: `host_ms=445599`
  - `Guest cycle spent=50001`
  - `Host time spent=445615ms`
  - 约 `112.2 cycles/s`
  - 退出码 `0`，未出现 difftest mismatch。

关键诊断：

- 静态目标形态没有被消除：
  - `x && UINT64_C(1)` / `x || UINT64_C(0)` 类 pattern 仍为 `6215` 处。
- 当前实现把 `LogicAnd/LogicOr` 的 `1` 判定写成了 `isConstLogicAllOnes(...)`。
- 但 SystemVerilog 逻辑 `&&` / `||` 的常量真值语义应判断 `non-zero`，不是判断 all-ones。
  - 例如 32-bit 常量 `32'd1` 是逻辑真，但不是 all-ones。
- 因此本轮 runtime 是当前源码的真实 50k 结果，但该优化没有有效命中目标热形态，不能作为该方向无效的最终结论。

判断：

- 相比 NO0139 off 50k `370943ms`，本轮 `445615ms` 慢约 `20.1%`。
- 相比 NO0137 50k `346589ms`，本轮慢约 `28.6%`。
- 负收益主要来自本轮同源 schedule 结构膨胀：
  - NO0139 off `boundary_activation_edges=2451687`
  - NO0141 `boundary_activation_edges=2791790`
  - BAE 增加约 `13.9%`
- 下一步应修正 `LogicAnd/LogicOr` 常量吸收为 `const zero` / `const non-zero` 语义，再重新做同源 emit/build/20k；20k 正向后再跑 50k。

