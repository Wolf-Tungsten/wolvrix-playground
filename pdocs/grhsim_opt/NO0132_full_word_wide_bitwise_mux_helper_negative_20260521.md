# NO0132: full-word wide bitwise/mux helper negative

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


背景：

- NO0128 perf 中宽位宽 bitwise helper 仍可见，但单个 helper 占比不高。
- 静态统计 NO0128 产物中宽 bitwise/mux 调用约 `28139` 个，其中 64-bit word 对齐宽度约 `21603` 个。
- 实验目标：对 1024/960/256/128 等 full-word 宽度生成 `_full` helper，避免每次调用后的 `grhsim_trunc_words` 尾部清理。

实现与验证：

- 新增 emitter option/env：
  - `emit_full_word_bitwise`
  - `GRHSIM_EMIT_FULL_WORD_BITWISE`
  - XS 脚本透传：`WOLVRIX_XS_GRHSIM_EMIT_FULL_WORD_BITWISE`
  - Python API：`emit_full_word_bitwise`
- 修改路径：
  - `wolvrix/lib/emit/grhsim_cpp.cpp`
  - `wolvrix/app/pybind/native/actions/emit.cpp`
  - `wolvrix/app/pybind/wolvrix/__init__.py`
  - `scripts/wolvrix_xs_grhsim.py`
  - `wolvrix/tests/emit/test_emit_grhsim_cpp.cpp`
- 验证：
  - `cmake --build wolvrix/build --target emit-grhsim-cpp -j$(nproc)` 通过。
  - `ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'` 通过，约 `55.83s`。
  - `python3 -m pip install --no-build-isolation -e wolvrix` 通过。

fresh XiangShan emit/build/runtime：

- fresh emit dir：
  - `tmp/no0132_xs_emit_full_word_bitwise/grhsim_emit`
- schedule 结构保持与 NO0128 对齐：
  - `compute_supernodes=74430`
  - `commit_supernodes=515`
  - `dag_edges=485905`
  - `boundary_values=1151073`
  - `boundary_activation_edges=2216514`
- emit timing：
  - `total=265225ms`
- 生成代码形态确认：
  - `_full` helper 调用约 `21603`
  - 剩余非对齐 bitwise/mux 调用约 `6536`
  - top `_full` helpers：
    - `grhsim_and_words_full<16>`: `5397`
    - `grhsim_or_words_full<16>`: `3611`
    - `grhsim_and_words_full<2>`: `2119`
    - `grhsim_not_words_full<16>`: `2016`
    - `grhsim_or_words_full<2>`: `2000`
    - `grhsim_mux_words_full<2>`: `1704`
- model build：
  - `real 276.35s`
  - 成功链接 `tmp/no0132_xs_emit_full_word_bitwise_emu/grhsim-compile/emu`
- CoreMark 50k:
  - 命令包含 `--diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`
  - 退出码：`0`
  - 未出现 difftest mismatch。
  - 进度：
    - 10k: `host_ms=35045`
    - 20k: `host_ms=128209`
    - 30k: `host_ms=228020`
    - 40k: `host_ms=341221`
    - 50k: `host_ms=472439`
  - `Guest cycle spent`: `50001`
  - `Host time spent`: `472455ms`
  - 约 `105.8 cycles/s`

判断：

- NO0132 虽然成功消除了约 `21.6k` 个 full-word 宽 bitwise/mux 的尾部 truncate，但 50k runtime 从 NO0128 当次复测 `348992ms` 退化到 `472455ms`，慢约 `35.4%`。
- `_full` helper 增加的代码形态/模板实例/优化压力显著大于少量尾部 mask 清理收益。
- 结论为明确负向；不默认启用，后续不要继续沿 full-word bitwise/mux helper specialization 投入。

