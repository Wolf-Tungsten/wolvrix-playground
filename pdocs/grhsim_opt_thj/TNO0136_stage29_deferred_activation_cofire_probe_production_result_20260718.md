# TNO0136 Stage 29 deferred-activation cofire probe production result（2026-07-18）

## 1. 范围、基线与结论

本记录承接 [TNO0135](./TNO0135_stage29_deferred_activation_cofire_counter_plan_20260718.md)，在当前仓库默认生成配置上完成了 Stage 29 的显式 `cofire-probe` production emit、O3/archive、emu link 以及 100/10k/50k 动态计数。

基线是 C++ native default：NO0300、ASLR 关闭、commit cap `8192`、native hybrid 默认、terminal pushforward `off`、shared-input peer `off`，其余 activity-schedule 选项保持 C++ 默认。`cofire-probe` 只在显式 policy 下编译计数器和 TSV dump，不改变 graph、activity schedule、Kahn level、active ID、batch、value slot、consumer/session map 或仿真逻辑；默认/off 仍不启用该插桩。

结论如下：

- 100、10k、50k 均未出现 difftest mismatch，功能门禁通过；`Host time spent` 在此处只是带 runtime-profile 插桩的诊断值，不能与未插桩 SimTop 性能比较。
- 50k 中前 12 对（pair `0..11`）均满足 `leader_without_follower=0` 且 `after_pending/follower_pending=leader_fire`，进入下一阶段的 12-pair strict overlay 计划。
- pair 12（`35026 -> 38043`）在 10k 已有 `leader_without_follower=2`，50k 为 `141`，故停止该 pair 的 strict 尝试；本阶段没有生成 strict candidate，也没有运行未插桩 SimTop 50k。
- 因而 Stage 29 不改变任何 C++ 默认选项；后续 Stage 30 只针对 pair `0..11` 单独设计 strict/no-mutation 对账和 walltime gate，不能把 13 对整体晋升。

## 2. Production emit 与构建记录

### 2.1 输入与 emit

Stage 28 fire profile 为
`build/logs/xs_perf/activity_stage19_table_runtime_profile_20260717/fire_50000.tsv`，SHA256
`4106fafbea0871724206d81fc5cda19088656d0e185a15c80ea5e9fe7655b11c`；profile 包含 `63,241` 个 compute row，`485` 个 commit row 被忽略。

production emit 使用了 `source env.sh`，并显式设置：

```text
WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1
WOLVRIX_XS_GRHSIM_POST_STATS_JSON=build/xs_activity_stage8_dp_p050_20260715/grhsim/wolvrix_xs_post_stats.json
WOLVRIX_XS_GRHSIM_DEFERRED_ACTIVATION_FORWARD_POLICY=cofire-probe
WOLVRIX_XS_GRHSIM_DEFERRED_ACTIVATION_FORWARD_PROFILE_PATH=build/logs/xs_perf/activity_stage19_table_runtime_profile_20260717/fire_50000.tsv
WOLVRIX_XS_GRHSIM_FINAL_TERMINAL_PUSHFORWARD_POLICY=off
WOLVRIX_XS_GRHSIM_FINAL_SHARED_INPUT_PEER_POLICY=off
```

命令主体为：

```text
source env.sh && env <上述变量> /usr/bin/time -v python3 scripts/wolvrix_xs_grhsim.py \
  build/xs_activity_stage22_terminal_pushforward_strict_20260718/wolf/wolf_emit/xs_wolf.f \
  SimTop \
  build/xs_activity_stage29_deferred_activation_cofire_probe_20260718/grhsim/grhsim_emit \
  build/xs_activity_stage29_deferred_activation_cofire_probe_20260718/grhsim/grhsim_emit/xs_wolf_grhsim.json \
  build/xs_activity_stage23_cap8192_cpp_default_20260718/grhsim/grhsim_emit/wolvrix_read_args.txt \
  info --waveform off --perf off
```

emit 日志：

```text
path: build/logs/xs/xs_wolf_grhsim_build_activity_stage29_deferred_activation_cofire_probe_20260718.log
SHA256: 41f62a2bb5563ef4ca661388fdf4f9b265f84b0c214f37582c44b3551878d94b
size: 275595 bytes
```

关键生产行为是：

