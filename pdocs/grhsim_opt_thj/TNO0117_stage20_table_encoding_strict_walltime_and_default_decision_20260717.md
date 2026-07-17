# TNO0117 Stage 20 table encoding strict walltime and default decision

记录日期：2026-07-17

状态：Stage 20 未插桩 50k 严格 page-local walltime 已形成 default/contiguous 的双 NUMA ABBA，以及 contiguous/gap 的 NUMA1 ABBA。table rewrite 在两个 NUMA 上方向反转，双 node 合并 walltime 仅 `-8 ms`（`-0.010753%`）；gap 相对 contiguous 的有效单 node结果为 `-55 ms`（`-0.074125%`），均未超过样本 spread。C++ native default 保持 `off`，不在 XS 脚本中另设默认。

## 1. staging、绑核绑内存与硬门禁

三种 binary 在 `/dev/shm/tanghaojin_stage20_table_20260717_2026/` 下按 `n0/n1 x default/contiguous/gap` 分开复制，连同 coremark 与 NEMU 共 `18` 个文件、`18` 个不同 inode。copy 本身也在目标 node 上使用 `taskset` 和 `numactl` 完成，以避免 NFS/file-page locality 污染。

镜像目标与 helper 为：

| node | target CPU | SMT sibling | opposite-node helper |
| --- | ---: | ---: | ---: |
| NUMA0 | `43` | `235` | `383` |
| NUMA1 | `139` | `331` | `287` |

正式 emu 绑定的实际命令骨架为：

```text
taskset -c <cpu> \
  numactl --physcpubind=<cpu> --membind=<node> \
  perf stat ... -- \
  setarch x86_64 -R <page-local-emu> ...
```

每轮运行前先对目标 node 的全部 `192` 个 CPU 做 30 秒 gate，要求 mean idle `>=99%`、minimum idle `>=95%`、target 与 sibling 各 `>=98%`。运行期监控除 target 外的 `191` 个 CPU，使用相同 mean/min 门槛。每个样本另外要求 page placement、perf、scheduler、functional、affinity、零 migration 和唯一正 walltime 全部通过。

build 后初始双 node survey 的绝对值为：

| node | CPU count | mean idle | minimum idle | minimum CPU | target idle | sibling idle |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| NUMA0 | `192` | `99.394010%` | `96.29%` | `214` | `98.70%` | `99.07%` |
| NUMA1 | `192` | `99.420573%` | `96.63%` | `148` | `99.30%` | `99.47%` |

两者均通过。正式 runner 沿用 TNO0085 之后的严格脚本：

```text
build/logs/xs_perf/page_local_retest_stage7plus_20260716/run_formal.sh
```

原始根目录与机读汇总：

```text
build/logs/xs_perf/activity_stage20_table_strict_20260717/
build/logs/xs_perf/activity_stage20_table_strict_20260717/valid_samples.tsv
build/logs/xs_perf/activity_stage20_table_strict_20260717/valid_group_means.tsv
```

## 2. 全部有效 raw 样本

每个样本均为 SimTop 50k，functional signature 是 `instrCnt=73580`、`cycleCnt=49996`、guest `50001`。表中 `wall` 才是最终端到端判据；PMU 仅用于诊断。

