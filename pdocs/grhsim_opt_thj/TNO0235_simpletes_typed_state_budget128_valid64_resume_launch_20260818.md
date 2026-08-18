# TNO0235：SimpleTES typed-state 续跑扩容到 128/64

日期：2026-08-18

## 1. 阶段结论

上一轮 `typed_state_gpt56sol_max_fresh2_20260816_182232` 已自然结束，精确终点为
`instance-5f0c84e9/db_state_012346`。本阶段按用户指示从这个 immutable checkpoint
继续，而不是 fresh 或重置搜索历史，将全局预算从 `64 generations / 32 valid`
单调扩展到 `128 generations / 64 valid`。

扩容后的主循环已在 node032 正常启动并进入调度阶段。启动日志明确报告：

```text
Checkpoint Loaded
Attempts: 43 | Gen fails: 0 | Gen cancels: 1 | Eval rejects: 0 | Evals: 41
DB nodes: 41 | Chains: 4/4 with nodes
Budget extension: generations 64→128 | valid 32→64
Starting 4 gen workers and 1 eval workers
Starting scheduler loop
```

截至本记录形成时，扩容轮仍在运行，尚没有新的 candidate 完成 SimTop 50k
性能验证；因此不能把本轮启动证据或源 checkpoint 的 best 当作新的性能结论。

## 2. 源 checkpoint 与基线身份

源 checkpoint：

```text
/nfs/home/tanghaojin/wolvrix-SimpleTES-workspace-5/SimpleTES/checkpoints/
grhsim_simtop_50k/typed_state_gpt56sol_max_fresh2_20260816_182232/
2026-08-16/instance-5f0c84e9/db_state_012346
```

源 `metadata.json` 的持久化计数为：

| 字段 | 值 |
| --- | ---: |
| generation attempts | `43` |
| completed evaluations | `41` |
| valid evaluations | `32` |
| generation failures | `0` |
| generation cancellations | `1` |
| evaluation failures | `0` |
| `best_score` | `1.0128054335166798` |
| best node | `180c854bbcbc406d8115ef7ee9af789a` |

源 best program 保留的是上一阶段已经测得的 all-materialized-value direct-member
方向：固定-ASLR SimTop 50k `43,223.25 → 42,777.50 ms`，即
`445.75 ms/1.031274%`；这是续跑的已有 seed，不是本阶段新测量。

源节点记录的代码身份为 parent
`0dc48d4aa6dd508812d3226221e7c7a594ff3e7b`、Wolvrix
`79ec2037b00f2d4894d72785277ebe3f5d37782d`，并继续遵守当前默认生成配置和
SimTop evaluator 的 fixed-ASLR、quiet-CCD、NUMA、PMU、功能与 walltime 门禁。

## 3. 启动配置与运行证据

本轮在 node032 使用的模型和凭据路径为：

| 项目 | 值 |
| --- | --- |
| model | `gpt-5.6-sol` |
| reasoning effort | `max` |
| Codex config | `/nfs/home/tanghaojin/.codex/config.thj.toml` |
| Codex auth | `/nfs/home/tanghaojin/.codex/auth.thj.json` |
| generation workers | `4` |
| evaluation workers | `1` |
| generation timeout | `10800 s` |
| evaluation timeout | `21600 s` |
| capacity continuations | `3` |
| transient continuations | `3` |
| selector | `rpucg` |
| output root | `typed_state_gpt56sol_max_fresh2_extend128_valid64_20260818_1050` |

实际 launcher 使用 `--resume` 指向上述 `db_state_012346`，同时显式传入
`--extend-resume-budget --max-proposals 128 --valid-target 64`。launcher
自己的预检通过后，于 `2026-08-18 10:56:09 +0800` 启动主循环；当时 node032
的 load average 为 `11.83 / 19.39 / 23.04`，进程仍保持存活。

运行目录和日志：

```text
/nfs/home/tanghaojin/wolvrix-SimpleTES-workspace-5/SimpleTES/checkpoints/
grhsim_simtop_50k/typed_state_gpt56sol_max_fresh2_extend128_valid64_20260818_1050/
launcher_20260818_1050.log
```

核对到的进程为 launcher PID `2007361`、SimpleTES 主循环 PID `2010840`；主循环
命令行同时包含 `--max-generations 128`、`--max-valid-evaluations 64`、
`--gen-concurrency 4`、`--eval-concurrency 1` 和 `--extend-resume-budget`。

## 4. 后续判定边界

- 只有扩容轮中通过完整 evaluator 的 candidate 才进入性能排序。
- 最终仍以 SimTop 50k `walltime` 为端到端指标，并要求同 CCD 的 fixed-ASLR
  ABBA/BAAB 和既有 quiet/NUMA/PMU/功能门禁。
- 新 best 在完成正式性能验证前只作为搜索状态，不自动落地到 Wolvrix，也不改变
  当前默认生成配置。
- 后续若需要再次扩容，应从本轮最新持久化 `db_state_*` 继续，并继续使用显式的
  单调预算扩展契约。

