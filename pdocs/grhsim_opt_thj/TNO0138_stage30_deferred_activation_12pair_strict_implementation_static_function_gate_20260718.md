# TNO0138 Stage 30 deferred-activation 12-pair strict implementation, static gate, and function gate

日期：2026-07-18

状态：Stage 30 的 strict overlay 已完成 production emit、O3/archive、emu link 和
100/10k/50k 功能门禁。正式性能结论仍未形成：当前机器被外部 `firtool`/`gsim`/Java
任务占用，双 NUMA formal runner 没有得到完整的平衡 ABBA/BAAB 有效组。`cofire-strict`
继续保持显式 default-off；不能用插桩 walltime、cycles 或不满足 idle gate 的样本代替
SimTop `Host time spent`。

## 1. 基线与实现边界

- 基线是当前仓库默认生成配置 NO0300，ASLR 关闭；control emu 为
  `build/xs_activity_stage23_cap8192_cpp_default_20260718/grhsim/grhsim-compile/emu`。
- strict 只接受 Stage29 前 12 个 cofire pair，排除 `35026 -> 38043`；固定 12 对的
  source/target、active ID、batch、108/108 op shape、50k fire、648 个 exclusive
  `ValueId` 及指纹。profile shape 或 schedule 改变时 fail-closed。
- C++ 新增 `deferred_activation_forward_policy=cofire-strict`，C++ 默认仍为 `off`；
  Python/native/XS 只转发显式选项，不在 XS 脚本另设默认。
- overlay 只替换普通 compute 的 changed-value/deferred lowering：baseline deferred
  flush 之后写 12 个无条件 target activation；fullpass、commit、seed、materialization、
  slots、active ID、batch 和 session 保持 baseline。

production emit 命令（完整 raw log）：

```text
build/logs/xs/stage30_strict_final_20260718.log
```

该日志 SHA256=`9fa737de7b83ad529b038b36da8ff5bd5d843704c4c6a3c0d1984c1d2097d9b0`，大小
`278007` bytes，`Exit status: 0`。严格门禁原始行如下：

```text
[GRHSIM_DEFERRED_ACTIVATION_STRICT] accounting=control compute_sources=12 tracked_change_values=1242 direct_value_groups=335 deferred_groups=87 deferred_source_value_updates=1174 deferred_direct_groups=87 deferred_aggregate_groups=0 forward_groups=0 active_mask_entries=504 planned_chunks=423 chunk1=342 chunk2=81 chunk4=0 chunk8=0 branchless_groups=422 guarded_groups=0 conditional_mask_updates=423 local_rmw=0 global_rmw=423 updated_bytes=504 estimated_activation_lines=423 work_units=3262
[GRHSIM_DEFERRED_ACTIVATION_STRICT] accounting=overlay compute_sources=12 tracked_change_values=594 direct_value_groups=332 deferred_groups=76 deferred_source_value_updates=529 deferred_direct_groups=76 deferred_aggregate_groups=0 forward_groups=12 active_mask_entries=502 planned_chunks=421 chunk1=340 chunk2=81 chunk4=0 chunk8=0 branchless_groups=408 guarded_groups=0 conditional_mask_updates=409 local_rmw=0 global_rmw=421 updated_bytes=502 estimated_activation_lines=445 work_units=1953
[GRHSIM_DEFERRED_ACTIVATION_STRICT] validated=true pairs=12 values=648
```

全局 deferred accounting 也由同一日志记录：

```text
control:   tracked_change_values=752375 direct_value_groups=140145 deferred_groups=136969 deferred_source_value_updates=925811 active_mask_entries=420843 planned_chunks=396572 branchless_groups=265317 conditional_mask_updates=327748 global_rmw=399483 updated_bytes=418250 estimated_activation_lines=549155 work_units=2417244
candidate: tracked_change_values=748354 direct_value_groups=140101 deferred_groups=136859 deferred_source_value_updates=921836 active_mask_entries=420817 planned_chunks=396546 branchless_groups=265163 conditional_mask_updates=327594 global_rmw=399457 updated_bytes=418224 estimated_activation_lines=549385 work_units=2409068
```

## 2. CPP/static 对账

只有以下 8 个 schedule CPP 改变；其他 schedule CPP、header、eval、runtime、state、
activity stats 和 emitter stats SHA 均相同。表中大小是原始文件 bytes：

| schedule CPP | control | strict | delta |
| --- | ---: | ---: | ---: |
| `11` | 29,268,760 | 29,257,580 | -11,180 |
| `52` | 16,481,482 | 16,470,290 | -11,192 |
| `53` | 13,068,529 | 13,046,221 | -22,308 |
| `54` | 12,351,388 | 12,329,004 | -22,384 |
| `56` | 14,143,796 | 14,132,616 | -11,180 |
| `57` | 13,563,137 | 13,551,957 | -11,180 |
| `59` | 14,553,166 | 14,519,626 | -33,540 |
| `60` | 13,035,601 | 13,024,421 | -11,180 |
| 合计（8 files） | 126,465,859 | 126,331,715 | -134,144 |

