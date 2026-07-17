# TNO0118 Stage 7+ P1 cap8192 corrected runtime attempt4 to6

记录日期：2026-07-17

状态：P1 current native-default `cap4096` 对 `cap8192` 已在正确 page-local、fixed-ASLR、whole-node strict protocol 下形成 N0 ABBA、N1 ABBA 和 N1 BAAB 三个完整有效组。三组 SimTop 50k walltime 均同向改善 `0.251%..0.566%`，但都低于 `1%`，N1 平衡合并 `-0.408054%` 也小于跨顺序 spread。N0 BAAB try4/5/6 均因 runtime whole-node minimum idle 低于 `95%` 作废，不能拼接；因此 current C++ native commit cap 继续保持 `4096`，P1 唯一剩余缺口为 N0 BAAB 完整反序组。

## 1. 对象、fresh staging 与绑定

对象与 [TNO0106](./TNO0106_stage7_plus_p1_cap8192_strict_window_rejection_20260717.md)、[TNO0111](./TNO0111_stage7_plus_p1_cap8192_attempt2_survey_rejection_20260717.md)、[TNO0112](./TNO0112_stage7_plus_p1_cap8192_attempt3_survey_rejection_20260717.md) 相同：

```text
A/control:   current C++ native-hybrid, commit cap4096
B/candidate: current C++ native-hybrid, commit cap8192
```

attempt4 不复用旧 `_v1` 文件，重新按 node 绑定复制到：

```text
/dev/shm/tanghaojin_stage7_p1_attempt4_20260717_2153/n0/
/dev/shm/tanghaojin_stage7_p1_attempt4_20260717_2153/n1/
```

复制本身使用目标 node 的 `taskset`、`numactl --physcpubind`、`numactl --membind` 和 `cp --reflink=never`。8 个文件 inode 全部不同：

| node | file | inode | bytes | SHA-256 |
| --- | --- | ---: | ---: | --- |
| N0 | `s14_default` | `5398` | `93,694,944` | `51b74981b0a23d93dc860e13f82248a3ec0c21153117df3f7889da55be918788` |
| N0 | `s14_cap8192` | `5400` | `93,671,816` | `28e871c4e66598b05659355b8027838f1a5e770beef803ec0434c0ef396bc1f7` |
| N0 | `coremark.bin` | `5403` | `16,712` | `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e` |
| N0 | `nemu.so` | `5404` | `567,504` | `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e` |
| N1 | `s14_default` | `5397` | `93,694,944` | `51b74981b0a23d93dc860e13f82248a3ec0c21153117df3f7889da55be918788` |
| N1 | `s14_cap8192` | `5399` | `93,671,816` | `28e871c4e66598b05659355b8027838f1a5e770beef803ec0434c0ef396bc1f7` |
| N1 | `coremark.bin` | `5401` | `16,712` | `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e` |
| N1 | `nemu.so` | `5402` | `567,504` | `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e` |

正式绑定保持：

```text
N0 target/sibling/helper = CPU43 / CPU235 / CPU191
N1 target/sibling/helper = CPU139 / CPU331 / CPU95

taskset -c <target> \
  numactl --physcpubind=<target> --membind=<node> \
  perf stat ... -- \
  setarch x86_64 -R <node-local-emu> ... -C 50000
```

pre-gate 检查本 node 全部 `192` 个 logical CPUs，runtime monitor 检查除 target 外的 `191` 个 CPUs；门槛仍为 whole-node mean `>=99%`、minimum `>=95%`、target/sibling 各 `>=98%`。每个正式样本还必须同时满足 placement、perf scheduling、task-clock/context-switch/migration、functional、affinity、ASLR personality `00040000` 和唯一正 `Host time spent`。

正式 raw 目录为：

```text
build/logs/xs_perf/page_local_retest_stage7plus_20260716/groups/n0/stage14_cap8192_strict_p1_abba_try4/
build/logs/xs_perf/page_local_retest_stage7plus_20260716/groups/n1/stage14_cap8192_strict_p1_abba_try4/
build/logs/xs_perf/page_local_retest_stage7plus_20260716/groups/n1/stage14_cap8192_strict_p1_baab_try4/
```

