# TNO0189 SimpleTES K3 Codex provider default and preflight

## 1. 阶段目标与结论

本阶段让 SimpleTES 的 Codex backend 支持活动 custom provider，并把 GrhSIM SimTop-50k 正式 launcher 的
operational default 从 `gpt-5.6-sol / OpenAI(MJY)` 切换为 `k3 / kimi`。reasoning effort 保持
`ultra`。

结论为 `PASS`：

- Codex credential override 不再写死 `model_providers.OpenAI`，而是安全绑定 TOML 中选中的 provider；
- GrhSIM launcher 默认使用 `~/.codex/config.kimi.toml`、`~/.codex/auth.kimi.json`、`k3/ultra`；
- 新增 `--preflight-only`，只做一次 ephemeral/read-only/schema-constrained Codex 请求并退出；
- focused `83/83`、SimpleTES full `145/145` 通过；
- 使用真实 Kimi 配置、真实 API key 和 production candidate schema 的 K3 preflight 通过；
- preflight 前后 checkpoint instance 数量与快照均未变化，没有启动新一轮 auto research。

本阶段的 SimpleTES commit 为：

`b73f399d703e162fb571e103a5df19a832c58029`。

## 2. 原问题与适配边界

原 `CodexExecClient` 已能检查任意 model/effort 与所选 TOML 是否精确一致，但认证 override 固定为：

- `model_providers.OpenAI.requires_openai_auth=false`；
- `model_providers.OpenAI.env_key="OPENAI_API_KEY"`。

Kimi 配置的活动 provider 是 `kimi`。backend 又有意不把 `auth.json` 复制进临时 `CODEX_HOME`，因此只改
launcher 的 model/path 会让 API key 仍绑定到错误 provider，不能构成完整 K3 支持。

本次改为：

1. 解析 `model_provider`，缺省时兼容既有 Codex 内建 `OpenAI`；
2. provider 名必须匹配 TOML bare-key 安全集合 `[A-Za-z0-9_-]+`；
3. custom provider 必须存在同名 `model_providers.<name>` table，否则 fail-close；
4. 用校验后的活动 provider 生成 `requires_openai_auth=false` 和 `env_key="OPENAI_API_KEY"` override；
5. override 继续作为 `create_subprocess_exec` 的独立参数传入，不经过 shell。

由此 Kimi 实际得到：

- `model_providers.kimi.requires_openai_auth=false`；
- `model_providers.kimi.env_key="OPENAI_API_KEY"`。

通用 `EngineConfig`/wizard 的 LiteLLM provider-neutral 默认没有改成机器本地 Kimi 路径，因为它们没有
GrhSIM 所需的 repo root 与 output schema。这里的“默认 K3”落在后续正式 GrhSIM SimpleTES 使用的
`datasets/grhsim/simtop_50k/launcher.py`；Codex backend 本身则已通用支持安全的 custom provider。

## 3. 实际 Kimi 配置身份

只审计并记录非敏感字段：

| 字段 | 值 |
| --- | --- |
| model | `k3` |
| model provider | `kimi` |
| reasoning effort | `ultra` |
| wire API | `responses` |
| Codex CLI | `0.145.0` |
| config SHA-256 | `45b47402163f54038c2c6a7b5746f37b1fc511a0e8b1052b034757ebb2d9bff9` |

`config.kimi.toml` 与 `auth.kimi.json` 均为普通、非 symlink 文件，权限均为 `0600`。auth 顶层只包含一个
非空 `OPENAI_API_KEY`。API key 的值未写入源码、文档、命令、日志或 checkpoint；本记录也不持久化 auth
文件哈希或 key 长度。

## 4. Credential 隔离保持不变

K3 适配没有通过复制 auth 文件来规避 provider 问题，仍保持原安全边界：

- 每次请求创建 mode `0700` 的临时 `CODEX_HOME`，只复制 mode `0600` 的 config；
- auth 只在 SimpleTES 父进程内解析，API key 仅注入父 Codex 进程的 `OPENAI_API_KEY`；
- auth 文件内容与 API key 不进入 Codex argv；正式 launcher argv 只含 auth 文件路径；
- model-generated tool shell 使用 `shell_environment_policy.inherit="none"`，只显式得到 PATH/HOME；
- Codex 使用 `--ephemeral`、`--sandbox read-only`、`network_access="disabled"`、空 MCP/notify；
- stderr 会按已知 secret 与敏感模式脱敏，模型响应若包含 auth secret 会被整体拒绝；
- preflight 完成后本次临时 home 已被 context manager 删除。

