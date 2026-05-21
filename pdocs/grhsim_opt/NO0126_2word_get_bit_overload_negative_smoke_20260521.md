# NO0126: 2-word get-bit overload prototype negative smoke

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


实验目的：

- NO0124 中最高频 helper 是 `grhsim_get_bit_words(`，计数 `39142`。
- generic helper 每次执行 `index / 64`、边界检查和 `index & 63`。
- 本实验只在 NO0124 生成产物 runtime header 中加入 `std::array<std::uint64_t, 2>` 同名 overload：
  - `index >= 128` 时返回 false。
  - `index < 64` 直接读 `value[0]`，否则读 `value[1]`。
- 不改 schedule，不改 emit 调用点，不做 static bit inline。

NO0126 prototype：

- 基于 `tmp/no0124_xs_emit_shift2_overload/grhsim_emit` 临时修改 `grhsim_SimTop_runtime.hpp`。
- model build：
  - `real 255.73s`
  - `user 5716.31s`
  - `sys 59.61s`
- difftest emu build：
  - `real 7.40s`
  - 成功链接 `tmp/no0126_no0124_runtime_getbit2_overload_emu/grhsim-compile/emu`
- CoreMark 20k：
  - 命令包含 `--diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`
  - 退出码：`0`
  - 未出现 difftest mismatch。
  - `Guest cycle spent`: `20001`
  - `Host time spent`: `111442ms`

判断：

- NO0126 20k smoke 略慢于 NO0124 的 `110258ms`，10k progress 也偏慢：`31457ms`。
- 不继续跑 50k。
- 这与 NO0120 的 static bit inline 负收益方向一致：`get_bit` 表面计数高，但更改代码形态没有转化为 runtime 收益，可能是 inlining/branch prediction/register pressure 的综合影响。
- 该 prototype 已恢复 NO0124 生成目录的 runtime header，不纳入源码。
- 当前已测最佳仍为 NO0124：CoreMark 50k 约 `143.1 cycles/s`。

