# TNO0257：SimpleTES post-g158 GPT max fresh research 启动

日期：2026-08-27

## 1. 阶段结论

在 g158 完成 Wolvrix 默认落地、fresh 功能回归和 SimTop 50k walltime 门禁后，
已从新的 post-g158 空 control 启动一轮独立 SimpleTES auto research。本轮不是
旧 checkpoint resume，也没有把历史 best patch 重复叠到已经落地的 baseline。

正式实例运行在 `node030`：

```text
output root:
SimpleTES/checkpoints/grhsim_simtop_50k/g158_native_gpt56sol_max_fresh_20260827_170020

instance:
2026-08-27/instance-0c4c9416

launcher PID / session:
3856760 / 3856760
```

launcher 已脱离 SSH，parent 为 PID 1；SimpleTES main 和初始 control evaluator
均已实查运行。当前阶段尚无 initial control walltime、candidate、valid count 或
best score，不从正在进行的构建推断性能结论。

## 2. 节点选择

启动前只在 `node030..node032` 范围内检查。整机负载和 runtime 同口径的严格
3 秒 whole-CCD gate 均指向 node030：

- node030 连续扫描分别有 `10/24`、`18/24` 个 CCD 通过；后一轮选择
  `node0:72-79,264-271`，mean idle `99.77125%`、min idle `99.00%`，
  target/sibling 均为 `100%`。另一份同口径快照有 `20/24` 通过。
- node031 在可比快照中为 `0/24`，同时存在多批 gem5/gsim 和 RemoteDev
  workload。
- node032 虽在一个瞬时快照中有 `13/24` 通过，但另一个快照为 `0/24`，且有
  高并发 CI Java/firtool/emu，负载波动明显大于 node030。

因此选择 node030，node032 仅作为后续负载恶化时的备选。上述扫描只读，不会
固定 evaluator 的运行 CPU；正式 runtime 仍由每次 evaluation 重新执行严格
whole-CCD/连续负载门禁。

## 3. Baseline 与 SimpleTES 身份

| 项目 | 值 |
| --- | --- |
| SimpleTES commit | `d1b689608751faf757ffd7c3eafc322f5d4e37eb` |
| pinned parent | `6e2436e37286264e9f03f114d14d81bae4ed313b` |
| pinned Wolvrix | `054c6a7c09b007a12eb36fdb49fcb659a1bfc590` |
| init seed SHA-256 | `dd49c2259376e764bfd6756bc1beac1941be731f93d1f6b82ae1ba28d1c997ae` |
| init mode | post-g158 schema-v2 empty `control` |

该 control 已包含 R/W/A、four-positive、原则化 hot-event、typed-state 和 g158
等已落地通用默认优化。instruction 明确禁止重新提议这些方向，也禁止 SimTop、
benchmark 或变量名匹配。旧 parent/Wolvrix pin 的 checkpoint 继续 fail-close。

## 4. 模型与预算

本轮显式参数为：

| 参数 | 值 |
| --- | --- |
| model / effort | `gpt-5.6-sol` / `max` |
| config / auth | `~/.codex/config.thj.toml` / `~/.codex/auth.thj.json` |
| generation / valid budget | `64` / `32` |
| workers | `4 gen` / `1 eval` |
| chains / candidates per chain | `4` / `1` |
| generation timeout | `10,800 s` |
| evaluation timeout | `21,600 s` |
| evaluator infra retries | `8` |
| build jobs | `4` |
| normal Codex retries | `2` |
| capacity / transient continuations | `3` / `3` |
| output mode / tool choice | `provider-structured` / `auto` |

GPT 路径没有接收 K3-only instruction suffix、model catalog 或 subagent cap；
因此不会干扰 GPT 5.6 Sol 自己的代理调度。config/auth 权限均为 `0600`，本文不
记录任何 secret 内容。

## 5. 启动门禁与勘误边界

使用 `SimpleTES/.venv/bin/python` 的真实 capability preflight 已通过：

```text
model=gpt-5.6-sol
effort=max
repo_tool_calls=1
model_catalog=native
response_chars=632
```

正式 launcher 又独立完成一次相同 capability gate，并先通过 evaluator toolchain
gate：compiler `/usr/bin/clang++`、scanner `/usr/bin/clang-scan-deps-19`、major
`19`。launcher log 随后确认 main 的 `64/32`、`4 gen/1 eval` 和
`gpt-5.6-sol/max` 参数。

首次人工 preflight 误用了 workspace 顶层 `.venv`，在导入 `simpletes` 时即以
`ModuleNotFoundError` 退出；它没有调用 API、没有创建 research instance，也
没有改变任何 checkpoint。切换到仓库自己的 `SimpleTES/.venv` 后才执行并通过
上述正式 preflight。

## 6. 后续观察入口

```text
SimpleTES/checkpoints/grhsim_simtop_50k/
  g158_native_gpt56sol_max_fresh_20260827_170020/
    launcher.log
    launcher.pid
    2026-08-27/instance-0c4c9416/run.log
```

后续只接受关闭 ASLR、通过动态 whole-CCD/NUMA/PMU/功能审计的 SimTop 50k
`Host time spent` walltime。节点若持续失去空闲 CCD，可以在 node030..node032
范围内迁移，但不得把受污染样本计为 candidate 性能结果。

## 7. 增量更新：本实例已作废

2026-08-27 后续审计发现 initial empty control 在同一 ELF 上给出了
`0.9845841078`，唯一候选的 ABBA/BAAB improvement 又相差 `0.513323 pp`，且
两组重新选择了不同 CPU。实例已于 `19:19:08 +08:00` 按指示终止，最终冻结在
`db_state_191910`；该树不再 resume、seed 或用于 landing。根因、完整绝对数据、
schema-v3 修复与有效性边界见
[TNO0258](./TNO0258_simpletes_control_bias_invalidation_and_mirrored_protocol_fix_20260827.md)。
