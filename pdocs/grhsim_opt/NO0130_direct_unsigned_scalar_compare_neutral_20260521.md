# NO0130: direct unsigned scalar compare prototype neutral

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


背景：

- NO0128 fresh 产物中 `grhsim_compare_unsigned_u64(` 调用量约 `45400`，排在 scalar mux 之后。
- 默认 unsigned scalar compare emit 为：
  - `grhsim_compare_unsigned_u64(lhs, rhs, width) <op> 0`
- 本实验增加一个非默认开关：
  - emitter attribute: `emit_direct_unsigned_scalar_compare`
  - env: `GRHSIM_EMIT_DIRECT_UNSIGNED_SCALAR_COMPARE`
  - XiangShan script env: `WOLVRIX_XS_GRHSIM_EMIT_DIRECT_UNSIGNED_SCALAR_COMPARE`
- 开关打开时，仅 unsigned scalar `< <= > >=` 直接 emit 为 C++ 比较；`width < 64` 时两侧显式 `grhsim_trunc_u64(expr, width)`，signed compare 保持 helper。

实现与验证：

- 修改 `wolvrix/lib/emit/grhsim_cpp.cpp`：
  - `EmitModel::emitDirectUnsignedScalarCompare`
  - scalar unsigned compare 可选择直接比较表达式。
- 修改 Python pybind：
  - `wolvrix/app/pybind/wolvrix/__init__.py`
  - `wolvrix/app/pybind/native/actions/emit.cpp`
- 修改 `scripts/wolvrix_xs_grhsim.py`：
  - 透传 `WOLVRIX_XS_GRHSIM_EMIT_DIRECT_UNSIGNED_SCALAR_COMPARE`
- 修改 `wolvrix/tests/emit/test_emit_grhsim_cpp.cpp`：
  - 默认路径仍检查 unsigned scalar compare helper。
  - 开关路径检查 unsigned scalar compare helper 被消除，同时 signed compare helper 保留。
- 验证：
  - `cmake --build wolvrix/build --target emit-grhsim-cpp -j$(nproc)` 通过。
  - `ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'` 通过，`58.10s`。
  - `python3 -m pip install --no-build-isolation -e wolvrix` 通过。

fresh XiangShan emit/build/runtime：

- fresh emit dir：
  - `tmp/no0130_xs_emit_direct_unsigned_scalar_compare/grhsim_emit`
- schedule 结构保持与 NO0128 对齐：
  - `compute_supernodes=74430`
  - `commit_supernodes=515`
  - `dag_edges=485905`
  - `boundary_values=1151073`
  - `boundary_activation_edges=2216514`
- emit timing：
  - `activity-schedule=188007ms`
  - `write_grhsim_cpp=40628ms`
  - `total=251136ms`
- 生成代码形态确认：
  - `grhsim_compare_unsigned_u64(` count: `1`，只剩 runtime helper 定义本身。
  - `grhsim_compare_signed_u64(` count: `1219`，signed 路径未改。
  - `grhsim_trunc_u64(` count: `73216`。
- model build：
  - `real 256.47s`
  - `user 5713.55s`
  - `sys 58.22s`
- difftest emu build：
  - `real 7.42s`
  - 成功链接 `tmp/no0130_xs_emit_direct_unsigned_scalar_compare_emu/grhsim-compile/emu`
- CoreMark 20k:
  - 命令包含 `--diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`
  - 退出码：`0`
  - 未出现 difftest mismatch。
  - `Guest cycle spent`: `20001`
  - `Host time spent`: `97971ms`
- CoreMark 50k:
  - 命令包含 `--diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`
  - 退出码：`0`
  - 未出现 difftest mismatch。
  - `Guest cycle spent`: `50001`
  - `Host time spent`: `349020ms`
  - 约 `143.3 cycles/s`

判断：

- NO0130 在结构上成功消除了约 `45k` 个 unsigned compare helper 调用，但 50k runtime 与 NO0128 当次复测 `348992ms` 完全持平。
- 直接比较引入的 `grhsim_trunc_u64` 与编译器优化后的 helper 形态基本等价，没有形成实际 runtime 收益。
- 保留为实验开关，不默认启用；后续不要继续围绕 scalar unsigned compare helper 消除投入，除非 profiling 显示新的热点证据。

