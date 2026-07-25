# TNO0180 SimpleTES v2 provider schema fix and long research launch

## 1. 状态与边界

在用户明确要求继续 auto research 后，本阶段从
[TNO0179](./TNO0179_simpletes_v2_pinned_native_control_canary_and_continuation_ready_20260725.md)
已经验证的 schema-v2 native control fresh 启动新的长期 SimpleTES run。没有 resume 或 seed 任何历史
schema-v1 checkpoint；旧 `continuation_20260723_194100` 仍保持原状。

第一次启动在 LLM preflight 阶段暴露 provider-facing JSON Schema 兼容问题，研究实例没有建立；修复
并通过真实 preflight、全量测试和独立提交后，第二次启动已经进入 initial control evaluator。本文记录
的是启动状态，不是阶段性能结论：当前没有 generated candidate、accepted 50k walltime、score 或默认
决策。

## 2. 启动前实例审计

启动前同时检查 SimpleTES scheduler/launcher/evaluator、workspace GrhSIM emu、checkpoint 与 trusted
runtime slot：

- 没有仍在运行的本 workspace auto-research 或 evaluator；
- 最新旧实例仍是 `continuation_20260723_194100/.../instance-50c610a6`，其 checkpoint 为
  `schema_version=1` 且 pin 不等于当前 v2 contract，不能 resume 或作为 v2 seed；
- `/tmp/simpletes-grhsim-native-control.341s20` 是已经结束的 TNO0179 direct control canary，不是
  research instance；
- 当前没有其它 v2 instance，因此使用默认单 slot 不会与另一个本任务 evaluator 竞争。

新 run 使用 `init_program.txt` 中的特殊 v2 control：digest
`d321c48a5d12bd27b92219b18afad7a04a6141d8ff52d966b4dc8dcf3f04fb07`、patch/options 均为空，
target pins 继续为 parent `fbe4e1cbbfcf45b52960545377020cb761c3ab25` 与 Wolvrix
`8f6ba14397b0c3d00cb909153af1c6464f4f1ed9`。

## 3. 首次启动的确定性 preflight 失败

第一次正式 launcher 使用正确的 MJY config/auth 路径、`gpt-5.6-sol` 和 `ultra`，但 Codex structured
output preflight 在服务端返回 HTTP 400：

```text
invalid_request_error
code=invalid_json_schema
In context=(), 'oneOf' is not permitted.
```

失败发生在 engine/instance 建立之前，launcher exit code 为 `2`；目标仓库未被修改，没有 initial
evaluator、candidate generation 或性能运行。该请求只是 launcher 的 harmless schema-constrained
preflight，没有研究输出。不能用 `--skip-preflight` 绕过，因为同一 schema 会让正式 proposal 也
确定性失败。

## 4. provider-compatible flat schema 修复

SimpleTES commit：

```text
3decc511e874e66f38d2bc41af845b03c156af28
fix: support Codex structured candidate output
```

修改边界：

1. `candidate.schema.json` 保持根 object、全部字段 required、object
   `additionalProperties=false`，保留 `candidate_mode` enum，使模型仍不能输出 `control`；
2. 删除 provider 不支持的顶层 `oneOf` 以及 string/array min/max keywords，改用字段 description
   告知模型 mode shape；nested scalar `anyOf` 保留；
3. `default-path=(patch non-empty, options empty)`、
   `explicit-options=(patch non-empty, options non-empty)` 继续由 evaluator fail-closed 交叉校验；
4. candidate document/patch 大小、路径、tracked-file/suffix、option count/allowlist/scalar safety、
   hypothesis/evidence 数量和长度仍由 evaluator 强制；
5. 在约束下沉时补强 raw evidence 检查：先拒绝空白项、超过 `32` 个 raw items 或单项超过
   `4,000` characters，再 canonicalize，避免先过滤空白项造成 cardinality 绕过。

这次修复只改变 SimpleTES provider contract 和 evaluator input validation，不改变 target
parent/wolvrix pins、candidate attribution、build、功能或 50k runtime protocol。

## 5. 修复验证

所有命令均先 source target `env.sh`。绝对验证结果：

| gate | 绝对结果 |
| --- | ---: |
| schema/bench + codex backend focused pytest | `77/77 PASS` |
| SimpleTES established full `tests/` scope | `139/139 PASS` |
| deprecation warnings | `17`，均为既有 `datetime.utcnow()` warning |
| evaluator/launcher `py_compile` | PASS |
| SimpleTES `git diff --check` | PASS |
| real `gpt-5.6-sol/ultra` structured-output preflight | PASS |

真实 preflight 使用用户指定的 `~/.codex/config.mjy.toml` 与 `~/.codex/auth.mjy.json`，只把路径交给
backend；key 内容没有进入 argv、日志、checkpoint 或本文。

## 6. 第二次正式长期启动

正式 run 参数：

| 字段 | 值 |
| --- | --- |
| output root | `SimpleTES/checkpoints/grhsim_simtop_50k/continuation_v2_20260725_090855` |
| instance | `2026-07-25/instance-ccad5879` |
| SimpleTES source commit | `3decc511e874e66f38d2bc41af845b03c156af28` |
| model / reasoning | `gpt-5.6-sol` / `ultra` |
| selector | `rpucg`，`4` chains，`k=1` |
| generation / evaluation concurrency | `1 / 1` |
| proposals / valid target | `64 / 32` |
| LLM / evaluator timeout | `5,400 s / 21,600 s` |
| max tokens | `32,768` |
| reflection | off |
| `GRHSIM_INFRA_RETRIES` | `8` |
| `GRHSIM_BUILD_JOBS` | `4` |
| trusted slot root | `/tmp/simpletes-grhsim-simtop-50k` |

`64/32` 是 launcher 允许的长期上限，比旧的 `16/8` 默认预算多四倍。infra retries 只允许同一个
已经 build/proof-gated 的候选多等空闲 CCD；它不放宽 quiet-CCD、fixed-ASLR、NUMA、perf、功能或
ABBA/BAAB gate。

启动后观察到：

```text
launcher PID=130634
SimpleTES main PID=130789
initial evaluator PID=135361
slot=/tmp/simpletes-grhsim-simtop-50k/0395ffde6780036f/slot-0
```

run log 已写出 Initialization，明确显示 model、backend、`64/32` budget、serial workers、timeouts、
reflection off 和 checkpoint root。initial evaluator 已取得 slot lock，创建 pinned control clone，并进入
fresh virtualenv/build preparation；这证明实例不只停留在 UI 或 preflight。

## 7. 当前结论与监控要求

本文截止点：auto research 正在运行，但 initial v2 control 尚未完成，因此 valid count、generation
attempts 和 50k walltime 都仍为 `0`/不存在。不得把 TNO0179 canary 的 `61,191.50/61,164.00 ms`
写成这个新 instance 的 initial result。

后续判活必须同时检查：

1. launcher/main/evaluator/emu 进程树；
2. `instance-ccad5879/run.log` 的 mtime 与尾部状态；
3. trusted slot 中 build/emit/focused/function/runtime artifact 的 mtime；
4. `db_state_*` 的 generation attempts、valid evaluations、best program 与 pin provenance。

长 build 或 quiet-CCD wait 期间 run log 可能暂时没有新增内容，不能仅据此判定停止。正常终止需核对
`Evolution Complete!`、`32/32` valid 或 `64` proposals exhausted，并确认 launcher exit 状态。未经
用户新指示，不并启第二个 instance；checkpoint、LLM I/O、build 和 `/tmp` runtime artifacts 均保持
untracked，不提交到 target 代码仓库。
