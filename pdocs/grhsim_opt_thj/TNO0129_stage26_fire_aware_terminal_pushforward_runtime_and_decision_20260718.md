# TNO0129 Stage 26 fire-aware terminal pushforward runtime and decision

记录日期：2026-07-18

状态：在当前 cap8192/C++ native-hybrid 默认生成配置（NO0300，ASLR 关闭）上，加入显式 runtime fire profile gate，完成 `min_source_fire=1000` 和 `10000` 两档 strict CPP、O3、功能及 fresh page-local 双 NUMA ABBA/BAAB 50k。两档的 walltime 合并均未改善，因此不改变默认，也不推荐打开 profile strict。

## 1. 基线、实现和验证

基线是当前仓库默认生成结果，而不是旧的 XS 脚本特例：

```text
build/xs_activity_stage23_cap8192_cpp_default_20260718/grhsim/grhsim_emit/
activity stats SHA-256 = 6c41b8b25d83e05d402dbeb6164553bdd10903b8c8e67efae8cfd3cf6542257c
```

新增选项默认关闭，默认值在 C++ `ActivityScheduleOptions` 中：

```text
finalTerminalPushforwardProfilePath = ""
finalTerminalPushforwardProfileMinSourceFire = 0
```

非空 profile 必须有精确的 `supernode_id<TAB>phase<TAB>f` header；compute supernode `0..63240` 各出现一次，commit 行只校验后忽略。文件不可读、缺失/重复/越界/溢出/坏格式均 fail-closed，不执行 mutation。有效 profile 的候选 gate 位于 conflict selection 之前，要求 `source_fire >= min_source_fire` 且 `target_fire <= source_fire`。本阶段使用的 profile 原文件和 SHA 为：

```text
build/logs/xs_perf/activity_stage19_table_runtime_profile_20260717/fire_50000.tsv
SHA-256 = 4106fafbea0871724206d81fc5cda19088656d0e185a15c80ea5e9fe7655b11c
compute rows = 63,241; ignored commit rows = 485
```

代码/绑定 focused 验证：`transform-activity-schedule` CTest `1/1`、XS sparse option unittest `17/17`、pybind option test `5/5`，parent/submodule `git diff --check` 全部通过。完整 `cmake --build wolvrix/build -j2` 后串行 CTest 为 `46/48`（`385.74s`），仅 `transform-comb-lane-pack`、`transform-repcut` 两个历史失败；无新增失败。首次只做 focused build 后直接跑全量 CTest 曾出现三个 stale binary segfault，全量 rebuild 后均恢复通过，因此不计为代码回归。profile path 仍是显式实验入口，没有改变 C++ 默认 off。

## 2. Activity 结构结果

两档均从同一个 `build/xs_activity_stage8_dp_p050_20260715/grhsim/wolvrix_xs_post_stats.json` 恢复，cap8192、native hybrid 和其它 schedule 选项不变。

| 版本 | profile gate | exact eligible | selected/applied | moved ops | compute BAE | total boundary edges | boundary values | logical bytes | compute-commit | DAG | activity stats SHA-256 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| cap8192 baseline/off | off | 0 | 0 | 0 | `1,721,698` | `1,983,326` | `1,000,463` | `2,614,060` | `261,628` | `527,990` | `6c41b8b25d83e05d402dbeb6164553bdd10903b8c8e67efae8cfd3cf6542257c` |
| min1000 strict | `source >= 1,000`, target not hotter | `372` | `80/80` | `83` | `1,721,618` | `1,983,246` | `1,000,383` | `2,613,973` | `261,628` | `527,990` | `59ff3940b56b193b3145c223d43033fbedb1599c223ad44c187886483bc45042` |
| min10000 strict | `source >= 10,000`, target not hotter | `110` | `54/54` | `55` | `1,721,644` | `1,983,272` | `1,000,409` | `2,613,999` | `261,628` | `527,990` | `2bae15a01d5737c65d8b5089a9e3ed9eb545adb4c8f6157ff99cec788f4221e2` |

