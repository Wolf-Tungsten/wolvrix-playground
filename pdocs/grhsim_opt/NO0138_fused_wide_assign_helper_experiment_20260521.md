# NO0138: fused wide assign helper experiment

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


背景：

- 生成代码里仍有大量宽逻辑形态：
  - `const auto next_words = grhsim_{and,or,xor,xnor,not,mux}_words(...);`
  - `grhsim_assign_words(dst, next_words, width)`
- 实验目标：对 materialized wide result 且需要 tracked-change 的 `Not/And/Or/Xor/Xnor/Mux`，一趟完成计算、截断、changed 检测和写回，减少 `std::array` 临时对象和二次遍历。

实现：

- 新增默认关闭 emit 开关：
  - `GRHSIM_EMIT_FUSED_WIDE_ASSIGN`
  - XiangShan 脚本透传：`WOLVRIX_XS_GRHSIM_EMIT_FUSED_WIDE_ASSIGN`
- 修改路径：
  - `wolvrix/lib/emit/grhsim_cpp.cpp`
  - `scripts/wolvrix_xs_grhsim.py`
  - `wolvrix/tests/emit/test_emit_grhsim_cpp.cpp`
- 保留默认主路径不变；测试设计显式打开 `emit_fused_wide_assign=1` 覆盖 fused helper 形态。

验证：

- `cmake --build wolvrix/build --target emit-grhsim-cpp -j32`：通过。
- `ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'`：通过，`56.70s`。
- `python3 -m py_compile scripts/wolvrix_xs_grhsim.py`：通过。

NO0138 XiangShan emit/build/runtime：

- 注意：本轮从 `tmp/grhsim_default_xiangshan_coremark_20260418/wolvrix_xs_post_stats.json` resume，schedule 结构与 NO0137 fresh 不完全同源，因此 runtime 不能直接纯归因给 fused helper。
- emit dir：
  - `tmp/no0138_xs_fused_wide_assign/grhsim_emit`
- schedule 结构：
  - `compute_supernodes=82351`
  - `commit_supernodes=533`
  - `dag_edges=550598`
  - `boundary_values=1244536`
  - `boundary_activation_edges=2451687`
- 静态代码形态：
  - fused wide assign helper 命中：`1281`
  - 旧 `const auto next_words = grhsim_{and,or,xor,xnor,not,mux}_words...`：NO0138 为 `0`
  - 对照 NO0137 同类旧形态：`1303`
- emit timing：
  - `activity-schedule=215870ms`
  - `write_grhsim_cpp=42244ms`
  - `total=287250ms`
- model build：
  - `real 255.87s`
  - `user 6149.08s`
  - `sys 68.50s`
- emu build：
  - `real 7.98s`
- CoreMark 20k：
  - 10k: `host_ms=30764`
  - 20k: `host_ms=111229`
  - `Host time spent=111236ms`
  - 约 `179.8 cycles/s`

判断：

- fused wide assign 在静态形态上有效，确实消除了目标 `next_words + assign_words` 模式。
- 20k 已慢于 NO0137 的 `97854ms`，且 schedule 结构也更大；按门禁不继续跑 50k。
- 该方向不能直接并入默认路径，当前保留为默认关闭实验开关。
- 若要继续评估，需要构造与 NO0128/NO0137 完全同源的 fresh schedule A/B，单独打开 `WOLVRIX_XS_GRHSIM_EMIT_FUSED_WIDE_ASSIGN=1`，否则 schedule 结构差异会掩盖代码形态收益。

