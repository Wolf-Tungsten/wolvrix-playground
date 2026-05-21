# NO0149: ctz active dispatch fresh C1/C2/C4 dynamic

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


背景：

- NO0145 perf 显示当前主要瓶颈偏 frontend / iTLB / branch pressure。
- NO0148 生成代码中 active word dispatch 仍有大量静态 bit 分支，本轮新增可选 `emit_ctz_active_dispatch`，用 `__builtin_ctz` + `switch (activeBitIndex)` 遍历 active bit，验证减少静态 branch 数量能否转成 CoreMark 50k runtime 收益。

配置：

- fresh emit 目录：`tmp/no0149_xs_ctz_active_dispatch`
- C1/C2/C4 dynamic 主体，`small_sibling_merge=1`，`small_overlap_merge=0`，`down_merge=0`
- 额外开启：`WOLVRIX_XS_GRHSIM_EMIT_CTZ_ACTIVE_DISPATCH=1`

验证：

- `cmake --build wolvrix/build --target emit-grhsim-cpp -j32`：通过。
- `ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'`：通过。
- `python3 -m py_compile scripts/wolvrix_xs_grhsim.py wolvrix/app/pybind/wolvrix/__init__.py`：通过。
- `python3 -m pip install --no-build-isolation -e wolvrix`：通过。

fresh emit：

- 日志确认 `emit_ctz_active_dispatch=True`
- `activity-schedule done 186826ms`
- `write_grhsim_cpp done 41141ms`
- `total done 249724ms`
- `/usr/bin/time`: `real 251.30s`
- 结构：
  - `supernodes=74945`
  - `compute_supernodes=74430`
  - `commit_supernodes=515`
  - `dag_edges=485905`
  - `boundary_values=1151073`
  - `boundary_activation_edges=2216514`
  - `ops_max=8192`

静态代码变化：

- NO0148 `activeWordFlags & bit if`: `74945`
- NO0149 `activeWordFlags & bit if`: `526`
- NO0149 `__builtin_ctz`: `9325`
- NO0149 `switch(activeBitIndex)`: `9325`
- NO0148 sched lines: `20572895`
- NO0149 sched lines: `20675464`
- 目录大小：NO0148 `2.2G`，NO0149 `2.0G`

build / relink：

- model archive 强制重编：
  - `real 269.13s`
  - `user 6112.58s`
  - `sys 63.28s`
- difftest emu relink：
  - `real 1.24s`
- `libgrhsim_SimTop.a` text 汇总：
  - `115808691`

CoreMark 50k：

- 命令口径：difftest enabled，`-C 50000`，`EMU_PROGRESS_EVERY_CYCLES=10000`。
- 10k: `host_ms=26429`
- 20k: `host_ms=108782`
- 30k: `host_ms=195463`
- 40k: `host_ms=284632`
- 50k: `host_ms=384770`
- `Host time spent=384783ms`
- 约 `129.94 cycles/s`
- 退出码 `0`，未出现 difftest mismatch。

对比：

- NO0137 50k: `346589ms`，约 `144.3 cycles/s`
- NO0148 50k: `348214ms`，约 `143.59 cycles/s`
- NO0149 50k: `384783ms`，约 `129.94 cycles/s`

判断：

- ctz active dispatch 大幅减少了静态 active bit `if` 数量，但没有减少 generated schedule 行数，model build 反而比 NO0148 慢约 `5.2%`。
- 50k runtime 比 NO0148 慢约 `36569ms`，约 `10.50%` 负向；比 NO0137 慢约 `38194ms`，约 `11.02%` 负向。
- 这说明 active dispatch 的静态 branch 数量不是当前最直接的 runtime 收益点；`ctz + switch` 的动态开销和更复杂控制流抵消甚至放大了 frontend 问题。该选项不应默认开启。

