# SimpleTES Codex capacity session continuation

## 1. 结论

[`TNO0202`](./TNO0202_simpletes_codex_failure_persistence_retry_and_budget256_restart_20260730.md)
已把 provider capacity 归入普通 transient retry，但普通 retry 会重新执行原 prompt，并增加
`exec_attempt`。本阶段按新的边界将精确的
`Selected model is at capacity` 改为优先在原 Codex 会话内发送 `continue`：

- 会话内 continuation 使用独立预算，不增加 SimpleTES `exec_attempt`，也不消耗
  `--retry` / launcher `--codex-exec-retries`；
- 默认每个会话最多 continuation `3` 次，退避为 `1/2/5 s`；通用可配置范围为
  `0..8`，完整退避序列为 `1/2/5/10/20/30/45/60 s`；
- 只有错误同时为可重试、命中精确 capacity 诊断且 JSONL 提供安全
  `thread.started.thread_id` 时才 continuation；否则立即回落到既有普通 retry/确定性失败路径；
- continuation 预算耗尽后，才允许既有普通 retry 新建会话并重发原 prompt；每个新会话拥有自己的
  continuation 预算；
- 四个 generation worker 各自使用独立 private `CODEX_HOME`，并以明确 thread ID resume；绝不使用
  `--last`，不会把一个 worker 续到另一个 worker 的会话。

实现已提交为 SimpleTES `162d95543b32c68ee762f3fd9d6794f1b2cce8ac`。本阶段没有修改
Wolvrix、生成默认、evaluator 或 SimTop 性能口径，也没有启动、停止或重启 auto research。

## 2. 为什么没有直接使用 Stop hook

Codex `0.145.0` 的 Stop hook 确实支持用 `decision=block` 生成一条 continuation user prompt，
但它不能捕获本问题。对官方 `rust-v0.145.0` 源码
`codex-rs/core/src/session/turn.rs` 的检查显示：

1. `run_turn_stop_hooks` 只位于 `run_sampling_request` 返回 `Ok(...)` 且当前 turn 不再需要
   follow-up 的分支；
2. provider capacity 走 `Err(e)` 分支，该分支发出 turn error 后直接 `break`；
3. 因此 capacity 对应的 `turn.failed` 发生时，Stop hook 没有执行机会。

这不是 hook 配置遗漏。为了实现相同的“给原对话再发一条消息”语义，backend 使用 Codex 官方
non-interactive resume 接口：从 JSONL 提取 exact thread ID，再执行
`codex exec resume <thread-id> -`，stdin 仅发送 `continue`。这正好利用错误分支保留的“用户可以继续
该 conversation”状态，同时避免把 continuation 冒充 SimpleTES retry。

## 3. 实现与审计边界

一次逻辑 request 的 private `CODEX_HOME` 现在保留到其 structured repair、普通 exec retry 和
capacity continuation 全部结束，随后仍按原有 bounded cleanup 删除。初始 `codex exec` 不再使用
`--ephemeral`，使本地 session 可以被 resume；不同逻辑 request 仍拥有不同 `0700` HOME。

失败 artifact 继续完整保存脱敏 JSONL/stderr/final output，并新增以下 metadata：

| 字段 | 含义 |
| --- | --- |
| `exec_attempt` | SimpleTES 普通 exec attempt；capacity continuation 时保持不变 |
| `capacity_continuation` | 当前会话内的 continuation 序号，初始 turn 为 `0` |
| `conversation_mode` | `start` 或 `resume` |
| `resume_thread_id` | resume 时实际使用的 exact thread ID |

resume artifact 文件名加入 `.continue-XX`，不会覆盖初始或其他 continuation 的证据。最终失败
details 另记录本次逻辑 request 已使用的 continuation 总数和上限。thread ID 只接受有界安全字符，
作为 argv 直接传递，不经过 shell；没有 thread ID 的早期 provider failure 仍按普通 retry 处理。

新增通用 CLI 参数 `--codex-capacity-continuations`，`EngineConfig` 和 checkpoint 非敏感配置快照
均记录其有效值。GrhSIM launcher 的 preflight 与正式 main command 都显式传递该参数，默认值为
`3`。旧 checkpoint 不含该字段时仍能加载，因此后续可以从当前运行产生的旧格式 checkpoint 正常
继续。

## 4. 验证

SimpleTES 提交前完成：

- Codex backend + GrhSIM launcher 针对性回归：`151 passed`；
- 全量回归：`245 passed`，另有 `24` 条既有 `datetime.utcnow` deprecation warning；
- `python -m compileall`、`git diff --check`：PASS；
- launcher GPT/max dry-run 明确生成
  `--retry 2 --codex-capacity-continuations 3`；
- installed `codex-cli 0.145.0` 的 `codex exec resume --help` 明确接受
  `[SESSION_ID] [PROMPT]`、`--json`、`--output-schema` 和 `-o`；
- 真实 GPT capability canary：`model=gpt-5.6-sol`、`effort=max`、repo tool calls `1`、
  canonical response `632 chars`、SHA-256
  `2d808a396a541ae72a7ff40790881d0115f8b36cb7dbc44dc346ff7c1a40fe36`，PASS。

单测明确覆盖：初始 capacity 后在同一 HOME、同一 `exec_attempt=1` 对 exact thread ID 发送
`continue` 并成功；continuation 耗尽后才将第三个 subprocess 作为普通 `exec_attempt=2` 重发原
prompt；带 `status 400/invalid request` 的 capacity 字样不允许 resume；无 thread ID 时保留普通
retry；参数上界、artifact metadata、factory/CLI/launcher/checkpoint 接线均闭合。

真实 canary 没有故意制造 provider capacity，因此它验证初始 non-ephemeral/session-capable 路径，
而 exact capacity→resume 分支由确定性 fake-Codex JSONL 回归覆盖。没有用持续请求去人为等待一次
上游 capacity。

## 5. 当前运行与性能边界

`2026-07-30T03:44:12+08:00` 检查时，既有正式 continuation 的 supervisor/launcher/main
PID `2616216/2616369/2619762` 仍存活，scheduler 为 `1 gen active / 1 eval active / 2 eval
queued`。该 main 在本提交前已加载旧 Python 代码，其 argv 只有 `--retry 3`，没有新参数；Python
不会热加载本提交，所以本阶段没有伪称当前进程已经使用新机制，也没有为了生效而擅自重启。

本阶段新增 candidate 数为 `0`，新增 accepted SimTop 50k walltime sample 数为 `0`，因此没有
新的绝对或相对性能数据，也不产生默认启用决策。Wolvrix 通用默认和最终以 fixed-ASLR SimTop
50k walltime 裁决的规则均保持不变。新机制从下一次 preflight/research 进程启动时生效。