min1000 probe/strict 的 reject 绝对计数为 `profile_min_source_fire=623`、`target_fire_gt_source=59`、`touched_supernode=292`，最终选 80；min10000 为 `924`、`20`、`56`，最终选 54。两档 strict validators（supernodes/kinds/scheduled_ops/capacity/commit/partition/stable_splice/DAG/topo/state-read/compute-commit/value fanout/value source/BAE/boundary/logical bytes）均为 `true`。

## 3. CPP、ELF 和功能绝对值

| 版本 | `.cpp` 文件数 | `.cpp` bytes | `.cpp` lines | O3 archive bytes/SHA-256 | emu bytes/SHA-256 |
| --- | ---: | ---: | --- | --- | --- |
| cap8192 baseline | `132` | `1,356,097,029` | `13,677,698` | `99,249,366` / `d257613a74a33dd2c9abe501373bd573f1ce053ffe29103d2cbab0410b779a90` | `93,671,816` / `31ab2b820cbce126199b7baef5d9f15909f6db1e39bb72d1b140bc398924ba65` |
| min1000 strict | `132` | `1,356,062,877` | `13,677,122` | `99,223,398` / `fb79885c2707101edef1dd57f30bd9d48361f7b622faeb6203089d10d0d790cc` | `93,643,144` / `14b5a21dd70c63d76b2a28374d8d359ad11fb0af9e8d22651348c27374d6f56c` |
| min10000 strict | `132` | `1,356,074,086` | `13,677,312` | `99,264,550` / `f9fc1eb27d3ad074eaec236799fb4354ae804268f94cc2628b102cf40e421636` | `93,675,912` / `722f11c5ba27faf30bbffe13a3600739cd8d6cedb5673b9ba7e870b0bbcef979` |

O3 emu ELF section bytes：

| 版本 | `.text` | `.rodata` | `.eh_frame_hdr` | `.eh_frame` | `.data` | `.bss` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| cap8192 baseline | `87,095,345` | `5,647,080` | `8,444` | `706,144` | `152` | `14,688` |
| min1000 strict | `87,067,553` | `5,647,112` | `8,444` | `706,240` | `152` | `14,688` |
| min10000 strict | `87,101,201` | `5,647,064` | `8,444` | `706,312` | `152` | `14,688` |

生成和链接日志：

```text
build/logs/xs/xs_wolf_grhsim_build_activity_stage26_fire_profile_min1000_probe_20260718.log
build/logs/xs/xs_wolf_grhsim_build_activity_stage26_fire_profile_min1000_strict_20260718.log
build/logs/xs/stage26_fire_profile_min1000_o3_clang_build_20260718.log
build/logs/xs/stage26_fire_profile_min1000_emu_build_20260718.log
build/logs/xs/xs_wolf_grhsim_build_activity_stage26_fire_profile_min10000_probe_20260718.log
build/logs/xs/xs_wolf_grhsim_build_activity_stage26_fire_profile_min10000_strict_20260718.log
build/logs/xs/stage26_fire_profile_min10000_o3_clang_build_20260718.log
build/logs/xs/stage26_fire_profile_min10000_emu_build_20260718.log
```

固定 ASLR、NUMA0 CPU43 的 candidate 功能终点：

| 版本 | 100 cycles（Host ms） | 10,000 cycles（Host ms） | 50,000 cycles（Host ms） | guest cycle | instr/cycle |
| --- | ---: | ---: | ---: | ---: | ---: |
| min1000 strict | `239` | `9,454` | `74,272` | `101/10,001/50,001` | `0/458/73,580` |
| min10000 strict | `229` | `9,512` | `74,593` | `101/10,001/50,001` | `0/458/73,580` |

日志为 `build/logs/xs/stage26_fire_profile_{min1000,min10000}_function_{100,10000,50000}_20260718.log`；所有运行 exit=0，无 mismatch/assert/fatal。

## 4. fresh staging 和 NUMA 运行协议

