# TNO0060 Stage 7 cross-socket runtime and default decision

日期：2026-07-15

## 1. Runtime 对象与方法

[TNO0059](./TNO0059_stage7_hybrid_default_implementation_and_fresh_gates_20260715.md) 形成了同一 current HEAD、同一 canonical checkpoint 的两套 fresh O3 emu：

- A：direct state-read `false`、pure-event bypass `false`，即 NO0300 rollback；
- B：direct state-read `true`、threshold-2 pure-event bypass `true`，packing `off`。

四组实验均按 A/B/A 执行 fixed-ASLR 50k，使用物理核及其 SMT sibling 做 quiet gate：

```text
双 sibling idle >= 99%
gate-to-run gap <= 5s
CPU 与 memory 绑定到同一 NUMA node
cycles/instructions/frontend-empty/frontend-cmask6/backend-stalls 100% scheduled
control cycles spread <= 1%
```

所有 12 个样本均 exit `0`，终点为 `50001/49996/73580/0x80001312`，负向扫描为 0。实际 pass gate-to-run gap 为 `7..9 ms`。

## 2. 四组有效结果

下表均以各组 A1/A2 均值为控制，负数表示 hybrid 更快或事件更少：

| CPU / sibling | NUMA | control spread | host | cycles | instructions | frontend empty | frontend cmask6 | backend stalls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `84 / 276` | 0 | `0.210691%` | `+4.256547%` | `+4.358093%` | `-4.835573%` | `+7.087494%` | `+10.166071%` | `-5.221529%` |
| `11 / 203` | 0 | `0.126274%` | `+4.977201%` | `+4.960010%` | `-4.835464%` | `+7.793776%` | `+11.167327%` | `-5.123079%` |
| `142 / 334` | 1 | `0.240544%` | `-12.488687%` | `-12.481145%` | `-4.835570%` | `-14.940333%` | `-17.577937%` | `-2.726686%` |
| `143 / 335` | 1 | `0.107049%` | `-12.233512%` | `-12.234684%` | `-4.835570%` | `-14.508406%` | `-17.010449%` | `-4.445880%` |

每个 NUMA node 上的两组都高度复现，但两个 node 方向相反：NUMA0 稳定回退约 `4.4%..5.0%`，NUMA1 稳定提升约 `12.2%..12.5%`。这不是 control 漂移、PMU multiplex 或功能路径差异。

## 3. 解释边界

hybrid 在四组中都稳定减少约 `4.8355%` retired instructions，backend stalls 也都下降，说明 direct state-read 与 pure-event bypass 的动态 work 缩减是真实的。

最终 cycles 由 frontend 主导：NUMA0 的 frontend empty/cmask6 分别恶化约 `7%..8%/10%..11%`，NUMA1 则改善约 `14.5%..14.9%/17.0%..17.6%`。同一 fresh binary、fixed virtual layout、local memory binding 下仍有这种跨 socket 反转，因此本阶段只能把它归类为 native code-layout 与硬件位置交互，不能声称已经定位到单一 BTB、op-cache、NUMA memory 或频率根因。

这也解释了 [TNO0057](./TNO0057_stage6_quiet_runtime_and_default_decision_20260715.md) 的历史 probe `-11.409784%`：该结果与本轮 NUMA1 数据一致，但不能代表 NUMA0。fresh rollback 与历史 NO0300 只存在诊断注释 ID 及 48-byte `.text` 级别的跨构建差异，已足以让这个前端敏感组合改变表现，不能用历史单组结果直接晋升默认。

## 4. 默认裁决

Stage 7 不采用 hybrid XS 默认。理由不是平均收益不足，而是受支持机器的一整个 NUMA/socket 上有两组可复现的 `>4%` 回退；简单平均四组会掩盖该最坏情况。

最终脚本状态：

```text
direct_single_writer_state_reads default = false
pure_event_compute_word_bypass default   = false
pure_event_compute_word_profile default  = false
pure_event_word_pack_policy default      = off
```

保留新增的 `WOLVRIX_XS_GRHSIM_DIRECT_SINGLE_WRITER_STATE_READS` 高层显式入口、低层 fallback 和配置日志，便于后续受控实验；它默认 `false`，不改变 current repository 的 NO0300 生成行为。最终配置 smoke 证明：无变量为 `false/false`，XS 高层可覆盖低层，低层变量在 XS 未设置时仍生效。

## 5. 后续约束

- 不再把 direct+bypass 的 retired-instruction 缩减直接等同于 SimTop 性能收益。
- 若后续重开该组合，必须至少跨 NUMA0/NUMA1 各一组 fresh fixed-ASLR A/B/A，并报告最坏组。
- 下一阶段回到 activity schedule/BAE 本身；结构候选即使减少 source 或 `.text`，仍由 current-default NO0300 的跨节点 50k 结果裁决。

## 增量更新 2026-07-17：绝对数值补录/勘误

