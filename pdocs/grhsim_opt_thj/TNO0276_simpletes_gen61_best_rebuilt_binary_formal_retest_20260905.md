# TNO0276: SimpleTES Gen61 best rebuilt-binary formal retest

日期：2026-09-05

状态：`FORMAL VALID RETEST; POSITIVE EFFECT REPRODUCED; NO SOURCE CHANGE`

## 1. 目的与结论

本记录复测当前 SimpleTES root 的 Gen61 best。运行阶段只使用已经生成的
control/candidate ELF，不重新编译；每个完整组仍按 schema-v4 的同一固定
CCD/CPU `ABBA+BAAB` 协议执行。结论是：候选的端到端正收益可以复现，但本次
幅度低于历史 best，不能把两次结果当作同一 ELF 的逐字节重放。

本次正式通过组的 pooled `Host time spent` 为：

| 版本 | control mean (ms) | candidate mean (ms) | 减少 (ms) | 改善 | score |
| --- | ---: | ---: | ---: | ---: | ---: |
| 历史 Gen61 formal | 43,950.25 | 41,524.00 | 2,426.25 | 5.520446% | 1.0584300645 |
| 本次重建 binary formal valid | 43,580.00 | 41,599.75 | 1,980.25 | 4.543942% | 1.0476024495 |

因此本次仍观察到约 `1.98 s` 的稳定端到端 walltime 减少和明确正方向；相对
历史改善幅度低 `0.976504 pp`，score 低 `0.0108276150`（约 `1.023%`）。
这不是候选优化消失：本次 candidate 比历史 candidate 只慢 `75.75 ms`
(`+0.1824%`)，而本次 control 比历史 control 快 `370.25 ms`
(`-0.8427%`)，主要差异来自 control 基线和构建环境。

## 2. 输入身份与重放边界

复测使用的候选文件是 Gen61 best，完整 candidate digest 为：

```text
681a3ba10b385bef5c997b840256438b9de505283832e6a34bfbf7281ebdc7a0
```

复用的 ELF 身份如下：

| artifact | size | SHA-256 |
| --- | ---: | --- |
| control (independent rebuild) | 83,517,504 B | `36d2c699af4380303b4d313e34ca09b6e782bae60fc1ace8e8cb181c5c25eee6` |
| candidate (independent rebuild) | 83,615,736 B | `8c64b4004f490fc506c05d5eb3cc649631f42d77629c8747dd0d0b183f42311b` |

历史 formal candidate ELF (`801c19f0...`) 已被后续构建覆盖，无法恢复；历史
control ELF 也有不同 Build ID。因此这里的“重建 binary”是同一 pinned patch 的
独立构建复测，不宣称 exact-ELF replay。对比检查显示当前生成输入与历史现场仅有
三个外围文件不同：`build/xs/rtl/rtl/Ftq.sv`、
`build/xs/rtl/rtl/LogPerfEndpoint.sv` 和
`testcase/xiangshan/build/generated-src/difftest_profile.json`；其余生成输入
保持一致。candidate patch 的历史 SHA-256 为
`06ad075dbaa888a5e343c6b551718184126b32dfbf555ca102376748cad9462e`。

## 3. 正式运行协议

运行节点为 node031，固定 placement 为：

```text
CCD: node0:56-63,248-255
target CPU: 56
sibling: 248
helper CPU: 96
NUMA node: 0
protocol: ABBA+BAAB (8 samples)
```

runtime 仍由现有 `runtime.py` 执行：每个 sample 在目标 NUMA 的新 tmpfs inode
上 first-touch staging，`setarch x86_64 -R`（进程 personality `00040000`），
`taskset`/`numactl` 固定 CPU 和内存，连续 whole-CCD monitor、进程 affinity、
executable/NUMA page locality、PMU scheduling/migration、功能签名和唯一正
`Host time spent` 都是硬门禁。正式结果 JSON 保存在：

```text
/tmp/simpletes-gen61-runtime-only-node031-20260905/results/direct_abba_baab/attempt-10.json
```

