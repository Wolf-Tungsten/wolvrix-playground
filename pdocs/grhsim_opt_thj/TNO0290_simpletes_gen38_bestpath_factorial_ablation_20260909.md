# SimpleTES gen38 best-path factorial ablation

## 阶段结论

本阶段针对 `TNO0289` 的 gen38 最佳 patch 做机制消融。最佳 patch 的三个语义机制定义为：

| 标签 | 机制 |
| --- | --- |
| A | hot selected input-seed active-mask chunk packing（8/4/2/1 planner） |
| B | selected hot input dispatch branch weighting（`GRHSIM_LIKELY`） |
| C | event-qualified commit path 上抑制 redundant global active-byte clear |

control 固定为 `control_v2`，从 RTL fresh 构建；A/B/C/AB/AC/BC/ABC 七个 candidate 使用完全相同的 parent、Wolvrix、generation input、toolchain 和 build config（另有 B0 baseline wrapper 作为记录）。全部构建通过 focused/function gate。运行使用最新 `runtime.py`，关闭 ASLR，固定同一 CCD/CPU 完成 ABBA 与 BAAB；以下结果只采用 gap 小于 `0.25 pp` 的 pair。`run_pair_sameccd.py` 的 `valid` 是 runtime lower gates（ASLR、affinity、NUMA、PMU、迁移、功能和 same-placement），不等同于 evaluator 的完整 schema-v4 stability gate；本记录另行报告 order gap、spread 和方向一致性。

## 结果

| arm | control walltime (ms) | candidate walltime (ms) | 减少 (ms) | 提升 | ABBA / BAAB | gap (pp) | 方向一致 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| A | 42,940.75 | 42,761.25 | 179.50 | 0.418018% | 0.305543% / 0.530146% | 0.224603 | 是 |
| B | 42,531.25 | 40,531.50 | 1,999.75 | 4.701837% | 4.765041% / 4.638703% | 0.126339 | 是 |
| C | 42,440.75 | 42,470.25 | -29.50 | -0.069509% | -0.177543% / 0.038955% | 0.216498 | 否 |
| AB | 42,704.75 | 40,694.50 | 2,010.25 | 4.707322% | 4.764356% / 4.650209% | 0.114147 | 是 |
| AC | 42,693.75 | 42,638.00 | 55.75 | 0.130581% | 0.127741% / 0.133418% | 0.005677 | 是 |
| BC | 42,493.00 | 40,461.25 | 2,031.75 | 4.781376% | 4.773334% / 4.789419% | 0.016084 | 是 |
| ABC | 42,102.50 | 40,200.00 | 1,902.50 | 4.518734% | 4.442255% / 4.595311% | 0.153055 | 是 |

所有 walltime 都是同一 pair 内 control/candidate 的四个样本均值，绝对值以 `Host time spent walltime_ms` 为准。A、B、C、AB、AC、ABC 的正式 result JSON 分别保存在
`build/grhsim_bestpath_ablation_20260909/results_node030_v1/A_vs_B0`、
`results_node031_v2/B_repeat6`、`results_node031_v2/C_repeat4`、
`results_node030_v1/AB_repeat6`、`results_node031_v2/AC_vs_B0`、
`results_node031_v2/BC_repeat2`、`results_node031_v2/ABC_vs_B0`。

## gap 复测与异常

B 臂前五轮 gap 为 `0.427290/0.468443/0.711317/0.497914/1.605585 pp`，第六轮才达到 `0.126339 pp`；AB 臂前五轮 gap 为 `1.616709/1.821706/0.668861/0.379601/0.357268 pp`，第六轮达到 `0.114147 pp`。C 臂前几轮方向不一致且 gap 超限，第四轮得到本表的低 gap 结果，但仍无正向收益。外部负载造成的 pre-gate/运行中污染只记为 retryable infrastructure outcome，没有计入样本。

BC 臂的第一份构建被发现使用了不同的独立生成输入和 toolchain（generation input `94722a…`、toolchain `7669097d…`），因此已明确废弃，不能与本表比较。随后复用 `control_v2` 的 generation input `0c63c318…`、toolchain `3139fef6…` 和 control artifact 完成 exact rebuild，旧身份构建没有覆盖。

BC exact v2 的同 CCD 结果为 control `42,493.00 ms`→candidate `40,461.25 ms`，减少 `2,031.75 ms/4.781376%`；ABBA/BAAB 分别为 `4.773334%/4.789419%`，gap `0.016084 pp`，方向一致。首轮 `BC_vs_B0` gap 为 `0.358137 pp`，因此按规则复测并选用 `BC_repeat2`。candidate generated fingerprint 为 `d14bd260a82c1b1bee2c67156352768709be83299540a3bceaa6eb309b082d7a`，`emu` 为 `82,992,832 B`（SHA-256 `097d44134bf62268e93fadd82b81972a4c0f7e31caf666e6c772b7d6efa7ae50`）。

## 解释边界

B 单项几乎解释了 ABC 的主要收益；AB 与 B 的提升接近，说明 A 在 B 已启用时只增加很小边际。A 与 AC 的弱正向结果低于 `1%`，C 的达标组轻微回退且方向不一致，暂不足以保留 C。单项/组合数值是各自相对同源 control 的端到端结果，不能把百分比直接相加，也不能用不同 CCD 的绝对 walltime 横向相减。本阶段完成的是相对 B0 的 factorial 消融；如需把每个机制的 leave-one-out 边际用于生产决策，仍应在同源二进制上另行测量。

## 构建身份

- parent commit：`6e2436e37286264e9f03f114d14d81bae4ed313b`
- Wolvrix pin：`054c6a7c09b007a12eb36fdb49fcb659a1bfc590`
- control `emu` SHA-256：`02654be2541f58be51dd36dbd48a93975b2560853561cf4829c6acfe9630c4b5`
- source SHA-256：baseline `0ed757db91f79df795562677d6f22789ad1aa84df818ef43786e8a18f6bdb196`；A `997e3605e07fd8528c89ca78f266333b5b93e906cb95053d59b960d10db057cb`；B `4d1aaff4b647ed3e064335d80762253666572fef2e0c1bebc574c1035768d051`；C `73e911542b40235b43616e62a452bf89b565fb4825c90eae491e8d2af696904c`；AB `9ff52935a9e6f16b0b4789f18a1ade4801b9b37056d4741ade45b1ccbe34deab`；AC `a979c9b3796acf032f4ae260daa93845b04bac3ccf09270dcdfe141572190d30`；BC `6b14e8c444dd0d42533dc598a46369bacb5e2ff623af1a3e99ced9c157004066`；ABC `4ced2a4a2a6f836e6f7b2f56214088fd1af73e0a1bf3009b421830f6e0c4184e`。

本阶段未修改生产 Wolvrix 默认源码，也未启动新的 SimpleTES research。

## 增量更新 2026-09-09：C 独立复测与门禁说明

用户另行要求重测 C，结果见 [TNO0291](./TNO0291_simpletes_c_independent_retest_20260909.md)：
`42,592.75→42,816.75 ms`，慢 `224.00 ms/0.525911%`，两个顺序均回退，
gap `0.034567 pp`，额外离线复核当前 evaluator 的全部 8 项稳定性门禁通过。
本表旧 `C_repeat4` 虽然 gap 达标，但其 candidate sample spread 为 `2.180350%`，
未通过当前 `<2%` 的完整稳定性门禁。保留本表原值作为历史记录；新结果未覆盖旧样本。