```text
policy=cofire-probe profile_valid=true profile_compute_rows=63241 profile_ignored_commit_rows=485 raw_pairs=490406 shared_value_pairs=246859 exact_eligible=3864 accounted=3864 static_positive=3864 selected=128 selected_values=4021 reported_selected=128 reported_near_selected=64 truncated=false global_control_work_units=2417244 global_candidate_work_units=2409068 global_work_units_delta=-8176 selected_fire_weighted_work_proxy_lower=-71582689 selected_fire_weighted_work_proxy_upper=60496519 selected_positive_work_proxy_candidates=13 selected_positive_work_proxy_values=691 selected_positive_static_saved_units=1396 selected_positive_target_ops=1382 selected_positive_fire_weighted_work_proxy_lower=98106 selected_positive_fire_weighted_work_proxy_upper=9734846 physical_supernode_tests_saved=0
[GRHSIM_DEFERRED_ACTIVATION_COFIRE] emit_probe=true pairs=13 fullpass_excluded=true commit_excluded=true
```

固定的 13 对及其 active metadata（`source_active_byte` 与
`target_active_byte` 不同，故均为跨 active word）如下：

| pair | source -> target | active ID | active byte | batch | source/target ops |
| ---: | --- | --- | --- | --- | ---: |
| 0 | `51194 -> 52335` | `51478 -> 52351` | `6434 -> 6543` | `53 -> 54` | `108 / 108` |
| 1 | `51196 -> 52337` | `52773 -> 53422` | `6596 -> 6677` | `54 -> 55` | `108 / 108` |
| 2 | `51195 -> 52336` | `50520 -> 51576` | `6315 -> 6447` | `52 -> 53` | `108 / 108` |
| 3 | `51197 -> 52338` | `52774 -> 53423` | `6596 -> 6677` | `54 -> 55` | `108 / 108` |
| 4 | `51193 -> 52334` | `51477 -> 52350` | `6434 -> 6543` | `53 -> 54` | `108 / 108` |
| 5 | `57291 -> 57901` | `57683 -> 57992` | `7210 -> 7249` | `59 -> 59` | `108 / 108` |
| 6 | `57289 -> 57899` | `55132 -> 55360` | `6891 -> 6920` | `57 -> 57` | `108 / 108` |
| 7 | `57290 -> 57900` | `54927 -> 55148` | `6865 -> 6893` | `56 -> 57` | `108 / 108` |
| 8 | `57294 -> 57904` | `58315 -> 58724` | `7289 -> 7340` | `60 -> 60` | `108 / 108` |
| 9 | `57293 -> 57903` | `57912 -> 58351` | `7239 -> 7293` | `59 -> 60` | `108 / 108` |
| 10 | `57292 -> 57902` | `57911 -> 58350` | `7238 -> 7293` | `59 -> 60` | `108 / 108` |
| 11 | `10635 -> 27668` | `10260 -> 28585` | `1282 -> 3573` | `11 -> 30` | `108 / 108` |
| 12 | `35026 -> 38043` | `25864 -> 27857` | `3233 -> 3482` | `28 -> 30` | `92 / 86` |

### 2.2 Generated source、O3 archive 与 emu link

生成目录为
`build/xs_activity_stage29_deferred_activation_cofire_probe_20260718/grhsim/grhsim_emit/`。
其中有 `132` 个 `.cpp`（`97` schedule、`33` state-init、`2` 其它）、`2` 个头文件；包含对象文件时目录共有 `273` 个 regular files。显式 probe 会改变 CPP（这是预期的计数器插桩），但 activity stats 和 emitter stats 仍与 baseline 对齐：

| artifact | SHA256 | size |
| --- | --- | ---: |
| `activity_schedule_supernode_stats.json` | `6c41b8b25d83e05d402dbeb6164553bdd10903b8c8e67efae8cfd3cf6542257c` | `5382` |
| `grhsim_emit_stats.json` | `9dd1bdddd01606507b2e3425917f260ca3ac8c5b88c55fa21408bffb17080a8b` | `418` |
| `libgrhsim_SimTop.a` | `46361e7f7ada5aa2a5b693647c5f19d7b282fd6bdd6d19d840f1f9ed01cbece3` | `101170888` |
| `grhsim-compile/emu` | `d5c3f11a8a4029d5eef34387d0a3240d5074db7a0f9d2c2c46059b61150a5d6d` | `95589792` |

O3 archive 命令日志：

```text
path: build/logs/xs/stage29_deferred_activation_cofire_probe_o3_build_20260718.log
SHA256: ff46a438abf206a65aa96acb5fd4f067a14f52f1c35d3eb570d2d967c106ada4
size: 24857 bytes
command: make -C build/xs_activity_stage29_deferred_activation_cofire_probe_20260718/grhsim/grhsim_emit CXX=clang++ -j4
elapsed: 9:52.10
exit: 0
```

emu link 日志：

