# NO0142: scalar LogicAnd/LogicOr non-zero constant absorb

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


背景：

- NO0141 的实现把逻辑真常量判断成 all-ones，导致 `32'd1` 这类 SystemVerilog 逻辑真值没有被吸收。
- 本轮把 `kLogicAnd/kLogicOr` 的常量真值判断改成 non-zero 语义：
  - `x && const_zero -> false`
  - `x && const_nonzero -> x`
  - `x || const_zero -> x`
  - `x || const_nonzero -> true`

实现：

- `wolvrix/lib/emit/grhsim_cpp.cpp`
  - 新增 `isConstLogicAnyNonZero(...)`。
  - `operandIsConstOne` 改为使用 non-zero 语义，不再要求 all-ones。
- `wolvrix/tests/emit/test_emit_grhsim_cpp.cpp`
  - 增加 `32'd1` / `32'd0` 的 `logic_and_*`、`logic_or_*` fixture。
  - 检查生成代码中对应 op block 不再保留 `&&` / `||`。
  - 增加 harness 语义断言。

验证：

- `cmake --build wolvrix/build --target emit-grhsim-cpp -j32`：通过。
- `ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'`：通过，约 `56.53s`。
- `python3 -m py_compile scripts/wolvrix_xs_grhsim.py`：通过。
- `python3 -m pip install --no-build-isolation -e wolvrix`：通过。

XiangShan emit/build/runtime：

- emit dir：
  - `tmp/no0142_xs_logic_const_nonzero/grhsim_emit`
- schedule 结构：
  - `supernodes=82676`
  - `compute_supernodes=82143`
  - `commit_supernodes=533`
  - `dag_edges=1294877`
  - `boundary_values=1418765`
  - `boundary_activation_edges=2791790`
- emit timing：
  - `read_json_file=25130ms`
  - `activity-schedule=437392ms`
  - `write_grhsim_cpp=41950ms`
  - `total=504473ms`
  - `real 506.23s`
- model + emu build：
  - `real 308.24s`
  - `user 7866.00s`
  - `sys 78.16s`
- 静态目标形态：
  - NO0141 中 `x && 32'd1` / `x || 32'd0` 类 pattern：`6215`
  - NO0142 同类 pattern：`0`
- CoreMark 50k：
  - 10k: `host_ms=39669`
  - 20k: `host_ms=134819`
  - 30k: `host_ms=231869`
  - 40k: `host_ms=330861`
  - 50k: `host_ms=444675`
  - `Guest cycle spent=50001`
  - `Host time spent=444690ms`
  - 约 `112.4 cycles/s`
  - 退出码 `0`，未出现 difftest mismatch。

判断：

- 语义修正有效，静态目标 pattern 从 `6215` 降到 `0`。
- runtime 基本不变：NO0141 `445615ms`，NO0142 `444690ms`，只快约 `0.2%`。
- 该方向不是主要瓶颈；后续不应继续在 scalar `LogicAnd/LogicOr` 常量吸收上投入，除非 perf 显示对应 batch 仍是热点。
- 下一步应回到高频 runtime path：wide helper、commit batch、activation/boundary value load/store，优先用真实 CoreMark 或 perf 证据选择候选。

