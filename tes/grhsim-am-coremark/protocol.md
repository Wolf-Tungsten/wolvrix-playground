# 评估协议（grhsim-am-coremark）

Φ 会把本文件原样内联进每个 proposal 的「评估协议」一节。改协议即改实验条件：
run 期间不修改，修改应在 insights.md 追加记录。

- 负载：`coremark-2-iteration.bin`，`-C 50000`（50k 周期窗），difftest 参考
  `riscv64-nemu-interpreter-so`。
- 计时：固定 5 rep。每 rep `taskset` 绑一个独立物理核（见 config
  `eval.rep_cores`，同 socket、非 SMT 兄弟），按 3+2 两批执行、批次间串行；评估间
  严格串行无干扰（全局 LOCK + 每批次起跑前 emu 进程守卫），不开任何 profile
  插桩。排序后若最大相邻比值 >=1.12 且两侧各 >=2 rep，按快/慢双簇分别取簇内
  中位，score 取快簇中位；否则取全 5 rep 中位。result 同时保留 raw median/CV、
  簇断点与两簇明细。该口径从 r003 起生效，避免 per-process 双态的跨簇 median
  生成不存在的中间态。
- 功能门：每 rep 退出码 0、nemu 在线逐指令核对无 mismatch，且 instrCnt/cycleCnt 落在
  金标窗内（中心 73,584/49,998，容差 ±16/±8——窗口覆盖 gsim 与 am 两种 emu 在 50k
  周期窗停止点上的确定性小差，见 config `eval.golden_tol`）。
- 回归门：`ctest -R grhsim` 全绿。
- 编译预算：cmake→emu 二进制就绪累计 ≤ 2400s，超预算判 `compile_timeout`。
- 流水线：wolvrix 全量构建（Release + ccache）→ ctest → `grhsim-am-lower-json
  <post_stats_json> SimTop --emit <dir> <emit_args>`（post_stats_json 为 wolvrix
  自解析 SV 的冻结归一化产物；emit_args 见 config）
  → difftest emu 构建 → 计时 reps。
- 可调旋钮（候选可覆盖）：`--emit-args` 透传给 lower-json，如 `--blocks-per-source`、
  `--max-atoms-per-block`、`--tree-atom-fold-max-instr`、`--dp-coarsen-*`、
  `--merge-when-min-group`、`--block-chunk-instructions` 等（取值语义见
  `wolvrix/docs/grhsim/grhsim-am-pipeline.md`）。
