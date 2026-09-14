# SimpleTES Astra budget-128/valid-64 resume

## 阶段结论

用户授权将最新 Astra auto research 扩容后继续，并明确确认累计预算
`128 attempts / 64 valid`。2026-09-14 已在 node030 从最终 checkpoint
恢复原实例 `ed572ae5`，不是 fresh research，也没有把 best 改成 baseline。
原研究见 [TNO0300](./TNO0300_simpletes_native_b_astra_fresh_launch_20260909.md)，
locale 修复见 [TNO0301](./TNO0301_simpletes_function_gate_locale_fix_20260910.md)。

截至 `11:02:26 +08:00`，仅一个研究引擎存活，四个 generation worker
正在处理请求，尚无扩容后新增完成的评测。本记录不宣称新增性能收益。

## 扩容前最终状态

上一段于 `2026-09-12T17:51:48+08:00` 正常退出，launcher returncode `0`；
结束原因是达到 `32/32 valid`，不是错误退出。最终 metadata 实测：

| 项目 | 值 |
| --- | ---: |
| generation attempts | 42 / 64 |
| valid evaluations | 32 / 32 |
| completed evaluations / DB nodes（含 seed） | 39 |
| generation failures | 1 |
| generation cancellations | 0 |
| evaluation failures | 0 |
| best generation | 34 |
| best score | 1.0247910863509748 |

best node 为 `3ad901efe47048cf8dbf3b44c912b01d`，原有 schema-v4
SimTop 50k pooled walltime 为 `40,469.00 → 39,490.00 ms`，减少
`979.00 ms / 2.419135635%`。ABBA/BAAB 的 walltime 减少比例分别为
`2.301315% / 2.536245%`，order gap `0.234930 pp`，原门禁通过。
score 相对 1 的增长约 `2.479109%`，不与 walltime 减少比例混用。
这里只记录扩容前 best 的既有测量，不是独立复测或生产默认落地结论。

精确恢复源（相对 workspace）：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/
hot_dispatch_b_gpt6astra_max_fresh_node030_20260909_225353/
2026-09-09/instance-ed572ae5/db_state_175142
```

没有改写该 checkpoint 的计数、节点、分数或配置。启动前为防止框架后续
轮换旧 checkpoint，将其逐字节归档到本次 launch root 的 `source_checkpoint/`，
并按 manifest 中逐文件 SHA-256 核验通过。关键恢复文件 SHA-256 为：

```text
metadata.json     c6e9ba0891ad4a5176dd5477fd7c30953d887956c8755e7be15cde9d703a1e71
config.json       0ab533a0f9e5b25a4aef8bf564d5e0648ca08bdaf843af7d21bb0098e2741173
nodes.json        77faa3770ea1c2e119ca307eb298304bd378c4672774021933bef8425da07cbf
policy.json       818ae8a4d7736b38bee2203e82a2da5e24fb2441620f646931022dcb12a84735
best_program.txt  18d5660cee83e5b3a7262581fa6c763e876eb68e07067823ff0b8563cc36d859
```

## 续跑契约与预检

只通过 launcher 的正式扩容入口增加累计上限：

```text
--resume <exact db_state_175142>
--extend-resume-budget
--max-proposals 128
--valid-target 64
```

恢复时已消费 42 次尝试、32 个 valid，因此累计尝试余量为 86，还需最多
新增 32 个 valid；不是从零重新获得 128 次尝试。保持：

- `gpt-6-astra / max`，原 THJ 派生私有 config 和 `~/.codex/auth.thj.json`。
- 原隔离安装的 `codex-cli 0.153.4`，PATH 显式选择该版本；本阶段未升级或改模型。
- SimpleTES commit `9d19a65c18c7605efe4ffb1d144c11cbc2061f0d`，含 locale 修复。
- parent executable pin `fd54f8deab18d861cd29fa4c3852f1013c3948f1`；
  Wolvrix pin `94109bc68e0f0ea76d6083b3c193750be9a7bfae`，原生默认含 B。
- 原 slot root `/tmp/simpletes-grhsim-post-hot-dispatch-b-astra-node030-20260909_225353`，
  control marker 在 node030 仍存在，后续按原身份校验协议复用。
- `4 gen / 1 eval`，generation/evaluation timeout `10800 / 21600 s`。
- `GRHSIM_INFRA_RETRIES=99`，build jobs `4`、CMake/package/OpenMP jobs `8`。
- supervisor 额外明确 `LC_ALL=C`；所有运行命令首先 source playground `env.sh`。
- 关闭 ASLR、同 CPU/CCD mirrored `ABBABAAB`、NUMA 页面本地化、strict quiet
  admission/连续负载审计和全部 schema-v4 稳定性门禁不变。

启动前 node030 未发现活动研究 main/launcher；当时 load 为
`25.20 / 30.50 / 44.56`，`/tmp` 文件系统可用 `232G`、`/dev/shm` 可用 `498G`。
这不代替运行前的 quiet-CCD 门禁。离线 launcher resume 校验通过；现有
resume/extend 聚焦测试为 `3 passed, 132 deselected in 6.90s`。
本次没有修改 SimpleTES/Wolvrix 生产源码，未把旧 full suite 冒充本次重跑。

## 首次预检拒绝与成功启动

第一次 launch root 后缀为 `20260914_105442`，工具链通过，但模型返回的
fresh pinned-blob challenge attestation 与实际值不匹配，发生
`SemanticValidationError`，于 `10:57:37 +08:00` 以 returncode `1` 结束。
引擎未启动，原 checkpoint 和预算未改变，日志和归档均保留。
失败结构化响应记录在 `.preflight_llm_attempts/` 的
`request-206488ce5154c9208d28996be63fbdde/`。本阶段没有进一步断言计算错误
原因，也没有跳过或放宽 attestation 校验。

确认第一 launcher 已退出后，以相同配置重新预检，第二次通过：

```text
GrhSIM evaluator toolchain preflight passed: compiler=/usr/bin/clang++, scanner=/usr/bin/clang-scan-deps-19, major=19
Codex capability preflight passed: model=gpt-6-astra, effort=max, repo_tool_calls=1, model_catalog=native, response_chars=632, response_sha256=689bdc3083d933cabd521e1342ba828c50cc884256fb9d30be509c67b3d2e3b2
Checkpoint Loaded: Instance ed572ae5
Attempts: 42 | Gen fails: 1 | Gen cancels: 0 | Eval rejects: 0 | Evals: 39
Budget extension: generations 64→128 | valid 32→64
(11:01:36) Starting 4 gen workers and 1 eval workers
(11:02:06) gen workers: 4 active / 0 queued, eval workers: 0 active / 0 queued
```

成功 launch root：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/
hot_dispatch_b_gpt6astra_max_extend128_valid64_node030_20260914_105917
```

该目录保存 `launch_manifest.json`、`dry_run.log`、`launcher.log`、
`supervisor.json` 和 `source_checkpoint/`。监督脚本为 workspace 下
`build/astra_resume_20260914/launch.py`，使用原 run 的 launch lock；仅监督
本次进程退出并写结果，不会在预算耗尽后自动启动新实例。

tmux session：`simpletes-astra-resume-20260914_105917`。
supervisor / launcher / engine PID：`660724 / 661525 / 680236`。

引擎的 exact resume 行为是继续写原 instance 目录；新的 output 参数不迁移
研究树。因此实际 `run.log` 和后续 `db_state_*` 仍位于原目录：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/
hot_dispatch_b_gpt6astra_max_fresh_node030_20260909_225353/
2026-09-09/instance-ed572ae5/
```
