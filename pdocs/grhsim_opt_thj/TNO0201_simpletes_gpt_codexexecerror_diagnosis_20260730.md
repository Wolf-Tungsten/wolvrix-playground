# SimpleTES GPT CodexExecError diagnosis

## 1. 诊断结论

[`TNO0200`](./TNO0200_simpletes_monotonic_resume_budget_extension_and_gpt_max_launch_20260729.md)
启动的 `gpt-5.6-sol/max` continuation 截至 `2026-07-30 00:44:59 +0800`
累计出现 `15` 次 `CodexExecError`。这些不是 evaluator、patch apply、schema repair 或
`5400 s` timeout；它们都是本地 `codex exec --json` 子进程以 status `1` 退出。

最重要的结论是：当前日志不足以把 15 次错误归为一个已确定的 provider 根因。SimpleTES
在 Codex 非零退出分支只保存有界 `stderr`，而实际包含 turn/provider failure 的
`events.jsonl` 位于临时 `CODEX_HOME`，退出后被删除。共同出现的 PATH-alias warning 只是
stderr 第一行，不是 15 次失败的根因证明。

运行不需要因本次诊断立即停止。最新持久化 checkpoint 已从启动时的 `15 valid` 推进到
`18 valid`，产生一个新 best；`00:44:37 +0800` scheduler 仍为
`1 gen active / 1 eval active / 2 eval queued`，launcher 尚未退出。

## 2. 数量与时间分布

启动 exact state 为 `64 attempts / 33 gen failures / 15 valid`。最新持久化状态
`db_state_001306` 为：

| 项目 | 绝对值 | 相对启动增量 |
| --- | ---: | ---: |
| generation attempts | `78` | `+14` |
| generation failures | `41` | `+8` |
| completed evaluations | `23` | `+3` |
| valid evaluations | `18` | `+3` |
| evaluation failures | `0` | `0` |
| best score | `1.0430050678250267` | previous `1.042845084360962` |

因此在该 checkpoint 覆盖的首批 14 个新 attempt 中，8 个 Codex 子进程失败、6 个产生了
可继续处理的 generation output，process-failure rate 为 `8/14 = 57.142857%`。该
checkpoint 后 launcher 又记录 7 次，因此当前日志合计 15 次；后 7 次尚未进入下一份
checkpoint，不能用旧 metadata 猜测当前完整 attempt/valid 计数。

错误形成两个明显 burst：启动后的前 8 次发生在 4 路 generation 阶段；后 7 次发生于
`00:21:20..00:33:36`，当时 backpressure 下只有 1 个 gen worker active。因此 4 路并发
会增加同时暴露面，但不是错误发生的必要条件，也不能作为单一根因。

## 3. 已见错误类型

15 条 launcher message 中：

- `12` 条除共同 PATH-alias warning 外没有保存其他诊断；
- `2` 条额外出现 Codex unified exec 创建进程失败：
  `Failed to create unified exec process: No such file or directory (os error 2)`；
- `1` 条额外出现安全策略确定性拒绝模型命令，因为命令包含 `rm -f`。

这些额外 stderr 事件也不能直接等同于最终 status `1` 根因。诊断时仍存活的会话同样有
PATH warning，并在两个 tool call 上出现 unified-exec `ENOENT`，但随后继续完成了近百个
repo command；普通 command exit `1/5` 也能由 agent 恢复。它们证明 code-mode/unified
exec 存在间歇性工具失败，却不能证明所有 non-zero turn 都由该错误终止。

当前可见的另一个放大因素是工具使用过宽：存活会话对 `/nfs/home/tanghaojin` 发起多个
无界 `find`，其中三个 bubblewrap 子进程已持续数分钟。它们会增加 NFS 与 session
latency，也提高长 turn 内遇到工具错误的机会，但仍不是对 15 个最终退出码的一一归因。

## 4. 为什么现有日志看不到真正根因

`simpletes/llm/codex_exec.py` 的非零退出路径执行顺序为：

1. `codex exec` stdout 写到 private home 下的 `events.jsonl`；stderr 写到
   `stderr.log`；
2. `process.returncode != 0` 时只调用 `_diagnostic_from_file(stderr_path)`；
3. 抛出 `CodexExecError`，离开临时 private-home context；
4. 临时目录连同 `events.jsonl`、可能存在的 final message 一并删除；
5. engine 将 error message 写入 `failure.json`，但新 8 条持久化记录的
   `artifact_paths=[]`、`error_details=[]`。

此前为 invalid JSON/repair 增加的完整响应持久化只在 Codex status `0`、读取到 response
之后生效，没有覆盖 subprocess non-zero 分支。因此当前不能从 disk 恢复那 15 个
`turn.failed/error` JSONL event，也不能负责任地判断隐藏部分究竟是 provider 401/429、
transport、server error、内部 Codex turn failure，还是别的错误。

## 5. 可排除项与相关因素

- `max` 配置不是系统性拒绝：capability gate、多个成功 generation、3 个新增 valid 和新
  best 均已通过；若 effort 无效，不会只间歇失败。
- auth/config 不是持续失效：同一 private provider endpoint 的其他请求正在成功；不过
  单次 401/429 仍因 JSONL 丢失而不能排除。
- 没有实际 `TimeoutError`、schema error 或 evaluator failure 记录。
- 不是 OS pid/file ceiling：诊断时 user cgroup 为 `3501/1384119` tasks，open-file limit
  `1048576`，系统 load `32` 位于 `384` 个 online CPU 上。
- 单个 native Codex 进程会建立约 `397` threads；4 worker 会放大开销，但资源上限证据不
  支持“线程耗尽导致本次 ENOENT”。
- 每个隔离 `CODEX_HOME` 位于 `/tmp/simpletes-codex-*`，Codex `0.145.0` 会明确拒绝在
  temporary dir 创建 PATH helper aliases；GPT-5.6 又自动启动
  `codex-code-mode-host`。这与 unified-exec `ENOENT` 有机制相关性，值得 A/B，但当前存活
  会话在同样 warning 下仍可工作，故尚不能写成已证实根因。

## 6. 影响与建议顺序

当前 `retry=0`，所以每个 Codex status `1` 都直接增加 generation failure 并消耗一个
proposal。它不会进入 evaluator，也不会污染 best patch；主要风险是提前耗尽
`192 proposals`，降低达到 `32 valid` 的概率。

建议后续按以下顺序修复；本次诊断尚未修改代码或重启运行：

1. 首先扩展 non-zero persistence：在 private home 清理前，将完整
   `events.jsonl`、stderr、可读 final output 与 metadata 以 `0600` 权限写入独立
   checkpoint-relative request 目录，记录 SHA-256、字节数、exit code，并做凭据脱敏。
2. launcher message 至少提取有界、脱敏的最后一个 `turn.failed/error` event，而不是只显示
   stderr 第一行；`failure.json.artifact_paths` 必须指向原始审计文件。
3. 用稳定、非 `/tmp` 的 private-home root 做受控 A/B，确认 PATH-helper warning 与
   code-mode/unified-exec `ENOENT` 是否消失。
4. 根因可分类后，再仅对 transport/provider/internal transient error 加 `1..2` 次有界退避
   retry；安全策略拒绝、schema/semantic failure 不应盲目重试。
5. 收紧 research prompt/只读文件范围，明确禁止从 `/nfs/home` 做无界 find，直接提供 exact
   checkpoint、文档和源码路径，以减少 NFS 扫描和 tool-call 数。

在完成第 1 项以前，不应仅凭共同 PATH warning、`ENOENT` 或历史上见过的 websocket 401
给 12 条 opaque failure 贴统一标签。
