# TNO0015 单核 native GrhSIM 合并前后 walltime

## 结论与口径

CoreMark、100,000 周期上限、完整 DiffTest/NEMU、8 对 AB/BA：after 的 Host time 配对平均增加 **30.766%**，bootstrap 95% CI 为 **[29.968%, 31.781%]**。8 对中 after 均更慢。

运行固定 node030 CPU96、单线程、NUMA1 本地 binary/library/anonymous state、ASLR disabled；关闭 trace/诊断插桩。每侧先 smoke 和预热，复用已验证的两组完整 trace，重新核对冻结身份。没有样本被功能或 placement/locality 门拒绝。

这是完整上游版本和 DefaultConfig 共同变化的结果。after 的 L2/LLC 容量、微架构和 DiffTest schema 均变化，详见 [TNO0004](./TNO0004_upstream_rtl_schema_memory_20261110.md)。静态 native compute supernodes 增加 22.012%，boundary activation edges 增加 24.419%；这些结构变化提供背景，单点原因需要另行归因。

## 汇总

| 指标 | before | after |
| --- | ---: | ---: |
| Host time 平均值 | 101.289250 s | 132.449250 s |
| Host time 中位数 | 101.548500 s | 132.092500 s |
| 外部 walltime 平均值 | 101.336631 s | 132.511241 s |
| 外部 walltime 中位数 | 101.596284 s | 132.154057 s |

| 配对统计 | Host time | 外部 walltime |
| --- | ---: | ---: |
| delta 平均值 | +30.765582% | +30.765600% |
| delta 中位数 | +30.429676% | +30.429373% |
| bootstrap 95% CI | [+29.967865%, +31.780650%] | [+29.968046%, +31.779631%] |
| after 更快 | 0/8 | 0/8 |

每对 delta 为 `(after / before - 1) × 100%`，平均值是配对 delta 的平均。CI 使用固定 seed 的 10,000 次配对 bootstrap。负数表示 after 更快。

## 逐对 Host time

| Pair | 顺序 | before (s) | after (s) | delta |
| --- | --- | ---: | ---: | ---: |
| 0 | AB | 102.863 | 133.554 | +29.8368% |
| 1 | BA | 101.660 | 132.402 | +30.2400% |
| 2 | AB | 100.430 | 131.181 | +30.6193% |
| 3 | BA | 100.921 | 130.992 | +29.7966% |
| 4 | AB | 101.437 | 132.584 | +30.7058% |
| 5 | BA | 101.857 | 131.783 | +29.3804% |
| 6 | AB | 102.162 | 136.628 | +33.7366% |
| 7 | BA | 98.984 | 130.470 | +31.8092% |

## 功能与身份

所有样本正常到达 Guest cycles 100001。before 固定为 PC `0x80000cde`、instrCnt 238535、cycleCnt 99996；after 固定为 PC `0x80000c1a`、instrCnt 250838、cycleCnt 99995。两侧 UART 均为 `Running CoreMark for 2 iterations\n`，各自完整 DiffTest 通过。

binary SHA256：before `54d08d3930f65aa7cb88eade13ab11d270640cec1cb9b3675aa0fd272380ad71`；after `d62216f60f81b0c0485922913c333997a11dcac0c93d3c3c7bcb8a653637d7f7`。编译器均为 Clang 23.1.2；input/reference 使用冻结副本。

原始产物：[summary.json](../../build/xs/kunminghu-v3-grhsim-merge-20261110/single-comparison/summary.json)、[pairs.csv](../../build/xs/kunminghu-v3-grhsim-merge-20261110/single-comparison/pairs.csv)、[manifest.json](../../build/xs/kunminghu-v3-grhsim-merge-20261110/single-comparison/manifest.json)、[完整日志与 locality/线程快照](../../build/xs/kunminghu-v3-grhsim-merge-20261110/single-comparison/)。

本记录只包含 native 结果；32 线程 RepCut 已在 native 结束后串行启动，结果另文记录。默认工作流未因本次结果改变。
