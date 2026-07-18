# TNO0127 Stage 25 commit-cap re-evaluation walltime and default decision

记录日期：2026-07-18

状态：在 TNO0126 计划的当前 cap8192/C++ native-hybrid 基线上重做 commit guard merge-cap。cap16384 的结构收益明显，但 fresh page-local 双 NUMA 的独立复测在 N1 BAAB 重复中出现稳定回退；因此不修改默认。cap32768 相对 cap16384 只再减少 `182` 个 BAE 且尚未进入 full CPP/runtime，按边际收益和布局风险停止。

## 1. 输入、候选和绝对结构值

所有候选从同一 post-stats checkpoint 恢复，未打开 terminal pushforward、probe、post-DP refine、Kahn pack 或其它实验开关。当前默认基线为：

```text
build/xs_activity_stage23_cap8192_cpp_default_20260718/grhsim/grhsim_emit/
```

结构扫描的绝对值：

| commit cap | total SN | compute SN | commit SN/runs | compute-compute pairs | compute-commit pairs | total BAE | DAG | boundary values |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `8192` baseline | `63,709` | `63,241` | `468` | `1,721,698` | `261,628` | `1,983,326` | `527,990` | `1,000,463` |
| `12288` structure-only | `63,703` | `63,241` | `462` | `1,721,698` | `260,238` | `1,981,936` | `527,484` | `1,000,463` |
| `16384` full | `63,700` | `63,241` | `459` | `1,721,698` | `260,164` | `1,981,862` | `527,331` | `1,000,463` |
| `32768` structure-only | `63,696` | `63,241` | `455` | `1,721,698` | `259,982` | `1,981,680` | `526,921` | `1,000,463` |

相对 cap8192，cap16384 是 `-1,464` total BAE、`-659` DAG、`-9` commit SN；cap32768 在此基础上只再减少 `182` BAE、`410` DAG。compute partition、graph、state-read 集合和 sink op 数均保持不变。cap12288/16384/32768 的 raw activity logs 分别为：

```text
build/logs/xs/xs_wolf_grhsim_build_activity_stage25_commit_cap12288_20260718.log
build/logs/xs/xs_wolf_grhsim_build_activity_stage25_commit_cap16384_full_20260718.log
build/logs/xs/xs_wolf_grhsim_build_activity_stage25_commit_cap32768_20260718.log
```

## 2. cap16384 full emit、O3 和功能 gate

cap16384 generated output：

```text
build/xs_activity_stage25_commit_cap16384_20260718/grhsim/grhsim_emit/
build/logs/xs/xs_wolf_grhsim_build_activity_stage25_commit_cap16384_full_20260718.log
build/logs/xs/stage25_commit_cap16384_o3_clang_build_20260718.log
build/logs/xs/stage25_commit_cap16384_emu_build_20260718.log
```

activity stats SHA-256 为 `70bb3f488b608e028191ab3c2f04233d163e3f2c39c67e4e92413851d551c5cf`；`grhsim_emit_stats.json` 与 cap8192 byte-exact，SHA-256 为 `9dd1bdddd01606507b2e3425917f260ca3ac8c5b88c55fa21408bffb17080a8b`。generated `.cpp` 总量为 `120` 个、`1,355,942,951` bytes、`13,676,920` lines；cap8192 对应 `132` 个、`1,356,097,029` bytes、`13,677,698` lines。O3 archive 为 `99,214,180` bytes，SHA-256 `701ee7d9975c16679a99b47ebd4fb1950e191883d69e2e507414525497050be3`；emu 为 `93,661,624` bytes，SHA-256 `7aba76bf5e843cfa0cfa96317acb8148bf3109303701df4ea5298946fec417ef`。

cap16384 emu 的 ELF section 绝对值为：`.text=87,097,093`、`.rodata=5,641,512`、`.eh_frame_hdr=8,348`、`.eh_frame=704,960`、`.data=152`、`.bss=14,688` bytes。cap8192 对应 `.text=87,095,345`、`.rodata=5,647,080`、`.eh_frame_hdr=8,444`、`.eh_frame=706,144`、`.data=152`、`.bss=14,688` bytes；因此 cap16384 `.text` 增加 `1,748` bytes，不能仅凭 BAE 下降推断 runtime 必然改善。

固定 ASLR 功能日志：

