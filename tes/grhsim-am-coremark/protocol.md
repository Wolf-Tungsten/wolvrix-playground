# 评估协议（grhsim-am-coremark）

Φ 会把本文件原样内联进每个 proposal 的「评估协议」一节。改协议即改实验条件：
run 期间不修改，修改应在 insights.md 追加记录。

- 负载：`coremark-2-iteration.bin`，`-C 50000`（50k 周期窗），difftest 参考
  `riscv64-nemu-interpreter-so`。
- 计时：**簇结构自适应协议（r004 起）**。先 3 rep（每 rep `taskset` 绑一个独立物理核、
  单批并行，见 config `eval.rep_cores`）；检出双峰（排序相邻倍率 > `cluster_ratio`=1.15）
  自动加跑至 ≤ `reps_max`=9；**score = 快簇中位**，弃用跨簇 median。每 rep 1Hz 只读
  采样 smaps_rollup/numa_maps 协变量。评估之间严格串行无干扰（全局 LOCK + 批次起跑前
  emu 进程守卫），正式计时不开 emu 内插桩。CV>5% 或 degraded（全 singleton）标
  `noisy`。整批慢态嫌疑时用 `evaluator.py retime --eval-id` 只补计时（不重建、不占预算）。
- 功能门：每 rep 退出码 0、nemu 在线逐指令核对无 mismatch，且 instrCnt/cycleCnt 落在
  金标窗内（中心 73,584/49,998，容差 ±16/±8——窗口覆盖 gsim 与 am 两种 emu 在 50k
  周期窗停止点上的确定性小差，见 config `eval.golden_tol`）。
- 回归门：`ctest -R grhsim` 全绿。
- 编译预算：cmake→emu 二进制就绪累计 ≤ 2400s，超预算判 `compile_timeout`。
- 流水线：wolvrix 全量构建（Release + ccache）→ ctest → `grhsim-am-lower-json
  <post_stats_json> SimTop --emit <dir> <emit_args>`（post_stats_json 为 wolvrix
  自解析 SV 的冻结归一化产物；emit_args 见 config）
  → difftest emu 构建 → 计时 reps。
- 表型声明（硬前置）：每个候选 commit 必须随附 worktree 根 `tes-candidate.json`
  （`{"hypothesis", "emit_args_add", "emit_args_remove"}`，无表型变更也要提交）；
  `record-eval` 对声明与实际 emit_args 做硬审计，不符拒登记。
- 可调旋钮（候选可覆盖）：`--emit-args` 透传给 lower-json，如 `--blocks-per-source`、
  `--max-atoms-per-block`、`--tree-atom-fold-max-instr`、`--dp-coarsen-*`、
  `--merge-when-min-group`、`--block-chunk-instructions` 等（取值语义见
  `wolvrix/docs/grhsim/grhsim-am-pipeline.md`）。
