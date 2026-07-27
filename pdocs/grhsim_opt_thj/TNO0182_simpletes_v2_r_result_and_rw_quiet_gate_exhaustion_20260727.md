# TNO0182 SimpleTES v2 R result and RW quiet-gate exhaustion

## 1. 阶段结论

[TNO0181](./TNO0181_simpletes_v2_cumulative_ablation_design_and_launch_20260727.md)
启动的 `R/RW/RWF/RWFA` fresh 累计消融已完成前两臂：

- `R` 完成 fresh build、focused、100/10k 与 fixed-ASLR SimTop 50k `ABBA + BAAB`，
  pooled walltime 为 `61505.75 -> 57466.50 ms`，绝对减少 `4039.25 ms`，改善
  `6.567272%`；
- `RW` 的 build、focused、100/10k、proof 与 artifact 固化均成功，但 50k 阶段的
  `9` 次基础设施调用已耗尽，最终 attempt 报告没有完整 CCD 通过 strict quiet-window gate；结果为
  `infrastructure_retry=1`、`control/candidate walltime=null`，不能用于判断 `W` 的收益；
- 串行 runner 已继续构建 `RWF`。当前不把 RW 的 retryable outcome 记作候选失败，也不提前裁决
  `W/F/A`。

## 2. 固定身份与功能门禁

- parent pin：`fbe4e1cbbfcf45b52960545377020cb761c3ab25`；
- Wolvrix pin：`8f6ba14397b0c3d00cb909153af1c6464f4f1ed9`；
- 两臂均为 `default-path`、零 enable option、只修改 `lib/emit/grhsim_cpp.cpp`；
- build config fingerprint：`920b5c7f1e32e61e7ad363145521736e9a10a68d0e0d112ce7b4406f00e820b3`；
- toolchain fingerprint：`3139fef644317380a048f6d32551a70f2e960fe73558188951636856f4617038`；
- `R` emu SHA-256：`fb0f34d6945dbd2c10eb43e08b347457c207ec47a2ede0e39b493ab90e644852`；
- `RW` emu SHA-256：`d1b39cc221f924e7197c496d9008e02f0114a618477b48980e11e93940c33bcc`。

两臂在进入 formal runtime 前均通过 focused tests、100-cycle 和 10k-cycle 功能门禁。candidate proof、
build/function logs、emu、CoreMark image 与 NEMU 已分别固化到 ignored artifact 目录
`build/grhsim_simpletes_v2_ablation_20260727/arms/r` 和
`build/grhsim_simpletes_v2_ablation_20260727/arms/rw`，每臂使用严格的 11-file
`SHA256SUMS`；累计 evaluator 的 immutable result 则单独保存在
`build/grhsim_simpletes_v2_ablation_20260727/cumulative_results/<arm>`，不污染
direct runner 的输入 manifest。

## 3. R 正式 50k walltime

| order | control accepted / ms | R accepted / ms | control mean / ms | R mean / ms | 绝对减少 / ms | 改善 |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| `ABBA` | `61722, 61842` | `57644, 57614` | `61782.00` | `57629.00` | `4153.00` | `6.722023%` |
| `BAAB` | `61225, 61234` | `57466, 57142` | `61229.50` | `57304.00` | `3925.50` | `6.411125%` |
| pooled | 4 samples | 4 samples | `61505.75` | `57466.50` | `4039.25` | `6.567272%` |

两种 order 均为正向，`direction_consistent_positive=true`，正式 `combined_score` 为
`1.0702887769396083`。spread 为：

- `ABBA` control `120 ms / 0.194231%`，candidate `30 ms / 0.052057%`；
- `BAAB` control `9 ms / 0.014699%`，candidate `324 ms / 0.565406%`；
- pooled control `617 ms / 1.003158%`，candidate `502 ms / 0.873552%`。

8 个 accepted 样本全部满足：

