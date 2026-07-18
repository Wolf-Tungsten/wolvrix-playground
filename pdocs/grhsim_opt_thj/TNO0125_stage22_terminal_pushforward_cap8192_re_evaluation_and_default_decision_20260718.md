# TNO0125 Stage 22 terminal pushforward cap8192 re-evaluation and default decision

记录日期：2026-07-18

状态：在 TNO0124 已采用的 C++ native cap8192 默认上重新生成 terminal pushforward strict，并用同一 clang++ 工具链构建 off/strict 两个 emu。strict 的结构收益和所有功能/NUMA gate 均成立，但四个独立 ABBA/BAAB 组的 walltime 没有正向收益；双 NUMA balanced strict 回退 `77.5 ms`（`0.104189073%`）。因此 terminal pushforward `strict` 保持 C++ native default `off`，`probe` 继续只读，不能晋升默认。

## 1. 比较对象和结构 gate

比较对象完全来自当前仓库 default：

```text
off:    build/xs_activity_stage23_cap8192_cpp_default_20260718/grhsim/grhsim_emit/
strict: build/xs_activity_stage24_cap8192_terminal_pushforward_strict_20260718/grhsim/grhsim_emit/
```

两边均从同一个 Stage8 post-stats JSON 恢复，commit cap 日志均为 `cpp-default`；strict 只增加 `final_terminal_pushforward_policy=strict`。strict evaluator 绝对统计仍为 `1,092,530` scanned、`287,944` pure、`1,054` exact eligible、`128` selected/applied、`128` moved ops、moved-op limit `1,125`，reject 为 move-limit `514`、touched-SN `412`、budget `0`、strict non-zero-add `0`。

结构 before/after：

| metric | off | strict | delta |
| --- | ---: | ---: | ---: |
| total supernodes | `63,709` | `63,709` | `0` |
| compute supernodes | `63,241` | `63,241` | `0` |
| commit supernodes | `468` | `468` | `0` |
| DAG edges | `527,990` | `527,990` | `0` |
| compute-compute value pairs | `1,721,698` | `1,721,570` | `-128` |
| total boundary activation edges | `1,983,326` | `1,983,198` | `-128` |
| boundary values | `1,000,463` | `1,000,335` | `-128` |
| logical boundary-byte proxy | `2,614,060` | `2,613,877` | `-183` |
| compute-commit value pairs | `261,628` | `261,628` | `0` |

严格 validator 全部为 `true`：`supernodes/kinds/scheduled_ops/capacity/commit/compute_partition/stable_splice/dag/topo/state_read/compute_commit/value_fanout/value_source/bae_gain/boundary_activation_edge_gain/boundary_value_gain/boundary_logical_byte_gain`。

activity stats SHA-256：

```text
off    6c41b8b25d83e05d402dbeb6164553bdd10903b8c8e67efae8cfd3cf6542257c
strict bcf246241f70a5eb7a04d6b084ecaf7665fed2c2de93744c3d2cc5c60e2c9ed9
```

`grhsim_emit_stats.json` 两边 byte-exact，SHA-256 为：

```text
9dd1bdddd01606507b2e3425917f260ca3ac8c5b88c55fa21408bffb17080a8b
```

## 2. generated C++ 静态审计

审计排除 `.o/.pch/.tmp`，只比较 138 个 canonical generated basenames：两边 `138/138`，无增删，`97` changed、`41` identical。schedule cpp 绝对值：

| metric | off | strict | delta |
| --- | ---: | ---: | ---: |
| schedule cpp files | `97` | `97` | `0` |
| schedule cpp bytes | `1,330,831,646` | `1,330,774,013` | `-57,633` |
| schedule cpp lines | `13,382,552` | `13,381,611` | `-941` |
| all 138 source bytes | `1,356,654,043` | `1,356,596,410` | `-57,633` |
| all 138 source lines | `13,684,108` | `13,683,167` | `-941` |

两边都保持 `66` 个 compute function、`31` 个 commit function、`63,709` 个 SN 的 ID、SN-to-batch、batch 内顺序。归一化 direct slot index 和 ordered-write affine base index 后，仅 `54` 个 compute batch 改变，精确等于 `42` 个 source batch 与 `43` 个 target batch 的并集；`127` 次 move 跨 batch、`1` 次同 batch，没有额外 batch 漂移。SN block 改变恰为 `256 = 128 source + 128 target`。

