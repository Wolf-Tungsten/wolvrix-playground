# TNO0253: g158 排序策略敏感性消融在 node032 完成

日期：2026-08-27

状态：`THREE-ARM FORMAL 50K PASS; ALL POSITIVE; POLICY SENSITIVITY ONLY; NOT LANDED`。

关联记录：[TNO0252](./TNO0252_g158_policy_sensitivity_ablation_node031_20260826.md) 完成了 g158 静态归因、三组候选并行 fresh build 和功能门禁，但 node031 的外部负载使 27 次入场尝试全部在 workload 前作废。本记录复用同一批 immutable artifacts，在 node029-node032 中重新选机并完成正式 SimTop 50k walltime。

## 1. 结论

node032 在四台候选机器中明显最空闲，严格 runtime 同款预扫描为 `24/24` CCD 通过。三组候选随后串行运行，各自在第 1 轮、第 1 次 paired attempt 完成同 CCD ABBA+BAAB，order gap 全部严格小于 `0.25 pp`：

| arm | control walltime | candidate walltime | 绝对变化 | 相对提升 | ABBA / BAAB | gap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `g158_demand_only` | `43,576.75 ms` | `43,066.00 ms` | `-510.75 ms` | `1.172070%` | `1.241125% / 1.102975%` | `0.138150 pp` |
| `g158_signature_only` | `43,350.25 ms` | `42,714.75 ms` | `-635.50 ms` | `1.465966%` | `1.403687% / 1.528143%` | `0.124456 pp` |
| `g158_full` | `43,374.75 ms` | `42,809.00 ms` | `-565.75 ms` | `1.304330%` | `1.260524% / 1.348097%` | `0.087574 pp` |

结果说明物理成员布局收益对两类内部排序信号都较稳健：只保留 demand policy 或只保留 phase/unit signature 均有正收益，完整组合也有正收益。signature-only 在本批次的观察值最高，比 full 高 `0.161636 pp`；但三组不是独立顶层开关，且没有做 signature-only 对 full 的直接配对 A/B，不能据此宣称 demand comparator 有负收益或 signature-only 已正式优于 full。

g158 仍应视为一个顶层优化，而非三项优化。本轮不 landing、不改默认，也不改变 SimpleTES baseline。

## 2. 四节点选机

在每台机器 source `wolvrix-playground-gsim-calibrate-5/env.sh` 后，使用 `mpstat -P ALL 1 3` 和 `runtime.py` 同款整 CCD gate 做只读扫描：

| node | load average | whole-machine idle | passing CCDs |
| --- | ---: | ---: | ---: |
| node029 | `46.99 / 47.96 / 52.29` | `87.42%` | `0/24` |
| node030 | `17.23 / 11.03 / 14.13` | `98.60%` | `18/24` |
| node031 | `54.37 / 47.86 / 47.40` | `91.15%` | `7/24` |
| node032 | `1.92 / 2.36 / 2.81` | `99.49%` | `24/24` |

node029 有持续 trace normalizer、Java 和 gem5 负载；node031 有一个约 12-core 的外部 `emu` 和约 16 个可迁移 `gem5.opt`；node030 可作为备选。node032 的最佳扫描 CCD 为 `node1:104-111,296-303`，mean/min idle `99.979% / 99.67%`，因此选择 node032。

node032 正式运行前还确认：

~~~text
perf_event_paranoid = -1
setarch personality = PER_LINUX (ADDR_NO_RANDOMIZE)
bestpath-direct.lock = available
baseline + three candidate SHA256SUMS = PASS
~~~

## 3. 候选与协议

候选语义与物化身份沿用 TNO0252：

- `g158_demand_only`：保留 read/write demand、2 的幂需求层、精确 demand、图顺序和物理类型组；移除 active phase/unit signature 排序。
- `g158_signature_only`：保留 active phase/unit signature、referenced/unreferenced 区分和物理类型组；移除 demand magnitude/class 排序。
- `g158_full`：冻结 g158 全部排序策略，patch SHA-256 `cf29862adc2441aed4f72d446295fa5e60557872e7b2c59fa7641608371f72a5`。

三臂全部对同一 `arms_v1/baseline_control`，性能 runner 严格串行，未并发运行。每个 arm 使用 SimTop 50k，headline 只取 `Host time spent walltime_ms`；先 ABBA、再 BAAB，同一 runtime engine 缓存并复用精确 CCD/CPU/sibling/helper/NUMA placement。workload 使用 `setarch x86_64 -R`，并要求 process personality 为 `00040000`。

每个样本还执行功能签名、affinity、CPU migration、NUMA locality、PMU schedule、pre-gate 和 continuous-load gate。BAAB 基础设施无效时丢弃同 attempt 的 ABBA；outer runner 只接受两种顺序都有效且 gap 严格 `<0.25 pp` 的首轮结果。运行参数为 `--retries 8 --gate-attempts 20 --threshold-pp 0.25`。

不同 arm 可以选择不同 CCD，因此只比较各自配对 control 的相对提升，不跨 CCD 直接比较 candidate 绝对 walltime。

## 4. 绝对样本与 placement

三组共 `24` 个正式样本，每组为 `4 control + 4 candidate`：