| node/group | sample | variant | wall ms | cycles | instructions | frontend empty | cmask6 | backend | task-clock ms | ctx | migration | runtime mean/min idle | emu pages N0/N1 | NEMU pages N0/N1 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| N0 default-contiguous | a1 | default | `74,629` | `272,575,789,385` | `164,521,438,449` | `1,246,870,583,379` | `161,720,937,170` | `90,480,485,421` | `74,568.68` | `926` | `0` | `99.456% / 96.180%` | `21,264 / 0` | `115 / 0` |
| N0 default-contiguous | b1 | contiguous | `74,423` | `271,939,418,137` | `162,161,181,694` | `1,248,140,613,250` | `161,969,701,439` | `88,333,303,593` | `74,398.75` | `965` | `0` | `99.458% / 97.210%` | `21,280 / 0` | `115 / 0` |
| N0 default-contiguous | b2 | contiguous | `74,431` | `271,993,696,410` | `162,161,181,763` | `1,247,513,496,236` | `161,880,949,728` | `89,109,728,562` | `74,406.15` | `914` | `0` | `99.454% / 97.090%` | `21,280 / 0` | `115 / 0` |
| N0 default-contiguous | a2 | default | `74,493` | `272,242,632,000` | `164,521,438,528` | `1,245,997,315,838` | `161,577,684,102` | `89,402,909,421` | `74,468.34` | `894` | `0` | `99.438% / 97.700%` | `21,264 / 0` | `115 / 0` |
| N1 default-contiguous | a1 | default | `74,213` | `271,662,157,149` | `164,521,437,551` | `1,242,018,273,567` | `160,894,953,208` | `90,114,555,221` | `74,199.68` | `646` | `0` | `99.476% / 96.550%` | `0 / 21,264` | `0 / 115` |
| N1 default-contiguous | b1 | contiguous | `74,430` | `272,473,543,993` | `162,161,181,295` | `1,251,122,467,229` | `162,467,235,153` | `88,371,471,953` | `74,414.03` | `701` | `0` | `99.461% / 96.300%` | `0 / 21,280` | `0 / 115` |
| N1 default-contiguous | b2 | contiguous | `74,273` | `271,832,095,097` | `162,161,181,350` | `1,247,200,199,014` | `161,805,271,101` | `88,571,562,097` | `74,251.12` | `761` | `0` | `99.573% / 96.660%` | `0 / 21,280` | `0 / 115` |
| N1 default-contiguous | a2 | default | `74,254` | `271,783,444,128` | `164,521,438,239` | `1,244,251,797,410` | `161,293,255,497` | `88,675,866,095` | `74,228.81` | `819` | `0` | `99.653% / 96.640%` | `0 / 21,264` | `0 / 115` |
| N1 contiguous-gap | a1 | contiguous | `74,185` | `271,539,804,169` | `162,161,180,784` | `1,246,266,689,625` | `161,641,654,867` | `87,769,134,058` | `74,161.62` | `811` | `0` | `99.668% / 96.740%` | `0 / 21,280` | `0 / 115` |
| N1 contiguous-gap | b1 | gap | `74,075` | `271,113,506,356` | `162,159,471,010` | `1,243,611,743,017` | `161,171,691,131` | `87,882,288,951` | `74,050.07` | `827` | `0` | `99.653% / 95.810%` | `0 / 21,263` | `0 / 115` |
| N1 contiguous-gap | b2 | gap | `74,212` | `271,587,908,736` | `162,159,471,059` | `1,243,646,302,204` | `161,207,480,770` | `90,543,696,193` | `74,185.83` | `869` | `0` | `99.657% / 96.730%` | `0 / 21,263` | `0 / 115` |
| N1 contiguous-gap | a2 | contiguous | `74,212` | `271,589,353,943` | `162,161,181,838` | `1,245,304,024,184` | `161,498,610,888` | `89,050,211,382` | `74,185.43` | `866` | `0` | `99.656% / 96.730%` | `0 / 21,280` | `0 / 115` |

## 3. walltime headline

有效组的绝对 walltime 汇总为：

| comparison | variant | samples | mean | minimum | maximum | spread | candidate delta |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| N0 default-contiguous | default | `74,629 / 74,493` | `74,561 ms` | `74,493` | `74,629` | `136` | — |
| N0 default-contiguous | contiguous | `74,423 / 74,431` | `74,427 ms` | `74,423` | `74,431` | `8` | `-134 ms` (`-0.1797%`) |
| N1 default-contiguous | default | `74,213 / 74,254` | `74,233.5 ms` | `74,213` | `74,254` | `41` | — |
| N1 default-contiguous | contiguous | `74,430 / 74,273` | `74,351.5 ms` | `74,273` | `74,430` | `157` | `+118 ms` (`+0.1590%`) |
| both nodes default-contiguous | default | four samples | `74,397.25 ms` | `74,213` | `74,629` | `416` | — |
| both nodes default-contiguous | contiguous | four samples | `74,389.25 ms` | `74,273` | `74,431` | `158` | `-8 ms` (`-0.010753%`) |
| N1 contiguous-gap | contiguous | `74,185 / 74,212` | `74,198.5 ms` | `74,185` | `74,212` | `27` | — |
| N1 contiguous-gap | gap | `74,075 / 74,212` | `74,143.5 ms` | `74,075` | `74,212` | `137` | `-55 ms` (`-0.074125%`) |

contiguous 相对 default 在 N0 提升、N1 回退，双 node 合并仅快 `8 ms`，远小于同组 `158..416 ms` spread，也远小于 `1%` 判定线。gap 相对 contiguous 仅有 N1 有效组，快 `55 ms` 同样小于 candidate `137 ms` spread。两者都没有可重复的端到端收益证据。

## 4. PMU 仅作诊断

default-contiguous 双 node 四样本均值：

| metric | default | contiguous | contiguous delta |
| --- | ---: | ---: | ---: |
| cycles | `272,066,005,665.5` | `272,059,688,409.25` | `-6,317,256.25` (`-0.002322%`) |
| instructions | `164,521,438,191.75` | `162,161,181,525.5` | `-2,360,256,666.25` (`-1.434620%`) |
| frontend empty | `1,244,784,492,548.5` | `1,248,494,193,932.25` | `+3,709,701,383.75` |
| cmask6 | `161,371,707,494.25` | `162,030,789,355.25` | `+659,081,861.00` |
| backend | `89,668,454,039.5` | `88,596,516,551.25` | `-1,071,937,488.25` |

