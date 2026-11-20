# TNO0007：XiangShan 归约公共输入保护独立复测

**开启 `reduction_common_guard` 后，这个 100k 周期窗口的外部 walltime 平均降低 1.638%，八对均更快。** 基线和保护版沿用上轮的同一对 ELF，本轮将两者相邻运行。配对 95% 区间整体低于零。

| 测量 | 关闭 A 平均秒数 | 开启 F 平均秒数 | 配对平均变化 | 配对 bootstrap 95% CI | F 更快 |
| --- | ---: | ---: | ---: | --- | ---: |
| 上轮，三版本交替 | 121.383 | 119.391 | −1.503% | [−5.147%, +2.303%] | 7/8 |
| 本轮，两版本相邻交替 | 111.667 | 109.831 | −1.638% | [−2.096%, −1.089%] | 8/8 |

## 对照与窗口

A 和 F 沿用上轮发布 ELF，SHA-256 分别以 `f42147a3ad5c` 和 `ff75a6256d53` 开头。F 仅开启 `reduction_common_guard`。两边都保留 shared-arm 和紧凑快照，均关闭 `commit_scalar_same_reader_groups`。该保护在公共输入连续阻断整组归约时跳过重复求值。上轮已在这两份 ELF 上核对两个 seed，每个 seed 有 99,999 条 DiffTest 记录一致。[发布产物与工作负载身份](../../build/armor-reduction-common-guard-retest-v1/measurement/manifest.json) · [双 seed 功能记录](../../build/armor-followup-v1/functional-xs/verified.json)

本轮沿用单核 XiangShan 的 CoreMark 起始 100k 周期窗口，seed 为 0，开启完整 DiffTest/NEMU。两边各预热一次，随后在 node030、CPU96、NUMA1 上单线程串行运行，关闭 ASLR，全程持有共享测量锁。奇数对先 A 后 F，偶数对先 F 后 A。上轮每对 A 和 F 之间还运行了提交分组版本 C。[预先固定的测量参数](../../build/armor-reduction-common-guard-retest-v1/measurement/policy.json) · [上轮三版本对照](./TNO0006_commit_and_common_guard_20261119.md)

主指标为每对外部 walltime 的百分比变化 `100 × (F/A − 1)`，八对取算术均值。95% 区间按配对百分比重采样 10,000 次，随机种子为 20261102。两轮结果分别统计。

## 逐对外部 walltime

| 对次 | 运行顺序 | 关闭 A（秒） | 开启 F（秒） | F 相对 A |
| ---: | --- | ---: | ---: | ---: |
| 1 | A → F | 113.967 | 111.465 | −2.195% |
| 2 | F → A | 111.151 | 111.100 | −0.046% |
| 3 | A → F | 112.536 | 110.322 | −1.968% |
| 4 | F → A | 108.221 | 107.105 | −1.031% |
| 5 | A → F | 109.603 | 107.996 | −1.466% |
| 6 | F → A | 111.393 | 108.966 | −2.180% |
| 7 | A → F | 112.512 | 109.679 | −2.518% |
| 8 | F → A | 113.953 | 112.017 | −1.699% |

四对先运行 A 时，F 平均变化 −2.037%，四对先运行 F 时为 −1.239%。全部 16 份正式样本都进入统计。每次均正常到达 PC `0x80000c1a`，执行 250,838 条 guest 指令，记录 100,001 个 guest cycles。线程、CPU、NUMA 和 ASLR 检查通过。同核 CPU288 在正式样本中的最低空闲率为 99.991%。[逐对原始秒数](../../build/armor-reduction-common-guard-retest-v1/paired-walltime.csv) · [样本核验与统计复算](../../build/armor-reduction-common-guard-retest-v1/review.json)

两轮的平均降幅接近，本轮在当前负载和基线配置上确认了独立开启归约公共输入保护的整机收益。与同读者提交分组同时开启时的增量收益还需单独测量。
