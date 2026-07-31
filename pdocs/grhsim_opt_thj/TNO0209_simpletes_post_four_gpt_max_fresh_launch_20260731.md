# TNO0209 SimpleTES post-four GPT max fresh launch

## 1. 阶段目标与当前状态

[TNO0208](./TNO0208_four_positive_simpletes_repin_and_native_50k_20260731.md) 已将 SimpleTES bench
迁移到 landed four-positive 空 control，并完成 production/control/performance 闭环。本阶段按用户指示从该
空 control 启动一轮全新的 auto research，使用 GPT-5.6 Sol、max reasoning，以及 THJ config/auth。

截至 2026-07-31 12:31:57 +08:00，正式实例已经启动并进入 initial control evaluator：

- output root：
  SimpleTES/checkpoints/grhsim_simtop_50k/four_positive_gpt56sol_max_fresh_20260731_122641_retry1；
- instance：
  2026-07-31/instance-73ee9786；
- launcher PID/SID/PGID：2476168/2476168/2476168；
- SimpleTES main PID：2485367；
- initial evaluator PID：2486915。

当前尚无本轮 generated candidate、valid candidate、50k walltime 或 best score，不能提前报告性能结论。

## 2. 固定代码与 control 身份

| 对象 | identity |
| --- | --- |
| evaluator parent pin | de37459cdd210794fa5d7423e6f32c145cf71261 |
| evaluator Wolvrix pin | fd12d83f5150cc98540ed3e8f2af3b79f8054da0 |
| SimpleTES repin commit | de12067713618cd30c266d95684355c0816b94d0 |
| launch 时 parent HEAD | 9d3dbee2d3453ceaf706a5d4eb72cc2fdae5878b |
| empty-control digest | 87c4e574878b47fe045475c798a462b6a5ac1f5ee1bb2a5df106796ca81a22bf |

parent HEAD 比 executable snapshot 多 TNO0207/TNO0208 文档提交，但 parent tree 的 Wolvrix gitlink 仍精确指向
fd12d83...。evaluator 使用 de37459.../fd12d83... 的固定 executable pin，不把运行中的文档提交当成
candidate 源码变化。

## 3. 模型、凭据与预算

正式参数为：

| 参数 | 值 |
| --- | --- |
| model | gpt-5.6-sol |
| reasoning effort | max |
| config | ~/.codex/config.thj.toml |
| auth | ~/.codex/auth.thj.json |
| output/tool mode | provider-structured / auto |
| selector | rpucg，4 chains，k=1 |
| generation/evaluation workers | 4 / 1 |
| max proposals / valid target | 64 / 32 |
| generation/evaluation timeout | 10,800 s / 21,600 s |
| ordinary Codex exec retries | 2 |
| exact-session capacity continuations | 3 |
| evaluator infra retries | 8 |
| build jobs | 4 |
| reflection | disabled |

GPT 分支没有接收 K3-only instruction suffix、private model catalog 或 subagent thread cap；GPT 保持其原生
delegation 行为。auth 文件只作为 launcher 输入路径，API key 没有写入本文、命令输出或 checkpoint 名称。

本轮采用 fresh launcher 允许的上限 64 proposals，并以 32 valid 为停止目标，延续上一阶段先取得
32 valid 再裁决的口径。四个 generation worker 可以并行，实际 evaluator 保持串行，避免 build/runtime
互相覆盖或性能采样竞争。

## 4. Dry-run 与真实 preflight

显式 dry-run 成功组装以下关键参数：

- model=gpt-5.6-sol、reasoning-effort=max；
- max-generations=64、max-valid-evaluations=32；
- gen-concurrency=4、eval-concurrency=1；
- provider-structured/auto；
- THJ config/auth；
- 没有 K3-only 参数。

独立真实 capability preflight 结果为 PASS：

- repo tool calls：1；
- model catalog：native；
- response chars：632；
- response SHA-256：
  b73b1e9887127f9fa7e57c9454532df40e577b69a1d47c6284a2212bb12b6407。

该 preflight 验证了当前 provider/auth、模型、repo tool、structured schema 和 harmless patch applicability；
随后正式 retry1 launcher 又成功越过其紧邻执行的 preflight，并创建 SimpleTES main 与 initial evaluator。

## 5. 第一次错误 cwd 启动与保留证据

第一次后台尝试使用 output root：

SimpleTES/checkpoints/grhsim_simtop_50k/four_positive_gpt56sol_max_fresh_20260731_122641

它没有产生 instance/checkpoint，只留下 launcher.log。失败顺序是：

1. 正式 preflight 首次请求命中 Selected model is at capacity；
2. exact-thread continuation 被触发；
3. 启动命令当时从 workspace 根而不是 README 规定的 SimpleTES Git 仓库执行；
4. codex exec resume 继承该非 Git cwd，因 trusted-directory 检查退出。

这不是 candidate/evaluator/50k 失败，也没有消耗 research proposal 或 valid budget。独立 preflight 已证明
同一 THJ provider/auth 可用；按 runbook 改为从 SimpleTES 仓库启动 retry1 后，正式 engine 正常进入
initial control。失败日志保留且未被 retry1 覆盖。

## 6. 后续观察入口与边界

持续日志：

SimpleTES/checkpoints/grhsim_simtop_50k/four_positive_gpt56sol_max_fresh_20260731_122641_retry1/launcher.log

checkpoint/LLM I/O：

SimpleTES/checkpoints/grhsim_simtop_50k/four_positive_gpt56sol_max_fresh_20260731_122641_retry1/2026-07-31/instance-73ee9786

当前只确认进程、参数、pin 和 initial evaluator 已启动；不把尚未完成的 initial control 写成 PASS，也不把
历史 TNO0208 的 4.045173% 当成本轮新 candidate 结果。后续进展应以该 instance 的 immutable checkpoint、
evaluation JSON、绝对 Host time spent 与完整 runtime audit 为准。
