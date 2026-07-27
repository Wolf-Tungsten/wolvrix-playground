# TNO0195：SimpleTES K3 context window 更正、中断审计与恢复启动（2026-07-28）

## 结论

- `k3_rwa_grounded_fresh_20260728_032742` 启动时，`~/.codex/config.kimi.toml` 的 `model_context_window` 仍为 `272000`，不是本轮预期的 K3 长上下文配置。
- 该实例于 `04:52:51 +0800` 收到人工 `SIGINT` 并优雅退出；正在运行的第一条 generation 被取消，未形成 final JSON、candidate patch，也未进入 build/evaluator。因此本次中断没有新的功能或 SimTop 50k 性能结论。
- 中断前的临时事件流已原样保存；最终 checkpoint 正常写入，launcher 以状态 `0` 退出。
- 用户将配置改为 `model_context_window = 1000000` 后，新 root `k3_rwa_grounded_ctx1m_resume_20260728_045517` 从该 checkpoint 恢复。确定性 K3 capability gate 通过，正式 scheduler 于 `04:56:05 +0800` 启动；已完成的 initial control 被复用，没有重复运行 50k control。
- 当前仍使用 Kimi `k3`、`ultra`（K3 侧映射为 max thinking）、`64 proposals / 32 valid`、单 generation/单 evaluator；最终性能口径仍只接受 fixed-ASLR、空闲 CCD、功能等价的 SimTop 50k `Host time spent` walltime。

## 中断实例审计

### 身份与既有 control

- root：`SimpleTES/checkpoints/grhsim_simtop_50k/k3_rwa_grounded_fresh_20260728_032742`
- instance：`7291c6c2`
- baseline pins：parent `d31118bea0feb563ad09476e1419f0f15aaf574f`；Wolvrix `16a9f493687a21a5428f1e1327a69834ea60c9f5`
- initial same-code ABBA：
  - control：`54,520 / 54,505 ms`，均值 `54,512.5 ms`
  - candidate-control：`54,555 / 54,613 ms`，均值 `54,584.0 ms`
  - candidate-control 比 control 慢 `71.5 ms / 0.131162577%`，仅作同码噪声记录
- control/candidate generated fingerprint 均为 `b55d17026338f456`；四个样本的 fixed-ASLR、CCD、NUMA、PMU、迁移与功能门禁均通过。

### 被取消 generation

- generation 开始：`03:45:18 +0800`
- `SIGINT`：`04:52:51 +0800`
- 持续时间：约 `4,053 s`（`67 min 33 s`）
- 保存事件流：`instance-7291c6c2/interrupted_generation_events.jsonl`
- 保存大小：`1,284,303 B`
- SHA256：`48d41a4c4959a9adfe8f4f1989c9d0475781ffaab60a0fc01cd4031b5fdccdb1`
- 事件绝对计数：
  - command started：`239`
  - command completed：`239`，其中成功 `235`、失败 `4`
  - reasoning completed：`146`
  - agent message completed：`24`
  - error item：`2`
  - `turn.completed`：`0`

这些计数证明 K3 一直在进行真实仓库研究，但在人工中断前没有返回最终 response。故不能从中恢复半成品 patch，也不能把其研究方向计为候选结果。

### 优雅退出结果

- final checkpoint：`instance-7291c6c2/db_state_045321`
- completed evaluations：`1`（既有 control）
- valid candidates：`0 / 32`
- generation failures：`0`
- generation cancellations：`1`
- evaluator/build：均未启动
- checkpoint best score：`0.9986900923347501`，对应既有同码 control 噪声，不是新优化收益
- supervisor、launcher、SimpleTES main、Codex 子进程均退出；`launcher.exit = 0`。

## 1,000,000 context 恢复

### 配置验证

启动前只读取非 secret 字段，确认：

```text
model_provider = "kimi"
model = "k3"
model_reasoning_effort = "ultra"
service_tier = "default"
model_context_window = 1000000
```

正式 generation 创建后，再检查其 ephemeral private config：

```text
/tmp/simpletes-codex-ihbwt27w/config.toml
model_context_window = 1000000
```

因此新的 context window 已进入实际 Codex 调用配置，而不只是修改了外层源文件。认证内容没有输出或复制到文档/日志。

### 恢复启动

- root：`SimpleTES/checkpoints/grhsim_simtop_50k/k3_rwa_grounded_ctx1m_resume_20260728_045517`
- supervisor PID：`3770845`，已脱离终端并重挂到 PID 1
- launcher PID：`3770993`
- SimpleTES main PID：`3775089`
- 首条 K3 generation PID（启动核验时）：`3775611`
- resume source：`db_state_045321`
- 恢复 instance：`7291c6c2`
- DB nodes：`1`
- completed evaluations：`1`
- generation cancellation history：`1`
- remaining proposal budget：`63`
- scheduler start：`04:56:05 +0800`
- `04:57:32 +0800` 的早期活性核验：新事件流 `31,128 B`、已完成 repo command `9`、`turn.completed = 0`；launcher 仍运行。

## 当前决定

- 不重启另一份并行实例；只保留上述 ctx1m resume。
- 不把被中断 generation 当成失败候选或性能数据，也不修改 Wolvrix 默认。
- 继续等待 1,000,000 context 下首个完整 JSON/patch；拿到后先检查 schema、非 placeholder、patch attribution 和 build/function gate，再由严格 SimTop 50k walltime 决定是否保留。
