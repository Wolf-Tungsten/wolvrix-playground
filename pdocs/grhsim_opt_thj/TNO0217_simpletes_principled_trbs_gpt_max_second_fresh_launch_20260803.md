# TNO0217：SimpleTES 原则化 TRBS GPT max 第二轮 fresh research 启动

日期：2026-08-03

## 1. 目标与当前状态

[TNO0216](./TNO0216_simpletes_principled_trbs_gpt_max_fresh_launch_20260801.md) 启动的
`instance-efb346a8` 已自然达到 `32/32 valid` 并退出，系统中没有遗留 launcher、SimpleTES main 或
evaluator 进程。用户判定该轮效果不理想，因此本阶段从同一原则化 TRBS native baseline 的 checked-in 空
control 直接启动第二轮独立 fresh auto research。

本轮没有使用 `--resume`，也没有把上一轮 `best_program.txt` 传给 `--init-program`。搜索树、chain history、
failure patterns、attempt/valid counters 和 candidate patch 均不继承上一轮；唯一继承的是已落地、已验证的
Wolvrix native baseline 与 SimpleTES bench contract。

截至 `2026-08-03 03:05:19 +0800`，新实例已越过 launcher 内建 capability preflight，创建 main 并进入
initial empty-control evaluator：

- output root：
  `SimpleTES/checkpoints/grhsim_simtop_50k/principled_trbs_gpt56sol_max_fresh2_20260803_030316`；
- instance：`2026-08-03/instance-44cd457d`；
- launcher PID/SID/PGID：`3134135/3134135/3134135`；
- SimpleTES main PID：`3138318`；
- initial evaluator PID/SID：`3138673/3138673`。

initial evaluator 已进入 quiet-CCD 检查，可见 `mpstat` 对动态选中的完整 CCD 运行门禁。当前还没有 generated
candidate、valid candidate、本轮 best 或正式 50k walltime，不能提前报告性能结果。

## 2. Fresh baseline 身份

| 对象 | identity |
| --- | --- |
| parent executable pin | `52ba7d9edcd713cd0ee3d8a605f1d4aa31b3c730` |
| Wolvrix native pin | `d3ed9dea975bddf01185dde5c548a69241a09de9` |
| SimpleTES bench commit | `6a169d4958066c4932240aba5cbe5729d794ad74` |
| launch 时 parent HEAD | `5854452da77f90e22336073eddafc252ad4a1c18` |
| empty-control digest | `2147a1179e1b655288a2368a95dd6fddc619cdd6feaab04179ddf7d4a6b21520` |

启动前重新执行 `init_program.txt --validate-only`，结果为 `valid=true`、`candidate_mode=control`、空 patch、
空 options 和 `files=[]`。因此 initial node 确实是原则化 TRBS native 默认本身，而不是上一轮候选的重测。

parent HEAD 只比 executable pin 多性能文档；evaluator 仍固定 checkout `52ba7d9.../d3ed9dea...`。原则化
TRBS 继续由 Wolvrix C++ emitter 通用默认提供，Python 流程继承，不借用 `targeted-direct`，也没有 SimTop
wrapper 专用打开。

## 3. 模型、凭据与研究预算

| 参数 | 值 |
| --- | --- |
| model | `gpt-5.6-sol` |
| reasoning effort | `max` |
| config | `~/.codex/config.thj.toml` |
| auth | `~/.codex/auth.thj.json` |
| output/tool mode | `provider-structured / auto` |
| selector | `rpucg`，`4 chains`，`k=1` |
| generation/evaluation workers | `4 / 1` |
| max proposals / valid target | `64 / 32` |
| generation/evaluation timeout | `10,800 s / 21,600 s` |
| ordinary Codex retries | `2` |
| capacity/transient exact-thread continuations | `3 / 3` |
| evaluator infra retries | `8` |
| build jobs | `4` |
| reflection | disabled |

四个 generation worker 只并发执行模型探索；evaluation 保持单 worker，避免 candidate build、slot 写入和正式
性能采样互相覆盖或争用。GPT 使用 Codex 原生 delegation，不接收 K3-only catalog、prompt suffix 或 agent
thread cap。API key 内容没有进入命令、文档或 checkpoint 名称。

## 4. 启动与观察入口

正式 launcher command line 已核验包含默认 `init_program.txt`，且不含 `--resume` 和旧
`best_program.txt`。main command line 同时确认：

- `--model gpt-5.6-sol --reasoning-effort max`；
- `--max-generations 64 --max-valid-evaluations 32`；
- `--gen-concurrency 4 --eval-concurrency 1`；
- `--timeout 10800 --eval-timeout 21600`；
- capacity/transient continuation 均为 `3`。

实时日志：

`SimpleTES/checkpoints/grhsim_simtop_50k/principled_trbs_gpt56sol_max_fresh2_20260803_030316/2026-08-03/instance-44cd457d/run.log`

launcher 汇总日志：

`SimpleTES/checkpoints/grhsim_simtop_50k/principled_trbs_gpt56sol_max_fresh2_20260803_030316/launcher.log`

本阶段只确认 fresh 边界、进程、参数、pin、preflight 和 initial evaluator 已启动。后续性能结论仍必须报告
绝对 `Host time spent` 与相对变化，并通过功能、固定 ASLR、whole-CCD quiet、同 CCD ABBA+BAAB、affinity、
NUMA、PMU 和 migration 审计。