min1000 初始 staging 为 `/dev/shm/tanghaojin_stage26_fire_profile_min1000_20260718_1211/n{0,1}`。N0 页面碰巧本地，但 N1 首个 ABBA control 的 `Host time=73,561ms` 被正式 runner 排除：`placement.tsv` 为 `emu 0/21260`、`nemu 110/5`，`placement_ok=0`。这不是性能样本，也不进入下表。随后 N1 使用全新目录 `/dev/shm/tanghaojin_stage26_fire_profile_min1000_n1_restage_20260718_1140/n1`，在 CPU171 上对每个文件执行 `taskset -c 171 numactl --physcpubind=171 --membind=1 cp --reflink=never`；新 inode 为 `5463/5464/5465/5466`，SHA 与源文件逐项一致。

min10000 从创建开始就对 N0 CPU43/`membind=0`、N1 CPU139/`membind=1` 逐文件复制，fresh staging 为：

```text
/dev/shm/tanghaojin_stage26_fire_profile_min10000_20260718_1415/n0/
/dev/shm/tanghaojin_stage26_fire_profile_min10000_20260718_1415/n1/
```

两档 staging 的 stat/SHA 原始记录：

```text
build/logs/xs/stage26_fire_profile_min1000_staging_stat_20260718.log
build/logs/xs/stage26_fire_profile_min1000_staging_sha256_20260718.log
build/logs/xs/stage26_fire_profile_min10000_staging_stat_20260718.log
build/logs/xs/stage26_fire_profile_min10000_staging_sha256_20260718.log
```

每个有效样本均由 `run_balanced_pair.sh`/`run_formal.sh` 执行：target CPU 使用 `taskset -c` 与 `numactl --physcpubind/--membind`，emu 使用 `setarch x86_64 -R`，前置和运行期均要求整 NUMA node 的 30 秒 idle gate/monitor，`numa_maps` 页面本地，perf 五项 scheduled，context/migration 检查，且只接受一个正的 `Host time spent`。有效样本的 function endpoint 全为 `instrCnt=73,580, cycleCnt=49,996, guest=50,001`。

## 5. min1000 的 50k walltime 和 PMU 原始值

最终判据是 `Host time spent`。下表的每个数字直接来自各组 `*_result.env`/`*_emu.log`，不是由比例反推；所有 16 个样本的 `run_status/placement_ok/monitor_ok/perf_ok/scheduler_ok/function_ok/affinity_ok/walltime_ok=1`，migration 均为 0。

### 5.1 walltime

| NUMA/order | control a1 | candidate b1 | candidate b2 | control a2 | control mean | candidate mean | delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| N0 ABBA | `74,345` | `74,096` | `74,274` | `74,369` | `74,357.0` | `74,185.0` | `-172.0ms (-0.231316%)` |
| N0 BAAB | `74,328` | `74,174` | `74,228` | `74,313` | `74,320.5` | `74,201.0` | `-119.5ms (-0.160790%)` |
| N1 ABBA | `74,160` | `74,318` | `74,315` | `74,018` | `74,089.0` | `74,316.5` | `+227.5ms (+0.307063%)` |
| N1 BAAB | `74,193` | `74,184` | `74,479` | `74,261` | `74,227.0` | `74,331.5` | `+104.5ms (+0.140784%)` |

按四个独立 group 等权，baseline `74,248.375ms`，candidate `74,258.500ms`，delta `+10.125ms (+0.013637%)`。

### 5.2 perf 原始行

列顺序：`cycles, instructions, frontend_noops, cmask6, backend_stalls, task-clock(ms), context-switches, migrations`。

