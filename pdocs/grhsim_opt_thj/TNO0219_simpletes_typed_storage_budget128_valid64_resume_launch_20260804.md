# TNO0219：SimpleTES typed-storage 搜索扩容至 128/64 并续跑

日期：2026-08-04

## 1. 结论与边界

按用户指示，本阶段暂不对 [TNO0218](./TNO0218_simpletes_principled_trbs_second_fresh_completion_20260804.md)
中的 typed persistent-state storage best 做消融，而是从同一搜索实例的最终 exact checkpoint 继续 auto
research。正式续跑没有创建 fresh 搜索树，也没有把 `best_program.txt` 当成新的独立 initial seed；它通过
SimpleTES 的显式 `--resume --extend-resume-budget` 契约恢复原 DB、四条 RP-UCG chain history、failure
records、计数和当前 best，并把累计绝对上限扩为：

- `max_generations: 64 -> 128`；
- `max_valid_evaluations: 32 -> 64`。

这里的 `64 valid` 是全程累计目标，即在已有 `32 valid` 基础上最多再取得 `32 valid`，不是另加 64 个。
截至 `2026-08-04 01:26:06 +0800`，launcher、main 与四个 Codex generation subprocess 均存活，实时日志
连续报告 `gen workers: 4 active / 0 queued`；尚无扩容后的新 candidate、evaluation 或 50k 性能数据。

## 2. Exact resume 身份

