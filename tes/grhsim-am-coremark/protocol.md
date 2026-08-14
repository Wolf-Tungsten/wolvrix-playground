# 评估协议（grhsim-am-coremark）

Φ 会把本文件原样内联进每个 proposal 的「评估协议」一节。改协议即改实验条件：
run 期间不修改，修改应在 insights.md 追加记录。

- 负载：`coremark-2-iteration.bin`，`-C 50000`（50k 周期窗），difftest 参考
  `riscv64-nemu-interpreter-so`。
- 计时：3 rep 取中位（CV>5% 自动加测至 5 rep），`taskset` 绑核（core 见 config
  `eval.core`），串行无干扰（全局 LOCK + emu 进程守卫）；不开任何 profile 插桩。
- 功能门（金标）：每 rep 退出码 0 且 `instrCnt = 73,580`、`cycleCnt = 49,996`。
- 回归门：`ctest -R grhsim` 全绿。
- 编译预算：cmake→emu 二进制就绪累计 ≤ 2400s，超预算判 `compile_timeout`。
- 流水线：wolvrix 全量构建（Release + ccache）→ ctest → `grhsim-am-lower-json
  <exec_json> SimTop --schedule --emit <dir> --block-chunk-instructions 3000`
  → difftest emu 构建 → 计时 reps。
- 可调旋钮（候选可覆盖）：`--emit-args` 透传给 lower-json，如 `--blocks-per-source`、
  `--max-atoms-per-block`、`--tree-atom-fold-max-instr`、`--dp-coarsen-*`、
  `--merge-when-min-group`、`--block-chunk-instructions` 等（取值语义见
  `wolvrix/docs/grhsim/grhsim-am-pipeline.md`）。
