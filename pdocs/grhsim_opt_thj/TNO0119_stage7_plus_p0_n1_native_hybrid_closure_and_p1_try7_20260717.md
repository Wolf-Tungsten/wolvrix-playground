# TNO0119 Stage 7+ P0 N1 native hybrid closure and P1 try7

记录日期：2026-07-17

状态：正确 page-local、fixed-ASLR、whole-node strict protocol 下，N1 `explicit-off -> current native-hybrid default` 的 ABBA+BAAB 八样本已完整闭合。SimTop 50k 平衡 walltime 为 `77,707.00 -> 74,571.75 ms`，default 提升 `3,135.25 ms`（`4.034707%`），两个顺序方向与幅度一致，确认 native hybrid 继续由 C++ 默认开启。同期 P1 cap8192 的 N0 BAAB try7 首样本因 runtime minimum idle `94.820%` 作废；commit cap default 仍为 `4096`。

## 1. P0 对象与 fresh N1 staging

P0 比较：

```text
A/control:   Stage14 explicit off
B/candidate: current C++ native-hybrid default
```

fresh staging 为 `/dev/shm/tanghaojin_stage7_p0_n1_20260717_2245/n1/`。复制使用 CPU139、`numactl --physcpubind=139 --membind=1` 与 `cp --reflink=never`；四个 inode 独立：

| file | inode | bytes | SHA-256 |
| --- | ---: | ---: | --- |
| `s14_off` | `5407` | `94,768,184` | `c1674532559292fba857ba56dff3acf20a2789e70517c677ba9e1e683c7ce204` |
| `s14_default` | `5408` | `93,694,944` | `51b74981b0a23d93dc860e13f82248a3ec0c21153117df3f7889da55be918788` |
| `coremark.bin` | `5409` | `16,712` | `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e` |
| `nemu.so` | `5410` | `567,504` | `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e` |

启动前 N1 raw survey 已落盘：

```text
build/logs/xs_perf/page_local_retest_stage7plus_20260716/stage14_native_hybrid_p0_n1_survey_20260717/n1.log
```

绝对 summary 为 count `192`、mean idle `99.768021%`、minimum `97.130000%` on CPU365、target CPU139 `100.000000%`、sibling CPU331 `99.670000%`，全部通过。正式 runner 仍使用：

```text
taskset -c 139 \
  numactl --physcpubind=139 --membind=1 \
  perf stat ... -- \
  setarch x86_64 -R <N1-local-emu> ... -C 50000
```

正式 raw 目录：

```text
build/logs/xs_perf/page_local_retest_stage7plus_20260716/groups/n1/stage14_native_hybrid_strict_p0_abba_try1/
build/logs/xs_perf/page_local_retest_stage7plus_20260716/groups/n1/stage14_native_hybrid_strict_p0_baab_try1/
```

## 2. 八个有效样本绝对值

| group | sample | variant | wall ms | cycles | instructions | frontend empty | cmask6 | backend | task-clock ms | ctx | monitor mean/min@CPU | emu pages N0/N1 | NEMU pages N0/N1 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| N1 ABBA | a1 | off | `77,852` | `284,773,269,265` | `172,881,430,699` | `1,303,392,319,295` | `169,285,291,373` | `94,630,294,822` | `77,768.95` | `878` | `99.770%/96.920%@CPU365` | `0/21,494` | `0/115` |
| N1 ABBA | b1 | default | `74,784` | `273,412,442,567` | `164,521,641,531` | `1,249,724,596,876` | `162,250,487,005` | `92,367,744,114` | `74,669.87` | `845` | `99.763%/97.000%@CPU365` | `0/21,264` | `0/115` |
| N1 ABBA | b2 | default | `74,607` | `273,098,653,474` | `164,521,640,513` | `1,250,149,234,321` | `162,324,232,336` | `90,161,373,533` | `74,580.46` | `889` | `99.759%/96.880%@CPU365` | `0/21,264` | `0/115` |
| N1 ABBA | a2 | off | `77,773` | `284,642,091,468` | `172,881,431,090` | `1,302,500,065,931` | `169,138,015,097` | `94,625,972,651` | `77,743.61` | `928` | `99.764%/96.990%@CPU365` | `0/21,494` | `0/115` |
| N1 BAAB | b1 | default | `74,556` | `272,899,766,414` | `164,521,641,027` | `1,247,334,508,579` | `161,850,998,261` | `91,782,116,508` | `74,530.37` | `874` | `99.775%/96.850%@CPU365` | `0/21,264` | `0/115` |
| N1 BAAB | a1 | off | `77,648` | `284,223,741,384` | `172,881,430,771` | `1,300,948,202,935` | `168,865,644,605` | `93,948,513,221` | `77,612.71` | `944` | `99.796%/96.970%@CPU365` | `0/21,494` | `0/115` |
| N1 BAAB | a2 | off | `77,555` | `283,814,714,504` | `172,881,430,080` | `1,299,829,007,448` | `168,675,318,981` | `92,799,019,571` | `77,525.11` | `902` | `99.798%/96.870%@CPU365` | `0/21,494` | `0/115` |
| N1 BAAB | b2 | default | `74,340` | `272,109,440,209` | `164,521,640,944` | `1,245,115,378,531` | `161,424,389,674` | `89,739,274,944` | `74,316.58` | `822` | `99.795%/97.800%@CPU365` | `0/21,264` | `0/115` |

八样本均满足：

```text
run_status=0
placement_ok=monitor_ok=perf_ok=scheduler_ok=1
function_ok=affinity_ok=walltime_ok=1
walltime_count=1, migration=0, ASLR personality=00040000
functional signature=73580/49996/50001
```

