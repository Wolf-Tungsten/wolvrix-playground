# TNO0197 SimpleTES repair raw-response persistence and JSON diagnostics

## 1. 目标与边界

本记录承接
[`TNO0196`](./TNO0196_simpletes_k3_parallel_generation_subagents_and_context_catalog_20260728.md)，
修复 K3 structured-response repair 的可观测性问题：下一次 retry 必须看到上一轮完整的
final response 及精确 JSON 错误位置；即使连续 3 次 repair 全部失败，人工也必须能从
checkpoint 旁恢复每一轮的响应，而不能依赖随后被删除的临时 `CODEX_HOME`。

本阶段只修改 SimpleTES LLM/engine 诊断路径和测试，不修改 Wolvrix、生成 C++、仿真语义、
默认优化或 GrhSIM evaluator。因此没有新的 SimTop 50k 候选，也没有 walltime 性能结论；
已有性能与默认决策保持不变。

## 2. 变更前根因与绝对证据

旧实现虽在当前 Python 调用栈中持有完整 `response_text`，但在构造下一次 repair prompt 时
会调用 `_safe_diagnostic()`：

1. `" ".join(text.strip().split())` 把所有换行和空白折成单行；
2. `compact[-2000:]` 只留下最后 `2000` 个字符；
3. `JSONDecodeError` 被压成固定文本 `Codex returned invalid JSON`，丢失
   `msg/lineno/colno/pos`；
4. `_invoke_once()` 返回后，`/tmp/simpletes-codex-*` 被删除；
5. repair 成功时 tracked output 仅留 bounded failure summary；3 次耗尽时 engine 只计数和
   打日志，既不保留响应，也不写 generation failure record。

运行中旧实例在 `2026-07-28 15:20:10 +08:00` 给出了直接证据：

```text
Error:    InvalidJSON
Message:  Codex returned invalid JSON; structured response exhausted 3 attempt(s)
failure_summaries:
  attempt 1: InvalidJSON: Codex returned invalid JSON
  attempt 2: InvalidJSON: Codex returned invalid JSON
  attempt 3: InvalidJSON: Codex returned invalid JSON
```

这证明 retry session 实际只能看到压平后的末尾 `2000` 字符，事后也无法恢复完整 JSON；
并不是本进程从未拿到原响应，而是传递和留存路径把它丢掉了。

## 3. 实现与提交

SimpleTES commit：

```text
c4e4a05da13f738316709df5d1c9d196c306576f
fix: preserve Codex repair response diagnostics
```

### 3.1 完整 repair 输入和精确 JSON 定位

`InvalidJSON` 现在保留并同时传入 repair prompt/metadata：

- parser message；
- 1-based line；
- 1-based column；
- 0-based Python character offset；
- 0-based UTF-8 byte offset；
- response 总字符数和 UTF-8 总字节数。

repair prompt 不再调用会压平/截尾的 `_safe_diagnostic()` 处理 response。它在现有
`4 MiB` final-output 硬上限内传入完整、保持换行和空白的上一轮 final response，并用明确
的 begin/end marker 把响应标为 data。若出现 credential-shaped span，只做保持字符数不变
的 `*` 掩码；因此 line/column/character offset 仍可直接映射。

### 3.2 durable artifact 格式

当 `codex_exec + --save-llm-io` 启用且一次 response 被拒绝时，在启动下一次 Codex session
前立即写入：

```text
<instance checkpoint dir>/llm_attempts/request-<128-bit random id>/
  attempt-01.response.txt
  attempt-01.metadata.json
```

- `response.txt` 直接保存完整响应文本，换行不是 JSON string escape，parser 行列可直接
  对照文件；
- `metadata.json` 保存 error type、精确位置、gen/chain-aware instance label、prompt
  SHA-256、原/存储长度、存储文件名、redaction 状态和内容 SHA-256；
- `llm_attempts` 与 request 目录权限为 `0700`，两个文件为 `0600`；
- request 使用独立 128-bit random ID，不使用全局 counter，4 workers 即使具有相同
  instance label 也不会互相覆盖；
- 文件由同目录临时文件 `fsync` 后原子 rename，写盘整体经 `asyncio.to_thread()` 移出
  event loop，NFS 慢 `fsync` 不会冻结 scheduler 和其余 generation workers；
- artifact 引用保存为相对 instance checkpoint 的路径，checkpoint 搬移或 resume 后仍可
  解析。

第一次即成功不会创建 `llm_attempts`。repair 成功后，相对 metadata path 进入 node 的
tracked raw output；repair 耗尽或 audit 写失败时，路径经 `LLMCallError.artifact_paths`
进入 `failure.json`。若 response 已提交但 metadata 写失败，异常仍携带已完成
`response.txt` 的相对路径，不留下不可定位的孤儿响应。

### 3.3 凭据与脱敏边界

