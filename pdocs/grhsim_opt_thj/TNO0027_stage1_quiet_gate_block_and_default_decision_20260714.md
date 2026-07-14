# TNO0027 Stage 1 quiet-gate block and default decision

记录日期：2026-07-14

状态：三种 policy 的 SimTop 50k 功能结果均 PASS，但本轮新增的 formal quiet A/B/A 被持续外部负载阻断。Stage 1 实现作为默认关闭的可复用 exact evaluator 保留；XiangShan current-default 继续为 `post_dp_refine_policy=off`，不以高负载数据晋升策略。

## 1. Quiet-gate 尝试

[TNO0022](./TNO0022_fresh_current_default_no0300_baseline1_20260714.md) 已在 CPU106/298、NUMA1、fixed-ASLR 下取得一组正式 current-default baseline：

```text
cycles       283,839,654,657
instructions 172,881,401,671
host wall    77,594 ms
five PMU events: 100% scheduled
pre-run CPU106/298: 100% / 100% idle
```

候选 build 完成后，主机进入多轮 XiangShan CI/firtool/GSIM/gem5 高负载。已执行全 384 CPU 三秒 survey，并对 CPU106/298、CPU148/340、CPU44/236、CPU151/343、CPU170/362 等 SMT pair 逐项复核。survey 偶尔能看到某一对 `100% / 100%`，但紧随其后的三秒 gate 会被可迁移任务占用；代表性结果为：

| Pair | NUMA | average idle | 处置 |
| --- | ---: | ---: | --- |
| 106 / 298 | 1 | `65.00% / 32.21%` | reject |
| 148 / 340 attempt 1 | 1 | `98.33% / 98.33%` | reject |
| 148 / 340 attempt 2 | 1 | `98.67% / 98.67%` | reject |
| 44 / 236 | 0 | `98.01% / 98.67%` | reject |
| 151 / 343 | 1 | `99.00% / 97.33%` | reject |
| 170 / 362 | 1 | `63.76% / 67.33%` | reject |

所有结果都违反两侧 `>=99%` 的 formal gate；主机 load 在观察窗口中从约 `70` 升至 `141`，随后进一步达到 `288.55`。

原始 gate/survey 保存在：

```text
build/logs/xs_perf/activity_stage1_policies_20260714/
```

## 2. Diagnostic control 证明

为判断“PMU process cycles 是否仍可勉强使用”，在 CPU148、NUMA1、fixed-ASLR 上运行了一次 matched resume-control，并采集与 baseline 相同的五事件。结果：

| Metric | quiet baseline | high-load diagnostic control | Delta |
| --- | ---: | ---: | ---: |
| cycles | `283,839,654,657` | `331,718,788,775` | `+16.87%` |
| instructions | `172,881,401,671` | `172,881,424,244` | `+0.000013%` |
| host wall | `77,594 ms` | `99,095 ms` | `+27.71%` |
| PMU scheduled | `100%` | `100%` | same |

guest endpoint 仍正确，instructions 也基本不变，但 cycles 和 wall 出现数量级远大于候选预期收益的漂移。它证明“PMU 100% scheduled”只说明事件没有 multiplex，不能抵消 SMT/cache/frequency/调度环境干扰。该 control 明确降级为 diagnostic；没有继续运行 strict/balanced/bae-budget 来制造不可解释的伪排序。

## 3. Default decision

Stage 1 已闭合以下事实：

- exact move/swap evaluator 的 unit、full recount、cap/topology/intent 和 SimTop 50k 功能正确；
- 三种 policy 的 BAE 下降约 `1.1%..1.2%`，DAG 下降约 `3.5%..3.8%`；
- generated `.cpp`、ELF `.text` 和 propagation entries 都有小幅真实下降；
- 三种候选均完成 fixed-ASLR 50k difftest，并到达完全相同的正确终点。

但本轮没有新增满足 quiet A/B/A 门槛的 candidate runtime 数据，因此不能声称 cycles 正收益，也不能依据结构或高负载 wall 选择 policy。按 [TNO0021](./TNO0021_current_default_baseline_and_stage1_refinement_plan_20260714.md) 的晋升规则：

- core 默认保留 `off`；
- `scripts/wolvrix_xs_grhsim.py` 的 current-default 也保留 `off`；
- `strict / balanced / bae-budget` 作为显式实验入口保留；
- 后续主机重新安静时，用本文已有三组 emu 继续 `control / candidate / control`，结果以新的增量 TNO 记录，不覆盖本文。

这不是把 Stage 1 判为 runtime negative，而是拒绝在没有合格测量的情况下改变默认配置。当前仓库默认生成仍严格符合用户指定的 NO0300、ASLR 关闭性能基线口径。

## 4. 阶段提交边界

Stage 1 的提交包含 exact evaluator、CLI/Python/XS 显式参数、focused tests 和 `TNO0021..TNO0027`。build、generated C++、emu、perf 与 gate 日志都留在 `build/`，不进入提交。按仓库要求先提交 Wolvrix 子模块，再由父仓提交子模块指针、XS 脚本和本阶段文档。
