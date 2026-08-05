# TNO0220：SimpleTES 64-valid continuation 从 node029 迁移到 node032

日期：2026-08-06

## 1. 最终结论

[TNO0219](./TNO0219_simpletes_typed_storage_budget128_valid64_resume_launch_20260804.md) 启动的
`128 generations / 64 cumulative valid` continuation 在 `node029` 长时间停留于 evaluator infrastructure
retry，无法通过严格的 whole-CCD admission 推进。按用户指示，本阶段已：

1. 向 node029 SimpleTES main 发送 SIGINT，等待 worker 清理和 final checkpoint 完整发布；
2. 确认 node029 launcher、main、Codex 与 evaluator 后代全部退出；
3. 在 `node032` 验证同一 NFS workspace、commit、THJ config/auth、CPU topology、空闲负载和无冲突进程；
4. 从 node029 final exact state `db_state_020746` 恢复，保持绝对预算 `128/64`，不重复扩容；
5. 显式固定与 node029 相同的 `codex-cli 0.146.0` 后正式启动 GPT-5.6 Sol max、`4 gen/1 eval`。

截至 `2026-08-06 02:15:54 +0800`，node032 launcher/main 存活，四个独立 Codex generation subprocess
均使用正确的 NVM binary，实时日志已报告 `gen workers: 4 active / 0 queued`。本阶段尚无 node032 新 candidate、
evaluation 或 SimTop 50k 数据；当前 best 仍是 TNO0218 的 typed-storage candidate。

## 2. node029 阻塞与停止

停止前 run log 长时间为：

```text
gen workers: 0 active / 0 queued, eval workers: 1 active / 3 queued
```

`2026-08-06 01:47:30 +0800` evaluator 再次报告：

```text
Retryable evaluation infrastructure outcome; retrying the same candidate in 30s
```

最近一次正常 evaluation checkpoint 仍是两天前的 `db_state_030631`，其中只有 `45 attempts / 34 valid /
40 completed evaluations`，best 未变。全机 load average 在迁移检查时已经回落到 `1.83/3.22/4.80`，但严格
whole-CCD gate 仍没有让 active candidate 完成；全机平均负载低并不保证任一完整 CCD 满足 evaluator 的逐 sibling
quiet 条件。

停止操作严格定位原进程：

| 对象 | PID / SID / PGID |
| --- | --- |
| node029 launcher | `2102396 / 2102396 / 2102396` |
| node029 main | `2105608 / 2102396 / 2102396` |

`02:07:24 +0800` 只向 main PID `2105608` 发送 SIGINT；scheduler 收到信号后取消 evaluator/queue，
`02:07:46` 写出 final `db_state_020746` 并正常打印 Final Results。随后 launcher 退出，node029 实查没有残留
SimpleTES main、launcher 或 evaluator 进程。

停止时内存中有 1 个 active evaluator 和 3 个 queued candidates；checkpoint 格式不持久化 pending evaluation
queue，它们被取消且没有计入 completed/valid，也没有被伪装成性能结果。停止清理阶段另一个已经调度的
generation counter 被计入 final metadata，因此 exact final 的 attempts 是 `46`，不是停止前旧 checkpoint 的
`45`；valid 和 completed evaluations 均未变化。

## 3. node029 final exact checkpoint