八次 per-run pre-gate 均首次通过：count 均为 `192`，mean idle 范围 `99.757240%..99.797656%`，minimum 范围 `96.73%..98.10%`。

## 3. walltime headline

| group | off samples | off mean/spread | default samples | default mean/spread | default delta |
| --- | --- | ---: | --- | ---: | ---: |
| N1 ABBA | `77,852 / 77,773` | `77,812.5 / 79 ms` | `74,784 / 74,607` | `74,695.5 / 177 ms` | `-3,117 ms` (`-4.005783%`) |
| N1 BAAB | `77,648 / 77,555` | `77,601.5 / 93 ms` | `74,556 / 74,340` | `74,448.0 / 216 ms` | `-3,153.5 ms` (`-4.063710%`) |
| balanced | four samples | `77,707.00 / 297 ms` | four samples | `74,571.75 / 444 ms` | `-3,135.25 ms` (`-4.034707%`) |

两种顺序各自都超过 `4%`，差异远大于各自 spread；因此 N1 的 corrected strict walltime 不再是待补推断，而是完整支持 native hybrid default。

## 4. PMU 诊断绝对均值

| group | metric | off mean | default mean | delta |
| --- | --- | ---: | ---: | ---: |
| N1 ABBA | cycles | `284,707,680,366.5` | `273,255,548,020.5` | `-11,452,132,346` (`-4.022418%`) |
| N1 ABBA | instructions | `172,881,430,894.5` | `164,521,641,022` | `-8,359,789,872.5` (`-4.835563%`) |
| N1 ABBA | frontend empty | `1,302,946,192,613` | `1,249,936,915,598.5` | `-53,009,277,014.5` (`-4.068416%`) |
| N1 ABBA | cmask6 | `169,211,653,235` | `162,287,359,670.5` | `-6,924,293,564.5` (`-4.092090%`) |
| N1 ABBA | backend | `94,628,133,736.5` | `91,264,558,823.5` | `-3,363,574,913` (`-3.554519%`) |
| N1 BAAB | cycles | `284,019,227,944` | `272,504,603,311.5` | `-11,514,624,632.5` (`-4.054171%`) |
| N1 BAAB | instructions | `172,881,430,425.5` | `164,521,640,985.5` | `-8,359,789,440` (`-4.835562%`) |
| N1 BAAB | frontend empty | `1,300,388,605,191.5` | `1,246,224,943,555` | `-54,163,661,636.5` (`-4.165190%`) |
| N1 BAAB | cmask6 | `168,770,481,793` | `161,637,693,967.5` | `-7,132,787,825.5` (`-4.226324%`) |
| N1 BAAB | backend | `93,373,766,396` | `90,760,695,726` | `-2,613,070,670` (`-2.798506%`) |
| balanced | cycles | `284,363,454,155.25` | `272,880,075,666` | `-11,483,378,489.25` (`-4.038275%`) |
| balanced | instructions | `172,881,430,660` | `164,521,641,003.75` | `-8,359,789,656.25` (`-4.835563%`) |
| balanced | frontend empty | `1,301,667,398,902.25` | `1,248,080,929,576.75` | `-53,586,469,325.5` (`-4.116756%`) |
| balanced | cmask6 | `168,991,067,514` | `161,962,526,819` | `-7,028,540,695` (`-4.159120%`) |
| balanced | backend | `94,000,950,066.25` | `91,012,627,274.75` | `-2,988,322,791.5` (`-3.179035%`) |

PMU 全部与 walltime 同向，但只用于解释；采用结论由上一节 walltime 决定。

## 5. P1 N0 BAAB try7 rejection

try7 前 standalone raw survey 已保存：

```text
build/logs/xs_perf/page_local_retest_stage7plus_20260716/stage14_cap8192_strict_p1_try7_survey_20260717/n0.log
```

它的 count/mean/min 为 `192 / 99.679167% / 95.790000%`（minimum CPU1），target/sibling 为 `99.600000%/99.900000%`，通过。正式 B1/cap8192 的 per-run pre-gate 也首次通过：count `192`、mean/min `99.722812%/95.03%`（CPU197）、target/sibling `99.57%/99.93%`。但 runtime monitor 的 CPU197 降到 `94.820%`：

| metric | B1 absolute value |
| --- | ---: |
| walltime | `74,400 ms` |
| cycles | `272,021,628,980` |
| instructions | `164,223,367,101` |
| frontend empty | `1,245,697,130,012` |
| cmask6 | `161,566,458,754` |
| backend | `89,252,118,828` |
| task-clock | `74,319.28 ms` |
| context switches / migration | `866 / 0` |
| runtime mean/min | `99.744% / 94.820%` on CPU197 |
| emu pages N0/N1 | `21,260 / 0` |
| NEMU pages N0/N1 | `115 / 0` |

该样本只有 `monitor_ok=0`，其它 gate 和唯一 walltime 均通过，但仍严格作废；A1/A2/B2 没有运行，try7 整组不进入 [TNO0118](./TNO0118_stage7_plus_p1_cap8192_corrected_runtime_attempt4_to6_20260717.md) 的任何均值。

## 6. 默认与队列决定

- native hybrid：N0 既有 strict balanced walltime 与本轮 N1 `-4.034707%` 相互确认，继续作为 C++ native default；XS 脚本不重复写同值默认，显式 off 仍保留回滚入口。
- commit cap：P1 的三个有效组虽都小幅正向，但 N0 BAAB try4..7 仍未闭合，cap8192 暂不晋升；C++ default 保持 `4096`。
- 下一步：N0 真正满足 runtime hard gate 时从空目录完整运行 P1 BAAB try8；在此之前不进入 cap16384，也不拼接 try4..7 的孤立样本。
