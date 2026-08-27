# TNO0259：SimpleTES 修正协议 fresh restart 与 initial control

日期：2026-08-27

## 1. 阶段结论

在 TNO0258 作废旧 research 树并提交 SimpleTES 协议修复后，已在 node030--node032
中重新扫描负载，并选择当时最适合的 node032 启动独立 fresh run。新实例没有
resume、没有 seed 旧 best，也没有复用旧 `/tmp` slot；它从当前 post-g158
baseline 的 RTL 流程重新构建 control。

```text
output root:
SimpleTES/checkpoints/grhsim_simtop_50k/
  g158_native_mirrored_gpt56sol_max_fresh_20260827_195900

instance:
2026-08-27/instance-9733393b

node:
node032.bosccluster.com

launcher PID / session:
3308303 / 3308303 (parent PID 1)

SimpleTES main PID:
3312973
```

launcher、main 和 generation workers 仍在运行；`run.log` 已进入
`4 gen / 1 eval` 调度。当前只确认 initial control 和启动状态，不把尚未完成的
candidate generation 当成性能结果。

## 2. 节点选择与启动参数

启动前对 node030、node031、node032 都执行了 `env.sh` 后的只读拓扑/进程检查和
whole-CCD 3 秒采样。可比快照如下：

| 节点 | 通过 CCD | 最佳落点摘要 | 负载观察 |
| --- | ---: | --- | --- |
| node030 | 10/24 | target `CPU41`，mean/min/target/sibling `99.458/98.67/99.67/100%` | `21` 个 emu、clang++，整机较忙 |
| node031 | 2/24 | target `CPU3`，mean/min/target/sibling `99.751/99.33/100/99.67%` | gem5 约 `48` 个，load `83..107` |
| node032 | 13/24 | `node1:120-127,312-319`，四项均 `100%` | 虽有 CI emu，但目标 CCD 连续复测全空闲 |

因此选 node032。正式 runtime 没有固定使用扫描时的落点，而是每个 evaluation
重新执行动态 whole-CCD gate；最终 initial control 选择了另一个当时更安静的
`node0:16-23,208-215`。

本轮显式参数：

```text
model / effort       gpt-5.6-sol / max
config / auth        ~/.codex/config.thj.toml / ~/.codex/auth.thj.json
budget               64 proposals / 32 valid
concurrency          4 generation / 1 evaluation
generation timeout   10800 s
evaluation timeout   21600 s
infra retries        8 (最多 9 次 runtime attempt)
normal retries       2
capacity/transient   3 / 3 exact-thread continuations
```

独立 capability preflight 先通过 `repo_tool_calls=1`、原生 GPT model catalog、
结构化候选和 pinned blob 校验；正式 launcher 的第二次 TOCTOU preflight 也通过。
config/auth 未进入日志或 checkpoint。

## 3. Fresh control 构建身份

control 首次构建从 RTL 开始，未使用旧 FIRRTL/ELF。构建过程依次完成 RTL、
`hier-flatten`、`comb-lane-pack`（`4159` groups）、`comb-loop-elim`、
`reg-to-mem`（`4318/4318`）和 C++ sched object 编译，最终功能门禁通过。

```text
parent commit       6e2436e37286264e9f03f114d14d81bae4ed313b
wolvrix commit      054c6a7c09b007a12eb36fdb49fcb659a1bfc590
control ELF SHA-256 4b719bd1f30f0c409b48a54797efd6bb1d30b5dad687a952457ef553e6831b8c
control image SHA    c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e
control NEMU SHA     094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e
ELF size             83,517,504 bytes
```

## 4. Initial control 的三次 runtime invocation

新的 evaluator 对 empty control 也执行完整 `ABBABAAB` 八样本组。前两次完整
invocation 被正确判为 retryable，第三次在第 6 个内部 attempt 成功。失败组的
样本和诊断均保存在 `/tmp/simpletes-grhsim-simtop-50k/.../attempts/`，没有计入
valid 或 score。

### 4.1 第一次 invocation：order gap 超门槛

同一组的绝对样本为：

