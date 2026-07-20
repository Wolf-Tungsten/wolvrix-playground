# TNO0162 SimpleTES best-seed continuation launch and attribution gate

记录日期：2026-07-20

状态：fresh continuation instance `4269c986` 已启动，且已完成初始 seed 的
unpatched emit、default-off build 和小负载功能 gate；enabled build 正在进行。本文只记录
启动与输入归因阶段，不把上一 instance 的结果冒充本轮结果，也不提前作默认采用结论。

前置的输入稳定化实现和启动契约见
[TNO0161](./TNO0161_simpletes_fingerprint_input_stabilization_and_best_seed_continuation_20260720.md)。
上一轮候选的性能信号和未采用原因见
[TNO0160](./TNO0160_simpletes_first_formal_search_results_and_default_decision_20260720.md)。

## 1. Instance and command

本轮不是对已耗尽预算的 `91f6580e` 做 resume，而是用上一轮 best program 作为初始节点，
重新打开一个独立预算。启动时间为 `2026-07-20 18:23:31 +08:00`：

```text
instance                 4269c986
checkpoint root          SimpleTES/checkpoints/grhsim_simtop_50k/formal_20260720_02
init program             .../formal_20260720_01/.../instance-91f6580e/db_state_161238/best_program.txt
seed digest              842fb6de071cbe880c582b00e0ce653fd1a907662b2b2b942d1459436a418e19
model / reasoning        gpt-5.6-sol / ultra
selector / chains        rpucg / 4
generation / eval        1 / 1 worker
new proposal budget      16
valid-candidate target   8
```

launcher 使用目标仓库的 `env.sh` 后调用 SimpleTES 自带 `.venv/bin/python`；API 配置和认证
仍分别来自 `~/.codex/config.mjy.toml` 与 `~/.codex/auth.mjy.json`，不会写入 argv、日志或
checkpoint。运行时继续使用动态空闲 CCD、关闭 ASLR、NUMA-local first-touch、迁移/PMU 审计，
最终指标仍是 SimTop 50k 的 `Host time spent` walltime。

seed 本身只修改 `lib/emit/grhsim_cpp.cpp`，并声明
`active_mask_gap_pack_policy=targeted-table-contiguous`；它是搜索起点，不是已接受的默认
配置。initial evaluation 不占用本轮 proposal 或 valid-candidate 配额。

## 2. Generation-input attribution gate

修复 commit `c7f0cef`（父仓库文档提交 `c7eeca7`）在 candidate checkout 的任何 emit 前，
把 control 的生成输入复制到 candidate 私有 inode，并在三个阶段复核 manifest。此次实时
复核得到 control/candidate 完全一致：

| input set | absolute files | fingerprint |
| --- | ---: | --- |
| control generation inputs | `2,103` | `e9ca0efd737dcc0b7a7e145059fce052fd5729abe34df43d8e4b10e1a84154ab` |
| candidate staged inputs | `2,103` | `e9ca0efd737dcc0b7a7e145059fce052fd5729abe34df43d8e4b10e1a84154ab` |

其中包括 `2,097` 个 RTL `.sv/.v` 和 `6` 个 XiangShan difftest generated-source 文件；
`.fir` 与 metadata 不纳入本 gate。candidate 日志中没有再次运行 XiangShan `sim-verilog`
或 `xs_simverilog`，所以这次 attribution 使用的是同一份已 elaborated 输入，而不是独立
重生成的上游快照。

## 3. Initial seed progress

截至本记录形成时，初始 seed 的阶段结果如下。小负载数值是诊断 gate，不是 50k headline：

| phase | absolute result | status |
| --- | --- | --- |
| unpatched same-options emit | completed at `18:52` | pass |
| disabled build | completed at `19:17` | pass |
| disabled focused tests | `24 passed` | pass |
| disabled 100-cycle function | `Host time spent: 190 ms` | pass |
| disabled 10,000-cycle function | `Host time spent: 11,968 ms` | pass |
| default-off generated fingerprint | byte-exact after disabled phase | pass |
| enabled build | started after `19:17:56` | in progress |
| enabled 50k ABBA/BAAB | no new result yet | pending |

`evaluation_842fb6de071cbe88.json` 和对应 `runtime_result` 在 slot 中仍有一个 mtime 为
`12:52` 的旧文件，属于 instance `91f6580e`；在新 run log 出现 `Initial score` 或文件
mtime 晚于本轮启动前，不得将其引用为 `4269c986` 的 walltime。当前因此没有新增绝对
50k 数值、相对变化或默认开启结论。

## 4. Next gate and decision rule

enabled build 完成后，evaluator 仍须完成 enabled focused/100/10k、manifest 复核和独立
SimTop 50k ABBA；只有通过后才会把 initial score 交给 SimpleTES scheduler，并继续提出
候选。每个候选都必须通过同一套 default-off byte fingerprint 和 enabled functional gate；
最终只保留端到端 walltime 正向且满足 order/quiet-CCD/ASLR/NUMA/PMU 约束的修改。低于可信
线、无法形成完整 ABBA/BAAB，或仅有静态代码收益的候选均保持 default-off。

本阶段的结论是“continuation 已真实启动且输入归因 gate 已闭合”，不是“seed 已重新验证为
性能正向”。后续 enabled 复评、scheduler 状态和候选结果另立增量 TNO。