源状态固定为：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/
principled_trbs_gpt56sol_max_fresh2_20260803_030316/
2026-08-03/instance-44cd457d/db_state_000359
```

launcher 先对该 exact state 执行 evaluator/checkpoint contract 校验，再把同一目录中的
`best_program.txt` 作为恢复所需 evolve context 传给 main；main 接收的 `--resume` 仍是精确
`db_state_000359`，没有再次按“latest”选择 checkpoint。

| 对象 | identity |
| --- | --- |
| SimpleTES commit | `6a169d4958066c4932240aba5cbe5729d794ad74` |
| evaluator parent executable pin | `52ba7d9edcd713cd0ee3d8a605f1d4aa31b3c730` |
| Wolvrix native pin | `d3ed9dea975bddf01185dde5c548a69241a09de9` |
| launch 时 parent HEAD | `6407746422604fb8a9d8f30049d4de00574e6f56`，只比 executable pin 多阶段文档 |
| source best candidate digest | `0fdabb9858b4a7f9afd1f301f5b7f6f7419f18bb80285fd81025f26afd3bda98` |
| source `best_program.txt` SHA-256 | `5723e113bb1f9e0c6110153bca609d17d1310b34369a439162b75c4e2f2a3117` |

恢复前 checkpoint 的累计状态为：

| 项目 | 绝对值 |
| --- | ---: |
| generation attempts | `40` |
| generation failures / cancellations | `0 / 0` |
| completed evaluations / DB nodes | `38 / 38` |
| valid evaluations | `32` |
| evaluator failures | `0` |
| best score | `1.06814371190328` |

因此新 generation 全局绝对上限还剩最多 `88` 次 attempt；valid 目标还差最多 `32` 个。上一轮达到 valid
上限时未 ingest 的 evaluation queue 项不在 final DB 中，本次不会把它们伪装成已完成历史结果。

## 3. RP-UCG 扩容语义

扩容不只修改 scheduler 的全局数字。source policy 的四条 chain 原来各有 `16` 个 prompt budget，已消费
计数分别为 `10 / 9 / 8 / 10`。resume contract 将每条 chain 的绝对 budget 单调扩为 `32`，同时保留：

- 每条 chain 已有 node 与 chain history；
- 已消费 prompt count；
- ready-chain 顺序和当前 inspirations/failure patterns；
- 所有已有 score、best node 与 generation/evaluation counters。

加载面板报告四条 chain 都有历史节点，扩容后 policy 尚余 `91 prompts`。该值来自逐 chain budget 与已消费
prompt count；真正停止还同时受 `generation_attempts < 128` 和 `valid_evaluations < 64` 两个全局条件约束。
历史 evaluator 不会重放，已有 best 也不会作为 initial control 重新计数。

checkpoint 会在下一次 evaluation 完成后持久化一条 budget-extension audit record，记录 source state、
`64→128`、`32→64`、扩容时 `40 attempts/32 valid` 和逐 chain policy 变化。首个新 checkpoint 尚未发布时，
原 immutable `db_state_000359` 仍完整保留；若进程在此窗口异常退出，可从同一 source state 重新执行显式扩容。

## 4. 模型与正式运行参数

| 参数 | 值 |
| --- | --- |
| model / effort | `gpt-5.6-sol / max` |
| config / auth | `~/.codex/config.thj.toml` / `~/.codex/auth.thj.json` |
| output/tool mode | `provider-structured / auto` |
| selector | `rpucg`，`4 chains`，`k=1`，reflection disabled |
| generation/evaluation workers | `4 / 1` |
| max generations / cumulative valid | `128 / 64` |
| generation/evaluation timeout | `10,800 s / 21,600 s` |
| ordinary Codex retries | `2` |
| capacity/transient exact-thread continuations | `3 / 3` |
| evaluator infra retries | `8`，由 evaluator 固定 |
| build jobs | `4`，由 evaluator 固定 |

GPT 继续使用 Codex 原生 delegation，不接收 K3-only instruction suffix、private model catalog 或 agent-thread
限制。evaluator 的默认生成路径、功能/attribution gate、whole-CCD quiet、CPU affinity、NUMA local、PMU、
关闭 ASLR、ABBA+BAAB 与 migration 检查均未改变；最终性能口径仍为 SimTop 50k walltime。

## 5. 启动前验证

正式启动前完成：

1. launcher `--dry-run` 对 exact checkpoint contract 校验通过；展开命令明确包含
   `--resume .../db_state_000359 --extend-resume-budget`、`--max-generations 128` 和
   `--max-valid-evaluations 64`；
2. resume budget-extension 与 exact-state/seed launcher focused tests 为 `2 passed`；
3. 启动时 capability preflight 通过后才创建 main；main 随后打印 exact Checkpoint Loaded 面板；
4. main 直接子进程实查为四个独立 `codex ... -m gpt-5.6-sol ... effort=max`，不是仅有四个 scheduler
   coroutine 但单个 Codex subprocess；
5. source config/auth 仅以路径传入，secret 内容没有写入命令、文档或 checkpoint 名称。

## 6. 运行入口与启动快照

续跑沿用原 output root 和 instance：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/
principled_trbs_gpt56sol_max_fresh2_20260803_030316/
2026-08-03/instance-44cd457d
```

实时 main 日志继续追加在：

```text
.../instance-44cd457d/run.log
```

本次 launcher 独立汇总日志为：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/
principled_trbs_gpt56sol_max_fresh2_20260803_030316/
launcher_resume_gen128_valid64_20260804.log
```

启动快照：

| 对象 | PID / SID / PGID |
| --- | --- |
| launcher | `2102396 / 2102396 / 2102396` |
| SimpleTES main | `2105608 / 2102396 / 2102396` |
| four Codex roots | `2105998 / 2106001 / 2106005 / 2106018` |

launcher 于 `01:23:55 +0800` 启动，main 于 `01:24:32 +0800` 创建；`01:24:38` 完成 checkpoint load 并
启动 scheduler，`01:25:08` 与 `01:25:38` 均报告 `4 active / 0 queued`、`eval 0 active / 0 queued`。
后者表示四个 generation 仍在模型探索、尚未产生待测 candidate，不是 evaluator 卡死。

本阶段只确认 exact resume、单调扩容、模型/凭据路径、并发 worker 和正式门禁已正确启动。当前 best 仍是
TNO0218 的 `47,620.25→44,582.25 ms`（`3,038.00 ms/6.379639%`）结果；在新 candidate 完成正式 evaluator
前，不报告任何额外性能提升，也不改 Wolvrix 默认实现。