128 个 selected output 在 off 中各有一条 standalone materialization comment 和两次 changed-value reference，strict 中均为 `0/0`；op comment 总数 `2,128,344 -> 2,128,216`，没有 op 丢失。slot 统计：总 entry `1,039,705 -> 1,039,577`（`-128`），按元素宽度计的 payload `2,448,160 -> 2,447,975 bytes`（`-185 bytes`）。

## 3. O3、emu 和功能 gate

两边都显式使用 `CXX=clang++ -j4`，避免生成 Makefile 的 PCH 被 GNU make 内建 `g++` 覆盖。raw logs：

```text
build/logs/xs/stage23_cap8192_cpp_default_o3_clang_build_20260718.log
build/logs/xs/stage24_cap8192_terminal_pushforward_strict_o3_clang_build_20260718.log
build/logs/xs/stage23_cap8192_cpp_default_emu_build_20260718.log
build/logs/xs/stage24_cap8192_terminal_pushforward_strict_emu_build_20260718.log
```

archive/emu absolute values：

| artifact | off | strict |
| --- | ---: | ---: |
| `libgrhsim_SimTop.a` bytes | `99,249,366` | `99,225,694` |
| emu bytes | `93,671,816` | `93,647,240` |
| emu SHA-256 | `31ab2b820cbce126199b7baef5d9f15909f6db1e39bb72d1b140bc398924ba65` | `fe30ebe234d1d20ade3caa3b40401fc0bb19405576ca12da9c8b2d8143080426` |
| `.text` | `87,095,345` | `87,070,721` |
| `.rodata` | `5,647,080` | `5,646,936` |
| `.eh_frame_hdr` | `8,444` | `8,444` |
| `.eh_frame` | `706,144` | `706,160` |
| `.data` | `152` | `152` |
| `.bss` | `14,688` | `14,688` |

strict fixed-ASLR functional logs：

```text
build/logs/xs/stage24_cap8192_terminal_pushforward_strict_function_100_20260718.log
build/logs/xs/stage24_cap8192_terminal_pushforward_strict_function_10000_20260718.log
build/logs/xs/stage24_cap8192_terminal_pushforward_strict_function_50000_20260718.log
```

绝对结果为 `100: instrCnt=0, cycleCnt=96, guest=101, Host time=265ms`；`10,000: 458/9,996/10,001, 9,491ms`；`50,000: 73,580/49,996/50,001, 74,333ms`。三个窗口 exit 均为 `0`，这些只是功能 gate，不作为 A/B headline。

## 4. fresh inode、NUMA survey 与 runner

formal staging 使用新目录，不复用 Stage7+ inode：

```text
/dev/shm/tanghaojin_stage24_terminal_20260718_0639/n0/
/dev/shm/tanghaojin_stage24_terminal_20260718_0639/n1/
```

N0/N1 的 off、strict、CoreMark、NEMU 共 8 个 inode 全部不同；stat/SHA raw：

```text
build/logs/xs/stage24_terminal_formal_staging_stat_20260718.log
build/logs/xs/stage24_terminal_formal_staging_sha256_20260718.log
```

| file | bytes | N0 inode | N1 inode | SHA-256 |
| --- | ---: | ---: | ---: | --- |
| `stage23_off` | `93,671,816` | `5423` | `5427` | `31ab2b820cbce126199b7baef5d9f15909f6db1e39bb72d1b140bc398924ba65` |
| `stage24_strict` | `93,647,240` | `5424` | `5420` | `fe30ebe234d1d20ade3caa3b40401fc0bb19405576ca12da9c8b2d8143080426` |
| `coremark.bin` | `16,712` | `5421` | `5425` | `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e` |
| `nemu.so` | `567,504` | `5422` | `5426` | `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e` |

正式 runner 仍为：

```text
taskset -c <target> numactl --physcpubind=<target> --membind=<node> \
  perf stat ... -- setarch x86_64 -R <staged-emu> ... -C 50000
```

N0 target/sibling/helper 为 `43/235/191`，N1 为 `139/331/95`；每个 sample 的 gate-to-run gap 均为 `7ms`。启动前 survey raw：

```text
build/logs/xs_perf/stage24_terminal_cap8192_20260718/surveys/n0_20260718_0641.log
build/logs/xs_perf/stage24_terminal_cap8192_20260718/surveys/n1_20260718_0642.log
```

survey absolute summary：N0 `count=192 mean=99.432083 min=97.900000%@CPU17 target=99.670000 sibling=99.730000`；N1 `count=192 mean=99.514427 min=96.570000%@CPU129 target=99.970000 sibling=99.500000`。两侧均满足 whole-node admission。

## 5. formal 50k walltime 原始值与 gate

