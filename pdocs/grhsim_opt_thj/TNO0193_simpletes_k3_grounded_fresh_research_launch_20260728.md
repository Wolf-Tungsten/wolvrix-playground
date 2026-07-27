# TNO0193 SimpleTES K3 grounded fresh research launch

## 1. 阶段结论

在 [TNO0192](./TNO0192_simpletes_k3_grounded_generation_fix_and_capability_gate_20260728.md)
完成 K3 grounded generation 修复和约 `36 s` 的真实能力检查后，本阶段启动新的 post-RWA fresh auto
research。正式实例为：

```text
root:     SimpleTES/checkpoints/grhsim_simtop_50k/k3_rwa_grounded_fresh_20260728_032742
instance: 2026-07-28/instance-7291c6c2
started:  2026-07-28 03:28:58 +08:00
```

截至本记录形成时，detached supervisor、launcher、SimpleTES scheduler 和 initial-control evaluator 均仍在运行；
`launcher.exit` 尚不存在。当前阶段只确认新的 deterministic capability gate 与启动输入 TOCTOU gate 通过，并进入
首次 SimTop 50k control；尚未生成或评测本轮候选，因而没有新的 candidate walltime、性能提升、Wolvrix 修改或
默认开关结论。

## 2. 固定输入与启动配置

本轮固定提交为：

```text
SimpleTES: 88abf71ee466dceeca7e3abe4537af73820f47b0
parent:    5a273817f7e8b10810bccb7df417b77d0a495682
Wolvrix:   16a9f493687a21a5428f1e1327a69834ea60c9f5
```

启动配置如下：

| 项目 | 值 |
| --- | --- |
| model / effort | `k3 / ultra` |
| backend | `codex_exec` |
| config / auth | `~/.codex/config.kimi.toml` / `~/.codex/auth.kimi.json` |
| output / tool mode | `local-json / required-first` |
| proposals / valid target | `64 / 32` |
| generation / evaluation concurrency | `1 / 1` |
| generation timeout | `5,400 s` |
| preflight timeout | `600 s` |
| evaluation timeout | `21,600 s` |
| max output tokens | `32,768` |
| infrastructure retries | `8` |
| build jobs | `4` |

正式 generation 的 `5,400 s` 上限只用于开放式代码与性能研究；启动前 capability gate 仍是
[TNO0192](./TNO0192_simpletes_k3_grounded_generation_fix_and_capability_gate_20260728.md) 的确定性 smoke
任务，不再占用正式 generation 的长时间上限。launcher 只有在 capability gate 和 preflight 前后输入 digest
一致后才会 spawn `main.py`；因此 instance 目录已经出现可作为两项启动 gate 均通过的结构证据。

## 3. 运行与性能协议

initial control evaluator 已进入正式 runtime。现场进程显示实际执行链包含：

```text
perf stat ... -- setarch x86_64 -R .../emu ... -C 50000
```

这确认 50k 仿真使用 `setarch x86_64 -R` 关闭地址随机化，并由 evaluator 在运行前进行 CPU/CCD 空闲检查；
最终性能口径仍为 SimTop 输出的绝对 `walltime_ms`。本轮继续使用 post-RWA native default 作为 control，候选只有
在功能、结构/证据和端到端 50k walltime 门禁通过后才可能保留。

首次 detach 命令在创建输出目录前因 shell 后台操作符结合方式提前返回；核对后确认它没有创建 instance、没有启动
launcher，也没有留下进程。随后先显式创建唯一输出目录，再启动上述 supervisor；当前只有
`instance-7291c6c2` 一个正式实例，没有并行或重复研究轮次。

## 4. 下一检查点

下一阶段必须单独记录：

1. initial control 的绝对 50k walltime 与完整 quiet-CCD/ASLR/NUMA/perf/功能门禁结果；
2. 第一条正式 K3 response 是否包含非 placeholder、可 clean apply 的 Wolvrix diff，以及 required-first repo tool
   约束是否在真实研究 prompt 下生效；
3. 候选若进入 evaluator，则记录 build、100/10k/50k 功能与 control/candidate 绝对 walltime；
4. 本轮结束或被显式停止时，再按持久化 output、valid evaluation 和性能结果汇总，不以生成文本长度代替性能结论。