N1 contiguous-gap 两样本均值：

| metric | contiguous | gap | gap delta |
| --- | ---: | ---: | ---: |
| cycles | `271,564,579,056` | `271,350,707,546` | `-213,871,510` (`-0.078755%`) |
| instructions | `162,161,181,311` | `162,159,471,034.5` | `-1,710,276.5` (`-0.001055%`) |
| frontend empty | `1,245,785,356,904.5` | `1,243,629,022,610.5` | `-2,156,334,294` |
| cmask6 | `161,570,132,877.5` | `161,189,585,950.5` | `-380,546,927` |
| backend | `88,409,672,720` | `89,212,992,572` | `+803,319,852` |

最关键的诊断是 contiguous 把 retired instructions 降低 `1.434620%`，但最终 walltime 只降低 `0.010753%`。因此不能以 instructions、cycles 或静态 chunk proxy 替代 `Host time spent`；本阶段默认判断严格使用 walltime。

## 5. 作废与未拼接的尝试

以下记录所有导致整组作废的 gate，不把其中已运行的孤立样本拼进有效组：

- N0 default-contiguous ABBA try1 未启动 emu：pre-gate mean `99.341979%`，minimum `94.49%` on CPU16，target `99.93%`，sibling `99.10%`。ABBA try2 才是第 2 节有效组。
- N0 default-contiguous BAAB try1 的首个 contiguous wall 为 `74,445 ms`，但 runtime mean/min 为 `99.353770% / 86.39%`（CPU95），整组作废。
- BAAB try2 首个 contiguous 为有效孤立样本 `74,405 ms`；随后 default 的三次 pre-gate 分别为 `99.052500% / 87.91%`（CPU209，target `100%`，sibling `98.97%`）、`88.056927% / 32.94%`（CPU30，target `85.69%`，sibling `71.78%`）、`91.288177% / 6.60%`（CPU55，target `69.12%`，sibling `99.83%`），整组作废。
- BAAB try3 的 contiguous/default/default wall 依次为 `74,620 / 74,983 / 74,929 ms`；第三项 runtime mean/min 为 `99.234398% / 74.57%`（CPU260，CPU198 也仅 `76.16%`），整组作废。
- BAAB try4 四项 wall 依次为 `74,808 / 74,876 / 74,476 / 74,388 ms`；最后一项 runtime mean/min 为 `99.279686% / 94.05%`（CPU23），整组作废。
- N0 contiguous-gap ABBA try1 五次 pre-gate 全失败、未启动 emu：`99.190990% / 88.21%`（CPU22，target `99.33%`，sibling `100%`）、`99.152240% / 93.64%`（CPU208，target `99.80%`，sibling `99.20%`）、`99.118281% / 87.93%`（CPU30，target `99.80%`，sibling `99.13%`）、`99.132604% / 93.09%`（CPU219，target `99.43%`，sibling `99.10%`）、`99.151562% / 92.21%`（CPU23，target `99.29%`，sibling `98.09%`）。
- N1 default-contiguous ABBA try1 与 contiguous-gap ABBA try1 均完整有效。

有效组内部也有 pre-gate retry；只有后续 retry 通过后才运行对应样本：

- N0 ABBA try2 `a2_default` attempt1 mean `99.382187%`、minimum `95.69%`、target `97.63%`，因 target `<98%` 失败；attempt2 mean `99.448438%`、minimum `94.49%` on CPU212，再次失败。
- N1 contiguous-gap `b2_gap` attempt1 mean `99.675625%`、minimum `94.50%` on CPU116，失败。

BAAB try3/try4 内另有不导致最终样本缺失的 pre-gate retries；本记录保留导致整组作废的最终 runtime failure 和所有进入 headline 的 raw 样本，不声称穷举每一个 admission retry。

这些失败说明当时 N0 whole-node 外部负载在实验过程中波动，不能以“target CPU 看起来空闲”代替整 node runtime gate，也不能通过放宽门槛补齐 BAAB。

## 6. 默认决定

保留 C++ native `active_mask_gap_pack_policy=off`：

1. table contiguous 的双 NUMA walltime 合并仅 `-0.010753%`，且两个 node 方向相反；
2. gap-only N1 walltime `-0.074125%` 小于 spread，N0 没有有效组；
3. `.text` 分别增加 `0.150075%/0.143188%`，没有静态证据足以覆盖 walltime 中性；
4. functional、validator 和回归正确性虽然全部通过，但它们只证明候选可用，不证明端到端更快。

两个 policy 保留为显式实验入口，便于后续与其它机制组合验证；默认值只保留在 C++ 单一来源中，XS 脚本不额外指定同值默认。Stage 20 到此停止，不根据 cycles/instructions 改写 walltime 结论。