四个正式组均使用 fresh page-local inode、`taskset`、`numactl --physcpubind/--membind`、`setarch x86_64 -R` 和 perf；每个样本的 placement、whole-node monitor、scheduler/affinity、functional signature、walltime 唯一性均为 `ok=1`，migration 为 `0`。原始 runner/driver 日志位于：

```text
build/logs/xs_perf/page_local_retest_stage7plus_20260716/groups/{n0,n1}/stage24_terminal_strict_cap8192_final_{abba,baab}_try1/
build/logs/xs_perf/stage24_terminal_cap8192_20260718/n{0,1}_{abba,baab}_try1_driver.log
build/logs/xs_perf/stage24_terminal_cap8192_20260718/raw_walltime.tsv
build/logs/xs_perf/stage24_terminal_cap8192_20260718/gates_placement_monitor.tsv
```

`raw_walltime.tsv` 的 16 个绝对 `walltime_ms`（`a`=off，`b`=strict）如下；不是从百分比反推：

| NUMA/group | a1 off | b1 strict | b2 strict | a2 off | off mean | strict mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| N0 ABBA | 74,404 | 74,382 | 74,682 | 74,499 | 74,451.5 | 74,532.0 |
| N1 ABBA | 74,509 | 74,516 | 74,169 | 74,183 | 74,346.0 | 74,342.5 |
| N0 BAAB | 74,687 | 74,829 | 74,513 | 74,497 | 74,592.0 | 74,671.0 |
| N1 BAAB | 74,136 | 74,362 | 74,239 | 74,157 | 74,146.5 | 74,300.5 |

四组原始值均可由相应日志中的 `walltime_ms` 唯一字段复核；所有样本功能终点均为 `instrCnt=73,580, cycleCnt=49,996, guest=50,001`。对应 gate/placement 的绝对记录还显示 N0 emu/NEMU 页面分别为 `21,260/115` 或 `21,206/115`（remote=0），N1 分别为 `0/0` local、`21,260/115` 或 `21,206/115` remote，符合各自 membind node；每个 gate-to-run gap 为 `7ms`。

## 6. PMU 原始值

为保留绝对数值，以下逐样本抄录 `raw_metrics.tsv`；列顺序为 `cycles instructions frontend_stall cmask6 backend_stall task_clock_ms context_switches migrations`。`task_clock_ms` 是 perf task-clock，不替代最终 walltime 判据。

```text
sample                 cycles        instructions    frontend_stall  cmask6       backend_stall  task_clock_ms  context_switches  migrations
n0_abba_a1             271848212802  164223544560    1243335371274   161215225901 90447136748   74296.86       887               0
n0_abba_b1             271966240361  164086093556    1244155370257   161397484203 90199632213   74351.82       968               0
n0_abba_b2             273162630917  164086094246    1249255655718   162305459583 91841970171   74653.35       918               0
n0_abba_a2             272472028260  164223544871    1246402575234   161685649699 91197656399   74471.81       866               0
n1_abba_a1             272748198074  164223544554    1247889520271   161989225354 91025419291   74493.09       677               0
n1_abba_b1             272804332233  164086094337    1248757431990   162189484608 90283271913   74499.10       676               0
n1_abba_b2             271535460539  164086092583    1241605855804   161021570926 90053802138   74154.16       655               0
n1_abba_a2             271572052256  164223544326    1241876937785   160996620307 90225537456   74168.57       628               0
n0_baab_a1             273015896843  164223546779    1249857725145   162279046374 90878795888   74664.88       850               0
n0_baab_b1             273445982633  164086096794    1250853531092   162528857842 92092685699   74803.56       919               0
n0_baab_b2             272557994295  164086093765    1247280924598   161926837959 90646167498   74490.61       852               0
n0_baab_a2             272404520654  164223545499    1247782425173   161934608004 89439593450   74474.81       859               0
n1_baab_a1             271339222719  164223544057    1241520279917   160905590760 89331680187   74119.09       709               0
n1_baab_b1             272204436056  164086093740    1245646645008   161670327436 90000451443   74348.60       663               0
n1_baab_b2             271752083007  164086093391    1241851445289   161030399043 91019660398   74223.01       697               0
n1_baab_a2             271421583772  164223544075    1241116670612   160842606171 90050273412   74142.08       683               0
```

由两次 `a` 和两次 `b` 的原始值计算出的分组均值也保留如下：

