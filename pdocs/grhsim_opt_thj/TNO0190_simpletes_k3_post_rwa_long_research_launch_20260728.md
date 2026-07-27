# TNO0190 SimpleTES K3 post-RWA long research launch

## 1. 阶段目标与当前结论

本阶段在 R/W/A 已落地并默认开启的 Wolvrix 基线上，继续启动 GrhSIM SimTop-50k auto research。
按用户要求，本轮使用上一阶段已验证的 Kimi Codex-compatible `k3/ultra`，并把搜索预算扩展为
`64 proposals / 32 valid evaluations`，不再只跑 8 个 valid 候选。

截至 `2026-07-28 00:56 +08:00`，启动状态为 `RUNNING`：

- 只创建了一个新实例 `instance-583068cb`；
- launcher、SimpleTES scheduler 和 initial evaluator 进程均存活；
- `main.py` 实际 argv 与初始化日志均确认 `k3/ultra`、`codex_exec` 和 Kimi config/auth；
- initial control evaluator 已取得 slot，并在隔离 control 环境中刷新 virtualenv、轮询动态 CCD；
- 当前还没有 initial 50k walltime、generation、valid candidate 或性能结论；
- 不据此保留任何新 patch，也不改变 Wolvrix 默认配置。

## 2. 为什么必须 fresh 启动

正式启动前逐一审计了 `checkpoints/grhsim_simtop_50k` 下已有的 6 个历史 instance，并使用 launcher 的
resume contract 做 fail-close 核查。当前生产契约是 schema v2，固定：

- parent executable pin：`d31118bea0feb563ad09476e1419f0f15aaf574f`；
- Wolvrix pin：`16a9f493687a...`；
- SimpleTES：`b73f399d703e162fb571e103a5df19a832c58029`。

历史状态不能用于本轮：

| 历史类别 | 数量 | 审计结果 |
| --- | ---: | --- |
| 仅初始化、无 checkpoint | `1` | 没有可恢复 state |
| schema v1，旧 pin `b90d204... / f17e90e...` | `4` | 与当前契约不兼容，resume fail-close |
| schema v2，pre-RWA pin `fbe4e1c... / 8f6ba14...` | `1` | 与 landed-RWA pin 不兼容，resume fail-close |

因此本轮没有传 `--resume`，也没有从历史 best program 取 seed，而是从当前仓库 checked-in 的空
`init_program.txt` fresh 启动。启动前 validate-only 结果为：

```json
{"candidate_digest":"345fe98fbbc4ff3b284117723d9f535b780fc137d4ea3f830540343510a2f41e","candidate_mode":"control","enable_options":{},"files":[],"valid":true}
```

这保证 initial control 就是当前 Wolvrix 通用默认生成配置，而不是把 pre-RWA patch 重放到新基线上。

## 3. 本轮代码与配置身份

| 项目 | 身份 |
| --- | --- |
| parent checkout 启动前 HEAD | `f618a282a92b1cc1f4a839412df3210c3325ed19` |
| evaluator executable parent pin | `d31118bea0feb563ad09476e1419f0f15aaf574f` |
| Wolvrix pin | `16a9f493687a21a5428f1e1327a69834ea60c9f5` |
| SimpleTES commit | `b73f399d703e162fb571e103a5df19a832c58029` |
| launcher SHA-256 | `8f84a040c5e09fe2a1b46efe5d352f3a599202b181293c85810bf55de2771976` |
| evaluator SHA-256 | `0fbdc274d87a3ff115bc8f2a7ec016970cb9124dbd2c2db752602468341414ce` |
| runtime SHA-256 | `fd3bb81b7295f90aed63ef6a829277563be4093ea26f76be22d6927f36f93f97` |
| init program SHA-256 | `b84fe01370487126f8a4fae35bf73dc1d7b89072dab38c6d172e9b1a20ccadae` |
| candidate schema SHA-256 | `c5654f3f008baa2c14e973bdbae2fa33ade3fac295bb9710694462ba051b72c2` |
| Kimi config SHA-256 | `45b47402163f54038c2c6a7b5746f37b1fc511a0e8b1052b034757ebb2d9bff9` |

Kimi config 路径为 `~/.codex/config.kimi.toml`，auth 路径为 `~/.codex/auth.kimi.json`。auth 文件内容、
API key、key 长度和 auth 哈希都没有写入本文、命令日志或 checkpoint。

启动时 parent worktree 只包含既有的 Wolvrix 子模块 dirty 状态；Wolvrix 中既有用户修改仍是
`.gitignore` 与 `external/mt-kahypar`，本阶段没有改动或清理它们。

## 4. 搜索与评测契约

正式参数如下：