- 命中实际 auth/proxy secret 时继续抛 `SensitiveOutput`，只调用 1 次，不 repair、不落
  artifact；
- 普通 credential-shaped 文本保留完整结构但做等字符数掩码；
- `redaction_count > 0` 时不保存 raw-response SHA-256，避免给低熵 token/password 提供
  离线猜测 oracle，只保存脱敏后文本 SHA-256；
- metadata 明确区分 `stored_response_complete` 和 `raw_response_persisted`；
- 非 ASCII span 脱敏可能改变 UTF-8 字节宽度，因此同时记录 raw 与 stored byte offset，
  line/column/character offset 保持一致。

### 3.4 任务关联与 resume

Generator 传给 backend 的 request label 现在包含：

```text
<instance>-gen<gen_id>-chain<chain_idx>-<batch index>
```

metadata 另存原始 prompt SHA-256。Engine 在构造 Generator 之前先解析真实 instance
checkpoint directory；fresh run 写入新 instance，resume 则继续写入旧 instance 根，绝不
写入会轮换删除的 `db_state_*`。Codex 异常无 artifact 时也会写一条 bounded failure
record；该行为限定在 `codex_exec`，不扩大其他 provider 的错误持久化范围。

## 4. 功能、安全和并发验证

### 4.1 完整回归

```text
Codex/engine focused: 60 passed, 0 warnings, 7.88 s
SimpleTES full:       225 passed, 24 warnings, 8.32 s
python compileall:    PASS
git diff --check:     PASS
```

full-suite 的 `24` 条 warning 全部来自已有 `simpletes/node.py` 的
`datetime.utcnow()` deprecation，未新增测试失败或 warning。

新增/扩展用例覆盖：

- 大于旧 `2000` 字符窗口的多行 Unicode malformed JSON 原样进入下一次 repair；
- parser `msg/line/column/character/UTF-8 byte` 与 Python `json.loads()` 完全相等；
- schema/local-semantic/response-validator rejection 均保留；
- 3 次耗尽后 `3` 份 response/metadata 顺序完整；
- 4 个并发逻辑请求、每个 3 次失败共 `12` 个 artifact 路径全部唯一；
- ephemeral HOME 全部删除而 durable artifact 仍存在；
- auth material 不落盘，credential-shaped 与非 ASCII 内容正确脱敏和定位；
- symlink root fail-close、metadata 部分失败仍返回 response path；
- artifact `fsync` 确认运行在 event-loop 线程之外；
- Engine 把 artifact、JSON details、gen/chain/shared-construction context 写进 failure record。

### 4.2 独立 artifact 实物 gate

受控 malformed response 的绝对输入为 `2702 characters / 2706 UTF-8 bytes`，错误位置为：

```text
Expecting ',' delimiter
line=5
column=3
character_offset=2678
raw_utf8_byte_offset=2682
stored_utf8_byte_offset=2682
```

实物结果：

| artifact | mode | size | SHA-256 |
| --- | ---: | ---: | --- |
| `attempt-01.response.txt` | `0600` | `2706 B` | `5ff103e0d2830bb0651e9aaea26351a56064add0bb41d4355697d77dc8236652` |
| `attempt-01.metadata.json` | `0600` | `1360 B` | `6a4b981407639c8d5e5d90dbb6e661c451b2c7da699c03d125789b4e01b031ec` |
| `llm_attempts/` | `0700` | directory | N/A |
| `request-261b.../` | `0700` | directory | N/A |

metadata 中 `raw_response_sha256 == stored_response_sha256 == response.txt SHA-256`，证明本例
无脱敏时落盘文本与原 final response 逐字节相同。该 gate 的临时证据根为：

```text
/tmp/simpletes-repair-artifact-gate.POCcn3
```

## 5. 对正在运行实例和后续 research 的影响

未向当前 supervisor/launcher/main/Codex 发送信号，也未停止或重启 research。`16:04:33`
快照仍为：

```text
main PID: 1045392
gen workers: 4 active / 0 queued
eval workers: 0 active / 0 queued
```

当前 main 在 `12:42:41` 启动，进程内仍是提交 `50de044` 时加载的旧 Python 类；源码提交
不会热替换该进程，因此本轮后续 retry 仍没有新 artifact 能力。这是有意保持运行实例不受
干扰的结果，不是修复未生效。下一次正常启动或 resume 会加载 `c4e4a05`，并在同一
instance checkpoint 根下创建 `llm_attempts`，现有 launcher/preflight、4 workers、K3
1M catalog 和 3-subagent 配置均无需改变，可继续 auto research。

空间上，每个 rejected final response 仍受 `4 MiB` 上限约束，一个逻辑请求最多 3 次，
最坏约 `12 MiB + metadata`；artifact 为审计证据，当前不自动清理。长轮结束后应按 run
归档或显式清理，不应在 research 进行中删除。

