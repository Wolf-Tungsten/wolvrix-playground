# NO0129: scalar mux ternary prototype negative smoke

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


背景：

- NO0128 fresh 产物 helper 调用计数中，`grhsim_mux_u64(` 是最大头部：
  - `grhsim_mux_u64`: `776858`
  - `grhsim_compare_unsigned_u64`: `45400`
  - `grhsim_get_bit_words`: `39142`
  - `grhsim_reduce_or_u64`: `33060`
- 原默认 scalar mux 使用 branchless mask-select helper：
  - `grhsim_mux_u64(cond, trueValue, falseValue)`
- 本实验增加一个非默认开关：
  - emitter attribute: `emit_scalar_mux_ternary`
  - env: `GRHSIM_EMIT_SCALAR_MUX_TERNARY`
  - XiangShan script env: `WOLVRIX_XS_GRHSIM_EMIT_SCALAR_MUX_TERNARY`
- 开关打开时，scalar mux emit 为 C++ `?:`，以测试短路求值能否减少嵌套 mux 链成本。

实现与验证：

- 修改 `wolvrix/lib/emit/grhsim_cpp.cpp`：
  - `EmitModel::emitScalarMuxTernary`
  - `kMux` scalar emit 可选择 `?:`
- 修改 Python pybind：
  - `wolvrix/app/pybind/wolvrix/__init__.py`
  - `wolvrix/app/pybind/native/actions/emit.cpp`
- 修改 `scripts/wolvrix_xs_grhsim.py`：
  - 透传 `WOLVRIX_XS_GRHSIM_EMIT_SCALAR_MUX_TERNARY`
- 修改 `wolvrix/tests/emit/test_emit_grhsim_cpp.cpp`：
  - 默认路径仍检查 `grhsim_mux_u64`。
  - 开关路径检查 scalar mux 变为 `?:`。
- 验证：
  - `cmake --build wolvrix/build --target emit-grhsim-cpp -j$(nproc)` 通过。
  - `ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'` 通过，`61.88s`。
  - `python3 -m pip install --no-build-isolation -e wolvrix` 通过。

fresh XiangShan emit/build/runtime：

- fresh emit dir：
  - `tmp/no0129_xs_emit_scalar_mux_ternary/grhsim_emit`
- schedule 结构保持与 NO0128 对齐：
  - `compute_supernodes=74430`
  - `commit_supernodes=515`
  - `dag_edges=485905`
  - `boundary_values=1151073`
  - `boundary_activation_edges=2216514`
- emit timing：
  - `activity-schedule=194624ms`
  - `write_grhsim_cpp=40323ms`
  - `total=259642ms`
- schedule 形态确认：
  - `grhsim_mux_u64(` count: `0`
  - ` ? (` count: `776858`
- model build：
  - `real 259.92s`
  - `user 5895.39s`
  - `sys 60.00s`
- difftest emu build：
  - `real 7.45s`
  - 成功链接 `tmp/no0129_xs_emit_scalar_mux_ternary_emu/grhsim-compile/emu`
- CoreMark 20k:
  - 命令包含 `--diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`
  - 退出码：`0`
  - 未出现 difftest mismatch。
  - `Guest cycle spent`: `20001`
  - `Host time spent`: `118897ms`

判断：

- NO0129 20k 比 NO0128 的 `109998ms` 慢约 `8.1%`，方向明确为负。
- 不继续跑 50k。
- 结论：高频 `grhsim_mux_u64` 不能简单换成 C++ `?:`。短路求值没有抵消分支/优化形态退化，branchless helper 仍应保持默认。
- 保留该路径为实验开关，不默认启用；后续不要重复 scalar mux ternary 方向，除非有 profiling 证据支持更细分的选择策略。

