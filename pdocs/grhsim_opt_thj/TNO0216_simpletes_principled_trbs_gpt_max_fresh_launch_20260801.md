# TNO0216：SimpleTES 原则化 TRBS GPT max fresh research 启动

日期：2026-08-01

## 1. 阶段目标与当前状态

[TNO0215](./TNO0215_principled_hot_event_simpletes_repin_and_continuation_readiness_20260801.md) 已把
SimpleTES bench 迁移到原则化 TRBS native 空 control。本阶段按用户指示，使用 GPT-5.6 Sol、max reasoning
以及 THJ config/auth 启动一轮新的 fresh auto research。

截至 `2026-08-01 20:13:28 +0800`，正式实例已经越过 launcher 内部 capability preflight，创建
SimpleTES main，并进入 initial empty-control evaluator：

- output root：
  `SimpleTES/checkpoints/grhsim_simtop_50k/principled_trbs_gpt56sol_max_fresh_20260801_200959`；
- instance：`2026-08-01/instance-efb346a8`；
- launcher PID/SID/PGID：`3336085/3336085/3336085`；
- SimpleTES main PID：`3340413`；
- initial evaluator PID/SID：`3341207/3341207`。

当前没有 generated candidate、valid candidate、best score 或本轮 50k walltime，不能提前报告性能结论。
evaluation 保持单 worker；initial control 未完成前不会并发运行候选性能测试。

## 2. 固定代码与 control 身份

| 对象 | identity |
| --- | --- |
| evaluator parent pin | `52ba7d9edcd713cd0ee3d8a605f1d4aa31b3c730` |
| evaluator Wolvrix pin | `d3ed9dea975bddf01185dde5c548a69241a09de9` |
| SimpleTES repin commit | `6a169d4958066c4932240aba5cbe5729d794ad74` |
| launch 时 parent HEAD | `83d166d766e1dad595209ec2dc57f5185b7682d0` |
| empty-control digest | `2147a1179e1b655288a2368a95dd6fddc619cdd6feaab04179ddf7d4a6b21520` |

parent HEAD 比 executable snapshot 多 TNO0214/TNO0215 文档提交；evaluator 仍精确 checkout
`52ba7d9.../d3ed9dea...`，不会把运行中的文档变化当成 candidate 源码。新 instruction 已将原则化 TRBS
列为 native baseline，并禁止通过端口名、SimTop identity、ValueId 或 raw slot-count 重建同类特化。

启动时关键文件 SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| `init_program.txt` | `ae8fccc4e13152d328f0b4b90d2710d5ee545a7abebf853d56d3bb1f86d88ed1` |
| `evaluator.py` | `59bca6e3ff0921499b2df2bff337c273f5d2997bed2032f92deb2ed371eae160` |
| `instruction.txt` | `765b4d0c51efd670f4f798ecf3df913699f252f8105746325d4496454cf61ac7` |

## 3. 模型、凭据、并发与预算

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
| ordinary Codex exec retries | `2` |
| exact-session capacity continuations | `3` |
| exact-session transient continuations | `3` |
| evaluator infra retries | `8` |
| build jobs | `4` |
| reflection | disabled |

GPT 分支不接收 K3-only model catalog、prompt suffix 或 agent-thread cap，保留 GPT/Codex 原生 delegation 行为。
auth 仅以文件路径交给 launcher；API key 内容没有进入命令、文档、日志路径或 checkpoint 名称。

本轮采用 fresh launcher 上限 `64 proposals`，以 `32 valid` 为停止目标。四个 generation worker 可并发等待
模型，evaluator 严格串行，因此不同 candidate 不会同时覆盖 evaluator slot、build tree 或争用正式性能 CCD。

## 4. Preflight 与正式启动证据

启动前的独立真实 capability preflight 为 PASS：

- model：`gpt-5.6-sol`；
- effort：`max`；
- repo tool calls：`1`；
- model catalog：`native`；
- response chars：`632`；
- response SHA-256：
  `dd1709ed96f5c2693fb728fdae0da261dcc92e02be7b15370e5f1f585c96b76b`。

该请求验证 THJ provider/auth、原生模型目录、repository tool、provider structured schema 和 harmless patch
applicability。正式 launcher 随后再次执行其内建 preflight；SimpleTES main 与 initial evaluator 已被创建，证明
正式启动也越过该门禁。

第一次后台 shell 封装把前置 `source`/`mkdir` 一起放入了短命 background job，在执行前即退出；复核时没有
进程、output directory、checkpoint、API 请求或 proposal。随后先同步创建 output root，再以独立 session 启动
上述正式 launcher。该 shell 封装失误不属于模型、candidate 或 evaluator failure，也没有消耗研究预算。

## 5. 观察入口与性能边界

实时 engine 日志：

`SimpleTES/checkpoints/grhsim_simtop_50k/principled_trbs_gpt56sol_max_fresh_20260801_200959/2026-08-01/instance-efb346a8/run.log`

launcher 汇总日志：

`SimpleTES/checkpoints/grhsim_simtop_50k/principled_trbs_gpt56sol_max_fresh_20260801_200959/launcher.log`

启动时 `run.log` 已记录 `gpt-5.6-sol`、`4/1 workers`、`64/32` budget、`10800/21600 s` timeout 和
initial evaluator。重定向的 `launcher.log` 可能因 Python block buffering 暂不刷新，运行中状态优先以
`run.log`、进程树和 immutable `db_state_*` 为准。

本轮后续结论只接受功能与 attribution gates 通过、关闭 ASLR、whole-CCD quiet、同 CCD ABBA+BAAB 的
SimTop 50k `Host time spent`。TNO0213 的 `7.621407%` 是已落地原则化 TRBS 的历史收益，不能写成本轮新
candidate 结果。

