# NO0125: 2-word bitwise overload prototype negative smoke

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


实验目的：

- NO0124 中仍有大量 generic bitwise helper 调用：
  - `grhsim_and_words(`: `13167`
  - `grhsim_or_words(`: `9410`
  - `grhsim_not_words(`: `4813`
  - `grhsim_xor_words(`: `749`
- 其中 65-128 bit bitwise 调用约 `8869` 个。
- 与 NO0123 不同，本实验不打开 `GRHSIM_EMIT_FIXED_2WORD_BITWISE=1`，也不改变 schedule 或 emit 调用点；只在 NO0124 生成产物的 runtime header 中给现有 `grhsim_{and,or,xor,xnor,not}_words(..., width)` 增加 `std::array<std::uint64_t, 2>` overload，依赖 C++ overload resolution 自动选择。

NO0125 prototype：

- 基于 `tmp/no0124_xs_emit_shift2_overload/grhsim_emit` 临时修改 `grhsim_SimTop_runtime.hpp`。
- 第一次实现错误地假设存在动态宽度 `grhsim_trunc_words_2(value, width)`，PCH 编译失败；修正为 overload 内构造 `out` 后调用 `grhsim_trunc_words(out, width)`。
- model build：
  - `real 256.69s`
  - `user 5742.39s`
  - `sys 60.11s`
- difftest emu build：
  - `real 7.42s`
  - 成功链接 `tmp/no0125_no0124_runtime_bitwise2_overload_emu/grhsim-compile/emu`
- CoreMark 20k：
  - 命令包含 `--diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`
  - 退出码：`0`
  - 未出现 difftest mismatch。
  - `Guest cycle spent`: `20001`
  - `Host time spent`: `113455ms`

判断：

- NO0125 20k smoke 已经慢于 NO0124 20k 的 `110258ms`，且 10k progress 也偏慢：`31636ms` 对 NO0124 的 `23964ms`/`23588ms` 档。
- 不继续跑 50k。
- 可能原因是动态宽度 overload 仍需运行时 tail truncation，函数重载还可能改变 inlining/优化形态；它没有 NO0124 shift overload 的确定收益。
- 该 prototype 已恢复 NO0124 生成目录的 runtime header，不纳入源码。
- 当前已测最佳仍为 NO0124：CoreMark 50k 约 `143.1 cycles/s`。