按 `grhsim_changed_<ValueId.index>` 的 unique set 比较，control=`613454`、strict=`612806`，
恰好 removed=`648`、added=`0`。静态 source diff 同时显示 deferred accumulator 更新净减
`645`、deferred group 声明净减 `11`，新增 unconditional forward group `12`；这是
emitter lowering 计数，不是 CPU 指令或 walltime 保证。

非 schedule 文件的 SHA256（control 与 strict 各自相同）为：

```text
grhsim_SimTop.hpp                  8022ea29a39ce82cd6f46fc4d2bb49d8cbc29b57d97459696710500d40f8da6d
grhsim_SimTop_eval.cpp             4d99029805f5ed72dd3de5200775a8b44969ea1265d985479cce8a37e1a072cc
grhsim_SimTop_runtime.hpp          07484074f859abd94f71fef13aaf6ab5b6d8c1f65d23d0e1d6333a5e4bd4d8ff
grhsim_SimTop_state.cpp             70f2cdae4c6fe903525ebfc52253aff1817e4169af3493439016c5d50d969dbe
activity_schedule_supernode_stats  6c41b8b25d83e05d402dbeb6164553bdd10903b8c8e67efae8cfd3cf6542257c
grhsim_emit_stats.json              9dd1bdddd01606507b2e3425917f260ca3ac8c5b88c55fa21408bffb17080a8b
```

## 3. O3、link 与二进制绝对值

O3/archive 命令使用 `CXX=clang++ -j4`，raw log SHA=`3b18dd1a0df6c7c9e0e0bddeb40cd975505c6a14bde872463abb0245f8b60e12`，大小
`24797` bytes，退出 0。archive：

```text
build/xs_activity_stage30_strict_final_20260718/grhsim/grhsim_emit/libgrhsim_SimTop.a
bytes=99234046
sha256=e5bc42cc93f834695af97fbf123f301b2698d71cede8bb82ae218ef9e0cf2bfd
```

emu link raw log SHA=`30d6691179bd882eb45efb7c17a8181b57c2a8b2db5bf8791c92389f1642af39`，大小
`5615` bytes，退出 0。control/strict emu 的绝对值：

| emu | bytes | SHA256 | `size text` |
| --- | ---: | --- | ---: |
| control | 93,671,816 | `31ab2b820cbce126199b7baef5d9f15909f6db1e39bb72d1b140bc398924ba65` | 93,495,071 |
| strict | 93,655,432 | `c2fbd21b379c2d7ae9d2b930386a3130254045bbbab3bfeefa311e2bebf0ac0b` | 93,479,439 |

strict 相对 control 的 `.text` 差为 `-15,632` bytes；这个静态差异只作解释，不能替代
SimTop walltime。

## 4. Fresh staging 与功能门禁

staging 根目录为全新 `/dev/shm/tanghaojin_stage30_cofire_strict_20260718_v1`。每个
node 的 control/candidate/coremark/NEMU 都用目标 CPU 的
`taskset -c <cpu> numactl --physcpubind=<cpu> --membind=<node> cp --reflink=never`
单独复制；N0 使用 CPU43，N1 使用 CPU139。8 个目标 inode、源/目标 SHA 和 `cmp` 结果
记录在：

```text
build/logs/xs/stage30_strict_final_staging_stat_sha_20260718.log
sha256=6162e0451a5804db288a5aaf34db92e238d55c63337eeb1504125d6e993cae5e
bytes=4752
```

例如 N0 inode 为 control=`5495`、candidate=`5496`、image=`5497`、NEMU=`5498`；N1
为 `5499..5502`。control/candidate/image/NEMU 的源 SHA 分别为：

```text
control   31ab2b820cbce126199b7baef5d9f15909f6db1e39bb72d1b140bc398924ba65
candidate c2fbd21b379c2d7ae9d2b930386a3130254045bbbab3bfeefa311e2bebf0ac0b
image     c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e
NEMU      094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e
```

control 和 strict 在 N0/N1 各完成 100/10k/50k fixed-ASLR 功能运行，所有 6 个 raw
log 均 exit 0，无 mismatch/assert/fatal：

| cycles | instrCnt | cycleCnt | guest | control Host time（诊断） | strict Host time（诊断） |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 100 | 0 | 96 | 101 | 210 ms | 144 ms |
| 10,000 | 458 | 9,996 | 10,001 | 9,518 ms | 9,456 ms |
| 50,000 | 73,580 | 49,996 | 50,001 | 74,532 ms | 74,270 ms |

这些单次功能运行没有 whole-node formal gate，Host time 只作为 raw log 字段保留，
不进入性能结论。六个 raw log 的 SHA/大小分别见 `build/logs/xs/` 下
`stage30_strict_final_function_{control,candidate}_{100,10000,50000}_20260718.log`；
其大小为 control=`680/820/1022` bytes、strict=`684/824/1026` bytes。

