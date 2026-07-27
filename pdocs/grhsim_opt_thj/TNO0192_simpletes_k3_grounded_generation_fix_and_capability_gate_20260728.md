# TNO0192 SimpleTES K3 grounded generation fix and capability gate

## 1. 阶段结论

本阶段修复 [TNO0191](./TNO0191_simpletes_k3_broken_run_diagnosis_and_graceful_stop_20260728.md)
暴露的 K3 生成问题，并完成真实 Kimi `k3/ultra` 能力验证。SimpleTES 修复提交为：

```text
88abf71ee466dceeca7e3abe4537af73820f47b0
```

结论如下：

- 旧轮次的 `27/27` 个持久化 K3 output 都是 placeholder/空候选，根因不在 evaluator 或 SimTop；
- Codex `0.145.0` 的 Responses 请求使用 `tool_choice=auto`，旧 prompt 又同时要求 JSON 与
  fenced EVOLVE marker。GPT/provider 组合能够容忍这两个缺口，K3/Kimi 组合会过早结束；
- 新 backend 对 K3 使用 `local-json + required-first`，第一条请求必须进入 repo tool loop；同一原始请求的
  transport retry 继续保持 `required`，真正的 tool-output follow-up 才回到 `auto`；
- 正式 generation 仍使用完整性能研究任务；启动前 capability gate 已拆成确定性的单文件读取、fresh nonce
  attestation 和 exact smoke patch，不再把一次开放式性能研究塞进 preflight；
- 新真实 capability gate 约 `36 s` 通过，返回 `632 chars`，完成 `1` 次 repo tool call，fresh digest、
  JSON shape、exact patch 和 pinned-tree clean apply 全部通过；
- 本阶段没有启动新的正式 auto research，没有修改 Wolvrix，也没有新的 SimTop 50k walltime 或默认决策。

## 2. GPT 与 K3 历史行为对照

对比使用 post-RWA K3 broken run 与上一轮有效 GPT continuation 的保存结果：

| 项目 | GPT `gpt-5.6-sol/ultra` | Kimi `k3/ultra` broken run |
| --- | ---: | ---: |
| scheduled attempts | `44` | `43` |
| generation failures | `5` | `12` |
| persisted outputs | `36` | `27` |
| evaluator-valid persisted outputs | `32/36 = 88.888889%` | `0/27 = 0%` |
| inner JSON bytes/chars mean | `18,472.2` | `178.5185` |
| inner JSON median | `17,811` | `181` |
| inner JSON range | `4,651..41,439` | `138..201` |
| non-empty patch | `36/36` | `21/27`，但全是 literal placeholder |
| unique patch bodies | `34` | `2`（placeholder/empty） |
| output-contract generation failures | `0` | `11` |

GPT 的 5 个 generation failure 都来自 timeout/capacity/503/stream transport；K3 除 1 个 cleanup race 外，
另有 11 个缺字段、非 object 或非法 control 的 contract failure。K3 保存的代表正文为：

```json
{"candidate_mode":"default-path","enable_options":[],"evidence":["placeholder"],"hypothesis":"placeholder","patch":"placeholder","schema_version":2}
```

另一个变体只把 hypothesis 改成 `placeholder - researching repository first`，patch 仍为空。

两条历史路径都由 Codex CLI 发 Responses 请求，且旧 backend 都依赖 `--output-schema`。Codex
`rust-v0.145.0` 源码把 Responses `tool_choice` 固定为 `auto`：

- <https://github.com/openai/codex/blob/rust-v0.145.0/codex-rs/core/src/client.rs#L850-L856>

因此，“GPT 之前可以运行”只能说明当时完整的 GPT model + provider + provider-structured output + prompt
组合会主动使用工具并遵守 schema；不能据此推断 K3 的内部架构，也不能把差异单独归责于 Kimi gateway。
Codex-compatible/Responses-compatible 表示 wire protocol 可互通，不保证在 `auto` tool choice、矛盾 prompt 和
structured-output 约束下有相同策略。

## 3. 诊断调用与时间边界

本阶段依次闭合以下真实/离线检查：

1. 旧 K3 preflight 被确认只要求 harmless placeholder，因此通过仅证明 transport 和 flat schema；
2. 旧正式轮次的 27 个保存 output 全量核对，确认没有遗漏真实 diff；
3. minimal Kimi Responses 请求显式使用 `tool_choice=required` 时返回 HTTP 200 function call，证明 endpoint
   具备基本 required-tool 能力；
4. 完整 GrhSIM 研究 prompt 加 required-first 后，K3 不再立即返回 placeholder，而是进入多轮 repo tool loop；
   该诊断使用修改前 backend，在 `1,800 s` 外部上限处干净退出。它没有 final response，旧实现又只把 JSONL
   保存在进程内存，因此不能事后恢复中间正文；私有 CODEX_HOME 已清理，无残留进程；
5. 将 capability gate 缩成确定性任务后，fresh K3 在约 `36 s` 内通过：

