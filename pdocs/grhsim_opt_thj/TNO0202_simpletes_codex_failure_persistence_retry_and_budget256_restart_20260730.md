# SimpleTES Codex failure persistence, retry, and budget-256 restart

## 1. 结论

[`TNO0201`](./TNO0201_simpletes_gpt_codexexecerror_diagnosis_20260730.md) 暴露的
non-zero 诊断缺口已经闭合。SimpleTES 现在会在 private `CODEX_HOME` 删除前完整保存经
结构保持脱敏的 `events.jsonl`、`stderr` 和存在时的 final output，并直接从
`error/turn.failed/thread.failed` 事件提取有界错误摘要。真实 canary 因此第一次把此前
opaque 的 status `1` 定位为 provider 返回：

```text
Selected model is at capacity. Please try a different model.
```

该错误已归入有界 transient retry；认证、权限、策略、invalid request 和 schema 类错误
仍不重试。Codex private home 也已从 `/tmp/simpletes-codex-*` 迁到 checkpoint 下的
`.codex_runtime/simpletes-codex-*`，当前进程不再出现 temporary-dir PATH alias warning。

旧运行已优雅停止；`max_generations` 随后从累计 `192` 扩为 `256`。最终正式 continuation
已从扩容后的 exact checkpoint 运行，累计 valid 目标仍为 `32`，不是再增加 32 个。

## 2. 旧运行停止点

`gpt56sol_max_budget192_valid32_resume_20260729_203538` 于
`2026-07-30 02:38 +0800` 收到 SIGINT，4 个进行中的 generation 被取消，launcher、main、
supervisor 及其 process group 均已退出。最终源状态为：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/k3_rwa_grounded_fresh_20260728_032742/
2026-07-28/instance-7291c6c2/db_state_023818
```

| 项目 | 绝对值 |
| --- | ---: |
| completed evaluations / DB nodes | `28 / 28` |
| generation attempts | `143` |
| generation failures / cancellations | `100 / 7` |
| evaluation failures | `0` |
| valid evaluations | `21 / 32` |
| best score | `1.0430327967236885` |
| best node | `89250ab41a414dfb86e98f98eddf3796` |
| best-program SHA-256 | `e5a5219b37f9e1f377672ec83a938fcb7baef6a4d1807f1cf24aeeed48e5a17d` |

当前 best 的正式 fixed-ASLR SimTop 50k walltime 为 control `54,311.50 ms`、candidate
`52,070.75 ms`，绝对减少 `2,240.75 ms`，相对提升 `4.125738%`。这仍是重启时的 best；
本记录阶段没有新增完成的性能评估。

## 3. 实现与安全边界

SimpleTES commit `7ea0d726cb56569b76db98f538cf247c26afe4e6` 完成：

- 每个逻辑 request 使用独立 `0700` 目录；每个 subprocess attempt 写独立的
  `attempt-XX.exec-YY.events.jsonl`、`stderr.log`、可选 final output 和 metadata，文件均为
  `0600`；
- metadata 记录 model/effort、request/structured/exec attempt、exit status、完整字节数、
  stored SHA-256、redaction count 和 checkpoint-relative artifact path；原文含凭据形状时只
  保存等长脱敏版本，不保存 raw hash；
- launcher/failure record 能直接看到脱敏后的 `turn.failed/error`，而不是只看到 stderr；
- `EngineConfig.retry` 传入 Codex backend；只对已分类的 transport、provider 5xx/429、
  websocket、unified-exec ENOENT 等 transient error 做最多 `0..3` 次内部退避重试。内部
  retry 不消耗新的 SimpleTES generation proposal；
- production run 的 private home 位于 instance `.codex_runtime`；preflight 使用全局私有
  `.codex_runtime`。每次 request 的子目录仍在结束后删除；
- 通用 research instruction 禁止对 `/nfs/home`、workspace、`/tmp`、evaluator slots 和
  checkpoint tree 做无界扫描，要求使用 repo 内 exact path、`rg`/`rg --files` 和只读检查。

真实 canary 保存的第一份 artifact 为：

```text
llm_attempts/request-477aee877d6574f90a5bed8da10c44ae/
attempt-01.exec-01.metadata.json
```

它引用完整 `297 B` JSONL，包含 `thread.started`、`turn.started`、`error` 和
`turn.failed` 四条事件；stored/raw SHA-256 均为
`a65d7e4dd8f23083da8e03d15a6418f9104523e8314bc35d40bae6082c2faf13`，目录/文件权限实测
为 `0700/0600`。这证明 retry 不再依赖猜测，失败完整内容可从 checkpoint 复核。

canary 随后表明 `at capacity` 也是 transient。commit
`f0aad95` 将 capacity/overload 类错误加入 retry，并把退避改为 `5/20/60 s`；正式运行因
连续容量波动选用允许上限 `3` 次 retry。commit `d65cffe` 另修复已扩容 checkpoint 的
exact restart：launcher 允许 resume 使用 `<=256` 的既有绝对上限，但 engine 仍要求普通
resume 完全相等，只有显式 `--extend-resume-budget` 才允许单调增大。因此没有放宽隐式扩容
或 checkpoint 契约。

## 4. 验证

- 首次实现：Codex backend `64 passed`、launcher `18 passed`、full `238 passed`；
- capacity 分类后：Codex backend `65 passed`、full `239 passed`；测试覆盖 capacity
  status-1 后同一 prompt 第二个 subprocess 成功，generation counter 只消费一次；
- exact extended-resume 修复后：launcher `18 passed`、full `239 passed`；
- 完整 artifact 单测同时覆盖大于 launcher 摘要上限的 JSONL、stderr/final-output、凭据
  脱敏、SHA/size/permission、并发 request 隔离、认证失败不重试和稳定非 `/tmp` HOME。

## 5. 启动审计

扩容与 restart 过程中保留了三个有用的失败目录，没有把它们伪装成正式成功运行：

1. `gpt56sol_max_budget256_valid32_resume_20260730_025520`：capability gate 通过，main 从
   `db_state_023818` 正确执行 `192→256` 扩容；4 个 generation 都返回 capacity。为补齐
   分类而优雅停止，形成 `db_state_025629`：`150 attempts / 104 failures / 10 cancellations /
   28 evals / 21 valid`，best 不变。
2. `gpt56sol_max_budget256_valid32_retryfix_20260730_025830`：capability gate 通过，但对已经
   保存为 256 的 checkpoint 再传 extension flag 被 engine 正确 fail-close；没有启动
   scheduler，也没有新增 proposal。这触发 exact extended-resume 修复。
3. `gpt56sol_max_budget256_valid32_exact_20260730_030120`：exact contract 已通过 launcher，
   但 capability gate 的 3 个 provider 请求持续 capacity，内部 `2` 次 retry 后明确退出；
   没有进入 research，3 份完整 preflight JSONL 均已保存。

最终正式目录为：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/
gpt56sol_max_budget256_valid32_capacityretry_20260730_030300
```

