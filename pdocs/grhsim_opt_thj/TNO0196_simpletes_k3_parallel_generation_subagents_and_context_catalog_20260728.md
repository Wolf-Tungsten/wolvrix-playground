# SimpleTES K3 parallel generation, subagents, and 1M catalog

## 1. 目标与承接状态

本记录承接
[`TNO0195`](./TNO0195_simpletes_k3_context_window_correction_and_resume_20260728.md)，
处理 K3 长轮 research 暴露出的三个运行框架问题：

1. 4 条 RPUCG chain 只有 1 个 generation worker，长期表现为
   `1 active / 3 queued`；
2. K3 单次 generation 的 `5400 s` timeout 已实际触发，和 K3 的响应速度不匹配；
3. `config.kimi.toml` 虽然写有 `model_context_window = 1000000`，API 后台却仍在
   约 256K 内压缩，同时当前 K3 没有真正得到可用的 spawned-agent 工具配置。

本阶段只修改 SimpleTES 运行框架和 K3 bench，不修改 Wolvrix、生成代码或仿真语义，
因此没有新增 SimTop 性能候选。已有最佳性能仅作为 resume 状态保留，不据本阶段改动
作新的默认性能结论。

## 2. 变更前的绝对状态

### 2.1 generation 并发与 timeout

变更前正式 main argv 的关键值为：

- RPUCG chains：`4`；
- generation concurrency：`1`；
- evaluation concurrency：`1`；
- generation timeout：`5400.0 s`；
- subagent limit：未传入；
- model catalog：未传入。

日志持续报告：

```text
gen workers: 1 active / 3 queued, eval workers: 0 active / 0 queued
```

`2026-07-28 11:25:43 +08:00` 已有一条 generation 达到 `5400 s` 后产生
`TimeoutError`。随后一条 generation 从同一时刻继续运行，到本阶段停机前仍未返回 final
candidate。

### 2.2 1M 配置为何没有生效

当前使用 `codex-cli 0.145.0`。该版本 bundled model catalog 中没有 `k3`，events/stderr
明确出现：

```text
Model metadata for k3 not found. Defaulting to fallback metadata
```

fallback 的绝对上限为 `272000` tokens。Codex 会先用 model metadata 的
`max_context_window` 钳制用户配置，再采用 `95%` effective window，因此原实际值为：

```text
resolved context = min(1000000, 272000) = 272000
effective context = 272000 * 0.95 = 258400
auto compact = 272000 * 0.90 = 244800
```

这和 API 后台观察到在约 256K 以内压缩一致。旧 trace 还出现过 multiple-compaction
warning。仅在 TOML 中继续增大 `model_context_window` 或 auto-compact 值不能越过 model
metadata 的 `272000` 上限。

