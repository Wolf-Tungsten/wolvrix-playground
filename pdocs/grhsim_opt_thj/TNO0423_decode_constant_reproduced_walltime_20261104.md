# TNO0423 恒零表回退同场复现与频率证据

本轮完成冻结 C/E 八对交替测量，前置两次 smoke、两次 warmup。CPU96、NUMA node1、私有 emu/NEMU/依赖库、单线程亲和性和 SMT sibling gate 全部通过；没有因为快慢删除样本。与之前两组有效 trace 使用的文件身份一致。

| 对次 | 顺序 | C 秒 | E 秒 |
| ---: | --- | ---: | ---: |
| 0 | CE | 98.213 | 97.487 |
| 1 | EC | 110.721 | 109.935 |
| 2 | CE | 98.045 | 97.369 |
| 3 | EC | 97.967 | 97.548 |
| 4 | CE | 97.995 | 97.319 |
| 5 | EC | 97.861 | 97.322 |
| 6 | CE | 97.921 | 97.340 |
| 7 | EC | 97.936 | 97.323 |

E/C 配对变化平均 **−0.628268%**，中位 **−0.657699%**；固定种子配对 bootstrap 95% 区间 **[−0.687882%, −0.556768%]**，八对全部 E 更快。C/E 均值 99.582375/98.955375 s，中位 97.981/97.3545 s。回退再次成立，无需触发未复现时再测独立八对的分支。

## 频率与运行状态

第二对 APERF/MPERF 为 C 1.29066、E 1.30693；其他配对约 1.42–1.43。该对 E 虽然 walltime 更短，CPU-wide APERF 总数却比 C 多约 0.539%，说明频率状态影响配对解释，不能用单次 walltime 替代工作量证据。

八对 CPU-wide APERF 的 E/C 平均差异为 −0.500279%，但它包含 CPU96 上的全部用户/内核活动，且不是精确覆盖 emu Host 区间的进程事件。因此只作为运行状态观察，不据此宣布指令数或 CPI 根因。后续进程 PMU 与地址采样是独立诊断，不混入本表。

- [全部普通样本与配对区间](../../build/xs/decode_constant_investigation_20261104_v1/walltime1/summary.json)
- [时间、频率和计数联表](../../build/xs/decode_constant_investigation_20261104_v1/walltime1/joined.csv)
- [输入和冻结文件身份](../../build/xs/decode_constant_investigation_20261104_v1/walltime1/manifest.json)
- [与有效 trace 的依赖库身份核验](../../build/xs/decode_constant_investigation_20261104_v1/walltime1/runtime_identity_gate.json)

构建队列直到普通测量 summary 写出后才启动；正式计时期间本任务没有并行编译。当前仅确认该性能差异可复现，尚未把静态结构变化确认为性能根因。