## 5. Formal walltime 当前状态

正式 runner 仍固定使用 `setarch x86_64 -R`、target `taskset+numactl`、30 秒整 node
admission/运行期 monitor、emu/NEMU `numa_maps`、五项 PMU、scheduler/migration、功能
终点和唯一正 `Host time spent`。有效样本必须同时满足所有字段为 1；以下绝对值仅列出
runner 已产生的 raw `walltime_ms`，不合格组不纳入任何均值：

| node/order/try | raw walltime（按 runner 名称顺序） | 结果 |
| --- | --- | --- |
| N0 ABBA try1 | a1(control)=74,504；b1(candidate)=74,309；b2(candidate)=74,376；a2(control)=74,482 | 作废，a2 `monitor_ok=0`，min idle=`94.600%` |
| N0 ABBA try2 | a1(control)=74,500；b1(candidate)=74,293；b2(candidate)=74,239；a2(control)=74,359 | 四样本全部 `run_status/placement/monitor/perf/scheduler/function/affinity/walltime_ok=1` |
| N0 BAAB try1 | b1(candidate)=74,363；a1(control)=74,393；a2(control)=74,435 | 作废，a2 `monitor_ok=0`，min idle=`94.700%`；b2 未启动 |
| N0 BAAB try2 | b1(candidate)=74,512；a1(control)=74,413；a2(control)=74,419 | 作废，a2 `monitor_ok=0`，min idle=`94.980%`；b2 未启动 |
| N0 BAAB try3/try4 | 无 | 10 次 admission 均无 quiet window，未启动 |
| N1 ABBA try1 | 无 | 10 次 admission 均无 quiet window，未启动 |

ABBA try2 是当前唯一完整有效的单 node/order 组，但在 N0 上不能单独代表双 NUMA
结论。对应 driver raw log 位于
`build/logs/xs_perf/stage30_deferred_activation_12pair_strict_20260718/`；try1/2
ABBA driver 分别为 `4898` bytes，BAAB try1/2 为 `3833` bytes，BAAB try3/4 和 N1
ABBA try1 为 `1310` bytes。无效组的 raw `*_result.env`、placement、gate、monitor、
perf CSV 和 emu log 全部保留在既有 group 目录。

同一时段的独立 30 秒 survey：N0 `mean_idle=93.831%`、`min_idle=73.620%`，N1
`mean_idle=93.827%`、`min_idle=46.750%`；raw logs 分别为
`build/logs/xs_perf/stage30_node0_idle_survey_20260718.log`（SHA
`b20d4f9b242f455535df120f9168148500c64f4460674ecd0bf73f3d4fd28c63`，`580462` bytes）和
`stage30_node1_idle_survey_20260718.log`（SHA
`940b4890f0320661ff780615651e42559915e6a02238f021e027e18abd477594`，`580462` bytes）。
当时可见外部高负载 `firtool`/`gsim`/Java 进程，因此没有杀掉外部任务，也没有降低
`mean>=99%`、`min>=95%` 门槛。

结论：Stage30 strict 已通过实现、静态、O3/link 和功能门禁，但尚未获得双 NUMA 平衡
`Host time spent`。在 TNO0139 完成 fresh page-local ABBA/BAAB 后，仍只以 walltime
决定是否保留显式 strict；C++ default 先保持 `off`。

## 6. 勘误（2026-07-19）：Stage28 broad accounting 与 Stage30 overlay accounting

第 1 节引用的全局 `accounting=candidate` 行是
`runDeferredActivationForwardProbe()` 对 Stage28 broad 128-pair private candidate 的诊断，
不是最终实际写入 CPP 的 Stage30 12-pair strict overlay。原文把
`2,417,244 -> 2,409,068` 当作 Stage30 全局结果不正确；局部 strict raw gate
`3,262 -> 1,953`、12 pairs、648 values 和生成源码差分均不受影响。

把 Stage30 局部 control/overlay delta 应用到全局 control 后，实际 12-pair strict
全局 accounting 为：

```text
work_units                  2417244 -> 2415935
tracked_change_values        752375 -> 751727
direct_value_groups          140145 -> 140142
deferred_groups              136969 -> 136958
deferred_source_updates      925811 -> 925166
forward_groups                    0 -> 12
active_mask_entries          420843 -> 420841
planned_chunks               396572 -> 396570
branchless_groups            265317 -> 265303
conditional_mask_updates     327748 -> 327734
global_rmw                   399483 -> 399481
updated_bytes                418250 -> 418248
estimated_activation_lines   549155 -> 549177
```

因此 Stage30 的真实 static work 差是 `-1,309`，不是 Stage28 broad probe 的
`-8,176`；estimated activation lines 为 `+22`。后续 TNO0139/runtime 决策只使用
本勘误后的 12-pair accounting，并继续以 SimTop `Host time spent` 为最终口径。
