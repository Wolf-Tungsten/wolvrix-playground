# TNO0132 Stage 27 shared-input peer probe production result

记录日期：2026-07-18

状态：probe 已完成，未进入 strict、CPP/O3 或 SimTop 50k。默认保持 `off`。

本记录承接 [TNO0131](./TNO0131_stage27_shared_input_peer_peel_probe_plan_20260718.md)。本阶段只做 no-mutation opportunity scan；`Host time spent` 仍是端到端性能唯一判据，但本阶段没有生成 candidate binary，因此没有可报告的 walltime 样本，也不以 cycles、instructions、fire 或 raw BAE 代替 walltime。

## 1. 基线与实现

使用当前仓库默认生成配置作为基线：NO0300、ASLR 关闭、C++ native-hybrid 默认、compute supernode cap `108`、commit supernode cap `8192`。terminal pushforward 显式关闭，以便把本阶段信号隔离为 shared-input peer probe。

fresh baseline activity-schedule 的绝对结构值为：

| 指标 | 原始值 |
| --- | ---: |
| graph ops | 7,204,108 |
| compute node ops total | 5,625,117 |
| supernodes | 63,709 |
| compute supernodes | 63,241 |
| commit supernodes | 468 |
| compute BAE (`compute_compute_value_pairs`) | 1,721,698 |
| total boundary activation edges | 1,983,326 |
| boundary values | 1,000,463 |
| DAG edges | 527,990 |
| compute-commit value pairs | 261,628 |
| state-read activation edges | 84,948 |
| memory-read activation edges | 47,830 |
| constant activation edges | 45,352 |
| other-compute activation edges | 1,805,196 |

实现新增 `final_shared_input_peer_*` C++ options，默认 policy 为 `off`；XS 只对显式 `WOLVRIX_XS_GRHSIM_FINAL_SHARED_INPUT_PEER_*` 环境变量做 sparse forwarding，不在脚本中设置隐含默认。候选使用既有 cheap-pure local-shared allowlist，profile parser 对 compute `0..63240` 要求恰好一行，commit 行忽略；缺失、重复、越界或 malformed profile 均 fail-closed。probe 不调用 graph mutation，也不改变 session/schedule。

active-byte/chunk 是 emitter-independent upper bound：对可删除 input，先按 `(logic_width+7)/8` 累加 logical bytes，再按每个 value 的 `ceil(bytes/8)` 累加 8-byte chunks；这不是 CPP active-mask write 的实测值。

## 2. 构建与回归

执行命令均先加载 `env.sh`。完整 build 日志：

```text
build/logs/stage27_full_build_20260718.log
```

聚焦 gate：

| gate | 结果 |
| --- | --- |
| `transform-activity-schedule` | 1/1 PASS |
| pybind activity-schedule options | 7/7 PASS |
| XS sparse option tests | 18/18 PASS |
| Python editable extension rebuild | PASS，见 `build/logs/stage27_python_editable_rebuild_20260718.log` |
| full CTest | 46/48 PASS |

完整 CTest 日志为 `build/logs/stage27_full_ctest_20260718.log`。失败仍是历史集合 `transform-comb-lane-pack` 与 `transform-repcut`，与 Stage 11--26 相同，没有新增失败；activity-schedule 本身 PASS。

第一次 production probe 使用了旧的 `.venv` `_wolvrix.so`，其 mtime 早于本次 C++ 修改；该 run 的 `removed_bytes=0` 仅用于发现 stale extension，已丢弃，不进入结论。重新 `pip install --no-build-isolation -e wolvrix` 后才进行下述正式 run。

## 3. 正式 production probe

正式 run 的核心配置如下：

```text
source /nfs/home/tanghaojin/wolvrix-playground-gsim-calibrate-2/env.sh
WOLVRIX_XS_GRHSIM_FINAL_TERMINAL_PUSHFORWARD_POLICY=off
WOLVRIX_XS_GRHSIM_FINAL_SHARED_INPUT_PEER_POLICY=probe
WOLVRIX_XS_GRHSIM_FINAL_SHARED_INPUT_PEER_PROFILE_MIN_SOURCE_FIRE=1000
WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1
```

