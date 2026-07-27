# TNO0191 SimpleTES K3 broken run diagnosis and graceful stop

## 1. 阶段结论

本记录闭合 [TNO0190](./TNO0190_simpletes_k3_post_rwa_long_research_launch_20260728.md)
启动的 `k3/ultra` 长轮次。该轮没有自然跑满 `64 proposals / 32 valid`，而是在确认生成端持续产生
placeholder/空候选后，于 `2026-07-28 01:19:19 +08:00` 发送 SIGINT，并由 SimpleTES 正常完成
graceful shutdown。

最终结论：

- initial control 的同二进制 ABBA sanity gate 正常，绝对 walltime 约为 `53.8 s`；
- 27 个已持久化 K3 output 都没有真实 patch，`valid evaluations = 0`；另一个已进入 evaluator、但在
  shutdown 时被移除的 pending output 内容未知；
- 没有候选进入 patch build、功能回归或 SimTop 50k 性能评测；
- best 仍是 initial control，不能把本轮 score 或 `3 ms` control 差值解释为优化收益；
- 本阶段不保留任何生成 patch，不修改 Wolvrix 代码或默认配置；
- 最终 checkpoint 已安全发布，后台 launcher exit code 为 `0`，当前没有该实例的残留进程。

## 2. 实例与最终状态