上游依据为 Codex 0.145.0 的
[`model_info.rs`](https://github.com/openai/codex/blob/rust-v0.145.0/codex-rs/models-manager/src/model_info.rs)
和
[`openai_models.rs`](https://github.com/openai/codex/blob/rust-v0.145.0/codex-rs/protocol/src/openai_models.rs)；
Kimi 官方配置说明给出的 K3 最大上下文为 `1048576`。

## 3. 实现

SimpleTES commit：

```text
50de0447a9eafdf06a087383cf654fbd77dbacd6
Enable parallel K3 research with 1M context
```

### 3.1 K3 model catalog 与私有复制

新增完整的 `k3_model_catalog.json`，以同一 Codex 0.145.0 bundled 完整 ModelInfo
为 schema/template，清除不适用于 K3 的 opaque/model-specific 字段，并固定：

| 字段 | 绝对值 |
| --- | ---: |
| `slug` | `k3` |
| `context_window` | `1000000` |
| `max_context_window` | `1048576` |
| `auto_compact_token_limit` | `900000` |
| `multi_agent_version` | `v1` |
| `comp_hash` | `null` |
| catalog size | `45418 B` |
| catalog SHA-256 | `ff608bc485e47e16747a3ddf0db9ba96c486796baa630478e1384d2f76bb37a7` |

由此当前 K3 的 resolved/effective/compact 口径为：

```text
resolved context = min(1000000, 1048576) = 1000000
effective context = 1000000 * 0.95 = 950000
auto compact = min(900000, 1000000 * 0.90) = 900000
```

`codex_exec` 新增可选 model-catalog 路径；每个 generation 都把 catalog 复制到自己的
private `CODEX_HOME`，权限固定为 `0600`，再以 private absolute path 覆盖
`model_catalog_json`。它不依赖用户 HOME 内的相对路径，也不让 4 个 worker 共享可变文件。

### 3.2 4 路 generation 与 3 小时 timeout

GrhSIM K3 launcher 默认改为：

- generation workers：`4`，与 `4` 条 chain 对齐；
- evaluation workers：仍为 `1`，继续串行使用 evaluator slot 和 fixed-ASLR runtime；
- generation timeout：`10800 s`；
- max proposals / valid target：正式 continuation 仍为 `64 / 32`。

因此只有模型研究并行，build/function/50k evaluator 仍串行，不改变性能测试协议。

### 3.3 subagent 严格限定为 K3 专属

K3 启动时显式使用：

```text
--enable multi_agent
--disable multi_agent_v2
-c agents.enabled=true
-c agents.max_concurrent_threads_per_session=3
```

在 Codex 0.145.0 V1 实现中，该计数只统计 spawned threads，不包含 root K3 线程，故
绝对上限确为同时打开 `3` 个 subagent。K3 instruction suffix 只说明“可自由决定是否、
何时以及把什么工作委派给最多 3 个 subagent”，不指定 CPP/perf/doc 等角色，不强制
必须 spawn，也不附加“subagent 不得继续委派”等额外限制；实际嵌套深度沿用 Codex
K3 默认。

为避免干扰 GPT-5.6 Sol Ultra：

- base `instruction.txt` 不包含任何 subagent 文本；
- K3-only `instruction.k3.txt` 只在 `MODEL == "k3"` 时追加；
- agent cap、V1 feature flags 和 K3 catalog 同样只在 K3 launcher 分支传入；
- 通用 `codex_exec` 的默认值仍为 `None`；未传参时不会改动 Codex 原生 delegation。

单元测试还把 launcher 临时切到 `gpt-5.6-sol`，确认命令中不存在 instruction suffix、
agent cap 和 K3 catalog 三项。因此 Ultra 继续使用自身自动 subagent 行为。

### 3.4 collaboration 审计

Codex JSONL trace 新增去重后的：

- `collaboration_tool_call_count`；
- `collaboration_tool_call_counts`，按 `spawn_agent/send_input/wait/close_agent`
  分类。

同一 item 的 started/completed 按 ID 只计一次；审计不保存 subagent prompt、thread ID、
agent message 或 `agents_states` 内容。只要实际发生 collaboration，即使结构化响应首次
成功，tracked raw output 也保留这一份 bounded audit envelope，便于后续确认 K3 是否
自主使用了 subagent。

## 4. 静态、单测与真实 K3 gate

### 4.1 catalog 离线解析

同一 `codex-cli 0.145.0` 执行 `codex debug models` 后确认：

- catalog 只有 `1` 个模型且 slug 为 `k3`；
- `1000000 / 1048576 / 900000` 三个窗口值逐项相等；
- `multi_agent_version = v1`、`comp_hash = null`；
- 不再落入 unknown-model fallback。

### 4.2 测试绝对结果

```text
focused: 144 passed, 14 warnings, 12.36 s
full:    213 passed, 24 warnings, 7.02 s
git diff --check: PASS
python compileall: PASS
```

warnings 均为已有 `datetime.utcnow()` deprecation warning，无新增失败。

### 4.3 真实 K3 capability preflight

独立 `--preflight-only` 通过：

```text
model=k3
effort=ultra
repo_tool_calls=1
response_chars=632
response_sha256=9608b97bb51cd0c0c94c9b6d122c2aa1f1747a27e54a0a570168b5446fe9fce2
```

正式重启的 preflight 从 launcher PID 启动到 main PID 出现约 `36 s`，并经过新增的
fallback-warning fail-close 检查后才进入 research。

## 5. 唯一一次优雅停机与 checkpoint

`2026-07-28 12:40:56 +08:00` 只向旧 SimpleTES main PID `3775089` 发送一次
`SIGINT`。scheduler 在 `12:41:18` 取消 active generation、停止 workers 并写出：

```text
/nfs/home/tanghaojin/wolvrix-SimpleTES-workspace-5/SimpleTES/checkpoints/
grhsim_simtop_50k/k3_rwa_grounded_fresh_20260728_032742/2026-07-28/
instance-7291c6c2/db_state_124118
```

旧 supervisor/launcher/main/Codex 全部退出，旧 continuation root 的
`launcher.exit = 0`。最终 checkpoint 的绝对状态为：

| 项目 | 绝对值 |
| --- | ---: |
| completed evaluations | `4` |
| valid evaluations | `2` |
| generation attempts | `12` |
| generation failures | `1` |
| generation cancellations | `2` |
| evaluation failures | `0` |
| best score | `1.0106070419494428` |
| best program SHA-256 | `4ad5d1d5dfd97e987f6aec3c5151bc0040f7289d4ae2d74cabc98d0b0fc7177d` |

best 节点保留的 SimTop 50k walltime 绝对值为：

```text
control mean   = 53831.5 ms
candidate mean = 53266.5 ms
improvement    = 565.0 ms / 1.0495713476310338%
```

这是停机前已有候选，不是本阶段运行框架修改产生的新性能结果。

## 6. 精确恢复后的运行态验证

从上述 `db_state_124118` 恢复到：

```text
/nfs/home/tanghaojin/wolvrix-SimpleTES-workspace-5/SimpleTES/checkpoints/
grhsim_simtop_50k/k3_rwa_parallel4_subagents3_ctx1m_resume_20260728_124203
```

启动进程：

| 角色 | PID |
| --- | ---: |
| supervisor | `1040779` |
| launcher | `1040955` |
| main | `1045392` |
| four root K3 Codex processes | `1046962 / 1046964 / 1046965 / 1046966` |

main argv 已直接确认：

```text
--gen-concurrency 4
--eval-concurrency 1
--timeout 10800.0
--instruction-suffix .../instruction.k3.txt
--codex-max-agent-threads 3
--codex-model-catalog .../k3_model_catalog.json
--resume .../db_state_124118
```

`12:43:01` 启动 workers；从 `12:43:31` 起连续心跳均为：

```text
gen workers: 4 active / 0 queued, eval workers: 0 active / 0 queued
```

四个 private home 均有 `45418 B`、mode `0600`、与仓库 SHA 完全相同的 catalog；四份
private config 均为 `model_context_window = 1000000`。四条 events/stderr 在本记录截止点
均无 `Model metadata for k3 not found` 或 fallback warning。

截止本记录时，4 个 K3 root 仍在自主研究，collaboration trace 的绝对调用数为
`0 / 0 / 0 / 0`。这不是 capability 失败：tool/上限已由实际 argv 启用，而 prompt 明确把
是否 spawn 交给 K3；后续若它自主委派，新增 trace 会持久化分类计数。尚未产生新
candidate、build、50k walltime 或性能结论，也尚未用一次超过 256K 的真实对话直接观察
900K compaction 点；当前闭合的是 catalog/config/runtime 解析链，而不是长上下文耗尽实验。

## 7. 阶段结论

1. `1 active / 3 queued` 已消除，当前为稳定 `4 active / 0 queued`；evaluator 仍串行。
2. K3 generation timeout 已从 `5400 s` 翻倍到 `10800 s`。
3. 原先约 256K 压缩的根因不是 TOML 未复制，而是 unknown-K3 的 `272000` metadata
   上限；private K3 catalog 已消除 fallback，解析口径变为 effective `950000`、compact
   `900000`。
4. K3 可自由使用最多 3 个 spawned subagent；没有固定角色。GPT-5.6 Sol Ultra 的
   prompt、agent flags 和 catalog 均不受影响。
5. auto research 已从最终 checkpoint 正常继续，当前不需要再启动第二个实例。

## 8. 增量更新：K3 已自主用满 3-subagent 上限

`2026-07-28 12:49 +08:00` 再次只读采样四条 root K3 events。相对于第 6 节较早的
`0 / 0 / 0 / 0` 截止点，当前去重后的 collaboration 结果变为：

| private generation | `spawn_agent` calls | started records | completed records |
| --- | ---: | ---: | ---: |
| `simpletes-codex-hpu0ek0n` | `3` | `3` | `3` |
| `simpletes-codex-7zus2nb6` | `0` | `0` | `0` |
| `simpletes-codex-51_wsry1` | `0` | `0` | `0` |
| `simpletes-codex-1ymyjjm3` | `3` | `3` | `3` |

两个 root 各自主 spawn `3` 个 subagent，另两个 root 尚未 spawn；没有统一的强制角色
或强制调用模式。这同时验证了 collaboration tool 对 K3 实际可用、V1 上限确实允许
3 个 spawned threads，以及“让 K3 自由发挥”而非“每次固定开 agent”的配置已生效。
此时 scheduler 仍为 `4 active / 0 queued`，未见 fallback、HTTP 429 或 rate-limit
warning，尚无新 candidate/50k 结果。