```text
repo_tool_calls=1
response_chars=632
response_sha256=988127b4f2901ca4a7bb027bfb774ca0a95a3e5566179398b87a4d816ce22287
```

该 response 的 mode、hypothesis 与 include-order patch 都要求逐字节匹配；唯一不预先给出的值是
`SHA256(ASCII(fresh_nonce) || NUL || pinned_blob)`。因此 pass 同时证明模型实际读取 immutable blob、返回正确
JSON，并能复制一个对 pinned Wolvrix clean apply 的 unified diff。smoke diff 只用于能力验证，不进入 evaluator、
不写 checkpoint、不保留为优化。

Capability gate 现在独立使用 `600 s` 上限和 `0` repair；正式 generation 仍可显式使用 `5,400 s`，因为真实
性能研究需要读代码、文档、generated C++ 和 perf 证据。两种时间口径不再混用。

## 4. 实现内容

### 4.1 生成契约

- Codex backend 的 generation prompt 只允许一个 JSON object，不再同时要求 Markdown fence/EVOLVE marker；
- backend 在通过 provider/local validation 后再补 extraction marker；
- provider schema 保持 Kimi 可接受的 flat shape；新 local schema 负责 non-empty/non-placeholder、cardinality、
  mode/options 关系、patch size 和末尾换行；
- schema/semantic failure 最多进行 2 次有界 repair，正式每次 repair 都重新要求一次 repo tool；
- GrhSIM 正式 launcher 固定 `local-json + required-first`，没有复用 targeted-direct 或任何 Wolvrix 优化开关。

### 4.2 required-first compatibility proxy

- 只监听随机 IPv4 loopback port，只接受 authenticated `POST /v1/responses`；
- upstream URL 必须是无 userinfo/query/fragment 的 HTTPS URL；禁用 redirect、environment proxy 和 request
  compression；真实 upstream key 只保留在 proxy，Codex 每个 attempt 得到不同的临时 loopback credential；
- 只改写第一条 accepted request；保存的只是 raw body SHA-256。相同 body 的 provider/stream retry 仍为
  `required`，不同 body 的 tool-output follow-up 保持 Codex 原始 `auto`；
- 转发必要的 Codex turn/session/request headers，解码 compressed response 后移除 `Content-Encoding`，不转发
  cookie；request/response 分别受 `16 MiB/64 MiB` 上限约束；
- bind/client/handler/stream failure 都做资源清理并返回固定脱敏错误，不把 provider exception、header 或 body
  写入日志。

### 4.3 Codex 进程与审计边界

- 每个 attempt 使用 `0700` 私有 CODEX_HOME；config、stdout JSONL、stderr 均为 `0600`；
- stdout/stderr 改为文件承接，不再由 `communicate()` 无界保存在 Python 内存；audit 只读最多 `8 MiB`
  stdout prefix 和 `1 MiB` stderr tail，final response 上限 `4 MiB`；
- timeout 会记录有界、secret-scrubbed 的 event/tool type/count trace，再 kill 整个 process group；
- cleanup 有有界 retry，`killpg` 失败会 fallback 到 direct child kill；
- checkpoint 新增 `reasoning_effort`、Codex output/tool mode、config/repo 和两层 schema path 等非敏感 provenance；
  auth path、API key 和 policy key 明确不落盘，旧 checkpoint 缺少新字段仍可加载。

### 4.4 Preflight Git 与启动 TOCTOU

- expected attestation 在 launcher 侧从 exact parent gitlink、Wolvrix commit 和 tracked blob 计算；
- model patch 用 temporary index 检查时，同时设置 temporary `GIT_OBJECT_DIRECTORY`，真实 object store 只作为
  alternate 读取；测试确认真实 objects、refs、index、worktree 均不变；
- 所有 launcher Git 检查先清除外部 `GIT_*` routing，再禁用 system/global config 和 optional locks；
- normal launch 在 preflight 前后比较 SimpleTES Python/task/schema、`main.py`、目标 `env.sh`、config/auth、exact
  init seed，以及 resume 时 exact state 的内容 digest；preflight 期间任何输入变化都会拒绝 spawn research。

## 5. 回归与阶段裁决

提交前回归：

```text
pytest: 210 passed, 24 warnings
compileall: PASS
git diff --check: PASS
```

24 个 warning 都是既有 `datetime.utcnow()` deprecation，不是本阶段新增失败。真实 K3 deterministic gate 为
PASS，退出后无 launcher/Codex/proxy 残留进程，也没有创建 checkpoint。

本阶段只修复 SimpleTES 和 GrhSIM bench；parent 仍 pin `d31118bea0feb563ad09476e1419f0f15aaf574f`，Wolvrix
仍 pin `16a9f493687a21a5428f1e1327a69834ea60c9f5`。没有任何 SimTop 50k 候选 walltime，因此不产生性能采用、
默认开关或 Wolvrix 源码结论。新的正式 fresh research launch 另行记录。
