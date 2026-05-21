# NO0128: land 2-word reduce-xor overload in emit source

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


实现内容：

- 在 `wolvrix/lib/emit/grhsim_cpp.cpp` 的 runtime template 中加入：
  - `inline bool grhsim_reduce_xor_words(const std::array<std::uint64_t, 2> &, std::size_t width)`
  - `width <= 64` 直接 popcount low word。
  - `65 <= width <= 128` 直接 popcount low word 与截断后的 high word。
- 在 `wolvrix/tests/emit/test_emit_grhsim_cpp.cpp` 的 two-word helper design 中加入 96-bit `kReduceXor` 输出，并在 harness 中覆盖 true/false 两个输入。

本地验证：

- `cmake --build wolvrix/build --target emit-grhsim-cpp -j$(nproc)`
  - 通过。
- `ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'`
  - 通过，`61.79s`。
- `python3 -m pip install --no-build-isolation -e wolvrix`
  - 通过。

fresh XiangShan emit/build/runtime：

- fresh emit dir：
  - `tmp/no0128_xs_emit_reducexor2_src/grhsim_emit`
- schedule 配置与 NO0124/NO0127 对齐：
  - `ENABLE_ESSENT_MFFC_BUILD=1`
  - `ENABLE_ESSENT_COARSEN=1`
  - `ENABLE_ESSENT_SMALL_SIBLING_MERGE=1`
  - overlap/down merge 关闭。
- schedule 结构：
  - `compute_supernodes=74430`
  - `commit_supernodes=515`
  - `dag_edges=485905`
  - `boundary_values=1151073`
  - `boundary_activation_edges=2216514`
- emit timing：
  - `activity-schedule=187792ms`
  - `write_grhsim_cpp=40068ms`
  - `total=261771ms`
- model build：
  - `real 259.36s`
  - `user 5744.46s`
  - `sys 59.29s`
- difftest emu build：
  - `real 7.42s`
  - 成功链接 `tmp/no0128_xs_emit_reducexor2_src_emu/grhsim-compile/emu`
- CoreMark 20k：
  - 命令包含 `--diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`
  - 退出码：`0`
  - 未出现 difftest mismatch。
  - `Guest cycle spent`: `20001`
  - `Host time spent`: `109998ms`
- CoreMark 50k：
  - 命令包含 `--diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`
  - 退出码：`0`
  - 未出现 difftest mismatch。
  - `Guest cycle spent`: `50001`
  - `Host time spent`: `345946ms`
  - 折算约 `144.5 cycles/s`

判断：

- NO0128 是源码落地后的 clean fresh emit/build/runtime，schedule 结构与 NO0124 保持一致。
- 20k 没有复现 NO0127 prototype 的强正向，但 50k 比 NO0124 `349396ms` 快 `3450ms`，约 `0.99%`。
- 当前已测最佳更新为 NO0128：CoreMark 50k 约 `144.5 cycles/s`。
- 该收益仍然很小，说明单个 2-word helper overload 只能做边际改善；5x 目标需要继续定位更大的 runtime 热点，例如宽操作临时对象、schedule dispatch/active mask 成本或 state/value slot 访问形态。