| 参数 | 绝对值 |
| --- | ---: |
| model / provider / reasoning | `k3 / kimi / ultra` |
| backend | `codex_exec` |
| selector | `rpucg` |
| chains / candidates per chain | `4 / 1` |
| prompts per chain | `16` |
| max generations/proposals | `64` |
| max valid evaluations | `32` |
| generation / evaluation concurrency | `1 / 1` |
| initial evaluation repeats | `1` |
| LLM timeout | `5,400 s` |
| evaluator timeout | `21,600 s` |
| max output tokens | `32,768` |
| evaluator infra retries | `8` |
| build jobs | `4` |
| checkpoint interval | 每 `1` 次 evaluation |
| reflection | `OFF` |
| LLM I/O checkpoint | `ON` |

性能裁决契约保持不变：最终 headline 是 SimTop 50k 日志中的 `Host time spent` walltime；动态选择通过
strict whole-CCD quiet gate 的 CPU；运行前和运行中都核查 CPU/NUMA/PMU/功能；实际 emu 命令使用
`setarch x86_64 -R`，personality 必须为 `00040000`。非 control 候选只有同时完成 `ABBA` 和 `BAAB`
两种顺序的 paired measurement，才会被接受为正式性能结果。没有端到端 walltime 正收益的修改不能默认开启。

## 5. 唯一实例与后台生命周期

本轮输出根目录为：

```text
/nfs/home/tanghaojin/wolvrix-SimpleTES-workspace-5/SimpleTES/checkpoints/grhsim_simtop_50k/k3_rwa_fresh_20260728_005300
```

实例目录为：

```text
2026-07-28/instance-583068cb
```

后台使用独立 session 的 `nohup setsid` supervisor，并以 mode `0700/0600` 创建目录和日志。启动检查点的
进程关系为：

```text
PID 2403019  supervisor/session leader
└─ PID 2403212  GrhSIM launcher.py
   └─ PID 2403213  SimpleTES main.py
      └─ PID 2406701  initial control evaluator.py
```

`launcher.pid` 保存 supervisor PID `2403019`。运行期间 `launcher.exit` 应不存在；supervisor 会在 launcher
自然结束后将真实退出码原子写入该文件。启动检查点确认 supervisor 的 parent 为 PID 1、上述进程共享 session
`2403019`，因此发起本次工作的交互 shell 退出不会带走研究进程。

第一次封装后台命令时，shell 的 `&` 优先级使局部路径变量没有进入预期分组，写 `launcher.pid` 时在
`/launcher.pid` 立即报 permission denied。随后立即核查：目标 output root 不存在，也没有来源于该路径的
launcher/main 进程，因此该次没有创建 instance、没有调用模型、没有进入 evaluator。修正分组后只执行了
一次正式启动，最终只存在上述 `instance-583068cb`。

## 6. 启动后的真实活动证据

`launcher.stdout.log` 和 instance `run.log` 已输出 SimpleTES Initialization panel，明确记录：

- instance ID `583068cb`；
- model `k3`、backend `codex_exec`、reasoning `ultra`；
- workers `gen=1 / eval=1`；
- budget `max_generations=64 / max_valid_evaluations=32`；
- timeouts `eval=21600s / LLM=5400s`；
- checkpoint interval 1、save LLM I/O enabled。

initial evaluator 已在 `/tmp/simpletes-grhsim-simtop-50k/02d8ec0c5cbeb4ef/slot-0` 工作。检查点时可见：

- isolation control virtualenv 文件在 `00:54..00:55` 持续刷新；
- evaluator 反复运行 `mpstat -P <动态 CCD CPUs> 1 3`，候选 CCD 范围随 survey 改变；
- evaluator 仍存活且处于正常 poll/wait 状态，不是僵尸进程；
- 尚未生成 `db_state_*` 或 initial runtime JSON，故当前 generation/valid 绝对值仍为 `0/0`。

这只证明真实 evaluator 已开始工作；不能把旧 slot 中留下的历史 runtime JSON 当成本轮 initial 结果。

## 7. 后续监控入口与阶段裁决

后续应从以下入口监控同一实例，不应另启新实例：

- `launcher.stdout.log`：launcher 与 scheduler 汇总输出；
- `2026-07-28/instance-583068cb/run.log`：实例日志；
- `2026-07-28/instance-583068cb/db_state_*`：每个已发布 checkpoint；
- slot `results/attempts/<digest>`：不可变 evaluator/runtime attempt；
- `launcher.exit`：只在正式轮次结束后出现的真实退出码。

本阶段裁决是：post-RWA K3 长轮次已按用户指示正式开始且当前仍在运行；没有恢复不兼容历史状态，也没有
启动第二个实例。由于 initial control 尚未完成，当前没有任何新的绝对 walltime、相对提升或代码保留结论。
下一次汇报应继续审计本实例的 checkpoint、accepted ABBA/BAAB walltime 和实际 patch，而不是仅凭日志静默
判断结束。
