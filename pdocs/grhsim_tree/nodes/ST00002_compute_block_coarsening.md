# ST00002 compute block 粗化（128 → 512/1024 A/B）

- 父节点：ST00001
- 状态：pruned-regression（2026-07-25，2k 门控回归 +15.1%/+23.0%）
- 代码状态：wolvrix @ `afcd5fd` + CLI 参数化改动（`tests/grhsim/am/lower_json_smoke.cpp` 新增 `--max-instructions-per-block`，`scripts/wolvrix_xs_grhsim_am.py` 与根 `Makefile` 透传 `XS_WOLF_GRHSIM_AM_MAX_INSTRUCTIONS_PER_BLOCK`，默认仍 128）
- 创建日期：2026-07-25

## 假设

ST00001 50k 稳态 profile：compute 阶段 2.79 µs/block exec、~132 指令/块 → ~21 ns/指令，远高于正常 1-2 ns，per-block 固定开销（分派、detector、activation 边界）主导。AN00001 静态对比：AM 36,963 compute block（硬上限 128 指令）vs legacy supernode mean 178 / max 3456 op。

提高 compute block 指令上限可直接：减少 block 数（分派次数下降）、减少跨块边界值（detector 密度下降）、减少 activation 调用点。调度器 `ProductionActivityScheduleStage` 本身已参数化（`ActivityScheduleOptions::maxInstructionsPerBlock`），128 仅是 CLI 硬编码，故本节点为低成本 A/B：512 与 1024 两档。commit 上限（4096）与 state-writes 上限（4096）不变。

风险：块变大后单块内冗余求值增多（块内指令不再被跨块 detector 保护，activation 粒度变粗），可能抵消固定开销收益——这正是需要实测的原因。

## 改动

- `wolvrix/tests/grhsim/am/lower_json_smoke.cpp`：新增 `--max-instructions-per-block <count>`（默认 128，与原硬编码一致）。
- `scripts/wolvrix_xs_grhsim_am.py`：同名参数透传。
- 根 `Makefile`：`XS_WOLF_GRHSIM_AM_MAX_INSTRUCTIONS_PER_BLOCK ?= 128` 并透传。

调度器零改动；`ctest -R "grhsim|am"` 10/10 通过（2026-07-25）。

A/B 配置（同一份 post-stats JSON、同一 emit 参数，仅上限不同）：

| 配置 | maxInstructionsPerBlock | 备注 |
| --- | --- | --- |
| cap128 | 128 | = ST00000 baseline，不重测 |
| cap512 | 512 | 对齐 legacy supernode mean 量级 |
| cap1024 | 1024 | 更激进粗化 |

## 测量

schedule 统计（2026-07-25，同一 post-stats JSON，仅上限不同；baseline 行引自 AN00001）：

| 指标 | cap128（baseline） | cap512 | cap1024 |
| --- | --- | --- | --- |
| compute blocks | 36,963 | 9,241 | 4,621 |
| commit blocks | 497 | 497 | 497 |
| detectors | 1,875,970 | 1,651,951 | 1,549,484 |
| activation 边 | 3,218,269 | 2,623,813 | 2,367,866 |
| scheduled 指令 | 8.99M（1.82x） | 8.54M（1.73x） | 8.34M（1.68x） |

**2k 功能 gate（2026-07-25，setarch -R + taskset，-C 2000）**：cap512 与 cap1024 均 rc=0，instrCnt=3 / cycleCnt=1,996，与 ST00001 同口径参考逐字一致，difftest 通过。

**2k 性能门控（2026-07-25，solo，`setarch -R` + `taskset -c 7`，profile OFF，-C 2000）**：

| 配置 | 2k 时间 | vs baseline | vs gsim 2k |
| --- | --- | --- | --- |
| gsim | 1,607 ms | - | 1.0x |
| cap128（baseline，ST00001 同口径） | 140,573 ms | 1.00x | 87.5x |
| cap512 | 161,755 ms | **+15.1% 回归** | 100.7x |
| cap1024 | 172,990 ms | **+23.0% 回归** | 107.6x |