- `personality=00040000`，即运行时 ASLR 已关闭；
- `cpu_migrations=0`，perf events 与 task-clock scheduled 均为 `100%`；
- affinity、完整 CCD pre-gate、持续 peer monitor、NUMA locality、功能签名均通过；
- `ABBA` 固定在 `node0:40-47,232-239` 的 CPU `41`，`BAAB` 固定在
  `node0:88-95,280-287` 的 CPU `88`。

一次未完成的 BAAB attempt 留下 `57188 ms` candidate 与 `61308/60925 ms` control 三个日志，
但没有第 4 个样本，整组已按协议丢弃；这些数不进入上述均值或 spread。

## 4. R 的 PMU 归因

| 指标 | control pooled mean | R pooled mean | 绝对变化 | 相对变化 |
| --- | ---: | ---: | ---: | ---: |
| cycles | `221913047274.00` | `207071850300.75` | `-14841196973.25` | `-6.687843%` |
| instructions | `162333462869.50` | `162389741689.25` | `+56278819.75` | `+0.034669%` |
| frontend no-ops | `1007662137375.50` | `932734403317.00` | `-74927734058.50` | `-7.435799%` |
| frontend cmask >= 6 | `131405349546.00` | `121955949307.50` | `-9449400238.50` | `-7.191032%` |
| backend stalls | `76115245455.25` | `74578364983.50` | `-1536880471.75` | `-2.019149%` |
| task-clock / ms | `61515.2975` | `57474.0200` | `-4041.2775` | `-6.569549%` |

其中 task-clock 绝对值由 8 个 accepted sample 的 raw perf CSV 重算，其余 PMU 值也逐项与 immutable
runtime result 交叉核对；raw runtime logs 归档在
`build/grhsim_simpletes_v2_ablation_20260727/cumulative_results/r/runtime_logs`，并由
`build/grhsim_simpletes_v2_ablation_20260727/cumulative_results/r/RUNTIME_SHA256SUMS` 独立校验；
该 manifest 的 SHA-256 为 `4051297e3579f14367b08cc434f43132cb1440d44514463b2293abf5c3693914`。
host retired instructions 基本不变，
而 cycles、frontend no-ops 和 task-clock 与 walltime 同向下降，支持 `R` 的收益来自
code-layout/front-end 改善，而非少执行了主机侧指令。R 的 build log 分别报告
`commit_supernodes=468`、策略 `cold_runs=20` 和 `cold_guards=46655`；这些计数的对象不同，不能把
`20/468` 当成 run 命中率。其中 `selected=1` 表示策略已选中，不代表只命中一个 run。

## 5. RW 基础设施结果与补测计划

RW evaluator 于 `2026-07-27 13:50:08 +0800` 结束，`eval_time=2580.202735 s`，最终字段为：

- `valid_candidate=0`；
- `infrastructure_retry=1`；
- error：`no dynamically discovered CCD passed the strict quiet-window gate`；
- `control_walltime_ms=null`、`candidate_walltime_ms=null`；
- accepted 50k samples：`0`。

因此当前没有 `B -> RW` 的性能数值，更不能用 `R` 与 RW 在不同历史时间窗中的 score 相减来声称
`W` 有效或无效。为避免重复构建，trusted baseline 的 emu/image/NEMU 和 control identity 已另行固化到
`build/grhsim_simpletes_v2_ablation_20260727/baseline`。四臂 evaluator 完全退出后将串行执行：

1. `B -> RW` runtime-only 配对，补齐 RW 的累计绝对/相对 walltime；
2. `R -> RW` direct 配对，直接隔离 `W`；
3. `RW -> RWF` 与 `RWF -> RWFA` direct 配对，分别隔离 `F` 与 `A`。

所有补测继续使用 runtime 默认的 50k、quiet-CCD、fixed-ASLR、NUMA、PMU 与 `ABBA -> BAAB`
协议；新的 direct runner 还与 SimpleTES trusted slot 共用排他锁，避免和后续 evaluator 或 auto research
误并发。最终四层归因、保留/停止建议与完整 artifact hash 将写入后续 TNO。