```text
path: build/logs/xs/stage29_deferred_activation_cofire_probe_emu_build_20260718.log
SHA256: b4c9e3e9c8c77c3cd52f8f7a7a3cf7a8ea06e7215cfb0ab347da82bf8944aa44
size: 6900 bytes
elapsed: 0:15.99
exit: 0
```

## 3. 动态功能与 cofire 原始值

运行使用固定-ASLR、单核诊断绑定。每条命令均先 `source env.sh`，并使用：

```text
taskset -c 86 numactl --physcpubind=86 --membind=0 setarch x86_64 -R ./emu -i <coremark-2-iteration.bin> \
  --diff <riscv64-nemu-interpreter-so> -b 0 -e 0 -C <cycles>
```

这是 profile 插桩诊断，不是双 NUMA 性能 gate；CPU86 的短时 idle 检查约为 `89.6%`。三次运行直接使用 build/NFS 路径，**没有**为 emu、NEMU 和 image 建立 fresh `/dev/shm` inode，没有在 N0 绑定下 first-touch copy，也没有执行 `numa_maps` page-placement 门禁。因此这些 walltime 明确不属于 performance sample；Stage 29 counters 无需为此重跑。emu build 与运行期均没有 difftest mismatch，达到 cycle limit 后正常返回 `0`。每个运行的 raw log 和 TSV 均保留绝对值、SHA256 与文件大小：

| cycles | raw log（Host time / instr / cycle / guest cycle / stop PC） | raw log SHA256（size） | cofire TSV SHA256（size） |
| ---: | --- | --- | --- |
| 100 | `378ms / 0 / 96 / 101 / 0x0` | `bd02d5afe4d1ae63c203d3195332477a84ff83f2d34174126a409758375825d2` (`4941`) | `a5ed4321e0306c30b4512846198714413d08feaa16de67bedd86a7cd34f025a5` (`754`) |
| 10,000 | `9585ms / 458 / 9996 / 10001 / 0x800027c6` | `74ca7b1b73fa5e58908c421ac7ed444b81149fb2b2d82513834de05b77801ffb` (`5183`) | `7c9d3e93fa1f779aef1c683471ea1eb8bc8ba68f030bac7b5990f04400c9a5ff` (`856`) |
| 50,000 | `75426ms / 73580 / 49996 / 50001 / 0x80001312` | `4d3a2d5ad2ee126fe34ccdfb3bf06b6631b28fb475d5d181e9aa2116674a6b9a` (`5589`) | `f67fd7cdff3d6488dc19e099227a113001e57fc58a9359452e2c1bf411d55764` (`1060`) |

日志路径分别为：

```text
build/logs/xs/stage29_cofire_100_20260718.log
build/logs/xs/stage29_cofire_10000_20260718.log
build/logs/xs/stage29_cofire_50000_20260718.log
build/logs/xs_perf/stage29_cofire_100_20260718.tsv
build/logs/xs_perf/stage29_cofire_10000_20260718.tsv
build/logs/xs_perf/stage29_cofire_50000_20260718.tsv
```

以下表格直接抄录 TSV 的绝对计数。`after_pending` 与
`follower_pending` 是实现中有意保留的同义列；这两列相等不是由比例反推。

### 3.1 100-cycle 原始值

```text
pair source->target leader_fire follower_fire before_pending after_pending follower_pending follower_already_pending baseline_flush_added leader_without_follower forward_would_add
0 51194->52335 1 1 1 1 1 1 0 0 0
1 51196->52337 1 1 1 1 1 1 0 0 0
2 51195->52336 1 1 1 1 1 1 0 0 0
3 51197->52338 1 1 1 1 1 1 0 0 0
4 51193->52334 1 1 1 1 1 1 0 0 0
5 57291->57901 1 1 1 1 1 1 0 0 0
6 57289->57899 1 1 1 1 1 1 0 0 0
7 57290->57900 1 1 1 1 1 1 0 0 0
8 57294->57904 1 1 1 1 1 1 0 0 0
9 57293->57903 1 1 1 1 1 1 0 0 0
10 57292->57902 1 1 1 1 1 1 0 0 0
11 10635->27668 1 1 1 1 1 1 0 0 0
12 35026->38043 1 1 1 1 1 1 0 0 0
```

### 3.2 10k-cycle 原始值