本轮唯一 output root：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/k3_rwa_fresh_20260728_005300
```

实例与最终 checkpoint：

```text
2026-07-28/instance-583068cb
2026-07-28/instance-583068cb/db_state_011928
```

生命周期时间线：

| 时间（`+08:00`） | 事件 |
| --- | --- |
| `01:19:19` | scheduler 收到 SIGINT |
| `01:19:28` | 两个 worker 停止，取消一个在途 generation，发布 `db_state_011928` |
| `01:19:29.578208` | `launcher.stdout.log` 最后写入 |
| `01:19:30.141232` | `launcher.exit` 原子写入 `0` |

保存的 launcher PID `2403019` 已不存在。这里的 exit `0` 表示 SIGINT 被框架正常处理，而不是本轮自然达到
`64/32` 预算。

## 3. Initial control 的绝对 50k walltime

root node 是 post-RWA native-default 空 control。正式口径仍取 SimTop 50k 日志中的
`Host time spent` walltime；本次 control-vs-control ABBA sanity 数据为：

| arm | 绝对样本（ms） | 算术均值（ms） | range / spread（ms） |
| --- | --- | ---: | --- |
| control | `53,713 / 53,876` | `53,794.5` | `53,713..53,876 / 163` |
| candidate-control | `53,865 / 53,718` | `53,791.5` | `53,718..53,865 / 147` |

同一 control 二进制的表面差值为 `3.0 ms / 0.0055767783%`，只证明测量噪声很小，不能作为端到端性能提升。
initial evaluator 绝对用时为 `655.9151987638324 s`，`01:04:47` 输出 initial score
`1.0000557708931708`。

## 4. Generation 与 evaluator 结果

最终 metadata/final panel 的绝对计数：

| 字段 | 绝对值 |
| --- | ---: |
| scheduler `generation_attempts` / `gen_id_counter` | `43 / 43` |
| 持久化 generation outputs | `27` |
| shutdown 时正在 evaluation 的 pending output | `1` |
| generation failures | `12` |
| generation cancellations | `1` |
| completed evaluations（含 initial） | `28` |
| generated candidate evaluations | `27` |
| valid evaluations | `0 / 32` |
| evaluation failures/rejects | `0 / 0` |

`generation_attempts=43` 是进入 generation queue 前的 scheduler 分配计数。结合 shutdown 前最后状态
`finished_nodes=28`（initial + 27 generated）、`gen_fail=12`、`gen_inflight=1`、`llm_q=2`、
`eval_inflight=1`，43 个 scheduled attempt 可以严格闭合为：

- `27` 个 generation output 完成 evaluator 并持久化为 generated node；
- `12` 个 generation failure；
- `1` 个额外 generation output 正在 evaluator 中，shutdown 时 evaluation 被取消、pending node 被移除；
- `1` 个 generation 正在模型调用中，被记为 generation cancellation；
- `2` 个 generation 仍在 generation queue，shutdown drain 时丢弃；
- 合计 `27 + 12 + 1 + 1 + 2 = 43`。

12 个 generation failure 的分类为：

| failure | 数量 |
| --- | ---: |
| 缺少 `schema_version` | `3` |
| response 不是 JSON object | `3` |
| 非法 `candidate_mode=control` | `5` |
| ephemeral Codex home cleanup `Directory not empty` OSError | `1` |

27 个完成 evaluator 并进入最终 checkpoint 的 generation output 均被正常判为 `validity=0`，没有发生
evaluator exception：

| CandidateError | 数量 |
| --- | ---: |
| patch 无末尾换行 | `21` |
| default-path 同时没有 patch/options | `5` |
| hypothesis 为空 | `1` |

因此 27 个已持久化 output 中不存在“功能通过但性能不佳”的候选；它们全部在 build/仿真之前就因候选语义
无效停止。第 28 个 pending output 没有被 checkpoint 保存，不能断言其正文或有效性，但它同样没有完成有效
性能评测。

## 5. K3 输出形态

以下长度只统计 27 个通过 generator flat schema、被保存为 node 的内层 JSON；11 个 schema-failed raw response
没有持久化正文，不能补算长度：

| 指标 | 绝对值（chars） |
| --- | ---: |
| min | `138` |
| max | `201` |
| mean | `178.5185185185` |
| 分布 | `138×1 / 170×4 / 181×21 / 201×1` |

语义分类：

- `21/27`：hypothesis、evidence、patch 都是同一 11-char placeholder，patch 无换行；
- `4/27`：hypothesis/evidence 为 placeholder，patch 为空；
- `1/27`：42-char hypothesis 仍包含 placeholder，evidence 为 placeholder，patch 为空；
- `1/27`：hypothesis/patch 为空且 evidence 是空数组。

即 27 个 persisted output 中，`26/27` 是明确 placeholder，`1/27` 是全空语义；`27/27` 都没有真实 diff，
也没有 enable options。这些比例不外推到 shutdown 时被移除、正文未保存的第 28 个 pending output。
最终 best node 仍是 initial control `41488c64e8994a6db0ac84b1ff8db5a5`。

## 6. 对上一阶段 preflight 的勘误

[TNO0189](./TNO0189_simpletes_k3_codex_provider_default_and_preflight_20260728.md) 记录的真实 K3
production-schema preflight 只证明了 endpoint/auth/Responses transport 可达，以及 K3 能返回一个满足 flat schema 的
JSON object。它没有证明：

- Codex/K3 实际调用过仓库工具；
- response 含真实、可应用的 unified diff；
- hypothesis/evidence 不是 placeholder；
- 候选能进入 build、功能与 SimTop 50k gate。

正式长轮次说明该 preflight 太弱，schema-valid placeholder 可以通过。该历史记录保留不改；本记录追加上述
能力边界勘误，后续修复必须用 repository-grounded capability gate 取代原 transport-only gate。

## 7. 证据入口与阶段裁决

相对证据路径：

- `SimpleTES/checkpoints/grhsim_simtop_50k/k3_rwa_fresh_20260728_005300/launcher.stdout.log`
- `SimpleTES/checkpoints/grhsim_simtop_50k/k3_rwa_fresh_20260728_005300/launcher.exit`
- `SimpleTES/checkpoints/grhsim_simtop_50k/k3_rwa_fresh_20260728_005300/2026-07-28/instance-583068cb/run.log`
- `SimpleTES/checkpoints/grhsim_simtop_50k/k3_rwa_fresh_20260728_005300/2026-07-28/instance-583068cb/db_state_011928/metadata.json`
- `SimpleTES/checkpoints/grhsim_simtop_50k/k3_rwa_fresh_20260728_005300/2026-07-28/instance-583068cb/db_state_011928/nodes.json`
- `SimpleTES/checkpoints/grhsim_simtop_50k/k3_rwa_fresh_20260728_005300/2026-07-28/instance-583068cb/db_state_011928/config.json`

本阶段唯一裁决是停止无效 K3 生成并保留诊断证据。initial control 的绝对 walltime 有效，但没有新的非 control
性能样本，也没有端到端正收益候选；Wolvrix 的 R/W/A 默认状态保持不变。
