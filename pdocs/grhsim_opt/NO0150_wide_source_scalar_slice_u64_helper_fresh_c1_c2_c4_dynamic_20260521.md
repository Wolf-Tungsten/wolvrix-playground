# NO0150: wide source scalar slice u64 helper fresh C1/C2/C4 dynamic

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


背景：

- NO0148 仍有大量 `grhsim_slice_words<1>(...)[0]` 模式。该形态会为 wide source、scalar result 的 slice 构造 `std::array<uint64_t, 1>` 临时对象，再取 `[0]`。
- 本轮新增 `grhsim_slice_u64_words`，对 `resultWidth <= 64` 的 wide-to-scalar slice 直接返回 `uint64_t`，减少临时对象和代码体积，验证该静态形态清理能否转成 CoreMark 50k runtime 收益。

配置：

- fresh emit / build 目录：`tmp/no0150_xs_slice_u64_words_same_stats`
- C1/C2/C4 dynamic 主体，`small_sibling_merge=1`，`small_overlap_merge=0`，`down_merge=0`
- 与 NO0148 同源结构，避免混入 checkpoint / graph 变化。

实现：

- 新增 `template <std::size_t SrcN> inline std::uint64_t grhsim_slice_u64_words(...)`。
- emit 侧新增 `sliceScalarFromWordsExpr` 和 `eventLogicExprFromScalarU64Expr`。
- `kSliceStatic` / `kSliceDynamic` / `kSliceArray` 对非 wide result 且 `resultWidth <= 64` 使用 `grhsim_slice_u64_words`。

验证：

- `cmake --build wolvrix/build --target emit-grhsim-cpp -j32`：通过。
- `ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'`：通过。
- `python3 -m py_compile scripts/wolvrix_xs_grhsim.py wolvrix/app/pybind/wolvrix/__init__.py`：通过。
- `python3 -m pip install --no-build-isolation -e wolvrix`：通过。

fresh emit：

- `activity-schedule done 187687ms`
- `write_grhsim_cpp done 41246ms`
- `total done 254297ms`
- `/usr/bin/time`: `real 255.91s`
- 结构：
  - `supernodes=74945`
  - `compute_supernodes=74430`
  - `commit_supernodes=515`
  - `dag_edges=485905`
  - `boundary_values=1151073`
  - `boundary_activation_edges=2216514`
  - `clusters_after_essent_coarsen=3084571`

静态代码变化：

- NO0148 `grhsim_slice_words<1>`: `68218`
- NO0150 `grhsim_slice_words<1>`: `0`
- NO0150 `grhsim_slice_u64_words`: `71059`
- NO0148 sched lines: `20572895`
- NO0150 sched lines: `20584797`
- 目录大小：NO0148 `2.2G`，NO0150 `2.0G`

build / relink：

- model archive 强制重编：
  - `real 258.32s`
  - `user 5723.47s`
  - `sys 61.58s`
- difftest emu relink：
  - `real 1.23s`
- `libgrhsim_SimTop.a` text 汇总：
  - NO0148: `115953957`
  - NO0150: `107232999`

CoreMark 50k：

- 命令口径：difftest enabled，`-C 50000`，`EMU_PROGRESS_EVERY_CYCLES=10000`。
- 10k: `host_ms=26179`
- 20k: `host_ms=101306`
- 30k: `host_ms=179102`
- 40k: `host_ms=259162`
- 50k: `host_ms=351240`
- `Host time spent=351253ms`
- 约 `142.35 cycles/s`
- 退出码 `0`，未出现 difftest mismatch。

对比：

- NO0137 50k: `346589ms`，约 `144.3 cycles/s`
- NO0148 50k: `348214ms`，约 `143.59 cycles/s`
- NO0150 50k: `351253ms`，约 `142.35 cycles/s`

判断：

- `grhsim_slice_u64_words` 清掉了所有 `grhsim_slice_words<1>` 临时数组形态，并让 `.text` 比 NO0148 下降约 `8.72MB`，model build 时间基本持平。
- 但 50k runtime 比 NO0148 慢约 `3039ms`，约 `0.87%` 负向；比 NO0137 慢约 `4664ms`，约 `1.35%` 负向。
- 该优化改善代码体积和局部表达式形态，但当前 CoreMark 热路径没有吃到收益；不能作为默认性能优化结论，需要配合 perf 进一步确认是否只是非热点代码缩小。