```text
pair source->target leader_fire follower_fire before_pending after_pending follower_pending follower_already_pending baseline_flush_added leader_without_follower forward_would_add
0 51194->52335 75 76 10 75 75 10 65 0 65
1 51196->52337 78 81 24 78 78 24 54 0 54
2 51195->52336 89 91 13 89 89 13 76 0 76
3 51197->52338 72 74 23 72 72 23 49 0 49
4 51193->52334 103 103 7 103 103 7 96 0 96
5 57291->57901 75 78 10 75 75 10 65 0 65
6 57289->57899 94 94 10 94 94 10 84 0 84
7 57290->57900 86 86 11 86 86 11 75 0 75
8 57294->57904 56 58 17 56 56 17 39 0 39
9 57293->57903 77 79 28 77 77 28 49 0 49
10 57292->57902 74 74 15 74 74 15 59 0 59
11 10635->27668 55 57 55 55 55 55 0 0 0
12 35026->38043 17 15 1 15 15 1 14 2 16
```

### 3.3 50k-cycle 原始值（最终动态判定）

```text
pair source->target source_active_id target_active_id leader_fire follower_fire before_pending after_pending follower_pending follower_already_pending baseline_flush_added leader_without_follower forward_would_add
0 51194->52335 51478 52351 8221 8313 1043 8221 8221 1043 7178 0 7178
1 51196->52337 52773 53422 8012 8102 1015 8012 8012 1015 6997 0 6997
2 51195->52336 50520 51576 7928 8013 1072 7928 7928 1072 6856 0 6856
3 51197->52338 52774 53423 7786 7865 1075 7786 7786 1075 6711 0 6711
4 51193->52334 51477 52350 7780 7857 1108 7780 7780 1108 6672 0 6672
5 57291->57901 57683 57992 7332 7401 1053 7332 7332 1053 6279 0 6279
6 57289->57899 55132 55360 7292 7370 1064 7292 7292 1064 6228 0 6228
7 57290->57900 54927 55148 7283 7358 1094 7283 7283 1094 6189 0 6189
8 57294->57904 58315 58724 7272 7325 1042 7272 7272 1042 6230 0 6230
9 57293->57903 57912 58351 7111 7185 1054 7111 7111 1054 6057 0 6057
10 57292->57902 57911 58350 7091 7155 1045 7091 7091 1045 6046 0 6046
11 10635->27668 10260 28585 3557 3559 3557 3557 3557 3557 0 0 0
12 35026->38043 25864 27857 3220 3649 706 3079 3079 706 2373 141 2514
```

## 4. 解释与 Stage 30 入口

对 pair `0..11`，50k 的 `after_pending` 恰好等于 `leader_fire`，且
`leader_without_follower=0`。`forward_would_add` 与
`baseline_flush_added` 也逐行相等，说明在本 workload 中 source fire 前
尚未置位的 target bit 会由 baseline deferred flush 提供；这只是时序证据，
不是 walltime 收益保证。

pair 12 的 50k 绝对值为 `leader_fire=3220`、
`follower_fire=3649`、`before_pending=706`、`after_pending=3079`、
`follower_pending=3079`、`baseline_flush_added=2373`、
`leader_without_follower=141`、`forward_would_add=2514`。它在 source
fire 后仍有 141 次 target 未 pending，若直接 unconditional forward 会
引入额外 activation 风险，因此停止该 pair，不以平均 follower fire 或
静态 proxy 掩盖这一事实。

Stage 30 可以只取 pair `0..11` 做独立 strict overlay 研究：优先删除/替换
对应 baseline deferred target-bit update，再以未插桩 100/10k/50k 功能和
SimTop 双 NUMA `Host time spent` walltime 裁决。正式 walltime 必须重新做
fresh `/dev/shm` inode、目标 node 绑定下 first-touch copy、独立 emu/NEMU/image、
`numa_maps` placement、整 node idle/runtime gate 和平衡 AB/BA。strict 版本必须重新验证
每个 pair 的 changed-group 唯一性、普通 compute-only、无 side effect、
fullpass/commit/seed 排除，以及 output/signature 等价；不得把本阶段的
插桩 walltime `378/9585/75426 ms` 当作性能结论。

## 5. Verification record

| gate | result |
| --- | --- |
| `source env.sh && cmake --build wolvrix/build -j4` | PASS |
| `WOLVRIX_TEST_DEFERRED_ACTIVATION_FORWARD=1 wolvrix/build/bin/emit-grhsim-cpp` | PASS |
| `python3 wolvrix/tests/pybind/test_emit_grhsim_cpp_options.py` | `12/12 PASS` |
| `python3 scripts/test_wolvrix_xs_grhsim_options.py` | `23/23 PASS` |
| O3 archive (`make ... CXX=clang++ -j4`) | exit `0` |
| emu link (`make ... difftest emu`) | exit `0` |
| fixed-ASLR emu 100/10k/50k | exit `0`, no difftest mismatch |
| default/off policy | unchanged; no cofire counters compiled |

本阶段完整 CTest 由后续总 gate 统一运行，未将 profile 插桩版本误报为
SimTop walltime 性能样本。
