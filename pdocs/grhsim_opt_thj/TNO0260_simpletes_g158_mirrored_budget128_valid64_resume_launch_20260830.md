# TNO0260：SimpleTES g158 mirrored 扩容到 128/64 并续跑

日期：2026-08-30

## 1. 阶段结论

`g158_native_mirrored_gpt56sol_max_fresh_20260827_195900` 已于
`2026-08-29 22:36:40 +0800` 正常达到累计 `32/32 valid` 后退出，不是崩溃、
超时或人工停止。本阶段从 finalize 后的精确 checkpoint 继续原有四条 search
chain，将绝对累计预算从 `64 generations / 32 valid` 单调扩展到
`128 generations / 64 valid`。

续跑已在 node030 启动；launcher 和 SimpleTES main 均存活，日志已确认 checkpoint
加载、预算扩展以及 `4 gen / 1 eval` 调度。当前尚无扩容后新增 candidate 完成
SimTop 50k，因此本记录不宣称新增性能收益。

## 2. 源 checkpoint 与结束状态

精确恢复源为：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/
  g158_native_mirrored_gpt56sol_max_fresh_20260827_195900/
    2026-08-27/instance-9733393b/db_state_223640
```

它是 finalization 最后发布的 canonical state。前一个 `db_state_223639` 内容相同，
但本次没有让 launcher 对 instance 目录再次执行“latest”选择，而是直接传入
`db_state_223640`。

最终持久化计数为：

| 字段 | 值 |
| --- | ---: |
| completed evaluations | `35` |
| valid evaluations | `32/32` |
| generation attempts | `44` |
| generation failures | `7` |
| generation cancellations | `0` |
| evaluation failures / rejects | `0` |
| best score | `1.0227358081756464` |
| best node | `6de5b2426b1a49ec9c762d5dafb6a94d` |

恢复文件的 SHA-256：

```text
metadata.json     2bf44683450344ba8c1e782dfd09d26c55d3292dd19a7a295eb7c6ad9876f7fc
config.json       5451d6e44297a6931bbcf0533858f1b071268b3a596e161c307d7981b6a95ed9
best_program.txt  49e8efeffd805d4a4d0aa6d30712f9ee87f12c76438722d4f589247283ae6750
nodes.json        d816fd5b279d60f78b05ddecfd319ef84bf90dcde2acec172641ac8cfb763f54
```

## 3. 扩容前 best 的性能边界

源 checkpoint 的 best 是 generation `38`、chain `3` 的候选，digest 为：

```text
e04bcaa5660bdb801115320c7d9101310357b1641998d03d5df36c3125e85cd5
```

schema-v3 同 CCD/CPU `ABBA+BAAB` 的绝对 walltime 为：

```text
ABBA control / candidate  45,457.50 / 44,489.50 ms
ABBA improvement          968.00 ms / 2.129461585%

BAAB control / candidate  43,047.50 / 42,048.00 ms
BAAB improvement          999.50 ms / 2.321853766%

pooled control            44,252.50 ms
pooled candidate          43,268.75 ms
pooled improvement        983.75 ms / 2.223038246%
order gap                 0.192392181 pp
```

八个样本固定在 `node0:32-39,224-231`、CPU `33`、sibling `225`，order gap
满足严格 `<0.25 pp`。以上是扩容前已有 best，只用于说明续跑起点，不是本阶段
新增结果，也不自动成为 Wolvrix 默认项。

## 4. 节点选择与失败启动审计

启动前对 node030--node032 进行了严格 3 秒 whole-CCD 扫描：

| 节点 | load 1/5/15 | 首轮通过 CCD | 主要外部负载 |
| --- | --- | ---: | --- |
| node030 | `66.60/59.15/57.33` | `0/24` | `59` 个 gem5、`1` 个 emu |
| node031 | `118.72/97.72/83.40` | `2/24` | `53` 个 gem5、`6` 个 emu |
| node032 | `98.61/116.57/104.32` | `0/24` | `53` 个 gem5、`34` 个 emu |

node031 的两个 CCD 连续两轮通过，其中 `node0:40-47,232-239` 复测
`mean/min=98.874/98.000%`，因此首先尝试 node031。但 evaluator toolchain
preflight 立即拒绝启动：node031 缺少与 clang 19 匹配的
`clang-scan-deps-19`。失败 launcher PID `422224` 已退出，只留下 `106` bytes
日志，SHA-256 为
`772ed58f239abf52c32ec836ef917e1704546c81a021a51e5f3251c51a4c4760`；它没有
进入 `main.py`、没有加载/修改 checkpoint，也没有消费 generation attempt。

node030 已安装并验证 `/usr/bin/clang-scan-deps-19` 与 clang `19.1.1` 匹配；
同时它在剩余两个可用节点中外部 emu 数更少，因此正式续跑转到 node030。
启动快照没有可立即测量的 passing CCD，不据此放宽门禁；runtime 仍会在每次
evaluation 前动态扫描，并在没有完整空闲 CCD 时返回 retryable infrastructure，
不会把污染样本计入 valid。

## 5. 扩容参数与启动证据

只把 valid 从 `32` 提到 `64`、保留原 `64` proposal 上限在数学上不可行：源
checkpoint 已消费 `44` 次尝试，只剩 `20` 次，少于还需要的 `32` 个 valid。
因此沿用此前 `64/32 -> 128/64` 的同类扩容口径：

```text
resume                     exact db_state_223640
extend-resume-budget       enabled
max generations            64 -> 128 (absolute cumulative limit)
max valid evaluations      32 -> 64  (absolute cumulative limit)
model / effort             gpt-5.6-sol / max
config / auth              ~/.codex/config.thj.toml / ~/.codex/auth.thj.json
generation workers         4
evaluation workers         1
generation timeout         10,800 s
evaluation timeout         21,600 s
normal exec retries        2
capacity/transient continue 3 / 3
GRHSIM_INFRA_RETRIES       8
GRHSIM_BUILD_JOBS          4
```

SimpleTES commit 为 `e107401b95ceec3b2fdad33742abb4d12b80547f`，启动时
工作树 clean。launcher 的 capability/toolchain/pin/schema 检查均通过；日志在
`2026-08-30 00:31:33 +0800` 明确记录：

```text
Checkpoint Loaded
Instance: 9733393b
Attempts: 44 | Gen fails: 7 | Gen cancels: 0 | Eval rejects: 0 | Evals: 35
DB nodes: 35 | Chains: 4/4 with nodes
Budget extension: generations 64->128 | valid 32->64
Starting 4 gen workers and 1 eval workers
```

运行入口：

```text
host: node030
launcher PID: 519075
main PID: 532465
output root:
SimpleTES/checkpoints/grhsim_simtop_50k/
  g158_native_mirrored_extend128_valid64_node030_20260830_003100/
    launcher.log
    launcher.pid
```

## 6. 后续判定边界

- 这是同一 research tree 的 exact resume，不是 fresh run，也没有把 best 变成新
  baseline；原 control、节点、分数、失败历史和四条 chain 全部保留。
- 扩容后的后续 checkpoint 必须记录 `64->128 / 32->64` 的 budget extension；
  若进程中断后按相同上限重启，应传精确 `128/64`，但不再重复传
  `--extend-resume-budget`。
- 最终性能仍只接受关闭 ASLR、同 CCD/CPU `ABBA+BAAB`、order gap `<0.25 pp`
  且通过功能、NUMA、PMU 和连续负载门禁的 SimTop 50k walltime。
- 新 candidate 的搜索分数不等于生产落地结论；仍需消融、fresh 前后回归和默认
  配置验证后，才能决定是否进入 Wolvrix。