```text
build/logs/xs/stage25_commit16384_function_100_20260718.log
build/logs/xs/stage25_commit16384_function_10000_20260718.log
build/logs/xs/stage25_commit16384_function_50000_20260718.log
```

绝对结果分别为 `100: Host time=201ms, instr=0, cycle=96, guest=101`；`10,000: 9,472ms, 458, 9,996, 10,001`；`50,000: 74,284ms, 73,580, 49,996, 50,001`。三个窗口 exit=0，无 mismatch/assert/fatal。

## 3. fresh staging 和 NUMA 协议

首次四组使用全新 staging：

```text
/dev/shm/tanghaojin_stage25_commit16384_20260718_0849/n0/
/dev/shm/tanghaojin_stage25_commit16384_20260718_0849/n1/
```

N1 BAAB 独立复测使用另一组 fresh inode：

```text
/dev/shm/tanghaojin_stage25_commit16384_20260718_0935/n0/
/dev/shm/tanghaojin_stage25_commit16384_20260718_0935/n1/
```

每个 staging 的 off、cap16384、`coremark.bin`、`nemu.so` 都通过 `cp --reflink=never` 生成独立 inode；复制使用 N0 CPU75/`membind=0`、N1 CPU171/`membind=1`。stat/SHA raw：

```text
build/logs/xs/stage25_commit16384_staging_stat_20260718.log
build/logs/xs/stage25_commit16384_staging_sha256_20260718.log
build/logs/xs/stage25_commit16384_try2_staging_stat_20260718.log
build/logs/xs/stage25_commit16384_try2_staging_sha256_20260718.log
```

正式 runner 仍是 `taskset -c target numactl --physcpubind=target --membind=node perf stat ... -- setarch x86_64 -R emu -i coremark.bin --diff nemu -b 0 -e 0 -C 50000`，并检查 whole-node pre/runtime idle、`numa_maps` placement、five PMU scheduled、migration=0、功能终点和唯一正 `walltime_ms`。四组首次运行及独立 try2 共 `20` 个样本，所有 `run_status/placement/monitor/perf/scheduler/function/affinity/walltime_ok=1`。

## 4. walltime 原始值

首次四组的 16 个原始 `walltime_ms` 直接来自各自 `result.env`，不是由比例反推：

| group | off a1 | cap16384 b1 | cap16384 b2 | off a2 | off mean | cap16384 mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| N0 ABBA | `74,641` | `74,189` | `74,194` | `74,481` | `74,561.0` | `74,191.5` |
| N1 ABBA | `74,633` | `74,596` | `74,451` | `74,518` | `74,575.5` | `74,523.5` |
| N0 BAAB | `74,255` | `74,209` | `74,309` | `74,571` | `74,413.0` | `74,259.0` |
| N1 BAAB | `74,200` | `74,160` | `74,309` | `74,204` | `74,202.0` | `74,234.5` |

对应原始目录和 driver 日志：

```text
build/logs/xs_perf/page_local_retest_stage7plus_20260716/groups/{n0,n1}/stage25_commit_cap16384_final_{abba,baab}_try1/
build/logs/xs_perf/stage25_commit_cap16384_20260718/n{0,1}_{abba,baab}_try1_driver.log
```

N1 BAAB 的独立 fresh try2 原始值为 off `74,118/74,082ms`、cap16384 `74,530/74,515ms`，均有效；均值 `74,100.0→74,522.5ms`，回退 `+422.5ms (+0.570131%)`。try2 原始目录/driver：

```text
build/logs/xs_perf/page_local_retest_stage7plus_20260716/groups/n1/stage25_commit_cap16384_final2_baab_try1/
build/logs/xs_perf/stage25_commit_cap16384_20260718/n1_baab_try2_driver.log
```

所有样本功能终点均为 `instrCnt=73,580, cycleCnt=49,996, guest=50,001`。raw PMU/墙钟抽取文件为：

```text
build/logs/xs_perf/stage25_commit_cap16384_20260718/clean_raw_metrics.tsv
build/logs/xs_perf/stage25_commit_cap16384_20260718/group_pmu_means_clean.tsv
build/logs/xs_perf/stage25_commit_cap16384_20260718/gates_placement_monitor.tsv
```

## 5. PMU 绝对均值

下表是首次四组两次 off/两次 cap16384 的原始 perf CSV 均值；列为 cycles、instructions、frontend-empty、cmask6、backend-stalls、task-clock(ms)、context-switches。PMU 只作诊断，不能替代 walltime：