| group | cycles off | cycles strict | instructions off | instructions strict | frontend off | frontend strict | cmask6 off | cmask6 strict | backend off | backend strict | task-clock off (ms) | task-clock strict (ms) | ctx off | ctx strict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| N0 ABBA | 272,160,120,531.0 | 272,564,435,639.0 | 164,223,544,715.5 | 164,086,093,901.0 | 1,244,868,973,254.0 | 1,246,705,512,987.5 | 161,450,437,800.0 | 161,851,471,893.0 | 90,822,396,573.5 | 91,020,801,192.0 | 74,384.335 | 74,502.585 | 876.5 | 943.0 |
| N0 BAAB | 272,710,208,748.5 | 273,001,988,464.0 | 164,223,546,139.0 | 164,086,095,279.5 | 1,248,820,075,159.0 | 1,249,067,227,845.0 | 162,106,827,189.0 | 162,227,847,900.5 | 90,159,194,669.0 | 91,369,426,598.5 | 74,569.845 | 74,647.085 | 854.5 | 885.5 |
| N1 ABBA | 272,160,125,165.0 | 272,169,896,386.0 | 164,223,544,440.0 | 164,086,093,460.0 | 1,244,883,229,028.0 | 1,245,181,643,897.0 | 161,492,922,830.5 | 161,605,527,767.0 | 90,625,478,373.5 | 90,168,537,025.5 | 74,330.830 | 74,326.630 | 652.5 | 665.5 |
| N1 BAAB | 271,380,403,245.5 | 271,978,259,531.5 | 164,223,544,066.0 | 164,086,093,565.5 | 1,241,318,475,264.5 | 1,243,749,045,148.0 | 160,874,098,465.5 | 161,350,363,239.5 | 89,690,976,799.5 | 90,510,055,920.5 | 74,130.585 | 74,285.805 | 696.0 | 680.0 |

原始提取结果及每组均值文件分别为：

```text
build/logs/xs_perf/stage24_terminal_cap8192_20260718/raw_metrics.tsv
build/logs/xs_perf/stage24_terminal_cap8192_20260718/group_pmu_means.tsv
build/logs/xs_perf/stage24_terminal_cap8192_20260718/group_wall_means.tsv
```

## 7. walltime 聚合、平衡计算和结论依据

按 node 对 ABBA 与 BAAB 两组等权，保持所有原始样本而不是只比较某一对：

| aggregate | off walltime (ms) | strict walltime (ms) | delta strict-off (ms) | delta (%) |
| --- | ---: | ---: | ---: | ---: |
| N0 balanced | 74,521.75 | 74,601.50 | +79.75 | +0.107015737% |
| N1 balanced | 74,246.25 | 74,321.50 | +75.25 | +0.101351920% |
| dual-NUMA balanced | 74,384.00 | 74,461.50 | +77.50 | +0.104189073% |

8 个 off 样本的整体 spread 为 `551ms`，strict 为 `660ms`；N0/N1 平衡均值差分别为 `275.50ms` 和 `280.00ms`。因此 strict 的回退在两侧都同向，且不是由单一异常样本产生。PMU 只作诊断：dual balanced 的绝对均值为 cycles `272,102,714,422.5 -> 272,428,645,005.125`（`+325,930,582.625`）、instructions `164,223,544,840.125 -> 164,086,094,051.5`（`-137,450,788.625`）、frontend `1,244,972,688,176.375 -> 1,246,175,857,469.5`（`+1,203,169,293.125`）、cmask6 `161,481,071,571.25 -> 161,758,802,700.0`（`+277,731,128.75`）、backend `90,324,511,603.875 -> 90,767,205,184.125`（`+442,693,580.25`）、task-clock `74,353.899 -> 74,440.526ms`（`+86.627ms`）、context switches `769.875 -> 793.5`；这些方向不能推翻 walltime 结果。

## 8. 默认决策

terminal pushforward strict 的结构收益是真实且可复现的：`-128` compute-compute BAE、`-128` total BAE、`-128` boundary values、logical-byte proxy `-183`，同时 DAG、commit roots、compute-commit pairs、batch/function membership 和功能输出保持不变。但在当前仓库默认的 C++ native cap8192、ASLR 关闭、fresh page-local 双 NUMA、ABBA/BAAB 平衡协议下，SimTop 50k 的最终判据是 walltime，strict 为 `74,384.00 -> 74,461.50ms`，回退 `+77.50ms (+0.104189073%)`。因此：

- C++ native `final_terminal_pushforward_policy` 默认继续为 `off`；
- `probe` 继续只读诊断，不参与生产 schedule；
- strict 保留为显式实验开关，后续若有更大收益候选仍可在 cap8192 基线之上复测；
- 本阶段不修改默认生成配置，也不以 cycles、instructions 或 task-clock 替代 walltime。