capability gate 已通过；main PID `2619762`、launcher PID `2616369`、supervisor PID
`2616216`。`2026-07-30 03:03:56 +0800` 的 exact load 与运行参数为：

| 项目 | 启动值 |
| --- | ---: |
| source state | `db_state_025629` |
| attempts / failures / cancellations | `150 / 104 / 10` |
| completed evals / DB nodes | `28 / 28` |
| valid | `21 / 32` |
| absolute generation limit | `256` |
| model / effort | `gpt-5.6-sol / max` |
| workers | `4 gen / 1 eval` |
| timeout / transient retries | `5400 s / 3` |

`03:04:56 +0800` scheduler 为 `4 active / 0 queued`。容量波动仍存在，但当前失败先写入
完整 artifact 并在同一个 generation 内退避重试；已观察到多份 metadata 的
`retryable=true` 和递增的 `exec_attempt`。截至 `03:06:35 +0800`，其中两个逻辑
generation 在 `exec_attempt=1..4` 均收到 provider capacity 后，才按有界策略各记为一次
generation failure；每个 generation 的 4 轮完整 metadata/JSONL 均已落盘。scheduler 随即
补入新任务，main、launcher 和 supervisor 继续存活。这说明 retry/persistence 修复已经生效，
但有界重试本身不能消除持续的上游容量不足。所有活跃 HOME 均位于 instance
`.codex_runtime`，日志没有 PATH-alias temporary-dir warning。
后续 candidate 仍由 evaluator 执行默认生成路径、功能、quiet CCD、CPU/NUMA/PMU、关闭
ASLR 和双 order fixed-ASLR SimTop 50k 门禁，最终性能口径仍只看 walltime。
