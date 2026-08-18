# TNO0236：SimpleTES typed-state 尝试上限扩展到 256 并续跑

日期：2026-08-19

## 1. 阶段结论

上一轮从 [TNO0235](./TNO0235_simpletes_typed_state_budget128_valid64_resume_launch_20260818.md)
启动的 `128`-attempt 续跑已达到 generation 上限，但 provider 429 使大量生成请求
失败，最终只完成 `38/64 valid`。本阶段从该轮最后一个持久化 checkpoint 精确恢复，
将最大 generation attempts 单调扩展到 `256`，保持 `max_valid_evaluations=64`
不变。

扩容后的 launcher 已在 node032 进入主循环，日志确认扩展契约和 worker 配置均生效：

```text
Attempts: 128 | Gen fails: 74 | Gen cancels: 2 | Eval rejects: 0 | Evals: 51
Budget extension: generations 128→256 | valid 64→64
Starting 4 gen workers and 1 eval workers
Starting scheduler loop
```

本阶段刚启动，尚无新的 valid candidate 或 SimTop 50k 性能结论。旧 best
`1.0128054335166798` 仍只是搜索 seed，不能计作本阶段新收益。

## 2. 恢复源与上轮状态

恢复源为：

```text
/nfs/home/tanghaojin/wolvrix-SimpleTES-workspace-5/SimpleTES/checkpoints/
grhsim_simtop_50k/typed_state_gpt56sol_max_fresh2_20260816_182232/
2026-08-16/instance-5f0c84e9/db_state_211121
```

该 checkpoint 的 `metadata.json` 记录：

| 字段 | 值 |
| --- | ---: |
| generation attempts | `128` |
| completed evaluations | `51` |
| valid evaluations | `38` |
| generation failures | `74` |
| generation cancellations | `2` |
| evaluation failures | `0` |
| best score | `1.0128054335166798` |
| best node | `180c854bbcbc406d8115ef7ee9af789a` |

上轮日志中的 generation failures 均为 Codex provider `429 Too Many Requests`，每个
请求已按当前 bounded retry/continuation 规则留下 repair artifacts；没有证据表明
SimTop evaluator 或代码功能门禁失败。扩容因此只改变尝试预算，不修改模型、基线、
evaluator 或生成配置。

## 3. 本轮启动配置

| 项目 | 值 |
| --- | --- |
| model | `gpt-5.6-sol` |
| reasoning effort | `max` |
| Codex config/auth | `/nfs/home/tanghaojin/.codex/config.thj.toml` / `/nfs/home/tanghaojin/.codex/auth.thj.json` |
| generation workers | `4` |
| evaluation workers | `1` |
| generation timeout | `10800 s` |
| evaluation timeout | `21600 s` |
| capacity/transient continuations | `3 / 3` |
| attempts | `128 → 256` |
| valid target | `64 → 64` |
| output root | `typed_state_gpt56sol_max_fresh2_extend256_valid64_20260819_0019` |

launcher 使用 `--resume` 指向 `db_state_211121`，并显式传入
`--extend-resume-budget --max-proposals 256 --valid-target 64`。预检阶段的 LiteLLM
远程 cost-map 请求超时后回退到本地表，但 GrhSIM toolchain 与 Codex capability
preflight 均通过；这不是研究失败。

本轮日志路径为：

```text
/nfs/home/tanghaojin/wolvrix-SimpleTES-workspace-5/SimpleTES/checkpoints/
grhsim_simtop_50k/typed_state_gpt56sol_max_fresh2_extend256_valid64_20260819_0019/
launcher_20260819_0019.log
```

## 4. 结果边界与后续规则

- 只有通过完整 evaluator、功能、fixed-ASLR、quiet-CCD、NUMA、PMU 门禁的 candidate
  才能进入性能排序。
- 最终端到端指标仍是 SimTop 50k walltime；当前扩容启动本身不产生性能数据。
- valid 目标保持累计 `64`，因此达到第 `64` 个 valid 后应自然停止；若 generation
  上限再次耗尽，应从最新 `db_state_*` 继续并保持单调扩展。
- provider 429 仍应按现有 retry/continuation 机制处理，不把失败尝试当作 valid，
  也不改变当前 Wolvrix 默认生成配置。