回归幅度远超 2% 噪声带且随上限单调恶化。按 2k 门控策略（README §4），未进行 50k 测量。

**归因（cap512 2k profile ON vs ST00001 baseline 2k profile ON）**：

| 指标 | baseline | cap512 | 变化 |
| --- | --- | --- | --- |
| block execs | 35.5M | 12.30M（compute 11.82M） | -65% |
| activation forward | 505M | 482.7M | 仅 -4.4% |
| activation backward | 30M | 22.7M | -24% |
| commit event marks | 1.29B | 1.29B | 持平 |
| compute 阶段时间 | 71.0%（~99.8s） | 74.8%（121.2s） | +21% |
| 每次 block exec 成本 | ~2.81 µs | ~9.86 µs | **3.5x** |

机制：粗化使 block exec 次数大降 65%，但 activation 次数几乎不降（-4.4%）——块仍然被同样频繁地激活，而每次激活要顺序执行 ~6.6 倍指令（块内无 detector 保护，值未变的指令也全部重算）。每次 block exec 成本涨 3.5x > 次数降 2.9x，净回归。per-block 固定开销（分派等）的节省被块内冗余求值淹没。

## 结论

**剪枝（pruned-regression，2k 门控）**。cap512/cap1024 在 2k 门控下分别回归 +15.1% / +23.0%，远超噪声带且单调恶化，按门控策略不再投入 50k 测量。

关键教训（修正候选池的依据假设）：

1. **"per-block 固定开销主导"的推断被证伪其杠杆方向**：块 exec 次数确实 -65%，但每次激活的冗余求值成本增长更快（3.5x），固定开销节省不是净收益的一阶项。
2. **activation 粒度是敏感点**：块变大后 activation 次数几乎不降（激活由跨块边界值驱动，边界值减少有限），冗余求值随块内线性增长。任何"块粗化"方向必须先解决块内求值去重（guard/条件执行），否则必然回归。
3. ST00003（activation 位图化）/ ST00004（分派扁平化）不改变激活粒度，只降 per-call 固定成本，方向不受本结论影响，但 expected_gain 应下调——固定开销项被证明不是主导项。
4. 遗留代码价值：`--max-instructions-per-block` 参数化已合入工具链（默认 128 不变），后续若块内 guard 落地可重新激活本方向 A/B。

## 子节点候选

- **冗余求值消除 / guard 强化**（新候选，源自本节点归因）：2k 与 50k 都显示每周期大量 block 被激活执行但值未变（activation 505M vs changed marks 48M，约 10:1）。在块内引入条件执行/detector 保护，或强化激活 guard 使"值未变不触发"，直接削减 ~90% 的无效 block exec。优先级应高于所有固定开销类优化。
- 50k 未测遗留风险：2k 为 boot 阶段，稳态活动率结构不同（ST00001：稳态 ~30% 块触发/eval）；若未来有证据表明稳态冗余求值占比远低于 boot，可重估粗化方向，但需先过 2k 门控的替代指标。

---

## 更新 2026-07-25（AN00002 复盘修正）

上方结论第 3 条（"ST00003/04 expected_gain 应下调——固定开销项被证明不是主导项"）被 [AN00002](../analysis/AN00002_am_vs_legacy_coarsen_reflection_20260725.md) 的定量分解**推翻**：用 cap128/cap512 两点拟合 F≈1.56 µs/exec、 m≈9.5 ns/指令，固定开销占 baseline compute 约 55%，与冗余求值同为一阶项。本节点回归的正确解读是"冗余求值随块内指令数线性放大、吃掉固定开销节省"，而非"固定开销小"。ST00003/04 已恢复高优先级（P1/P2）；本节点遗留的 `--max-instructions-per-block` 参数化在便宜原语落地后可重开 A/B。
