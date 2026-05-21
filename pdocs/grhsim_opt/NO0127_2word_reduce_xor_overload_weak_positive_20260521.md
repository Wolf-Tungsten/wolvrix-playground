# NO0127: 2-word reduce-xor overload prototype weak positive

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


实验目的：

- NO0124 生成产物中 `grhsim_reduce_xor_words(` 调用计数约 `1197`。
- 其中 65-128 bit 调用约 `1037`，当前 generic helper 需要按 live words 循环并执行 tail truncation。
- 本实验只在 NO0124 生成产物 runtime header 中加入 `std::array<std::uint64_t, 2>` 同名 overload，不改 schedule，不改 emit 调用点。

NO0127 prototype：

- 基于 `tmp/no0124_xs_emit_shift2_overload/grhsim_emit` 临时修改 `grhsim_SimTop_runtime.hpp`。
- model build：
  - `real 256.86s`
  - `user 5722.31s`
  - `sys 59.99s`
- difftest emu build：
  - `real 7.46s`
  - 成功链接 `tmp/no0127_no0124_runtime_reducexor2_overload_emu/grhsim-compile/emu`
- CoreMark 20k：
  - 命令包含 `--diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`
  - 退出码：`0`
  - 未出现 difftest mismatch。
  - `Guest cycle spent`: `20001`
  - `Host time spent`: `105508ms`
- CoreMark 50k：
  - 命令包含 `--diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`
  - 退出码：`0`
  - 未出现 difftest mismatch。
  - `Guest cycle spent`: `50001`
  - `Host time spent`: `347268ms`
  - 折算约 `144.0 cycles/s`

判断：

- NO0127 的 20k smoke 比 NO0124 的 `110258ms` 快约 `4.3%`，但 50k 只比 NO0124 的 `349396ms` 快 `2128ms`，约 `0.61%`。
- 该优化是真实 50k 正向，但收益很弱，且目前只是 runtime-header prototype，尚未纳入源码。
- 实验后已恢复 NO0124 生成目录的 runtime header。
- 当前已测最佳更新为 NO0127 prototype：CoreMark 50k 约 `144.0 cycles/s`；已落地源码的最佳仍为 NO0124：CoreMark 50k 约 `143.1 cycles/s`。