| group | cycles off | cycles cap16384 | instructions off | instructions cap16384 | frontend off | frontend cap16384 | cmask6 off | cmask6 cap16384 | backend off | backend cap16384 | task-clock off | task-clock cap16384 | ctx off | ctx cap16384 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| N0 ABBA | `272,717,847,644.0` | `271,380,356,768.0` | `164,223,368,931.5` | `164,337,638,930.5` | `1,247,822,227,300.5` | `1,242,188,135,764.5` | `161,953,984,938.0` | `161,031,654,619.0` | `91,050,060,182.0` | `89,161,177,075.5` | `74,535.885` | `74,167.420` | `892.0` | `838.5` |
| N0 BAAB | `272,166,155,117.0` | `271,609,187,193.0` | `164,223,368,618.5` | `164,337,638,900.0` | `1,244,539,312,936.0` | `1,242,869,883,468.5` | `161,435,648,229.0` | `161,150,984,706.5` | `90,959,056,596.5` | `89,598,766,586.0` | `74,388.115` | `74,232.370` | `863.5` | `900.0` |
| N1 ABBA | `272,984,436,274.0` | `272,770,277,213.0` | `164,223,368,028.5` | `164,337,639,305.0` | `1,248,729,800,066.0` | `1,248,469,987,954.0` | `162,144,328,336.5` | `162,062,363,272.0` | `91,576,627,173.0` | `91,023,494,178.5` | `74,560.500` | `74,509.085` | `687.0` | `680.0` |
| N1 BAAB | `271,624,226,474.0` | `271,717,006,071.5` | `164,223,368,444.0` | `164,337,639,026.0` | `1,240,680,023,007.0` | `1,242,633,370,216.5` | `160,776,411,963.5` | `161,070,487,926.5` | `91,583,409,828.0` | `90,629,843,778.5` | `74,190.015` | `74,221.830` | `616.5` | `636.5` |

独立 try2 的 N1 BAAB PMU 均值也保留在 `group_pmu_means_clean.tsv`：off cycles `271,292,547,823.0`、instructions `164,223,368,030.5`、frontend `1,240,780,401,555.0`、cmask6 `160,779,298,070.5`、backend `89,722,013,931.5`、task-clock `74,087.620ms`、ctx `638.5`；cap16384 分别为 `272,672,594,457.0`、`164,337,639,186.0`、`1,248,135,073,720.5`、`161,982,569,185.5`、`90,851,393,944.0`、`74,473.640ms`、`699.0`。

## 6. balanced walltime 与决定

首次四组按 NUMA 对 ABBA/BAAB 等权：

| aggregate | off walltime (ms) | cap16384 walltime (ms) | delta (ms) | delta (%) |
| --- | ---: | ---: | ---: | ---: |
| N0 balanced | `74,487.00` | `74,225.25` | `-261.75` | `-0.351403601%` |
| N1 balanced | `74,388.75` | `74,379.00` | `-9.75` | `-0.013106821%` |
| dual-NUMA balanced | `74,437.875` | `74,302.125` | `-135.750` | `-0.182366839%` |

但 N1 BAAB fresh try2 将该组从 `74,202.0→74,234.5ms` 更新为独立均值 `74,100.0→74,522.5ms`；把两次 N1 BAAB 等权并入 N1 balanced 后，N1 为 `74,363.25→74,451.00ms`（`+87.75ms`, `+0.118001836%`），双 NUMA 为 `74,425.125→74,338.125ms`（`-87.000ms`, `-0.116896008%`）。这说明 cap16384 的 N0 收益不能稳定外推到 N1；独立 N1 BAAB 两次均值分别为 `74,234.5ms` 和 `74,522.5ms`，candidate 方向不一致且第二次两样本同向回退。

因此本阶段决策为：

- 不把 C++ native `maxOpInCommitSupernode` 从 `8192` 改为 `16384`；
- 不进入 cap32768 full CPP/O3/50k，因其相对 cap16384 仅再减 `182` BAE，且静态 `.text` 已随 cap16384 增加 `1,748` bytes；
- 保留显式 `12288/16384/32768` 实验入口，当前默认仍是 cap8192；
- 继续优先研究动态 fire-aware、layout 稳定的 terminal pushforward，最终仍只以 fresh page-local 双 NUMA `Host time spent` 裁决。