| arm | control samples (ms) | candidate samples (ms) | placement |
| --- | --- | --- | --- |
| `g158_demand_only` | `43,662 / 43,517 / 43,637 / 43,491` | `43,035 / 43,062 / 43,030 / 43,137` | `node1:128-135,320-327`; CPU 128; sibling 320; helper 0; NUMA 1 |
| `g158_signature_only` | `43,352 / 43,277 / 43,280 / 43,492` | `42,688 / 42,725 / 42,751 / 42,695` | `node0:80-87,272-279`; CPU 80; sibling 272; helper 96; NUMA 0 |
| `g158_full` | `43,403 / 43,307 / 43,318 / 43,471` | `42,791 / 42,826 / 42,833 / 42,786` | `node0:80-87,272-279`; CPU 80; sibling 272; helper 96; NUMA 0 |

各 order 的绝对均值：

| arm | ABBA control -> candidate | BAAB control -> candidate |
| --- | ---: | ---: |
| `g158_demand_only` | `43,589.50 -> 43,048.50 ms` | `43,564.00 -> 43,083.50 ms` |
| `g158_signature_only` | `43,314.50 -> 42,706.50 ms` | `43,386.00 -> 42,723.00 ms` |
| `g158_full` | `43,355.00 -> 42,808.50 ms` | `43,394.50 -> 42,809.50 ms` |

## 5. 功能与基础设施门禁

全部 24 个样本满足：

- guest cycle、terminal PC、functional signature 和唯一 walltime 字段通过；
- personality 唯一值为 `00040000`，地址随机化关闭；
- affinity 正确，CPU migration 均为 `0`；
- binary 和 NEMU NUMA local ratio 均为 `1.0`；
- PMU/task-clock audit 通过，最低 scheduled percent 为 `100.0%`；
- ABBA/BAAB 的 placement identity 完全一致。

负载绝对范围：

| arm | pre mean idle | pre min idle | continuous mean idle | continuous min idle |
| --- | ---: | ---: | ---: | ---: |
| `g158_demand_only` | `98.4375%..100.0%` | `97.67%..100.0%` | `99.018667%..99.132667%` | `98.84%..99.00%` |
| `g158_signature_only` | `99.4175%..100.0%` | `98.00%..100.0%` | `99.403333%..99.704000%` | `98.84%..99.60%` |
| `g158_full` | `99.1875%..100.0%` | `98.33%..100.0%` | `99.348000%..99.682000%` | `98.67%..99.57%` |

没有 infrastructure retry、无效 order 或重跑轮次；三个 runner 均以 status 0 结束，node032 没有残留消融进程。

## 6. PMU 佐证

相对各自 control 的 pooled PMU 变化：

| arm | cycles | instructions | backend stalls |
| --- | ---: | ---: | ---: |
| `g158_demand_only` | `-1.132958%` | `+0.143086%` | `-1.807246%` |
| `g158_signature_only` | `-1.480395%` | `-0.423077%` | `-6.215960%` |
| `g158_full` | `-1.306597%` | `-0.317529%` | `-5.861545%` |

cycles 方向与三组 walltime 一致。signature-only 和 full 的 backend-stall 降幅明显大于 demand-only，但这仍只是同一布局策略不同 ranking policy 的敏感性，不证明它们是不同顶层机制。

## 7. 与 TNO0248 的关系

TNO0248 对冻结 full g158 的独立 fresh 结果为 `43,223.00 -> 42,491.25 ms`、提升 `1.692964%`；本轮 full 为 `43,374.75 -> 42,809.00 ms`、提升 `1.304330%`。两轮方向一致，本轮低 `0.388634 pp`。

两轮的 generated fingerprint、toolchain/build host 和 binary identity 不同，因此不混池绝对样本，也不把两轮差值当成 patch 回归。它们共同支持“g158 full 稳定正收益”，正式幅度应按各自配对批次报告。

## 8. 证据与决策边界

输出根：

~~~text
wolvrix-playground-gsim-calibrate-5/build/grhsim_g158_ablation_20260826/results_node032_20260827_v1/
~~~

| arm | summary SHA-256 | selected result SHA-256 |
| --- | --- | --- |
| `g158_demand_only` | `199391b593c106a683a215708cd4d3d55c8be9681f8093c203f6fe64e9b0f01c` | `169382618ab7de70bebc779a3c8d2e47b5d33237c7571ffef4b126c6f6abce78` |
| `g158_signature_only` | `0a58c0ebc2e3fe563e1363904e25405b2b9f1c2f2b14b12c82490bc14009d716` | `3743e6bc13898a609b7d92afa531168a6640955635b3a1245807172fa5e52bee` |
| `g158_full` | `353d009da5e115dbae1de29474b44fe2208838d1f362a6aa0086ad0836cce05d` | `765d74f00f8b46dd5d7869a308cc6d2bb250f87f123d7b46db8e41e1f0949be8` |

- 本轮证明三种内部 ranking policy 都能保留约 `1.17%..1.47%` 的端到端正收益。
- 本轮不支持把 demand、signature、physical grouping 计为可相加的独立优化；full 没有表现出两者简单相加，反而位于两个单策略观察值之间。
- 若要决定是否用 signature-only 取代 full，需要另做二者直接同 CCD A/B；当前结果只足以说明 full 正收益可复现、内部排序具有鲁棒性。
- 没有修改 Wolvrix 源码、默认配置或 SimpleTES 基线。SimpleTES 仍保持停止状态，ignored build artifacts 不影响后续恢复研究。