| NUMA/order/slot | model | wall ms | cycles | instructions | frontend | cmask6 | backend | task ms | ctx | mig |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| N0 ABBA a1 | control | 74345 | 271910730809 | 164223546948 | 1241743254941 | 160974188899 | 92206474730 | 74325.17 | 803 | 0 |
| N0 ABBA b1 | candidate | 74096 | 270972717009 | 164090567204 | 1237203586218 | 160150192451 | 90623445982 | 74075.75 | 819 | 0 |
| N0 ABBA b2 | candidate | 74274 | 271607930442 | 164090568177 | 1240792235322 | 160733219142 | 90786272042 | 74252.79 | 821 | 0 |
| N0 ABBA a2 | control | 74369 | 271999322378 | 164223547143 | 1242843594535 | 161156721625 | 91602868928 | 74347.86 | 808 | 0 |
| N0 BAAB a1 | control | 74328 | 271894635425 | 164223547517 | 1242945888040 | 161141655059 | 91009335781 | 74311.44 | 764 | 0 |
| N0 BAAB b1 | candidate | 74174 | 271561878486 | 164090567457 | 1240554062084 | 160716766657 | 90834506203 | 74155.31 | 763 | 0 |
| N0 BAAB b2 | candidate | 74228 | 271640305662 | 164090567551 | 1240984447635 | 160705780422 | 91005871050 | 74204.55 | 837 | 0 |
| N0 BAAB a2 | control | 74313 | 271766627006 | 164223547509 | 1242908052667 | 161158008478 | 90169607566 | 74286.84 | 907 | 0 |
| N1 ABBA a1 | control | 74160 | 271836252061 | 164223543645 | 1242707429557 | 161102067960 | 90924744403 | 74158.28 | 430 | 0 |
| N1 ABBA b1 | candidate | 74318 | 272357878190 | 164090558449 | 1245243847867 | 161453786971 | 90977218536 | 74311.27 | 513 | 0 |
| N1 ABBA b2 | candidate | 74315 | 272218435611 | 164090558192 | 1244746963720 | 161342246224 | 90948730069 | 74311.32 | 435 | 0 |
| N1 ABBA a2 | control | 74018 | 271579260431 | 164223543674 | 1241740045247 | 160912297498 | 90433463414 | 74019.75 | 353 | 0 |
| N1 BAAB a1 | control | 74193 | 271632768407 | 164223544418 | 1242146554497 | 161042114826 | 90194202493 | 74178.72 | 655 | 0 |
| N1 BAAB b1 | candidate | 74184 | 271707114503 | 164090558438 | 1243266846155 | 161112746990 | 89323585992 | 74178.45 | 483 | 0 |
| N1 BAAB b2 | candidate | 74479 | 272638488685 | 164090559352 | 1245419887249 | 161489492441 | 92268344779 | 74461.13 | 673 | 0 |
| N1 BAAB a2 | control | 74261 | 271828825114 | 164223544151 | 1242290141438 | 161020036727 | 91441609335 | 74244.15 | 682 | 0 |

按 NUMA 汇总的诊断均值（仍不是 headline）：N0 cycles `271,892,828,904.5 -> 271,445,707,899.75`、task-clock `74,317.827 -> 74,172.100ms`；N1 cycles `271,719,276,503.25 -> 272,230,479,247.25`、task-clock `74,150.225 -> 74,315.543ms`。N1 instructions 虽 `164,223,543,972 -> 164,090,558,607.75`，但 walltime 仍回退。

原始汇总 TSV：`build/logs/xs_perf/stage26_fire_profile_min1000_all_raw_20260718.tsv`。

## 6. min10000 的 50k walltime 和 PMU 原始值

### 6.1 walltime

| NUMA/order | control a1 | candidate b1 | candidate b2 | control a2 | control mean | candidate mean | delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| N0 ABBA | `74,681` | `74,549` | `74,457` | `74,979` | `74,830.0` | `74,503.0` | `-327.0ms (-0.436991%)` |
| N0 BAAB | `74,151` | `74,555` | `74,212` | `74,484` | `74,317.5` | `74,383.5` | `+66.0ms (+0.088808%)` |
| N1 ABBA | `74,256` | `74,458` | `74,399` | `73,700` | `73,978.0` | `74,428.5` | `+450.5ms (+0.608965%)` |
| N1 BAAB | `73,788` | `74,042` | `74,084` | `74,036` | `73,912.0` | `74,063.0` | `+151.0ms (+0.204297%)` |

四个独立 group 等权：baseline `74,259.375ms`，candidate `74,344.500ms`，delta `+85.125ms (+0.114632%)`。

### 6.2 perf 原始行