启动前在线 survey 的绝对 summary 为 N0 count `192`、mean/min `99.645104%/95.900000%`（minimum CPU262）、target/sibling `99.900000%/100.000000%`；N1 count `192`、mean/min `99.683646%/97.000000%`（CPU360）、target/sibling `99.730000%/99.770000%`。N0 try6 前复测为 count `192`、mean/min `99.757917%/98.670000%`（CPU19）、CPU16 `99.870000%`、target/sibling `99.570000%/100.000000%`。这三次 survey 只通过 `mpstat | awk` 在线汇总，完整 stdout 没有落盘；该 raw 缺失明确保留，不能伪造日志路径。正式 runner 的每样本 pre-gate 与 runtime monitor 则均已完整保存。

## 2. 12 个有效样本绝对值

所有样本的 functional signature 均为 `instrCnt=73580`、`cycleCnt=49996`、guest `50001`；result 中 `run/placement/monitor/perf/scheduler/function/affinity/walltime` 全为 PASS，walltime count 均为 `1`，migration 均为 `0`。

| group | sample | variant | wall ms | cycles | instructions | frontend empty | cmask6 | backend | task-clock ms | ctx | runtime mean/min@CPU | emu pages N0/N1 | NEMU pages N0/N1 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| N0 ABBA | a1 | default | `74,823` | `273,481,126,870` | `164,521,452,148` | `1,251,180,801,308` | `162,457,632,034` | `91,424,169,125` | `74,751.11` | `999` | `99.770%/98.610%@CPU5` | `21,264/0` | `115/0` |
| N0 ABBA | b1 | cap8192 | `74,457` | `272,331,447,105` | `164,223,367,254` | `1,244,754,823,778` | `161,442,330,270` | `91,834,283,187` | `74,425.75` | `990` | `99.750%/98.530%@CPU208` | `21,260/0` | `115/0` |
| N0 ABBA | b2 | cap8192 | `74,313` | `271,818,702,360` | `164,223,368,789` | `1,243,326,854,595` | `161,230,101,464` | `90,273,677,704` | `74,279.68` | `976` | `99.749%/95.410%@CPU213` | `21,260/0` | `115/0` |
| N0 ABBA | a2 | default | `74,753` | `273,420,091,912` | `164,521,452,285` | `1,251,886,367,501` | `162,579,640,852` | `90,524,418,022` | `74,723.86` | `979` | `99.717%/96.560%@CPU213` | `21,264/0` | `115/0` |
| N1 ABBA | a1 | default | `74,054` | `271,067,020,238` | `164,521,452,173` | `1,237,613,211,321` | `160,262,492,613` | `90,388,120,603` | `74,029.37` | `821` | `99.719%/96.840%@CPU365` | `0/21,264` | `0/115` |
| N1 ABBA | b1 | cap8192 | `73,849` | `270,320,643,786` | `164,223,367,280` | `1,233,813,852,480` | `159,612,978,520` | `90,745,051,381` | `73,823.00` | `801` | `99.728%/96.920%@CPU365` | `0/21,260` | `0/115` |
| N1 ABBA | b2 | cap8192 | `73,768` | `269,997,353,775` | `164,223,366,734` | `1,232,791,877,920` | `159,485,872,137` | `89,816,192,563` | `73,739.39` | `834` | `99.731%/96.680%@CPU365` | `0/21,260` | `0/115` |
| N1 ABBA | a2 | default | `74,403` | `272,325,710,529` | `164,521,452,420` | `1,245,957,812,671` | `161,612,267,841` | `89,730,958,514` | `74,377.03` | `849` | `99.715%/97.840%@CPU360` | `0/21,264` | `0/115` |
| N1 BAAB | b1 | cap8192 | `74,165` | `271,417,206,816` | `164,223,367,339` | `1,241,504,973,107` | `160,914,444,467` | `89,638,834,017` | `74,135.36` | `882` | `99.746%/96.970%@CPU360` | `0/21,260` | `0/115` |
| N1 BAAB | a1 | default | `74,543` | `272,846,507,887` | `164,521,452,418` | `1,248,737,931,820` | `162,072,099,115` | `90,054,804,283` | `74,517.20` | `863` | `99.728%/96.800%@CPU360` | `0/21,264` | `0/115` |
| N1 BAAB | a2 | default | `74,755` | `273,632,014,252` | `164,521,452,821` | `1,253,242,454,343` | `162,799,859,680` | `90,498,876,460` | `74,727.56` | `870` | `99.719%/96.580%@CPU360` | `0/21,264` | `0/115` |
| N1 BAAB | b2 | cap8192 | `74,758` | `273,667,081,898` | `164,223,368,975` | `1,253,398,028,594` | `162,922,513,110` | `90,454,772,431` | `74,728.38` | `891` | `99.719%/96.880%@CPU360` | `0/21,260` | `0/115` |