profile 为 Stage19 50k profile：`build/logs/xs_perf/activity_stage19_table_runtime_profile_20260717/fire_50000.tsv`，SHA256 为 `4106fafbea0871724206d81fc5cda19088656d0e185a15c80ea5e9fe7655b11c`。profile 解析结果为 compute rows `63,241`、ignored commit rows `485`、`profile_valid=true`。

正式日志：

- 默认 probe：`build/logs/xs/xs_wolf_grhsim_build_activity_stage27_shared_input_peer_probe_rerun_20260718.log`，SHA256 `6d431ccbf82a77495f56511c116b8de3e66999888ea5ce223b4f715ad45f2274`。
- 宽 peer scan：`build/logs/xs/xs_wolf_grhsim_build_activity_stage27_shared_input_peer_probe_wide_20260718.log`，SHA256 `8e7be8d26702f0aa70af3ab0c4e2fad4c61a0064dae312c486c24612851c3daa`。
- 两次 output stats JSON 的 SHA256 均为 `6c41b8b25d83e05d402dbeb6164553bdd10903b8c8e67efae8cfd3cf6542257c`，与 baseline 结构值一致。

两次 probe 的绝对 funnel：

| 配置 | scanned | pure | exact eligible | selected | moved ops | moved-op limit | eligible BAE | selected BAE | eligible active bytes/chunks | selected active bytes/chunks | truncated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `max_peers=8`, `max_candidates=4096` | 1,092,530 | 330,338 | 80 | 14 | 15 | 1,125 | 134 | 17 | 134 / 134 | 17 / 17 | true |
| `max_peers=256`, `max_candidates=100000` | 1,092,530 | 330,338 | 80 | 14 | 15 | 1,125 | 134 | 17 | 134 / 134 | 17 / 17 | true |

对应默认 probe 的完整 reject 绝对计数为：

```text
rejected_split_or_node_size=121004
rejected_source_empty=158
rejected_kind=581567
rejected_width=59463
rejected_declared_or_port=258547
rejected_input_no_def=1
rejected_input_too_many=14
rejected_no_common_peer=14513
rejected_peer_invalid=16962
rejected_capacity=500
rejected_peer_scan_limit=16418
rejected_output_consumer=27836
rejected_terminal=16
rejected_no_removable_input=14142
rejected_input_owner_source=4143
rejected_fanout_mismatch=0
rejected_dag_support=463
rejected_profile_invalid=0
rejected_profile_min_source_fire=281
rejected_profile_peer_fire_gt_source=9
rejected_selection_touched_supernode=66
```

宽 scan 只把 `rejected_peer_scan_limit` 改为 `10270`、`rejected_capacity` 改为 `502`、`rejected_dag_support` 改为 `475`，selected candidate 列表完全不变。两次 selected raw TSV SHA256 均为 `21000cdea1cf59cff70f5048dbb743f68ca84c032ea423a4d791dd6627558b31`：

```text
build/logs/xs_perf/stage27_shared_input_peer_probe_selected_20260718.tsv
build/logs/xs_perf/stage27_shared_input_peer_probe_wide_selected_20260718.tsv
```

## 4. Selected candidate 原始值

下表抄录正式日志中的全部 14 个 selected candidate；`removed_boundary_values`、`added_boundary_values`、`dag_delta` 在 14 行均为 `0`，`added_bae` 均为 `0`。