该文件 SHA-256 为
`fccd72b95413e4e04cc98a3aa6a7c489b1784947975086dacad56ca8f2c4b491`。

## 4. 八个正式样本与双顺序结果

原始 walltime（ms）按执行顺序为：

```text
control 43367, candidate 41520, candidate 41649, control 43719,
candidate 41419, control 43492, control 43742, candidate 41811
```

| order | control mean (ms) | candidate mean (ms) | 减少 (ms) | 改善 |
| --- | ---: | ---: | ---: | ---: |
| ABBA | 43,543.0 | 41,584.5 | 1,958.5 | 4.497853% |
| BAAB | 43,617.0 | 41,615.0 | 2,002.0 | 4.589953% |
| pooled | 43,580.0 | 41,599.75 | 1,980.25 | 4.543942% |

四个 paired control-candidate 差值为 `1,847/2,070/2,073/1,931 ms`，均为
正，均值 `1,980.25 ms`，样本标准差 `110.81 ms`。这说明方向不是由某一个
单独样本造成的。

## 5. 稳定性与机制交叉检查

本组的 schema-v4 稳定性摘要如下：

| gate | value | limit | result |
| --- | ---: | ---: | --- |
| wall order gap | 0.092101 pp | < 0.25 pp | PASS |
| control block shift | 0.169803% | < 1% | PASS |
| candidate block shift | 0.073318% | < 1% | PASS |
| control sample spread | 0.860486% | < 2% | PASS |
| candidate sample spread | 0.942313% | < 2% | PASS |
| cycles order gap | 0.176808 pp | < 0.5 pp | PASS |
| wall/cycles gain gap | 0.180287 pp | < 0.5 pp | PASS |
| user-cycles/task-clock delta | 0.167822% | < 0.25% | PASS |

pooled cycles 改善为 `4.724229%`，与 walltime 的方向一致；所有 sample 的
function、affinity、fixed-ASLR、NUMA locality、PMU scheduled/migration 和
continuous monitor gate 均通过。故这组满足当前 evaluator 的 `valid_candidate=1`
和 `combined_score=1.0476024495`，不是仅凭单次 walltime 的诊断结果。

## 6. 失败尝试与噪声边界

本次 wrapper 共执行 10 次完整尝试：6 次在 quiet/pre-gate 或 workload monitor
阶段被标记为 retryable infrastructure，2 次完成八样本但稳定性门禁失败，随后
第 10 次通过全部门禁并正常结束。不能把失败组混入正式 score。两个完整但无效的
组仍提供了幅度交叉证据：

| attempt | control pooled (ms) | candidate pooled (ms) | raw wall gain | 拒绝原因 |
| --- | ---: | ---: | ---: | --- |
| 7 | 43,577.5 | 41,144.5 | 5.583156% | order gap `0.741205 pp`、control shift `1.5627%`、candidate spread `2.4669%` |
| 9 | 43,417.75 | 40,961.0 | 5.658400% | order gap `0.626075 pp`、多项 block/spread/cycles gate |

这两个组的 raw gain 与历史 `5.520446%` 同一量级，但 evaluator 正确将其
`valid_candidate` 置为 `0`。它们只能作为“优化方向仍存在”的辅助证据，不能替代
attempt-10 的 formal 结果。

## 7. 决策与后续边界

1. Gen61 的正向端到端效果在独立重建 binary 上得到 formal 复现；本次不修改
   Wolvrix 源码、默认选项或 SimpleTES 基线。
2. 采用本次 formal valid 结果作为当前重建现场的可信数字：
   `43,580.00 -> 41,599.75 ms`，`1,980.25 ms/4.543942%`，score
   `1.0476024495`。
3. 历史 `5.520446%` 仍保留为 Gen61 原始 formal 结果；由于 exact ELF 不可恢复，
   后续若需确认幅度，应在更空闲节点使用同一 build manifest 再做一组独立
   ABBA+BAAB，而不是拼接本次与历史样本。
4. 主线 SimpleTES 仍在 node030 运行，本复测没有停止、修改或重启它；其 best
   仍为 Gen61 / `1.0584300645`。