## 3. walltime headline 与 PMU 诊断

每个完整组的绝对 walltime：

| group | default samples | default mean/spread | cap8192 samples | cap8192 mean/spread | delta |
| --- | --- | ---: | --- | ---: | ---: |
| N0 ABBA | `74,823 / 74,753` | `74,788 / 70 ms` | `74,457 / 74,313` | `74,385 / 144 ms` | `-403 ms` (`-0.538857%`) |
| N1 ABBA | `74,054 / 74,403` | `74,228.5 / 349 ms` | `73,849 / 73,768` | `73,808.5 / 81 ms` | `-420 ms` (`-0.565820%`) |
| N1 BAAB | `74,543 / 74,755` | `74,649 / 212 ms` | `74,165 / 74,758` | `74,461.5 / 593 ms` | `-187.5 ms` (`-0.251176%`) |

N1 ABBA+BAAB 顺序平衡合并为 default `74,438.75 ms`、spread `701 ms`，cap8192 `74,135.00 ms`、spread `990 ms`，delta `-303.75 ms`（`-0.408054%`）。双 node 只合并已有 ABBA 时为 `74,508.25 -> 74,096.75 ms`，delta `-411.5 ms`（`-0.552288%`）。若将 N0 ABBA estimator 与 N1 平衡 estimator 各赋 `50%` node 权重，暂定估计为 `74,613.375 -> 74,260.000 ms`，delta `-353.375 ms`（`-0.473608%`）；由于 N0 BAAB 缺失，这不是最终 balanced headline。

组内 PMU 均值及绝对 delta：

| group | metric | default mean | cap8192 mean | delta |
| --- | --- | ---: | ---: | ---: |
| N0 ABBA | cycles | `273,450,609,391` | `272,075,074,732.5` | `-1,375,534,658.5` (`-0.503029%`) |
| N0 ABBA | instructions | `164,521,452,216.5` | `164,223,368,021.5` | `-298,084,195` (`-0.181183%`) |
| N0 ABBA | frontend empty | `1,251,533,584,404.5` | `1,244,040,839,186.5` | `-7,492,745,218` (`-0.598685%`) |
| N0 ABBA | cmask6 | `162,518,636,443` | `161,336,215,867` | `-1,182,420,576` (`-0.727560%`) |
| N0 ABBA | backend | `90,974,293,573.5` | `91,053,980,445.5` | `+79,686,872` (`+0.087593%`) |
| N1 ABBA | cycles | `271,696,365,383.5` | `270,158,998,780.5` | `-1,537,366,603` (`-0.565840%`) |
| N1 ABBA | instructions | `164,521,452,296.5` | `164,223,367,007` | `-298,085,289.5` (`-0.181183%`) |
| N1 ABBA | frontend empty | `1,241,785,511,996` | `1,233,302,865,200` | `-8,482,646,796` (`-0.683101%`) |
| N1 ABBA | cmask6 | `160,937,380,227` | `159,549,425,328.5` | `-1,387,954,898.5` (`-0.862419%`) |
| N1 ABBA | backend | `90,059,539,558.5` | `90,280,621,972` | `+221,082,413.5` (`+0.245485%`) |
| N1 BAAB | cycles | `273,239,261,069.5` | `272,542,144,357` | `-697,116,712.5` (`-0.255131%`) |
| N1 BAAB | instructions | `164,521,452,619.5` | `164,223,368,157` | `-298,084,462.5` (`-0.181183%`) |
| N1 BAAB | frontend empty | `1,250,990,193,081.5` | `1,247,451,500,850.5` | `-3,538,692,231` (`-0.282871%`) |
| N1 BAAB | cmask6 | `162,435,979,397.5` | `161,918,478,788.5` | `-517,500,609` (`-0.318587%`) |
| N1 BAAB | backend | `90,276,840,371.5` | `90,046,803,224` | `-230,037,147.5` (`-0.254813%`) |

