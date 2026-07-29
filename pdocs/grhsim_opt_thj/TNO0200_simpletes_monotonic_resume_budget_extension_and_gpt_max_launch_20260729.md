# SimpleTES monotonic resume budget extension and GPT max launch

## 1. 结论与边界

[`TNO0199`](./TNO0199_simpletes_k3_gpt_post_rwa_research_completion_20260729.md)
归档的 post-RWA 搜索在 `64` 次 generation attempt 后只有 `15/32` valid，停止原因是
proposal 上限，而不是搜索空间或 valid 目标本身。因此允许 exact checkpoint 继续扩容没有
算法上的原则性障碍；`max_generations` 是资源停止边界，不是 candidate 语义的一部分。

但扩容不能只改 scheduler 的全局上限。旧 checkpoint 同时保存了 RP-UCG 的逐 chain
prompt budget；若只把全局 `64` 改大，4 条 chain 仍会停在旧预算，最终可能出现“全局预算
未满、但没有 chain 可调度”的永久等待。此次实现因此采用显式、单调、fail-close 的恢复
契约，并同时扩展全局与逐 chain budget，保留已有 node、score、attempt、chain history 和
计数，不重放历史 evaluator。

## 2. 实现

SimpleTES commit `9109485df6803dca60ed715c3870ebc67228ed11` 新增：

- `--extend-resume-budget`；只能与 `--resume` 一起显式使用，普通 exact resume 仍要求预算
  与 checkpoint 完全一致；
- generation/valid 上限只允许单调不减；chain 数、`k_candidates` 以及会破坏恢复语义的
  配置变化继续确定性拒绝；
- RP-UCG 按新绝对上限重算逐 chain prompt budget，同时保留各 chain 已消费计数和历史；
- checkpoint metadata 持久化旧/新预算与扩容历史，后续恢复可追溯；
- GrhSIM launcher 普通新任务仍限制为 `64 proposals`，只有显式 budget-extension resume
  才允许更大的、受 launcher 上界保护的预算。

真实最终 checkpoint 的只读恢复探针得到：

| 项目 | 扩容前/恢复值 |
| --- | ---: |
| DB nodes | `20` |
| generation attempts | `64` |
| valid candidates | `15` |
| best score | `1.042845084360962` |
| generation budget | `64→192` |
| 每 chain prompt budget | `16→48` |
| 4 条 chain 已消费 prompt | `16 / 16 / 7 / 16` |
| 可继续调度的 chain | `0 / 1 / 2 / 3` |
| 扩容后剩余 prompt | `137` |

SimpleTES commit `3124fd60df6d7d9cf6354b397531d5aefc39ae86` 又把 Codex
reasoning-effort CLI 的通用合法值扩为
`low/medium/high/xhigh/max/ultra`。这是 parser 兼容修复；本轮明确使用 `max`，新增的
`xhigh` 仅供以后选择，没有改变本轮配置，也没有给 K3 或 GPT 注入额外 prompt。

## 3. 验证

- budget-extension focused/全量回归在首个 commit 前通过；合入 `xhigh/max` 后再次完成
  targeted `22 passed` 与 SimpleTES full `231 passed`；
- 对真实 `db_state_143702` 的恢复探针只在内存中验证 node、attempt、best、chain count 和
  ready-chain 集合，没有写回源 checkpoint；
- dry-run 展开出的主命令为 `max_generations=192`、累计
  `max_valid_evaluations=32`、`gpt-5.6-sol/max`、`4 gen/1 eval`，并包含显式
  `--extend-resume-budget`；
- private config/auth 的权限与非空凭据已由 launcher gate 检查；文档不复制 secret。

## 4. 启动审计

正式启动前曾出现两个互不相同的确定性失败，均发生在研究主循环或 checkpoint 写入前，
失败目录均保留：

1. `gpt56sol_max_budget192_valid32_resume_20260729_202818` 的 capability gate 通过，
   但旧 CLI 尚未接受 `max`，main 以 argparse `exit=2` 退出；这直接触发了上述
   `3124fd60` 修复。
2. 修复后的首次目录
   `gpt56sol_max_budget192_valid32_resume_20260729_203418` 中，模型调用了 repo tool，
   但没有逐字复写 deterministic smoke patch，capability gate 以语义错误 `exit=1`；没有
   修改源 checkpoint。

第二次全新启动目录为：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/
gpt56sol_max_budget192_valid32_resume_20260729_203538
```

其 capability gate 已通过，随后 main 于 `2026-07-29 20:36:48 +0800` 正确载入：

| 项目 | 启动值 |
| --- | ---: |
| source state | `instance-7291c6c2/db_state_143702` |
| attempts / gen fails / gen cancels | `64 / 33 / 3` |
| completed evals / DB nodes | `20 / 20` |
| cumulative valid target | `15→32` |
| absolute proposal limit | `64→192` |
| model / effort | `gpt-5.6-sol / max` |
| workers | `4 gen / 1 eval` |
| generation timeout | `5400 s` |
| supervisor / main PID | `1179514 / 1184389` |

`20:39:06 +0800` 的运行核验显示 supervisor/main 存活，scheduler 为
`4 active / 0 queued`。启动早期有 3 次 Codex CLI non-zero generation failure，随后失败
计数保持不变且 4 个 worker 均持续工作；日志首行显示的 PATH-alias warning 只是有界 stderr
开头，不能在没有完整错误证据时当作根因。研究当前仍在进行，尚无本轮新增 candidate
或 SimTop 50k walltime；当前已知 best 仍是 control `53,742.50 ms`、candidate
`51,534.50 ms`，减少 `2,208.00 ms/4.108480%`。

本轮仍由 evaluator 执行默认生成路径、功能、quiet CCD、CPU affinity、NUMA、PMU、
关闭 ASLR 和双 order fixed-ASLR SimTop 50k 门禁。目标是累计达到 `32 valid`，不是在已有
`15 valid` 之外再新增 32 个；若先达到 `192` 次绝对 attempt 上限，则按资源边界自然停止。
