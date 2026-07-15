# TNO0039 Stage 3 quiet A/B/A and default decision

记录日期：2026-07-14

状态：Stage 3 conservative true-clone candidate 完成有效 atomic quiet fixed-ASLR A/B/A；cycles `+0.145%`，低于 `1%` 可信线，判定接近中性且无可信正收益，默认继续关闭。

## 1. 测量口径修正

机器存在周期性短负载，且未绑核的 `mpstat` 会随机迁入被测 sibling，造成假性 gate 失败。本轮最终采用：

```text
CPU142 / sibling334 / NUMA1
taskset -c 0 mpstat -P 142,334 1 3
numactl --physcpubind=142 --membind=1
setarch $(uname -m) -R
```

gate 解析与 `perf` 启动必须在同一 shell helper 内原子执行；双 sibling 平均 idle 均 `>=99%` 才立即启动 emu，并记录 `gate_end_ns/run_start_ns`。五事件与前阶段相同，均要求 running ratio `100%`。

先前 CPU65/257、116/308、108/300 的 gate 失败样本全部排除。CPU142/334 最早一条 control 虽 gate 合格，但 gate 到 perf 相隔约 `140 s`，也降级为 diagnostic；正式 A/B/A 从原子 helper 重新开始，不混入该样本。

## 2. Atomic gates 与功能

| Run | Gate idle | gate-to-run gap | PMU five events | Endpoint |
| --- | --- | ---: | ---: | --- |
| control1 | `99.67% / 100.00%` | `7 ms` | `100%` | `50001/49996/73580/0x80001312` |
| candidate | `99.00% / 100.00%` | `6 ms` | `100%` | `50001/49996/73580/0x80001312` |
| control2 | `100.00% / 100.00%` | `7 ms` | `100%` | `50001/49996/73580/0x80001312` |

三轮 difftest 正常，负向关键词为零。两侧 control cycles spread 为 `0.194394%`，构成有效包夹，无需追加 control。

## 3. 五事件结果

| Metric | control1 | candidate | control2 | Candidate vs control mean |
| --- | ---: | ---: | ---: | ---: |
| cycles | `285,173,672,576` | `285,864,262,766` | `285,728,572,894` | `+0.144732%` |
| instructions | `172,881,216,769` | `172,746,488,766` | `172,881,217,760` | `-0.077931%` |
| frontend empty slots | `1,308,115,263,828` | `1,309,362,990,942` | `1,310,538,163,614` | `+0.002771%` |
| frontend cmask6 | `170,156,056,822` | `169,988,437,477` | `170,584,623,997` | `-0.224160%` |
| backend stalls | `92,663,833,438` | `95,000,153,531` | `93,173,938,642` | `+2.239876%` |
| host wall | `77,881 ms` | `78,101 ms` | `78,038 ms` | `+0.181504%` |

108 个 clone 将 instructions 降低约 `0.078%`，但 frontend empty 基本不变，backend stalls 增加约 `2.24%`；最终 cycles 轻微回退 `0.145%`。本轮可信阈值为：

```text
max(1%, baseline spread 0.194394%) = 1%
```

candidate 既没有可信正收益，也没有超过阈值的可信退化；性能分类为 neutral。

## 4. Default decision

Stage 3 conservative candidate 的 exact structure 为 BAE `-0.0027%`、DAG `-18`、boundary values `-64`，而 runtime 没有正向信号。current-default 保持：

```text
enable_local_shared_compute=false
post_dp_refine_policy=off
kahn_level_pack_policy=off
```

true-clone 基础设施、hard budgets、full rebuild validator 与显式实验入口默认关闭保留。当前 exactly-two/source-already-local 策略停止继续调参：机会只有 108 个，单纯增加 clone budget 无效。

下一阶段先对 `rejected_consumer_nodes` 做 no-mutation 分桶，确认其中有多少是 singleton common-expression owner；只有双 consumer 的 operand locality 与 cap 都成立时，才试 common-owner true clone。该扩展必须作为新阶段独立提交，不能与本阶段 neutral 结果混在一起。

## 5. 原始数据

正式文件位于：

```text
build/logs/xs_perf/activity_stage3_local_clone_20260714/formal_control1_*
build/logs/xs_perf/activity_stage3_local_clone_20260714/formal_candidate_*
build/logs/xs_perf/activity_stage3_local_clone_20260714/formal_control2_*
build/logs/xs_perf/activity_stage3_local_clone_20260714/run_formal_atomic.sh
```

`diagnostic_gap_control1_*` 与所有 `discarded_pair*` 明确保留为无效诊断，不得混入正式均值。