instructions 在三个组中都稳定约 `-0.181183%`，walltime 则为 `-0.251%..-0.566%`。这只作为机制诊断；最终决定仍以 walltime 与 spread 为准。

## 4. N0 BAAB try4/5/6 作废绝对值

所有已运行的孤立样本如下；未列项没有启动：

| try/sample | variant | validity | wall | cycles | instructions | frontend | cmask6 | backend | task-clock | ctx | monitor mean/min@CPU | placement emu;NEMU |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| try4 b1 | cap8192 | valid alone, group invalid | `74,537` | `272,705,554,076` | `164,223,368,203` | `1,247,091,400,959` | `161,826,525,181` | `91,715,017,520` | `74,509.13` | `887` | `99.704%/95.300%@CPU16` | `21,260/0;115/0` |
| try4 a1 | default | **invalid** | `74,942` | `274,018,312,553` | `164,521,454,093` | `1,255,904,306,015` | `163,256,537,770` | `90,124,471,570` | `74,911.04` | `927` | `99.735%/94.990%@CPU16` | `21,264/0;115/0` |
| try5 b1 | cap8192 | **invalid** | `74,514` | `272,572,402,324` | `164,223,367,822` | `1,247,372,073,214` | `161,881,699,560` | `90,573,806,950` | `74,485.22` | `883` | `99.724%/94.930%@CPU16` | `21,260/0;115/0` |
| try6 b1 | cap8192 | valid alone, group invalid | `74,366` | `271,965,432,611` | `164,223,367,608` | `1,244,005,146,455` | `161,289,978,343` | `90,634,149,220` | `74,337.12` | `900` | `99.720%/95.460%@CPU20` | `21,260/0;115/0` |
| try6 a1 | default | **invalid** | `74,608` | `272,943,500,105` | `164,521,452,402` | `1,249,293,344,803` | `162,160,695,329` | `90,215,119,930` | `74,580.61` | `870` | `99.722%/94.730%@CPU20` | `21,264/0;115/0` |

三个 invalid 样本的唯一失败项都是 runtime monitor minimum `<95%`；placement、perf、scheduler、functional、affinity、walltime 和 migration `0` 均通过，但不能覆盖环境 gate 失败。try4 在 a1 后停止，try5 在 b1 后停止，try6 在 a1 后停止；不允许把 try4 b1、try6 b1 或任何 invalid wall 拼成 BAAB。

pre-gate retry 也保留：有效 N0 ABBA a2 attempt1 mean/min `99.748542%/94.80%`（CPU215）失败，attempt2 `99.699010%/96.56%`（CPU213）通过；N0 BAAB try4 b1 attempt1 `99.729740%/94.80%`（CPU72）失败，attempt2 `99.689062%/94.43%`（CPU72）失败，attempt3 `99.689844%/96.99%`（CPU64）通过。

## 5. 当前决定与下一步

这批 corrected page-local 结果已经推翻“cap8192 在两个 node 上方向相反”的旧印象：三个有效组的 walltime 和 cycles 都同向下降。不过，现阶段仍不把 cap8192 写成 C++ native default：

1. 三组 walltime 收益都低于既定 `1%` 实用阈值；
2. N1 平衡收益 `0.408054%` 小于 default/candidate 跨顺序 spread `701/990 ms`；
3. N0 只有 ABBA，缺少同一 node 的 BAAB 反序闭环；
4. invalid 孤立样本不能用于人为补齐组数。

因此 C++ commit cap default 保持 `4096`，脚本中也不增加 XS 专用同值默认。N0 whole-node gate 恢复时优先从空目录完整运行 BAAB try7；若 N0 继续失败而 N1 安静，则利用 N1 窗口补 P0 native-hybrid `off/default` 的旧欠账。只有 P1 双 node balanced 闭合后才进入 cap16384，不因三个小幅正向组直接跳档。