原文四组正式结果只保留了相对变化。现从原始 `perf stat -x,` CSV 补录四个 A/B/A、共 12 个 accepted samples 的五项绝对计数；没有用百分比反推原始值。事件及单位为：

- `cycles:u`：hardware cycles count；
- `instructions:u`：retired instructions count；
- `de_no_dispatch_per_slot.no_ops_from_frontend:u`：frontend-empty slots count；
- `cpu/de_no_dispatch_per_slot.no_ops_from_frontend,cmask=0x6/u`：frontend-empty `cmask>=6` cycles count；
- `de_no_dispatch_per_slot.backend_stalls:u`：backend-stall slots count。

| node / CPU | 顺序 | sample | cycles | instructions | frontend empty | frontend `cmask>=6` | backend stalls |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| N0 / 84 | 1 | rollback A1 | `284,842,175,398` | `172,881,253,531` | `1,305,239,458,416` | `169,711,933,945` | `92,822,582,243` |
| N0 / 84 | 2 | hybrid B | `297,569,336,431` | `164,521,454,498` | `1,398,517,878,489` | `187,126,863,339` | `88,759,269,813` |
| N0 / 84 | 3 | rollback A2 | `285,442,944,195` | `172,881,252,196` | `1,306,676,883,877` | `170,005,841,527` | `94,475,795,590` |
| N0 / 11 | 1 | rollback A1 | `284,346,674,786` | `172,881,270,938` | `1,301,094,175,343` | `168,911,770,614` | `94,231,592,484` |
| N0 / 11 | 2 | hybrid B | `298,638,849,295` | `164,521,659,978` | `1,402,570,543,469` | `187,795,801,864` | `90,067,139,943` |
| N0 / 11 | 3 | rollback A2 | `284,705,957,339` | `172,881,272,306` | `1,301,227,780,044` | `168,949,734,930` | `95,629,416,376` |
| N1 / 142 | 1 | rollback A1 | `311,164,882,772` | `172,881,269,384` | `1,463,118,044,848` | `195,868,862,150` | `94,303,519,029` |
| N1 / 142 | 2 | hybrid B | `272,655,872,484` | `164,521,474,338` | `1,246,601,393,889` | `161,819,706,970` | `91,066,330,034` |
| N1 / 142 | 3 | rollback A2 | `311,914,272,786` | `172,881,269,534` | `1,468,004,164,178` | `196,792,277,884` | `92,934,534,355` |
| N1 / 143 | 1 | rollback A1 | `314,243,498,517` | `172,881,270,144` | `1,478,924,861,214` | `198,504,828,499` | `94,738,152,900` |
| N1 / 143 | 2 | hybrid B | `275,649,259,755` | `164,521,475,089` | `1,263,870,383,472` | `164,627,497,150` | `90,364,304,164` |
| N1 / 143 | 3 | rollback A2 | `313,907,282,619` | `172,881,270,354` | `1,477,787,776,331` | `198,237,881,117` | `94,399,277,933` |

原始路径前缀为 `build/logs/xs_perf/activity_stage7_hybrid_default_20260715/`；上述四组按顺序分别对应：

```text
rollback_a1_perf.csv / hybrid_b_perf.csv / rollback_a2_perf.csv
rollback3_a1_perf.csv / hybrid3_b_perf.csv / rollback3_a2_perf.csv
rollback2_a1_perf.csv / hybrid2_b_perf.csv / rollback2_a2_perf.csv
rollback4_a1_perf.csv / hybrid4_b_perf.csv / rollback4_a2_perf.csv
```

所有 12 份 CSV 的五个事件均为 `100.00%` scheduled。本补录不改变原文对旧协议、NUMA 反转或默认关闭的历史结论。

原文 `host` 列同样只给了相对值；从同组 `*_emu.log` 的 `Host time spent` 行补录 wall milliseconds：

| node / CPU | 顺序 | sample | host ms |
| --- | ---: | --- | ---: |
| N0 / 84 | 1 | rollback A1 | `77,939` |
| N0 / 84 | 2 | hybrid B | `81,293` |
| N0 / 84 | 3 | rollback A2 | `78,009` |
| N0 / 11 | 1 | rollback A1 | `77,804` |
| N0 / 11 | 2 | hybrid B | `81,730` |
| N0 / 11 | 3 | rollback A2 | `77,906` |
| N1 / 142 | 1 | rollback A1 | `84,972` |
| N1 / 142 | 2 | hybrid B | `74,452` |
| N1 / 142 | 3 | rollback A2 | `85,182` |
| N1 / 143 | 1 | rollback A1 | `85,815` |
| N1 / 143 | 2 | hybrid B | `75,276` |
| N1 / 143 | 3 | rollback A2 | `85,722` |

原始路径仍为 `build/logs/xs_perf/activity_stage7_hybrid_default_20260715/{stem}_emu.log`，stem 与上表 PMU CSV 一一对应。上述 wall 原值直接取日志，不是由相对值反推。