```text
ABBA: control [43213, 42909] ms, candidate [42946, 42931] ms
      improvement = +0.284480156%
BAAB: control [42949, 42919] ms, candidate [42911, 43083] ms
      improvement = -0.146736852%
pooled self-bias = +0.069190069%
order gap         = 0.431217008 pp
```

虽然 pooled 偏差很小，但 gap 不满足严格 `<0.25 pp`，整组作废。其余 8 次
内部 attempt 因外部负载或无 CCD 通过而退出，最终未返回可接受结果。

### 4.2 第二次 invocation：同样作废

```text
ABBA: control [43613, 43146] ms, candidate [43521, 43242] ms
      improvement = -0.004610807%
BAAB: control [43199, 43919] ms, candidate [43127, 43154] ms
      runtime recorded gap = 0.965376 pp (group rejected)
```

runtime 的正式诊断记录为 `mirrored order gap 0.965376 pp`，超过门槛；该
invocation 的其它 attempt 也多次遇到 fixed-CCD pre-gate 失败，整组不计入
initial score。所有样本文件仍保留在本地 slot 供审计。

### 4.3 第三次 invocation：schema-v3 control 通过

最终通过的组固定在：

```text
CCD       node0:16-23,208-215
NUMA      0
target    CPU16
sibling   CPU208
helper    CPU96
```

八个样本的 process audit 全部是 `cpus_allowed_list=[16]`、
`expected_cpu=16`，ASLR、NUMA、PMU、功能和连续 monitor gate 全部通过。绝对
`Host time spent` 如下：

| index | role | walltime (ms) |
| ---: | --- | ---: |
| 1 | control | 42,928 |
| 2 | candidate-control | 42,921 |
| 3 | candidate-control | 42,814 |
| 4 | control | 42,719 |
| 5 | candidate-control | 42,684 |
| 6 | control | 42,726 |
| 7 | control | 42,860 |
| 8 | candidate-control | 42,835 |

按 order 聚合：

```text
ABBA control mean       42,823.50 ms
ABBA candidate mean     42,867.50 ms
ABBA improvement        -44.00 ms / -0.102747323%

BAAB control mean       42,793.00 ms
BAAB candidate mean     42,759.50 ms
BAAB improvement        +33.50 ms / +0.078283831%

order gap               0.181031155 pp
raw pooled control      42,808.25 ms
raw pooled candidate    42,813.50 ms
raw self-bias           -5.25 ms / -0.012263991%
```

`0.181031155 pp < 0.25 pp` 且 `0.012263991% < 0.25%`，所以 evaluator 将该
empty control 的语义 score 归一为精确 `1.000000`，同时保留上述 raw 数据：

```text
normalized combined_score = 1.0
normalized walltime pair  = 42,810.875 / 42,810.875 ms
normalized delta           = 0 ms / 0%
runtime/evaluation schema  = 3
```

这不是宣称 control 有性能提升；它表示 baseline 通过了同码自检后以中性分数
进入搜索。`run.log` 随后记录：

```text
(21:32:54) Initial score: 1.000000
(21:32:54) Starting 4 gen workers and 1 eval workers
```

## 5. 有效性边界与后续入口

- TNO0257 的旧 instance `0c4c9416`、其 `0.9845841078` initial score 和
  `1.0041417447` best 均已由 TNO0258 明确作废；新实例不读取其 checkpoint。
- TNO0256 的 g158 正式落地回归 `43,702.00 -> 42,959.00 ms`、
  `1.700151%` 仍然是有效的生产性能结论。
- 当前新 research 尚无 candidate 50k walltime；只有通过后续同一 schema-v3
  evaluator 的八样本组、严格双 order gap 和所有机器门禁的结果才可计入
  `valid` 或 best。
- SimpleTES bench 修复提交为
  `e107401b95ceec3b2fdad33742abb4d12b80547f`；本轮启动时工作树干净。
- 前置作废记录对应的 parent 文档提交为 `7fef9c6d9d725f190f232ad7830f8e6ac4c9cb70`；本记录随本阶段文档提交归档。

后续观察入口：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/
  g158_native_mirrored_gpt56sol_max_fresh_20260827_195900/
    launcher.log
    launcher.pid
    2026-08-27/instance-9733393b/run.log
```
