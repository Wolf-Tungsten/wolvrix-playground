# TNO0166 SimpleTES long best-seed continuation launch

记录日期：2026-07-21

状态：已从上一轮最终 `best_program.txt` 启动新的 fresh SimpleTES instance `25411edd`。
本轮将 generated proposal 上限从 `16` 扩到 `32`，generated valid target 从 `8` 扩到
`16`，截至 `2026-07-21 17:22 +08:00` 正在执行初始 seed 的独立归因构建，尚无本轮
accepted SimTop 50k walltime、generation 或 valid candidate，不形成新的性能或默认结论。

上一轮完整结果与 seed 选择见
[TNO0165](./TNO0165_simpletes_best_seed_continuation_final_results_and_default_decision_20260721.md)。

## 1. Run identity

```text
instance                    25411edd
start                       2026-07-21 16:59:59 +08:00
output root                 SimpleTES/checkpoints/grhsim_simtop_50k/formal_20260721_03
run log                     .../2026-07-21/instance-25411edd/run.log
slot root                   /tmp/simpletes-grhsim-simtop-50k
SimpleTES commit            1daaf8aaf8b110ab2ac3d92eb7cadaff28fa4304
pinned evaluator parent     b90d20461d276def682f19a28be1fe65a4387eef
pinned wolvrix              f17e90e14c3ad70a3ee93f7c6540e13dae54940a
pre-launch docs parent      55cf97f24a1419e47786b02f84afe507cceb5e47
model / reasoning           gpt-5.6-sol / ultra
generator backend           codex_exec
```

API endpoint/config 读取 `~/.codex/config.mjy.toml`，认证读取
`~/.codex/auth.mjy.json`；记录中不复制 endpoint 细节或 secret。launcher 初始化输出确认
实际模型为 `gpt-5.6-sol`、backend 为 `codex_exec`，不是只做 dry-run。

## 2. Durable seed and provenance

```text
seed path
SimpleTES/checkpoints/grhsim_simtop_50k/formal_20260720_02/2026-07-20/
instance-4269c986/db_state_133044/best_program.txt

bytes                       14,571
file SHA256                 1711b4c8b0097164add65fca011b1b65567c02b07d78b3567fe35538ada509ab
candidate digest            4ce54fe69ba60931c52a19225d9235548960ec88e40f36792c8c08b3780a4bf1
changed file                lib/emit/grhsim_cpp.cpp
enable option               active_mask_gap_pack_policy=targeted-direct
```

该 seed 在上一轮的 pooled 绝对 walltime 为 control `73,828.00 ms`、candidate
`73,458.50 ms`，改善 `369.50 ms / 0.500487620%`。这些数值只解释为何选择该 seed；fresh
instance 必须先独立复评，不能继承旧 score，也不能据此应用 patch 或修改默认。

## 3. Longer bounded-search budget

本轮使用：

| setting | absolute value |
| --- | ---: |
| maximum generated proposals | `32` |
| generated valid target | `16` |
| RPUCG chains | `4` |
| prompts per chain | `8` |
| generation workers | `1` |
| evaluation workers | `1` |
| LLM hard timeout | `5,400 s` |
| evaluator hard timeout | `21,600 s` |
| maximum tokens | `32,768` |
| runtime infrastructure retries | `4` after the first attempt |

SimpleTES commit `1daaf8a` 将 bench 参数 validation 的 proposal 上限扩到 `64`，默认值仍是
`16/8`；本次显式选择 `32/16`，因此不会再次在仅 8 个 generated valid candidates 时停止。
`GRHSIM_INFRA_RETRIES=4` 只允许同一已构建 evaluator 在 quiet-CCD 等 retryable
infrastructure outcome 后最多再试 4 次，不放宽任何性能 gate，也不重复计算 failed sample。

上一轮四次 Codex generation 都在 `3,000 s` hard timeout 结束。本轮把 LLM timeout 提高到
`5,400 s`，给复杂 proposal 更多完成时间；`codex_exec` 没有 whole-generation retry，因此
仍由 `32` 个 proposal 总预算吸收 generation failure。

## 4. Frozen evaluation contract

启动命令先 source 仓库 `env.sh`。除搜索预算和 timeout/retry allowance 外，evaluator 契约
保持不变：

- baseline 是 pinned parent/wolvrix 的当前默认生成配置；每个 candidate 使用隔离 clone；
- control snapshot 向 candidate 私有复制 `2,103` 个 generation inputs；本轮 candidate
  工作树重新计算 fingerprint 为
  `e9ca0efd737dcc0b7a7e145059fce052fd5729abe34df43d8e4b10e1a84154ab`；
- disabled candidate 必须与 control byte-identical，enabled candidate 必须区别于 control，
  unpatched same-options build 用于排除 option 自身或环境漂移；
- focused、100/10k、50k function/signature/terminal-PC gate 均保持；
- runtime 只在某个完整 CCD 通过 quiet-window admission 后选择其中一个 CPU，禁止与外载共享
  CCD；执行时关闭 ASLR，要求 personality `00040000`；
- binary/NEMU 必须 NUMA-local，单 CPU affinity、zero migration、PMU scheduled `100%`、
  continuous monitor 均为 accepted sample 的硬条件；
- 每个候选执行 SimTop 50k ABBA 后再执行另一 NUMA node 的 BAAB，headline 指标只使用
  `Host time spent` walltime，绝对值和相对变化必须同时保存；
- 只有 fresh end-to-end walltime 正向且超过 `max(1%, control spread)` 的修改才能应用或默认
  开启；CPP/ELF/perf 只作为原因分析证据。

## 5. Launch-time progress snapshot

截至 `2026-07-21 17:22:43 +08:00`：

```text
new accepted 50k samples        0
new generation attempts         0 / 32
new generated valid candidates  0 / 16
initial seed score               pending
active phase                     initial seed, unpatched same-options attribution build
candidate slot key               240719f63589edae/slot-0
build-log size                   1,455,731 bytes
build-log mtime                  2026-07-21 17:22:27 +08:00
latest visible progress          reg-to-mem group 4316 / 4318
```

构建日志仍在刷新，并且已经越过 fresh input staging 进入 emitter pipeline；没有重新执行
`Generating XiangShan`、`sim-verilog` 或 `xs_simverilog`，符合复用固定 control generation
inputs 的预期。由于初始 evaluator 尚未产生 walltime，本记录不复用上一轮的数值作为本轮
baseline，也不宣称新优化已被接受。

## 6. Current decision

```text
long SimpleTES instance active  yes
apply seed patch to user tree   no
change C++ default              no
new wolvrix source commit       none
new performance conclusion      none yet
```

后续由 instance `25411edd` 自主完成初始 seed 复评并进入最多 `32` 次 proposal、`16` 个
generated valid candidate 的搜索。阶段性结果继续按 `RULES.md` 新增 TNO 文档；达到停止条件后
再汇总所有 absolute walltime、相对变化、失败预算和默认采用决定。
