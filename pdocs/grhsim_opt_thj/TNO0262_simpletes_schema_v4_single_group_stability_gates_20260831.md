# TNO0262: SimpleTES schema-v4 single-group stability gates

状态：node030 上正在扩容的 post-g158 SimpleTES 已优雅停止在 `49/64 valid`，并完成
schema-v4 单组稳定性门禁实现与回归。每个候选仍只运行一个同 CCD/CPU 的原子
`ABBABAAB` 八样本组；本阶段按用户决定**不**增加高分候选的第二个独立确认组，也未
重启 auto research。

## 1. 停止点与可恢复证据

活动任务位于 node030：

```text
launcher PID: 519075
main PID:     532465
output:       SimpleTES/checkpoints/grhsim_simtop_50k/
              g158_native_mirrored_extend128_valid64_node030_20260830_003100
```

向 main 进程发送 `SIGTERM` 后，`run.log` 记录 `Received SIGTERM`、`Stopping 5
workers`，并在原 instance 目录写出最终 checkpoint：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/
  g158_native_mirrored_gpt56sol_max_fresh_20260827_195900/
  2026-08-27/instance-9733393b/db_state_014436

valid candidates: 49/64
best score:       1.02273581
```

随后复查 node030、node031、node032，launcher、main、evaluator 与候选构建子进程
均已退出。node031 的旧 launcher 只留下缺少 `clang-scan-deps-19` 的 preflight 失败
记录，没有创建研究状态；node032 没有本轮任务。

## 2. 新的单组门禁

原 schema-v3 已有两个门禁：同一固定 CCD/CPU 上原子 `ABBABAAB`，以及 walltime
ABBA/BAAB 收益 gap `<0.25 pp`。它能拒绝历史 g158 `+4.566244%` 的
`4.893068 pp` order gap，但不能拒绝两个半组同时改变性能状态的情况：历史 gen38
`+2.223038%` 的 wall order gap 只有 `0.192392 pp`，同时 control/candidate 两个
半组的绝对水平却分别漂移 `5.446020%/5.642640%`。

schema-v4 保留原协议，并在同一八样本上增加以下 fail-closed 门禁；没有增加仿真
样本或自动复测：

| gate | 公式 | 严格门槛 |
| --- | --- | ---: |
| role block shift | `abs(mean(ABBA)-mean(BAAB))/pooled_mean`，control/candidate 分别计算 | `<1%` |
| role sample spread | `(max-min)/pooled_mean`，control/candidate 四样本分别计算 | `<2%` |
| cycles order gap | ABBA 与 BAAB 的 cycles 改善百分比之差 | `<0.5 pp` |
| wall/cycles gain gap | pooled walltime 与 pooled cycles 改善百分比之差 | `<0.5 pp` |
| user-cycles/task-clock proxy delta | pooled `cycles:u/task-clock` 的 candidate/control 差 | `<0.25%` |

一次失败会在 `failed_stability_gates` 和错误文本中同时列出全部超限项，并重跑完整
八样本组。wall/order/host-load 类失败继续返回 retryable infrastructure outcome，不消耗
valid candidate；生成候选若纯 PMU coherence 失败，则先用 evaluator 配置的重试预算
重跑（默认共三组）。如果预算内每个完整组都只失败 PMU coherence 门禁，便终止拒绝
该生成候选，避免候选固有的 cycles/wall 或 proxy 差异造成 SimpleTES 无限重试。
initial control 是同一 binary 自比较，不能套用“候选固有差异”，因此即使连续纯 PMU
失败也始终保留 infrastructure retry。若任一轮同时出现 wall 或环境门禁失败，也仍按
infrastructure outcome 处理。`task-clock` 的正数毫秒值、`msec` 单位、调度率和 CPU
利用率现在一并 fail-close；candidate 的 wall spread 百分比也正式进入 metrics。

这里的 `cycles:u/task-clock` 是 user-space cycles 与 task-clock 的比值，只作为频率
变化代理；task-clock 不是只覆盖 `cycles:u` 的严格同口径时间，因此文档和字段不再把
它称为严格的 effective frequency。

这是测量接受语义的变化，因此 runtime result、evaluation result 与 immutable attempt
版本由 `3` 升到 `4`。旧 `db_state_014436` 保留为只读研究档案；resume dry-run 明确
返回：

```text
checkpoint evaluator result schema differs from the current measurement contract:
expected=4, observed=[3]
```

后续探索必须 fresh 启动 schema-v4，或把同 pin 候选作为新的初始程序重新评价；不能
直接继承旧树的弱门禁分数。

## 3. 历史异常与稳定组回放

### 3.1 历史 g158 `+4.566244%`

把 TNO0247 的八份真实 perf 数值固化为回归 fixture。原始端到端 walltime 为
`43,564.25 -> 41,575.00 ms`，减少 `1,989.25 ms`、表面提升 `4.566244%`；schema-v4
回放结果为：

| metric | value | decision |
| --- | ---: | --- |
| wall order gap | `4.893068 pp` | FAIL |
| control/candidate block shift | `4.677000% / 0.447384%` | FAIL / PASS |
| control/candidate spread | `12.041984% / 3.102826%` | FAIL / FAIL |
| cycles order gap | `0.747245 pp` | FAIL |
| wall/cycles gain gap | `2.099721 pp` | FAIL |
| user-cycles/task-clock proxy delta | `2.200231%` | FAIL |

因此此前偶然达到 `+4.566244%` 的组会被第一层单组门禁直接拒绝。

### 3.2 历史 gen38 `+2.223038%`

原始 walltime 为：

```text
C,B,B,C,B,C,C,B = 47452,45111,43868,43463,42029,42684,43411,42067 ms
pooled: 44252.50 -> 43268.75 ms, +983.75 ms / +2.223038%
```

测试同时固化旧 checkpoint 的八份 `cycles:u` 与 node032 原 perf CSV 中对应的八份
task-clock 数值，不用按 walltime 合成 PMU 数据。

新门禁回放结果为：

| metric | value | decision |
| --- | ---: | --- |
| wall order gap | `0.192392 pp` | PASS |
| control/candidate block shift | `5.446020% / 5.642640%` | FAIL / FAIL |
| control/candidate spread | `10.774533% / 7.122924%` | FAIL / FAIL |
| cycles order gap | `1.756510 pp` | FAIL |
| wall/cycles gain gap | `0.906146 pp` | FAIL |
| candidate user-cycles/task-clock proxy advantage | `0.925688%` | FAIL |

因此 schema-v4 不会再把这组偶然满足 wall order gap 的测量接受为 valid。

### 3.3 fresh g158 稳定正式组

直接读取 [TNO0248](./TNO0248_simpletes_g158_node030_fresh_sameccd_retest_20260825.md)
正式组的八份原始 perf CSV，并重新交给 schema-v4 summary。端到端 walltime 仍为
`43,223.00 -> 42,491.25 ms`，减少 `731.75 ms`、提升 `1.692964%`；新门禁为：

| metric | value | decision |
| --- | ---: | --- |
| wall order gap | `0.084992 pp` | PASS |
| control/candidate block shift | `0.168892% / 0.255347%` | PASS / PASS |
| control/candidate spread | `1.071189% / 0.924896%` | PASS / PASS |
| cycles order gap | `0.066780 pp` | PASS |
| wall/cycles gain gap | `0.010846 pp` | PASS |
| user-cycles/task-clock proxy delta | `0.016793%` | PASS |

这说明既有可信正收益不会被当前阈值误杀，同时历史两个高估组均可由第一层门禁直接
识别。门禁只裁决单组测量是否可信，最终保留/default 的 headline 仍是 SimTop 50k
端到端 walltime。

## 4. 回归与边界

完成的验证：

```text
focused runtime + bench tests: 149 passed
full SimpleTES tests:          299 passed, 24 existing deprecation warnings
compileall:                    PASS
init control --validate-only:  PASS
GPT 5.6 Sol max + THJ fresh 64/64 dry-run: PASS
schema-v3 resume probe:        expected fail-closed
```

新增测试覆盖所有门槛的严格边界（等于门槛拒绝、略低于门槛通过）、PMU-only 连续
失败的 generated/control 分流、PMU 失败后恢复、PMU 与 wall 混合失败，以及完整 retry
history 保留。

实现提交：SimpleTES `48bb78cfd33857c21d9c7fafafcea6bcfc28576e`。

本阶段未调用模型、未启动新 SimpleTES instance、未运行新的 SimTop 性能实验、未修改
Wolvrix 生产代码或默认选项。第二独立确认组仍不属于当前协议；若未来采用，应作为
单独的测量合同变更记录，而不是隐式加入本次 schema-v4。
