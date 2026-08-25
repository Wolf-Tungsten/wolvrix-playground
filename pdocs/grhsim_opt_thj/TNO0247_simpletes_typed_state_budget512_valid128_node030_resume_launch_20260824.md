# TNO0247: SimpleTES typed-state budget-512/valid-128 node030 resume launch

日期：2026-08-24

## 1. 阶段目标

上一段 typed-state auto research 已达到累计 `64/64 valid` 并正常退出。本阶段不创建 fresh baseline，也不丢弃四条 research chain；从最终 checkpoint 精确恢复，将累计 valid 目标翻倍到 `128`，同时把绝对 generation-attempt 上限扩到 `512`，并把执行主机从 node032 迁移到负载相对较低的 node030。

## 2. 恢复源与上一阶段结果

恢复源：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/
  typed_state_gpt56sol_max_fresh2_20260816_182232/2026-08-16/
  instance-5f0c84e9/db_state_030132
```

`metadata.json` 与最终日志一致：

- generation attempts：`185`；
- completed evaluations / DB nodes：`98 / 98`；
- valid evaluations：`64/64`；
- generation failures / cancellations：`81 / 2`；
- evaluation failures：`0`；
- best node：`621109d489774ae2b6361cc30c8dffdc`，generation `158`；
- best score：`1.0478472639807577`。

该 best 的正式 SimTop 50k pooled walltime 为 control `43,564.25 ms`、candidate `41,575.00 ms`，绝对减少 `1,989.25 ms`，相对提升 `4.566244%`。这是扩容前既有结果，不是 node030 新测结果；本次启动时尚无新增 valid candidate 或新增性能结论。

## 3. 扩容实现与验证

原 launcher 的 exact-resume 硬上限为 `256 proposals`，无法表达本次累计 `128 valid` 的合理尝试预算。根据前一阶段 `185 attempts -> 64 valid` 的实际转换率，仅保留 `256` 上限只剩 `71` 次尝试，明显不足以稳定获得另外 `64` 个 valid。故保持累计约 `4:1` 的预算比例，将允许的单调恢复上限从 `256` 扩为 `512`：

```text
SimpleTES commit: c8f1da8f5940e90192e30d16a3536bc8dd057e77
subject: bench: allow 512-attempt resume extensions
```

修改只扩大 launcher 的受控 resume ceiling，并同步 README 与边界测试；没有放宽 checkpoint pin、schema、功能、quiet-CCD、fixed-ASLR、NUMA、PMU 或 walltime 门禁。

验证结果：

- focused GrhSIM bench：`82 passed`；
- SimpleTES full suite：`265 passed`，另有 `24` 个既有 warning；
- SimpleTES 工作树在提交后 clean。

## 4. node030 工具链恢复

第一次远端启动于 `2026-08-24 11:53:22 +08:00` 创建 launcher PID `2352737`，在写入 research 状态前被确定性工具链预检拒绝：node030 有 Clang `19.1.1`，但没有匹配的 `clang-scan-deps-19`。该失败实例未进入 `main.py`，未消费 generation attempt，也未修改恢复 checkpoint。

用户随后在 node030 安装 `clang-tools-19`。复查结果为：

```text
compiler=/usr/bin/clang++
scanner=/usr/bin/clang-scan-deps-19
major=19
```

没有降低或旁路工具链门禁。

## 5. 正式续跑状态

成功启动时间：`2026-08-24 11:55:57 +08:00`。

```text
host: node030
launcher PID: 2364430
main PID: 2370584
model: gpt-5.6-sol
reasoning effort: max
Codex CLI: 0.146.0
config: ~/.codex/config.thj.toml
auth: ~/.codex/auth.thj.json
workers: 4 gen / 1 eval
LLM timeout: 10800 s
eval timeout: 21600 s
Codex exec retries: 2
capacity continuations: 3
transient continuations: 3
evaluator infrastructure retries: 8
budget: 512 attempts / 128 valid
```

launcher 日志：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/
  typed_state_gpt56sol_max_fresh2_extend512_valid128_node030_20260824_115557/
  launcher_20260824_115557.log
```

启动证据：

- evaluator toolchain preflight PASS；
- Codex capability preflight PASS，确认 `gpt-5.6-sol/max`、repo tool call 和 provider structured output；
- checkpoint 加载 `185 attempts / 98 evals / 64 valid / 98 nodes`，四条 chain 均存在；
- 单调预算记录为 `generations 256 -> 512`、`valid 64 -> 128`；
- scheduler 已报告 `4 gen workers active / 0 queued`，`1 eval worker` 就绪。

## 6. 状态与结论边界

- 这是原 research tree 的 exact resume，不是从旧 best 创建的新 baseline；control 与已有节点历史保持不变。
- `db_state_030132` 是只读恢复源；后续 checkpoint 仍写入原 `instance-5f0c84e9` 目录，launcher 专用目录保存本次外层日志。
- node032 已确认无残留 SimpleTES 进程，当前只有 node030 运行本轮研究。
- 性能裁决继续只接受通过同 CCD、fixed-ASLR、NUMA、PMU、功能门禁的 SimTop 50k `Host time spent` walltime；当前没有可据此修改 Wolvrix 默认项的新结果。
