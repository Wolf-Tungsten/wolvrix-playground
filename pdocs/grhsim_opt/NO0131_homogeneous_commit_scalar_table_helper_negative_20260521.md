# NO0131: specialized homogeneous commit scalar table helper negative

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


背景：

- 已有 20k perf 样本显示热点分散在 `eval_commit_batch_*`，且 `apply_commit_scalar_state_write_table` 是最高单个具名 helper，self 约 `1.30%`。
- 统计 NO0128 fresh 产物中的 generic direct commit scalar table：
  - table 数：`3732`
  - entry 数：`22737`
  - homogeneous table 数：`3363`
  - homogeneous entry 数：`19864`
  - homogeneous entry 占比：`87.36%`
- 因此做一个小实验：对 homogeneous generic table 调用生成 typed helper：
  - `apply_commit_scalar_state_write_bool_table`
  - `apply_commit_scalar_state_write_u8_table`
  - `apply_commit_scalar_state_write_u16_table`
  - `apply_commit_scalar_state_write_u32_table`
  - `apply_commit_scalar_state_write_u64_table`
- 目标是消掉 per-entry `switch(kind)`，mixed table 和 existing range helper 不动。

实现与验证：

- 修改 `wolvrix/lib/emit/grhsim_cpp.cpp`：
  - `EmitModel::emitSpecializedCommitScalarTables`
  - emitter option/env:
    - `emit_specialized_commit_scalar_tables`
    - `GRHSIM_EMIT_SPECIALIZED_COMMIT_SCALAR_TABLES`
  - homogeneous generic commit table 改调 typed helper。
  - runtime 生成 typed helper 声明和定义。
- 修改 Python/XS 透传：
  - `scripts/wolvrix_xs_grhsim.py`
  - `wolvrix/app/pybind/wolvrix/__init__.py`
  - `wolvrix/app/pybind/native/actions/emit.cpp`
- 修改 `wolvrix/tests/emit/test_emit_grhsim_cpp.cpp`：
  - 默认 commit-cond-batch 仍检查 generic helper。
  - 开关路径检查 homogeneous u8 commit table 改为 typed helper。
- 验证：
  - `cmake --build wolvrix/build --target emit-grhsim-cpp -j$(nproc)` 通过。
  - `ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'` 通过，`55.74s`。
  - `python3 -m pip install --no-build-isolation -e wolvrix` 通过。

fresh XiangShan emit/build/runtime：

- fresh emit dir：
  - `tmp/no0131_xs_emit_specialized_commit_scalar_tables/grhsim_emit`
- schedule 结构保持与 NO0128 对齐：
  - `compute_supernodes=74430`
  - `commit_supernodes=515`
  - `dag_edges=485905`
  - `boundary_values=1151073`
  - `boundary_activation_edges=2216514`
- emit timing：
  - `activity-schedule=188506ms`
  - `write_grhsim_cpp=40981ms`
  - `total=251599ms`
- 生成代码形态确认：
  - generic `apply_commit_scalar_state_write_table(` count: `371`
  - typed `apply_commit_scalar_state_write_(bool|u8|u16|u32|u64)_table(` count: `3373`
  - typed range helper count: `923`
- model build：
  - `real 256.13s`
  - `user 5698.61s`
  - `sys 58.98s`
- difftest emu build：
  - `real 7.41s`
  - 成功链接 `tmp/no0131_xs_emit_specialized_commit_scalar_tables_emu/grhsim-compile/emu`
- CoreMark 20k:
  - 命令包含 `--diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`
  - 退出码：`0`
  - 未出现 difftest mismatch。
  - `Guest cycle spent`: `20001`
  - `Host time spent`: `99527ms`
- CoreMark 50k:
  - 命令包含 `--diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`
  - 退出码：`0`
  - 未出现 difftest mismatch。
  - `Guest cycle spent`: `50001`
  - `Host time spent`: `351903ms`
  - 约 `142.1 cycles/s`

判断：

- NO0131 成功把大部分 homogeneous generic commit table 调用转为 typed helper，但 50k runtime 比 NO0128 当次复测 `348992ms` 慢约 `2911ms`，约 `0.83%`。
- 消掉 `switch(kind)` 没有收益，可能是编译器对原 helper 已经优化得足够好，或者多 helper 增加了 I-cache/调用形态成本。
- 保留为非默认实验开关，不默认启用；后续不要继续围绕 commit scalar typed table helper specialization 投入。

