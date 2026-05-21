# NO0148: scalar logic const expr absorb fresh C1/C2/C4 dynamic

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


背景：

- NO0137 生成代码中仍有大量 `kLogicAnd/kLogicOr` 的常量表达式没有被吸收，例如 `en && static_cast<std::uint32_t>(UINT64_C(1) & mask)`。
- 原逻辑只识别 IR operand 的 `kConstant`，没有识别 emit 后的等价 C++ 常量表达式。本轮在 emit 侧加入保守的 scalar const expr 解析，吸收 `UINT*_C(...)`、整数后缀、`static_cast<bool/u*/i*>(...)`、顶层 `&`、`grhsim_cast_u64(...)` 等形态。

验证：

- `cmake --build wolvrix/build --target emit-grhsim-cpp -j32`：通过。
- `ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'`：通过。
- `python3 -m py_compile scripts/wolvrix_xs_grhsim.py wolvrix/app/pybind/wolvrix/__init__.py`：通过。
- `python3 -m pip install --no-build-isolation -e wolvrix`：通过。

fresh emit：

- 配置：C1/C2/C4 dynamic 主体，`small_sibling_merge=1`，`small_overlap_merge=0`，`down_merge=0`。
- `read_json_file done 25331ms`
- `activity-schedule done 188221ms`
- `write_grhsim_cpp done 40245ms`
- `total done 253798ms`
- `/usr/bin/time`: `real 255.45s`
- 结构：
  - `supernodes=74945`
  - `compute_supernodes=74430`
  - `commit_supernodes=515`
  - `dag_edges=485905`
  - `boundary_values=1151073`
  - `boundary_activation_edges=2216514`
  - `ops_max=8192`

build / relink：

- model archive 强制重编：
  - `real 255.84s`
  - `user 5726.26s`
  - `sys 62.58s`
- difftest emu relink：
  - `real 1.22s`
- `libgrhsim_SimTop.a` text 汇总：
  - `115953957`
- 目标 warning 模式 `&& ((static_cast<std::uint32_t>(((UINT64_C(1))` 在 NO0148 sched 文件中无命中。

CoreMark 50k：

- 命令口径：difftest enabled，`-C 50000`，`EMU_PROGRESS_EVERY_CYCLES=10000`。
- 10k: `host_ms=25131`
- 20k: `host_ms=99778`
- 30k: `host_ms=177367`
- 40k: `host_ms=256954`
- 50k: `host_ms=348202`
- `Host time spent=348214ms`
- 约 `143.59 cycles/s`
- 退出码 `0`，未出现 difftest mismatch。

对比：

- NO0137 50k: `346589ms`，约 `144.3 cycles/s`
- NO0147 `-Os` 50k: `349991ms`，约 `142.86 cycles/s`
- NO0148 50k: `348214ms`，约 `143.59 cycles/s`

判断：

- scalar logic const expr absorb 能消掉一类无意义逻辑常量 warning，并简化局部源码形态。
- 但 50k runtime 仍比 NO0137 慢约 `1625ms`，约 `0.47%` 负向；没有证明能带来 XiangShan CoreMark 速度收益。
- 继续方向仍应是结构性减少 generated code footprint / branch / iTLB 压力，而不是局部 scalar expression 清理。

