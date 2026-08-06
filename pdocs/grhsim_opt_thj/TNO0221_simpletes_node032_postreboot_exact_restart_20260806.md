# TNO0221：SimpleTES 在 node032 重启后的精确恢复

日期：2026-08-06

## 1. 结论

[TNO0220](./TNO0220_simpletes_64valid_node029_to_node032_migration_20260806.md) 记录的 node032
continuation 因节点重启被操作系统中断。重启没有产生 final checkpoint；中断前内存中的 1 个 active evaluation
和 3 个 queued evaluations 没有被计入 completed/valid，也没有形成可恢复的 pending queue。

本阶段已经从迁移源 `db_state_020746` 再次执行 exact restart，并确认：

- 绝对预算仍为 `128 generations / 64 cumulative valid`，没有再次扩容；
- 恢复面板为 `46 attempts / 40 completed evaluations / 40 DB nodes / 34 valid`，best 不变；
- 使用 THJ config/auth、`gpt-5.6-sol`、`max`、`4 gen / 1 eval`；
- 四个 generation worker 都实际运行，并显式使用 NVM `codex-cli 0.146.0`；
- 截至 `2026-08-06 17:14:19 +0800`，日志为 `gen workers: 4 active / 0 queued`。

因此 auto research 已在 node032 正常继续。本阶段没有新的 candidate evaluation、SimTop 50k walltime 或性能结论，
也没有修改 SimpleTES/Wolvrix 代码与 Wolvrix 默认选项。

## 2. 重启中断审计

node032 本次 boot time 为：

```text
2026-08-06 17:03:46 +0800
```

重启后实查 node032 没有存活的旧 launcher、main、Codex 或 evaluator；node029 也没有重新出现本轮进程。
旧运行日志最后一条 scheduler 状态在 `17:01:44 +0800`：

```text
gen workers: 0 active / 0 queued, eval workers: 1 active / 3 queued
```

实例目录中的 checkpoint 仍只有：

```text
db_state_000358
db_state_000359
db_state_020746
db_state_021244
```

其中 `db_state_021244` 是 TNO0220 已记录的 node032 默认 Codex `0.145.0` 撤销启动审计状态，包含 4 个
generation cancellations，不能作为正式搜索状态。重启前的正确 `0.146.0` 运行虽已生成并排队四个候选，但尚无
evaluation 完成，所以没有发布比 `db_state_020746` 更新的 checkpoint。SimpleTES checkpoint 不持久化 pending
evaluation queue；这四个内存候选随重启丢失，恢复后将重新生成，不伪造为完成结果。

## 3. 精确恢复源与不变量

本次正式恢复源仍为：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/
principled_trbs_gpt56sol_max_fresh2_20260803_030316/
2026-08-03/instance-44cd457d/db_state_020746
```

恢复前重新核验的绝对状态：

| 项目 | 绝对值 |
| --- | ---: |
| generation attempts | `46 / 128` |
| generation failures / cancellations | `0 / 0` |
| completed evaluations / DB nodes | `40 / 40` |
| valid evaluations | `34 / 64` |
| evaluator failures | `0` |
| best score | `1.06814371190328` |

证据哈希与 TNO0220 的 node029 final exact checkpoint 相同：

| 对象 | SHA-256 |
| --- | --- |
| `metadata.json` | `35e34e71d1a568232af749cf1d22379e6dd6db1305854d1740df26e09793bc46` |
| `config.json` | `cda3473e6aca1e849b8d8659b9e4c5d2ce3fab8babb489c2d1602e620a851bcd` |
| `policy.json` | `59085f11b8ec4749d29ed2865fab566171061acbf9e778014c07bf7a3c792276` |
| `nodes.json` | `da253bdef68a3b0ffb13b8c6b684970f91a9c344212be4d52a5f7ef35213bb95` |
| `best_program.txt` | `5723e113bb1f9e0c6110153bca609d17d1310b34369a439162b75c4e2f2a3117` |

启动 dry-run 明确解析为 `--resume .../db_state_020746`、`--max-proposals 128`、`--valid-target 64`，
且不含 `--extend-resume-budget`。因此这是对同一搜索树的 exact restart，不是 fresh run，也没有把
`46/34` 当作新的相对预算起点。metadata 中的 `instance_id=3434e52a` 与目录名 `instance-44cd457d` 不同，仍是
TNO0220 已解释的既有 resume 标签漂移；nodes/config/policy/best 与恢复源哈希闭合。

## 4. 启动与运行身份

node032 重启后默认 `/usr/local/bin/codex` 仍是 `0.145.0`。正式命令在 source `env.sh` 后显式将：

```text
/nfs/home/tanghaojin/.nvm/versions/node/v24.18.1/bin
```

置于 `PATH` 首位；该 binary 实测为 `codex-cli 0.146.0`。运行参数保持：

- `gpt-5.6-sol / max`，`~/.codex/config.thj.toml` 与 `~/.codex/auth.thj.json`；
- generation/evaluation timeout `10,800 / 21,600 s`；
- ordinary retries `2`，capacity/transient exact-thread continuations `3 / 3`；
- `4 gen / 1 eval`。

第一次 post-reboot 启动尝试因远端只读 guard 的 shell 引号错误在创建 launcher 前 fail-close；没有进程、日志、
checkpoint 或搜索状态变化。修正 guard 后的正式运行身份如下：

| 对象 | PID / SID / PGID |
| --- | --- |
| node032 launcher | `18435 / 18435 / 18435`，PPID `1` |
| node032 main | `21161 / 18435 / 18435` |
| four Codex roots | `21808 / 21814 / 21820 / 21827`，各自 SID/PGID 等于自身 PID |

main 于 `17:12:49 +0800` 加载 `46 attempts / 40 evals / 40 nodes`，报告 `88 prompts` policy
headroom，并启动四个 generation worker。`17:13:19`、`17:13:49` 与 `17:14:19` 连续报告：

```text
gen workers: 4 active / 0 queued, eval workers: 0 active / 0 queued
```

四个 main direct children 的 executable/command line 均确认是 NVM `codex 0.146.0`、
`-m gpt-5.6-sol`、`model_reasoning_effort=max`，不是 node032 默认的 `0.145.0`。

## 5. 日志与后续判定

实例主日志继续追加在：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/
principled_trbs_gpt56sol_max_fresh2_20260803_030316/
2026-08-03/instance-44cd457d/run.log
```

本次 post-reboot launcher 日志为：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/
principled_trbs_gpt56sol_max_fresh2_20260803_030316/
launcher_resume_node032_postreboot_codex0146_gen128_valid64_20260806.log
```

后续只有通过 node032 本机 whole-CCD quiet、fixed-ASLR、CPU/NUMA/PMU、功能与成对 ABBA/BAAB gate 的
SimTop 50k walltime 才能形成性能结论；本次恢复动作本身不改变当前 best，也不授权保留或默认开启新的优化。
