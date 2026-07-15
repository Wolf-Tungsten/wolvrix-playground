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