fake-Codex 单测同时验证了 Kimi override、OpenAI legacy fallback、auth 不复制、secret 不进 argv、无关父环境
变量不继承，以及 custom provider 缺 table/危险 provider 名的 fail-close。

## 5. Launcher 默认与 preflight-only

GrhSIM launcher 当前固定：

- model：`k3`；
- reasoning effort：`ultra`；
- config：`~/.codex/config.kimi.toml`；
- auth：`~/.codex/auth.kimi.json`。

`--dry-run` 仍只构造并打印未来命令，不执行子进程。新增的 `--preflight-only` 在调用 `build_command()` 之前
直接进入 `run_codex_preflight()`：它只验证 target repo、config/auth、production candidate schema，构造
`CodexExecClient` 并调用一次 `preflight()`。该路径不会：

- 加载或执行 GrhSIM evaluator；
- 构造 `SimpleTESEngine`；
- 应用 candidate patch；
- 创建 output/checkpoint/instance；
- 调度 generation 或 50k 仿真。

使用方式：

```bash
cd SimpleTES
source ../wolvrix-playground-gsim-calibrate-5/env.sh
./.venv/bin/python datasets/grhsim/simtop_50k/launcher.py --preflight-only
```

正常不带 `--dry-run`/`--preflight-only` 的 launcher 才会进入正式 research。本阶段没有执行该正常入口。

## 6. 离线与全量回归

| gate | 绝对结果 | 状态 |
| --- | ---: | --- |
| Python syntax | 4 个修改 Python/test 文件 | `PASS` |
| focused Codex + GrhSIM bench | `83/83` | `PASS` |
| SimpleTES full pytest | `145/145`，`17` 条既有 deprecation warnings | `PASS` |
| `git diff --check` | 无错误 | `PASS` |
| launcher dry-run identity | `k3/ultra/config.kimi/auth.kimi` | `PASS` |
| dry-run checkpoint snapshot | 前后相同 | `PASS` |
| 独立安全代码审计 | 无阻断项 | `PASS` |

full pytest 的 17 条 warning 全部来自既有 `datetime.utcnow()` deprecation，不是本次新增失败。

提交后的关键文件 SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| `simpletes/llm/codex_exec.py` | `8c6adb6294e3e8f022e0a1da64b630a458c29024034aa3b546429a30ebbdf0f5` |
| GrhSIM `launcher.py` | `8f84a040c5e09fe2a1b46efe5d352f3a599202b181293c85810bf55de2771976` |
| production candidate schema | `c5654f3f008baa2c14e973bdbae2fa33ade3fac295bb9710694462ba051b72c2` |
| Codex backend tests | `552234b1c651687c4473b88dae2421f05c6650aed01147e3d00571b57544c2e2` |
| GrhSIM bench tests | `366f44a6dd3acd5a2463fb67488e9becc525347c8b63660df91e2be9ebdaf8fc` |

## 7. 真实 K3 production-schema preflight

在上述测试通过后，实际执行一次：

`launcher.py --preflight-only --llm-timeout 600`

真实调用使用：

- Kimi `k3/ultra` config；
- `auth.kimi.json` 中的真实 API key；
- 当前 GrhSIM target repo，read-only sandbox；
- production `candidate.schema.json`；
- ephemeral Codex session。

输出为 `Codex preflight passed: model=k3, effort=ultra`，exit code `0`。这同时验证了：

1. Kimi endpoint/auth/provider routing 可用；
2. Codex-compatible `responses` wire API 可用；
3. K3 接受并返回符合 production flat JSON schema 的 structured output；
4. response secret scan 与本地 JSON Schema validation 通过。

preflight 前后 `checkpoints/grhsim_simtop_50k` 的 instance 数量都为 `6`，路径/mtime 排序快照 SHA-256 均为：

`08b28e8d0c2aff470a112e76e88b45124b3e66ac0ecd6d6b401411b9fc4bfbf9`。

结束后没有新的 `main.py`/GrhSIM launcher research 进程，也没有本次请求遗留的临时 Codex home。

## 8. 阶段裁决

K3 已成为下一次 GrhSIM SimpleTES 正式 launcher 的默认模型，并已完成真实 provider/auth/schema preflight。
当前代码和 checkpoint 均处于可继续状态，但本阶段明确停在 preflight：没有创建新 instance，没有评估 initial
control，也没有启动下一轮 auto research。后续只有在收到明确指示后才运行不带
`--dry-run`/`--preflight-only` 的正式 launcher。