正式迁移源：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/
principled_trbs_gpt56sol_max_fresh2_20260803_030316/
2026-08-03/instance-44cd457d/db_state_020746
```

| 项目 | 绝对值 |
| --- | ---: |
| generation attempts | `46 / 128` |
| generation failures / cancellations | `0 / 0` |
| completed evaluations / DB nodes | `40 / 40` |
| valid evaluations | `34 / 64` |
| evaluator failures | `0` |
| best score | `1.06814371190328` |
| best node | `a55f5c96f68e4dc3815befc2f9f89341` |

budget-extension audit 仍只有 TNO0219 的一条 `64→128 generations / 32→64 valid` 记录；四条 chain 的
prompt counts 为 `11 / 9 / 9 / 11`，每条 absolute budget 仍是 `32`，ready chains 为 `1/2/0/3`。

证据哈希：

| 对象 | SHA-256 |
| --- | --- |
| `metadata.json` | `35e34e71d1a568232af749cf1d22379e6dd6db1305854d1740df26e09793bc46` |
| `config.json` | `cda3473e6aca1e849b8d8659b9e4c5d2ce3fab8babb489c2d1602e620a851bcd` |
| `policy.json` | `59085f11b8ec4749d29ed2865fab566171061acbf9e778014c07bf7a3c792276` |
| `nodes.json` | `da253bdef68a3b0ffb13b8c6b684970f91a9c344212be4d52a5f7ef35213bb95` |
| `best_program.txt` | `5723e113bb1f9e0c6110153bca609d17d1310b34369a439162b75c4e2f2a3117` |

## 4. node032 接管条件

迁移前通过 non-interactive SSH 在 node032 完成只读核验：

| 项目 | node032 结果 |
| --- | --- |
| hostname | `node032.bosccluster.com` |
| CPU | 双路 AMD EPYC 9684X，`96 cores/socket`、SMT2、`384` logical CPUs、2 NUMA nodes |
| 初始 load average | `0.25 / 0.75 / 1.22` |
| memory | `1.0 TiB total / 958 GiB available` |
| `/tmp` | `878 GiB total / 733 GiB available` |
| conflicting user SimpleTES process | `0` |
| SimpleTES commit | `6a169d4958066c4932240aba5cbe5729d794ad74` |
| parent HEAD | `0ff550a0ce2160ab8afefcba6b196bbff973d54f` |
| Wolvrix pin | `d3ed9dea975bddf01185dde5c548a69241a09de9` |

workspace、checkpoint、`~/.codex/config.thj.toml` 与 `~/.codex/auth.thj.json` 都位于两机可见的同一 NFS
device，文件非空且权限为 `0600`（代码文件除外）。API key 内容没有输出或写入文档。node032 与 node029 CPU
型号和拓扑一致；正式 evaluator 仍会对每次 ABBA/BAAB 单独执行 whole-CCD quiet、CPU/NUMA/PMU、关闭 ASLR、
personality、migration 和功能 gate，不能仅用启动时 load average 替代 admission。

## 5. Codex CLI 版本纠偏

node032 默认 `PATH` 首次解析到 `/usr/local/bin/codex`，版本为 `0.145.0`；node029 正式运行使用的是
`/nfs/home/tanghaojin/.nvm/versions/node/v24.18.1/bin/codex`，版本 `0.146.0`。模型、THJ API 与 schema 虽未
改变，但为避免把客户端版本变化混入 exact continuation，第一次 node032 main 在任何 generation 完成、
candidate 入队或 evaluator 启动前被优雅停止。

第一次远端启动的审计状态：

- launcher/main：`1584139 / 1586374`；
- source 仍为 `db_state_020746`；
- 停止时四个 generation 均明确记录 `Generation cancelled`；
- `0` 个新 evaluation、`0` 个新 valid、best 不变；
- 产生的 `db_state_021244` 记录 `4` cancellations，只作为 rejected launch audit，不作为后续 resume source。

最终启动在 source `env.sh` 后显式把共享 NVM `0.146.0` 目录放到 `PATH` 首位。正式 preflight 与四个 research
Codex subprocess 的 executable path 均实查为该 NVM binary。preflight 期间 LiteLLM 获取公开 model-cost map
超时后使用本地 backup；capability probe 随后通过并创建 main，因此该 warning 没有改变模型、API、上下文或
checkpoint contract。

## 6. node032 最终正式运行

最终 launcher command 使用 exact restart，而不是再次扩容：

- `--resume .../db_state_020746`；
- `--max-proposals 128 --valid-target 64`；
- 不含 `--extend-resume-budget`；
- `gpt-5.6-sol / max`，THJ config/auth；
- `4 gen / 1 eval`，generation/evaluation timeout `10,800 / 21,600 s`；
- ordinary retries `2`，capacity/transient exact-thread continuations `3 / 3`。

运行身份：

| 对象 | PID / SID / PGID |
| --- | --- |
| node032 launcher | `1598098 / 1598098 / 1598098`，PPID `1` |
| node032 main | `1602277 / 1598098 / 1598098` |
| four Codex roots | `1602524 / 1602530 / 1602532 / 1602543`，各自独立 SID/PGID |

main 于 `02:14:59 +0800` exact load `46 attempts / 34 valid / 40 nodes`，保留四条 chain 和 best，报告
`88 prompts` policy headroom；`02:15:29` 已报告 `4 active / 0 queued`。四个 direct children 的 command line
均为 NVM `codex 0.146.0`、`-m gpt-5.6-sol`、`model_reasoning_effort=max`。

实时 main 日志继续追加在：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/
principled_trbs_gpt56sol_max_fresh2_20260803_030316/
2026-08-03/instance-44cd457d/run.log
```

最终 node032 launcher 日志：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/
principled_trbs_gpt56sol_max_fresh2_20260803_030316/
launcher_resume_node032_codex0146_gen128_valid64_20260806.log
```

checkpoint metadata 的 `instance_id` 显示 `3434e52a`，而持久化目录仍是 `instance-44cd457d`。这是 TNO0219
第一次 resume 时 CheckpointManager 把启动临时 ID 写入后续 metadata 的既有标签漂移；本次 exact load 的
nodes/config/policy/best 哈希与 source state 一致，不代表创建了 fresh tree。后续识别运行应优先使用持久化目录、
exact source checkpoint 和证据哈希。

本阶段只完成安全迁移与运行验证，不产生新的性能结论，也不改 Wolvrix 默认代码。node032 后续 candidate 仍须
以本机成对 control/candidate walltime 和所有正式 gate 判断，不能把两台机器的绝对 walltime 样本直接混为一组。
