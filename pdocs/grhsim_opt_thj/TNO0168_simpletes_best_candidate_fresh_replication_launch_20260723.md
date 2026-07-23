# TNO0168 SimpleTES best-candidate fresh replication launch

## 1. 目标

在 [TNO0167](./TNO0167_simpletes_long_continuation_final_results_semantic_audit_and_default_hold_20260723.md) 的 gen 27 最佳程序上启动新的 SimpleTES instance。该 run 先对 `18.353021%` 候选做 fresh attribution/ABBA/BAAB 独立复现，随后继续 `32 proposals / 16 valid` auto research；不从带 pending policy 的旧 checkpoint 原地 resume。

## 2. Seed 与启动契约

```text
init program:
SimpleTES/checkpoints/grhsim_simtop_50k/formal_20260721_03/2026-07-21/instance-25411edd/db_state_110407/best_program.txt
bytes: 46653
sha256: 988d6b504c773b118ef57a9d380c9fcfe689aaabd251ffde7e81e7fe02810ae7

output root:
SimpleTES/checkpoints/grhsim_simtop_50k/continuation_20260723_194100

instance:
50c610a6
```

启动命令：

```bash
source wolvrix-playground-gsim-calibrate-5/env.sh
GRHSIM_INFRA_RETRIES=4 SimpleTES/.venv/bin/python \
  SimpleTES/datasets/grhsim/simtop_50k/launcher.py \
  --init-program SimpleTES/checkpoints/grhsim_simtop_50k/formal_20260721_03/2026-07-21/instance-25411edd/db_state_110407/best_program.txt \
  --max-proposals 32 \
  --valid-target 16 \
  --llm-timeout 5400 \
  --output-path SimpleTES/checkpoints/grhsim_simtop_50k/continuation_20260723_194100
```

初始化日志确认 generator 为 `gpt-5.6-sol`、timeout `5400 s`、gen/eval worker 各 `1`、stream-k 开启、budget 为 `32/16`。launcher 继续使用既有 MJY API/auth 配置和 `ultra` reasoning 配置；quiet whole-CCD、fixed-ASLR、NUMA first-touch、PMU、功能、ABBA→BAAB promotion gate 均未放宽。

## 3. 启动勘误

同日较早的 instance `ca06b6e2` 只完成初始化便收到 SIGINT，没有 checkpoint、metadata 或 evaluation，不能作为研究结果。为避免污染账本，后续只跟踪 fresh instance `50c610a6`。

## 4. 截止状态

截至 `2026-07-23 20:11 +08:00`：

- unified exec session `32342` 仍存在，尚未返回 exit code。
- initial seed 的 isolated candidate 环境正在 fresh 重建；disabled attribution build log 最新推进到 `hier-flatten` 之后，文件仍持续更新。
- instance 目录目前只有初始化 `run.log` 与空 `shared_constructions`；尚无 `db_state_*`、metadata 或 evaluation JSON。
- 因此目前没有新的 50k walltime、score、valid candidate 或默认结论。
- 不应重复启动第二个 worker；继续观察 `50c610a6` 即可。

运行日志：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/continuation_20260723_194100/2026-07-23/instance-50c610a6/run.log
```

本记录只闭合 fresh continuation 的启动状态。后续第一组正式 ABBA/BAAB 或终止结果应另建增量文档，并同时记录绝对 walltime 与相对变化。

## 5. 增量更新 2026-07-23 20:45 +08:00

session `32342` 仍返回 session id 且没有 exit code。enabled seed build 日志已经更新到 `20:43:39`，最新阶段为 `pass hier-flatten start`；这证明 worker 仍在实际推进，不是只剩空 PTY。SimpleTES instance 目录仍未写出首个 checkpoint/evaluation，因此当前正式结果仍为零，不能给出新的 walltime 或 score。
