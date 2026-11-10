# TNO0018 32 线程 RepCut 主实验 walltime

## 结果与适用范围

最终主系列完成 8 对 AB/BA，所有样本通过完整 DiffTest/NEMU、功能签名、线程 placement、NUMA locality 和 code-page 检查。Host time 的配对平均 delta 为 **+32.179%**，中位数为 **+18.341%**，bootstrap 95% CI 为 **[+15.007%, +60.360%]**；8 对中 after 均更慢。

该系列中途发生明显的绝对耗时变化，不能直接把 +32.179% 当作稳定的版本退化幅度。Pair 5 按 BA 运行，B 为 58.899 s，随后 A 为 26.109 s；后面两对 A 降到约 19–20 s，B 降到约 24–26 s。全部通过门槛的样本均保留，没有删除 Pair 5 或选择子区间报告。为检查这项未决问题，随后使用完全相同的 binary 和参数追加一次完整 8 对，独立记录在 [TNO0019](./TNO0019_repcut_confirmation_20261110.md)。

## 固定条件

- 两侧均来自 `scripts/grhsim32.py --performance`；`configuration.json` 的 performance 均为 true。
- node030、CPU0–31、32 个运行线程（31 workers + 参与计算的 host lane 9）、pinning enabled、all-spin。
- NUMA0 严格 `membind=0`、ASLR disabled、共同的 LD_PRELOAD/timing 设置、codepages=auto。
- CoreMark 冻结镜像、同一 NEMU、100,000 周期上限、完整 DiffTest；关闭 trace 和诊断计数。
- 两侧分别 smoke、100k verify 和预热，正式样本按 AB/BA 交替。无空闲准入检查，CPU governor 保持 schedutil。
- before retained 为 seed 3 的迁移候选；after retained 为 seed 7 的 initial。选择过程见 [TNO0014](./TNO0014_repcut_retained_build_gates_20261110.md)。

实际 code-page 记录固定：before 88,080,384 字节、after 104,857,600 字节，均为一个全部使用 huge page 的 region。各侧 binary SHA、运行配置、指令进度和 UART 输出在所有样本中固定。

## 汇总

| 指标 | before | after |
| --- | ---: | ---: |
| Host time 平均值 | 38.241125 s | 48.159125 s |
| Host time 中位数 | 46.825500 s | 54.329500 s |
| 外部 walltime 平均值 | 38.327171 s | 48.264125 s |
| 外部 walltime 中位数 | 46.906054 s | 54.428417 s |

| 配对统计 | Host time | 外部 walltime |
| --- | ---: | ---: |
| delta 平均值 | +32.179191% | +32.130400% |
| delta 中位数 | +18.341146% | +18.364281% |
| bootstrap 95% CI | [+15.007495%, +60.359752%] | [+15.022672%, +60.183499%] |
| after 更快 | 0/8 | 0/8 |

每对 delta 为 `(after / before - 1) × 100%`；配对平均值不是两侧总时间之比。CI 使用固定 seed、10,000 次配对 bootstrap，只描述本系列，不覆盖跨时段变化。

| Pair | 顺序 | before (s) | after (s) | delta |
| --- | --- | ---: | ---: | ---: |
| 0 | AB | 49.565 | 53.947 | +8.8409% |
| 1 | BA | 47.357 | 53.066 | +12.0552% |
| 2 | AB | 49.119 | 56.667 | +15.3668% |
| 3 | BA | 48.312 | 57.249 | +18.4985% |
| 4 | AB | 46.294 | 54.712 | +18.1838% |
| 5 | BA | 26.109 | 58.899 | +125.5889% |
| 6 | AB | 19.209 | 24.264 | +26.3158% |
| 7 | BA | 19.964 | 26.469 | +32.5837% |

## 功能与产物

before 固定为 PC `0x80000cde`、instrCnt 238535、cycleCnt 99996；after 固定为 PC `0x80000c1a`、instrCnt 250838、cycleCnt 99995。两侧 Guest cycles 均为 100001，终止原因为周期上限，UART 均为 `Running CoreMark for 2 iterations\n`。每个版本分别通过 NEMU，且与同版本 native 的进度一致；跨版本不要求相同周期的 PC/指令数相等。

binary SHA256：before `8f95d65a4012f52a041948cee8dd6e64c08beb0a212122a831ee26527ce2ec76`；after `23a2fe3de33bbc036e3400c7221fc4e4881e2d0a723c779ed799cdabaf7960de`。两侧编译器均为 Clang 19.1.1。

原始产物：[summary.json](../../build/xs/kunminghu-v3-grhsim-merge-20261110/repcut-comparison-final/summary.json)、[pairs.csv](../../build/xs/kunminghu-v3-grhsim-merge-20261110/repcut-comparison-final/pairs.csv)、[manifest.json](../../build/xs/kunminghu-v3-grhsim-merge-20261110/repcut-comparison-final/manifest.json)、[逐次命令、日志和监控](../../build/xs/kunminghu-v3-grhsim-merge-20261110/repcut-comparison-final/)。

此前两次未完成系列分别因 NUMA 门和退出阶段 verifier 被拒绝，完整保留并全部排除于本统计，见 [TNO0016](./TNO0016_repcut_strict_numa_runtime_20261110.md)、[TNO0017](./TNO0017_repcut_teardown_affinity_verifier_20261110.md)。本系列 8 对没有门槛拒绝。