| NUMA/order/slot | model | wall ms | cycles | instructions | frontend | cmask6 | backend | task ms | ctx | mig |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| N0 ABBA a1 | control | 74681 | 272955457200 | 164223547550 | 1250872778182 | 162477699920 | 89491437228 | 74620.24 | 809 | 0 |
| N0 ABBA b1 | candidate | 74549 | 272827269842 | 164207064051 | 1248087520652 | 161621718808 | 90797288459 | 74528.72 | 854 | 0 |
| N0 ABBA b2 | candidate | 74457 | 272158285140 | 164207065069 | 1244906612430 | 161074324720 | 90239711649 | 74436.90 | 836 | 0 |
| N0 ABBA a2 | control | 74979 | 273774508404 | 164223551221 | 1254355392735 | 163003706515 | 91147089109 | 74960.41 | 861 | 0 |
| N0 BAAB a1 | control | 74151 | 271579665234 | 164223547928 | 1242888169074 | 161133308313 | 89519173635 | 74137.97 | 731 | 0 |
| N0 BAAB b1 | candidate | 74555 | 272643231687 | 164207065057 | 1246620147654 | 161361003304 | 91260365977 | 74534.60 | 815 | 0 |
| N0 BAAB b2 | candidate | 74212 | 271345965986 | 164207063378 | 1241344992775 | 160506089872 | 88992561450 | 74187.27 | 916 | 0 |
| N0 BAAB a2 | control | 74484 | 272791095438 | 164223547289 | 1248499847223 | 162094078335 | 90861420978 | 74470.74 | 760 | 0 |
| N1 ABBA a1 | control | 74256 | 272481925683 | 164223365716 | 1245701790761 | 161601480219 | 91796670442 | 74259.57 | 287 | 0 |
| N1 ABBA b1 | candidate | 74458 | 272713909630 | 164207076918 | 1247798240548 | 161542636603 | 90565269284 | 74451.01 | 471 | 0 |
| N1 ABBA b2 | candidate | 74399 | 273004871503 | 164207076420 | 1250659213571 | 162050850595 | 89445603922 | 74399.60 | 341 | 0 |
| N1 ABBA a2 | control | 73700 | 270411909877 | 164223364022 | 1233894384841 | 159667964118 | 90985001570 | 73701.02 | 340 | 0 |
| N1 BAAB a1 | control | 73788 | 270517229841 | 164223363763 | 1234826186892 | 159782456715 | 90804982869 | 73782.16 | 474 | 0 |
| N1 BAAB b1 | candidate | 74042 | 271028123900 | 164207076196 | 1238120870923 | 159970109680 | 90251946102 | 74024.21 | 691 | 0 |
| N1 BAAB b2 | candidate | 74084 | 271453524527 | 164207076285 | 1242648590897 | 160671863137 | 88509345326 | 74084.61 | 361 | 0 |
| N1 BAAB a2 | control | 74036 | 271293078032 | 164223363954 | 1239748819048 | 160598493363 | 90533929302 | 74037.60 | 340 | 0 |

按 NUMA 汇总的诊断均值：N0 task-clock `74,547.340 -> 74,421.872ms`，N1 task-clock `73,945.088 -> 74,239.857ms`；N1 cycles `271,176,035,858.25 -> 272,050,107,390.0`。N1 instructions 只下降约 `0.0099%`，不能抵消 walltime `+300.75ms`。

原始汇总 TSV：`build/logs/xs_perf/stage26_fire_profile_min10000_all_raw_20260718.tsv`。

## 7. 决定和后续边界

两档 profile 都保持默认关闭：

- min1000 双 NUMA 四组等权 `74,248.375 -> 74,258.500ms`，回退 `+10.125ms (+0.013637%)`；N0 两组改善、N1 两组回退。
- min10000 双 NUMA 四组等权 `74,259.375 -> 74,344.500ms`，回退 `+85.125ms (+0.114632%)`；N1 两组均明显回退。
- cycles、instructions、frontend/backend、task-clock 只解释现象，不改变 walltime headline。
- C++ 默认仍为 cap8192/native hybrid，profile path 仅作显式、fail-closed 实验开关；不把 profile 或阈值写成 XS 专属默认。

结论是 runtime fire 的单向 source/target gate 能减少结构边，但当前两档都无法转化为稳定端到端收益，且表现出 NUMA/layout 敏感性。后续若继续 activity schedule，应先解决 profile 与 generated layout 的稳定映射，再用同一 fresh page-local 协议验证。
