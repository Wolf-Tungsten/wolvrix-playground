# SimpleTES rate-limit and transport-timeout continuation

## 1. 范围与运行约束

本次只读审计以下仍在追加的日志：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/
  typed_state_gpt56sol_max_fresh2_20260816_182232/
  2026-08-16/instance-5f0c84e9/run.log
```

审计和修改期间没有停止或重启现有 auto research。`2026-08-19 09:35 +0800`
只读核查时，node032 上原 launcher/main PID `1205133/1207812` 仍在运行，生成和
evaluation 子进程均有活动。运行中的 Python 进程不会热加载本次源码修改，因此新规则只从
后续正常启动或恢复开始生效。

本记录承接 [TNO0210](./TNO0210_simpletes_codex_remote_compact_and_reconnect_session_continuation_20260731.md)
的 exact-thread continuation 机制和
[TNO0236](./TNO0236_simpletes_typed_state_budget256_valid64_resume_launch_20260819.md)
记录的 `256 attempts/64 valid` 扩容运行。

## 2. 错误快照与分类

截至 `2026-08-19 09:35 +0800`，按顶层 generation failure 消息计数，而不是按嵌套
`sanitized_trace` 的重复文本计数：

| 顶层错误 | 绝对次数 | 修改前行为 | 本次结论 |
| --- | ---: | --- | --- |
| `429 Too Many Requests` | `74` | 仅作为普通 Codex exec retry，消耗 SimpleTES `--retry` | 纳入 capacity continuation；存在 exact thread ID 时发送 `continue`，使用独立有界预算 |
| remote compact | `6` | 已使用 remote-compact exact-thread continuation | 保持现状，不重复新增 |
| `TimeoutError` | `1` | 直接终止该 generation，不进入 continuation | 仅 transport/compact-backed timeout 可 continuation；裸超时仍不续跑 |

唯一顶层 timeout 的绝对诊断为 `10,800 s`，其 trace 已完成 `870` 个 event、`430` 次
repository tool call，并含多次 `Reconnecting...`、`stream disconnected before completion`
和 `Upstream request failed`。首条 JSONL 同时保存了有效 `thread.started` ID。因此该实例不是
“没有会话的纯耗时超限”，而是已有大量工作、随后受传输故障拖到总 timeout；恢复同一 thread
比重新丢弃全部上下文更合适。

以下文本虽然出现在嵌套 trace 中，但不单独触发 `continue`：

- `OutputTextDelta without active item` 和 stale temp-dir cleanup 是伴随告警，不是可靠的终止原因。
- `Failed to create unified exec process` / `No such file or directory (os error 2)` 仍只属于普通
  exec retry；孤立的工具进程创建失败不足以证明 LLM turn 可恢复。
- `SemanticValidationError`、`InvalidJSON` 继续走已有的结构化 repair，不发送裸 `continue`。
- authentication、permission、policy、invalid request、schema 和 `400/401/403/404` 仍由
  non-retryable 清单优先拦截。

## 3. 实现

SimpleTES commit：`25d6b7a97cb969747a86ba01da0d7ef0846f213f`。

改动位于 `simpletes/llm/codex_exec.py`：

1. 将显式 `rate limit`、`too many requests`、`status 429` 加入 capacity diagnostic 清单。
2. timeout 落盘前从当前 JSONL 提取 exact thread ID，并记录 retry/remote-compact/reconnect/
   transient-session 分类字段。
3. `TimeoutError` 只有在同一 trace 含 remote-compact 或 reconnect/stream-disconnect 证据时才标为
   retryable；裸 wall-clock timeout 不会因此扩大重试范围。
4. continuation 仍要求有效 thread ID，并受现有 capacity/transient 独立次数上限和退避序列约束；
   用尽后才回落到普通 exec retry。

## 4. 回归

```text
.venv/bin/pytest -q tests/test_codex_exec_backend.py
79 passed in 9.94s

.venv/bin/pytest -q
265 passed, 24 warnings in 9.00s
```

新增回归覆盖：

- bare `429 Too Many Requests` 在有 thread ID 时以同一 private HOME 和 exact thread 执行
  `codex exec resume ... continue`，且不消耗普通 exec retry。
- reconnect-backed timeout 在杀掉超时本地进程后恢复保存的 exact thread，并发送 `continue`。
- 原有纯 timeout 用例继续直接报告 `TimeoutError`，证明没有把所有 timeout 一概放入 continuation。

## 5. 当前状态

- SimpleTES 源码和测试已提交。
- 现有 node032 任务未重启、未被发送信号、未创建替代实例。
- 当前任务继续使用启动时已加载的旧 Python 代码；本修复将在下一次正常启动或恢复时生效。
- 本次只修改 LLM 基础设施，不涉及 Wolvrix 优化 patch、默认生成配置或 SimTop 性能口径。
