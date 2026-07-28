# SimpleTES GPT-5.6 Sol THJ switch and resume preflight

## 1. 阶段结论

本阶段按人工指示停止 K3 continuation，并准备从其最新完整 checkpoint 切换到新的
`gpt-5.6-sol/ultra` provider。结论如下：

- K3 main 于 `2026-07-28 22:53:20 +0800` 收到 `SIGINT`，但停在
  `Stopping 5 workers...` 约 4 分钟；确认已无 Codex/SimTop 子进程后强制结束，最终
  `launcher.exit=247`，supervisor、launcher 和 main 均已退出；
- 强制结束前没有新的 completed evaluation。唯一最新完整恢复点仍是
  `instance-7291c6c2/db_state_153501`；
- 新 `config.thj.toml`/`auth.thj.json` 均为 mode `0600` regular file。只核对非敏感结构：
  配置声明 `gpt-5.6-sol`、`ultra` 和 `OpenAI` provider，认证文件包含非空
  `OPENAI_API_KEY`；正文、日志和 checkpoint 均不记录 key；
- GrhSIM launcher 新增显式 `--model` 与 `--reasoning-effort`，但数据集默认仍保持
  `k3/ultra`，没有改变此前的 K3 默认决策；
- GPT 分支恢复历史稳定的 `provider-structured + auto`；K3 继续独占
  `local-json + required-first`、K3 instruction suffix、1M catalog 和 agent cap；
- 新配置上的真实 deterministic capability preflight 已通过：`1` 次 repository tool
  call、`632` chars，response SHA-256 为
  `4479d74f6230e3c9de2a054383161e0c2f42975792d28f34fbc94040c073c608`；
- 上述 launcher 与回归修改已实际提交为 SimpleTES
  `da860d19ef49c54033de51bb5c0df250b29c3fec`；
- 本阶段没有新候选 build 或 SimTop 50k 样本，不产生新的性能保留或默认开关结论。

## 2. 恢复状态与现有绝对性能

恢复点绝对路径为：

```text
/nfs/home/tanghaojin/wolvrix-SimpleTES-workspace-5/SimpleTES/checkpoints/
grhsim_simtop_50k/k3_rwa_grounded_fresh_20260728_032742/2026-07-28/
instance-7291c6c2/db_state_153501
```

其持久化状态为：

| 项目 | 绝对值 |
| --- | ---: |
| generation attempts | `18` |
| completed evaluations | `6` |
| valid candidates | `3 / 32` |
| generation failures | `2` |
| generation cancellations | `2` |
| evaluation failures | `0` |
| best score | `1.0175669535154988` |

当前 best 的正式 SimTop 50k pooled walltime 为 control `54,304.75 ms`、candidate
`53,367.25 ms`，绝对减少 `937.50 ms`，相对提升 `1.726368%`。这是恢复点中的既有
K3 探索结果，不是本次 GPT 切换产生的新数据；功能、fixed-ASLR、quiet-CCD、NUMA、
PMU 与双 order 口径不变。

恢复必须传入 exact `db_state_153501`，不能改用旧 GPT checkpoint：历史 GPT states
属于 pre-RWA 或旧 schema/pin，launcher 会 fail-close。虽然父目录名含 `k3`，恢复后的
新 checkpoint 将记录 GPT model/config provenance；SimpleTES 的 resume 语义会继续写入
原 `instance-7291c6c2`，新的 output root 只承载 launcher/supervisor 日志。

## 3. 模型分支修正

当前 launcher 在本阶段前把以下参数无条件固定为 K3 路径：

```text
--codex-output-mode local-json
--codex-tool-choice-mode required-first
```

新 GPT provider 使用的 endpoint 不满足 required-first compatibility proxy 的 HTTPS
upstream 契约；如果只替换 config/auth，client 会在研究启动前 fail-close。历史 GPT
轮次使用 Codex 原生 provider structured output 与 `auto` tool choice，
[TNO0192](./TNO0192_simpletes_k3_grounded_generation_fix_and_capability_gate_20260728.md)
统计其 `36` 个持久化 output 中 `32` 个通过 evaluator schema/semantic gate。

因此 launcher 现在按显式 model 选择：

| 项目 | K3 默认 | GPT 本轮 |
| --- | --- | --- |
| output mode | `local-json` | `provider-structured` |
| tool choice | `required-first` | `auto` |
| instruction suffix | K3-only | 不传 |
| model catalog | K3 1M catalog | 不传，使用原生 metadata |
| agent cap/feature flags | K3-only，最多 3 | 不传，保留 Ultra 原生 delegation |

`--model` 与 `--reasoning-effort` 的 CLI 默认仍分别为 `k3`、`ultra`。本轮只有显式
参数选择 `gpt-5.6-sol`，不会静默改变后续未带参数的 K3 launcher 行为。

## 4. 并发、timeout 与启动契约

本轮沿用 `4` 条 RPUCG chain 对应的 `4` 个 generation workers、`1` 个串行 evaluator。
外层 Codex request 各自使用 private `CODEX_HOME`，目标仓库以 `--sandbox read-only`
打开，不存在多个 worker 共同写入一个 patch 文件的路径；候选只通过独立 final response
进入 SimpleTES。GPT 不接收 K3 的显式 subagent 配置，由 Ultra 自行决定 delegation。

generation timeout 回到 GPT 历史长轮使用的 `5,400 s`；`10,800 s` 是因 K3 较慢而
单独翻倍的口径。evaluator timeout 仍为 `21,600 s`，预算仍为 `64 proposals / 32 valid`，
runtime infra retries 为 `8`，build jobs 为 `4`。

提交完成后使用以下固定参数启动独立 supervisor：

```text
model:                  gpt-5.6-sol
reasoning effort:       ultra
config:                 ~/.codex/config.thj.toml
auth:                   ~/.codex/auth.thj.json
resume:                 exact db_state_153501
generation/evaluation:  4 / 1
generation timeout:     5400 s
evaluation timeout:     21600 s
proposal/valid budget:  64 / 32
output root:             gpt56sol_thj_resume_20260728_231748
```

正式 launcher 仍会在 spawn main 前重新执行 capability gate，并用 launch-input digest
做 TOCTOU 复核。只有该 gate 通过才创建研究进程。

## 5. 回归与边界

本阶段完成：

```text
launcher-focused pytest: 18 passed, 62 deselected
launcher dry-run:         PASS
real GPT capability:      PASS (repo_tool_calls=1, response_chars=632)
```

dry-run 确认正式 argv 包含 `gpt-5.6-sol/ultra`、`provider-structured/auto`、exact resume、
`gen=4/eval=1`，并且不含 K3 instruction suffix、K3 catalog 或
`--codex-max-agent-threads`。本记录只闭合模型切换、恢复输入和启动前 gate；新的候选性能
必须继续由端到端 SimTop 50k walltime 决定，只有正向端到端修改才能保留或默认开启。
