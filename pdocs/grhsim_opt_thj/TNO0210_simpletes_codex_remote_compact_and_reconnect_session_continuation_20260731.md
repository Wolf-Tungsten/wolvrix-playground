# SimpleTES Codex remote-compact/reconnect session continuation

## 1. 结论

[TNO0203](./TNO0203_simpletes_codex_capacity_session_continuation_20260730.md)
只对精确的 provider capacity 错误执行同会话 `continue`。本轮 fresh research 随后暴露了另一类
可恢复的终止：Codex 在已经完成约 180–205 条事件、86–96 次仓库工具调用后，因 remote
compaction 返回异常；最新一次还先出现
`Reconnecting... (stream disconnected before completion: Upstream request failed)`，最终同一 turn
以 remote-compaction failure 退出。

SimpleTES commit `6517bfc4ef8134d8e6758c17c1d3f707206efb67` 已将以下错误纳入独立的
exact-session continuation：

- `Error running remote compact task` / remote-compaction output-count mismatch；
- `Reconnecting...`；
- `stream disconnected before completion`；
- `Upstream request failed`。

新机制默认每个会话最多尝试 `3` 次 `continue`，不消耗 capacity continuation，也不消耗
SimpleTES 普通 exec retry。只有独立预算耗尽或没有安全 thread ID 时，才回落到普通 retry
并以原 prompt 新建会话。当前运行中的进程没有重启，因而仍使用启动时加载的旧代码；该机制从
下一次 preflight/research 启动或明确恢复时生效。

## 2. 当前实例中的直接证据

证据来自 [TNO0209](./TNO0209_simpletes_post_four_gpt_max_fresh_launch_20260731.md) 的正式实例
`73ee9786`，失败 metadata 和完整 JSONL 均位于该实例的 `llm_attempts/request-*`。四次 terminal
failure 均有合法的 `thread.started.thread_id`，因此不是只能重新发送整条 prompt 的早期连接失败：

| 本地时间 | request | thread ID | events | repo calls | JSONL bytes | 主诊断 |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `15:57:31` | `cfc1a8ab...` | `019fb721-bb49-7012-bd93-9e0d3d1fed4e` | `186` | `87` | `1,130,333` | remote compact，`0 from 2 output items` |
| `16:10:16` | `1c8a3b43...` | `019fb72d-af34-71b1-b7b6-e82b88f6c305` | `196` | `96` | `1,278,056` | remote compact，`0 from 1 output items` |
| `16:28:23` | `16ab60de...` | `019fb739-5c6f-7971-84c8-b9f7acda7f47` | `180` | `86` | `2,072,112` | remote compact，`0 from 1 output items` |
| `16:46:01` | `ace1a977...` | `019fb749-f240-74c0-a970-9a507f35f19e` | `205` | `91` | `1,628,536` | 两次 reconnect，随后 remote compact |

旧进程对四次错误均写出 `retryable=false` / `classified as non-retryable`，所以每次只执行一个
subprocess，就直接计为一次 generation failure；其 argv 虽有普通 `--retry 2`，也没有机会使用。
最新一次的 `Reconnecting...` 不是把 Codex 正常的内部重连提示误当失败：backend 只在 Codex
subprocess 已非零退出后分类，若 Codex 内部重连成功并正常退出，不会触发额外 continuation。

## 3. 实现与预算边界

新增通用 `--codex-transient-continuations`，范围为 `0..8`，默认 `3`，退避序列为
`1/2/5/10/20/30/45/60 s`。GrhSIM bench 当前三层预算严格分开：

| 层次 | 默认 | 行为 |
| --- | ---: | --- |
| capacity session continuation | `3` | 只处理 model-at-capacity，在 exact thread 发送 `continue` |
| transient session continuation | `3` | 只处理 remote compact/reconnect/stream failure，在 exact thread 发送 `continue` |
| ordinary Codex exec retry | `2` | 前两层不适用或耗尽后，新建会话并重发原 prompt |

每个 generation request 继续使用 request-private `CODEX_HOME`。continuation 从完整失败 JSONL 提取
明确 thread ID，执行 `codex exec resume <thread-id> -`，stdin 只发送 `continue`；仍不使用
`--last`，四个 generation worker 不会续到彼此的会话。每个 ordinary retry 建立的新会话重新获得
自己的 bounded continuation 预算。

subprocess 的 `cwd` 现在固定为 `codex_repo_root`。这同时修复了 TNO0209 首次启动暴露的边界：
即使外层 launcher 从非 Git 目录调用，exact-thread resume 也不会因继承错误 cwd 而触发 Codex
trusted-directory 检查失败。

完整失败 JSONL、stderr、可选 final output 仍在 continuation 之前持久化。metadata 保留旧
`capacity_continuation` 字段以兼容 schema-v1 artifact consumer，并新增更准确的
`session_continuation`、`continuation_reason`，以及
`remote_compact_failed`、`reconnect_failed`、`transient_session_failure` 分类。这样如果
`continue` 仍失败，原始失败与后续失败都能分别定位，不会因 retry 覆盖。

配置已贯通 `EngineConfig`、通用 CLI、client factory、checkpoint 非敏感快照、状态显示、GrhSIM
launcher preflight 和正式 command。bench README 也记录了三套预算及关闭参数，后续 SimpleTES
探索无需另行 patch 即可使用。

## 4. 验证

提交前完成：

- Codex backend、GrhSIM launcher 与 checkpoint focused 回归：`179 passed`；
- 全量 SimpleTES 回归：`251 passed`，另有 `24` 条既有 `datetime.utcnow` deprecation warning；
- `python -m compileall` 与 `git diff --check`：PASS；
- GPT/max launcher dry-run 明确输出
  `--retry 2 --codex-capacity-continuations 3 --codex-transient-continuations 3`，且没有调用模型或创建
  research instance。

确定性 fake-Codex 回归分别覆盖纯 remote-compact、纯 reconnect、同一 private HOME/exact thread 的
`continue` 成功、transient continuation 耗尽后才进行 ordinary fresh retry、`cwd=repo_root`、参数
上下界、失败分类和 artifact metadata。capacity 原路径也继续通过，证明新增预算没有挤占或改变其
行为。

全量测试的两次早期命令问题不属于代码回归：从 parent cwd 调用时，pytest 因项目导入根不正确而
无法收集 `datasets`；改到 SimpleTES 根后只绑定 CPU191，又使 runtime fixture 声明的 helper CPU16
落在测试 cpuset 外。最终使用包含 fixture CPU 的 `7,15,16,191` cpuset 后，全部 `251` 项通过。

本阶段没有执行真实 provider canary：用户明确要求当前 eval workers 工作期间先实现、不要重启，
因此避免另起模型请求；真实失败形状由上述四份完整生产 JSONL 固定，exact resume 分支由确定性单测
覆盖。

## 5. 当前运行与性能边界

`2026-07-31T17:05:41+08:00` 复核时，原 launcher/main PID `2476168/2485367` 仍存活，日志为
`1 gen active / 0 queued`、`1 eval active / 2 queued`。main 的启动 argv 仍只有
`--codex-capacity-continuations 3`，没有新参数；Python 不会热加载 commit `6517bfc...`，因此本文
没有声称当前四次失败已被自动救回，也没有擅自停止或重启实例。

本阶段只修改 SimpleTES，Wolvrix、生成默认和 evaluator 性能规则均未变化；新增 candidate、accepted
SimTop 50k sample 和 walltime 数据均为 `0`。因此没有新的绝对/相对性能结论或默认优化决策，最终
性能仍以关闭 ASLR、空闲 CCD、双 order 的 SimTop 50k walltime 为准。