| rank | C compute node | S | P | source fire | peer fire | source/peer ops | node ops | inputs/outputs/shared | BAE gain | logical bytes | active chunks | work proxy | topo distance | storage distance |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 826112 | 47475 | 47477 | 10763 | 226 | 84/74 | 1 | 2/1/2 | 2 | 2 | 2 | 10537 | 1044 | 2 |
| 1 | 124186 | 12202 | 20597 | 1379 | 693 | 55/100 | 1 | 2/1/2 | 2 | 2 | 2 | 686 | 5034 | 8395 |
| 2 | 836792 | 40240 | 40239 | 26839 | 26839 | 102/107 | 1 | 2/1/2 | 2 | 2 | 2 | 0 | 1 | 1 |
| 3 | 670117 | 43377 | 41360 | 50000 | 209 | 92/51 | 2 | 3/1/1 | 1 | 1 | 1 | 99582 | 1404 | 2017 |
| 4 | 693743 | 61538 | 61539 | 45788 | 17258 | 99/90 | 1 | 2/1/1 | 1 | 1 | 1 | 28530 | 1 | 1 |
| 5 | 795777 | 23021 | 28047 | 18722 | 4688 | 97/69 | 1 | 2/1/1 | 1 | 1 | 1 | 14034 | 16885 | 5026 |
| 6 | 693193 | 61572 | 61574 | 18596 | 11346 | 66/27 | 1 | 2/1/1 | 1 | 1 | 1 | 7250 | 1 | 2 |
| 7 | 693570 | 61923 | 61928 | 11465 | 5341 | 68/35 | 1 | 2/1/1 | 1 | 1 | 1 | 6124 | 76 | 5 |
| 8 | 457445 | 29276 | 29244 | 50003 | 50000 | 105/97 | 1 | 2/1/1 | 1 | 1 | 1 | 3 | 1224 | 32 |
| 9 | 980456 | 41776 | 44018 | 1943 | 1941 | 72/80 | 1 | 1/1/1 | 1 | 1 | 1 | 2 | 2170 | 2242 |
| 10 | 456075 | 29235 | 29237 | 50000 | 50000 | 99/91 | 1 | 2/1/1 | 1 | 1 | 1 | 0 | 6183 | 2 |
| 11 | 456412 | 29267 | 29241 | 50000 | 50000 | 98/91 | 1 | 2/1/1 | 1 | 1 | 1 | 0 | 1237 | 26 |
| 12 | 522402 | 41237 | 40882 | 50000 | 50000 | 103/24 | 1 | 2/1/1 | 1 | 1 | 1 | 0 | 1717 | 355 |
| 13 | 522869 | 41242 | 40881 | 50000 | 50000 | 106/102 | 1 | 2/1/1 | 1 | 1 | 1 | 0 | 19 | 361 |

其中严格 `source_fire > peer_fire` 的 selected 行是 rank `0,1,3,4,5,6,7,8,9`，共 `9` 个，raw BAE/active-byte/chunk 上界为 `11/11/11`；其余 5 行 source/peer fire 相等，贡献 `6` 个 BAE。严格子集的 `11 / 1,721,698 = 0.000638904%`，全部 selected 的 `17 / 1,721,698 = 0.000987397%`。这仍只是结构上界，尚未证明 active-ID、batch、slot 或 CPP write site 会减少。

## 5. 决策

1. 两档 peer 上限扫描的 selected 列表和 SHA 完全一致，说明当前可见收益集中在同一小组；但 funnel 仍有高 fanout truncation，不能把 `exact=80` 解读为全空间精确总数。
2. 即使采用更严格的 `source_fire > peer_fire`，稳定 selected 子集也只有 9 个、11 个 raw BAE/active-byte/chunk 上界；相对于 1,721,698 compute BAE 低于千分之一百分点，并且没有 slot/batch 稳定性或真实 emitter byte 证据。
3. 按 TNO0131 的停止条件，本阶段不实现 strict mutation，不生成 CPP/O3，不运行 SimTop 50k；因此不存在可比较的 walltime，也不报告任何“性能提升”。C++ 默认继续 `finalSharedInputPeerPolicy=off`，XS 仅保留显式 probe override。
4. 后续若重新开启该方向，必须先增加 emitter-side active-ID/batch/slot 证明，再按 TNO0130 的 first-touch NUMA 协议和 `Host time spent` 做 fresh ABBA/BAAB；不能仅凭这 17 个 BAE 上界放宽 cap 或改变默认。
