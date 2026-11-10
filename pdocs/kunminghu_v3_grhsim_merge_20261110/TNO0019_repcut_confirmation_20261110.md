# TNO0019 32 线程 RepCut 同 binary 复测

## 动机与结论

[TNO0018](./TNO0018_repcut_primary_paired_walltime_20261110.md) 的主系列中出现明显的绝对时间下降，因此追加一次完整 8 对 AB/BA。没有重新构建、分区、选择或迁移，也没有更换工作负载、NEMU、运行参数或检查门槛。

复测的 Host time 配对均值为 **+2.904%**，中位数 **−0.065%**，bootstrap 95% CI 为 **[−1.458%, +8.379%]**，after 更快 4/8。它没有复现第一轮的明显退化。当前证据不足以确认 32 线程的稳定版本差异；第一轮的 +32.179% 不能作为稳定幅度使用。

两轮 `manifest.json` 逐字段完全相等。所有 32 个正式运行样本（两轮各 8 对）按版本核对 binary SHA、runtime、code-page、NUMA node/policy，均一致。全部功能、线程和 locality 检查通过。计时变化的外部原因没有被测量；不据此指定某个外部任务、CPU 频率或硬件资源为原因。

两轮独立保留，不合并统计，不删除慢样本，不用复测覆盖主实验。单核的 8 对结果仍按 [TNO0015](./TNO0015_native_paired_walltime_20261110.md) 记录。

## 复测统计

| 指标 | before | after |
| --- | ---: | ---: |
| Host time 平均值 | 17.004250 s | 17.506625 s |
| Host time 中位数 | 16.964000 s | 17.059500 s |
| 外部 walltime 平均值 | 17.098364 s | 17.612799 s |
| 外部 walltime 中位数 | 17.055904 s | 17.166615 s |

| 配对统计 | Host time | 外部 walltime |
| --- | ---: | ---: |
| delta 平均值 | +2.903504% | +2.958048% |
| delta 中位数 | −0.065388% | −0.012866% |
| bootstrap 95% CI | [−1.458106%, +8.378737%] | [−1.357755%, +8.359862%] |
| after 更快 | 4/8 | 4/8 |

| Pair | 顺序 | before (s) | after (s) |
| --- | --- | ---: | ---: |
| 0 | AB | 16.918 | 16.605 |
| 1 | BA | 16.752 | 16.168 |
| 2 | AB | 16.765 | 16.342 |
| 3 | BA | 16.739 | 17.060 |
| 4 | AB | 17.010 | 17.059 |
| 5 | BA | 17.429 | 17.356 |
| 6 | AB | 17.329 | 19.812 |
| 7 | BA | 17.092 | 19.651 |

复测末尾两对 after 时间也有所上升，全部纳入统计。逐对 delta 与外部 walltime 见 CSV。测量范围仍是两个完整 DefaultConfig 的 100k 周期仿真，不是同等提交指令数的比较，也不是单独的 GrhSIM 后端优化比较。

## 产物

- [复测命令与 runner SHA](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/repcut-confirmation-command.json)
- [summary.json](../../build/xs/kunminghu-v3-grhsim-merge-20261110/repcut-confirmation/summary.json)、[pairs.csv](../../build/xs/kunminghu-v3-grhsim-merge-20261110/repcut-confirmation/pairs.csv)、[pairs.json](../../build/xs/kunminghu-v3-grhsim-merge-20261110/repcut-confirmation/pairs.json)
- [manifest.json](../../build/xs/kunminghu-v3-grhsim-merge-20261110/repcut-confirmation/manifest.json)、[逐次日志与监控](../../build/xs/kunminghu-v3-grhsim-merge-20261110/repcut-confirmation/)
- [校验与报告生成脚本](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/make-final-report.py)、[总报告](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/report.json)
