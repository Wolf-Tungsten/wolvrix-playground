# TNO0154 Stage 33 fresh same-commit current-default control

日期：2026-07-19

状态：父仓库 `4857a5b`、`wolvrix` 子模块 `f17e90e` 已提交后，重新 editable install，并在
同一提交上生成 current C++ default control。该 control 是 Stage33 strict 和后续 Stage7+
候选共用的唯一 fresh A；旧 Stage23 artifact 只作交叉核对，不再充当 formal A。默认配置仍
由 C++ emitter 解析，XS 只保留平台必要的显式恢复点；运行时 ASLR 由 formal runner 用
`setarch x86_64 -R` 关闭。

## 1. Input and option boundary

固定输入：

```text
filelist  build/xs_activity_stage22_terminal_pushforward_strict_20260718/wolf/wolf_emit/xs_wolf.f
          sha256=68cbb67e3350ed8e59318f51939603e9aa694b1e39dfa2e63c115524906d3d28 bytes=308641
poststats build/xs_activity_stage8_dp_p050_20260715/grhsim/wolvrix_xs_post_stats.json
          sha256=165f5c58e06d0d8a483c49d80733f5a7a211bc27772dac5b1608b0c177a0b573
read_args build/xs_activity_stage23_cap8192_cpp_default_20260718/grhsim/grhsim_emit/wolvrix_read_args.txt
          sha256=b0fade4b968e4491b42fc6693eea0aa65d6a8b4829c2c5d902175acc647414d5 bytes=351
```

emit log：

```text
build/logs/xs/stage33_current_default_control_emit_20260719.log
sha256=9de24196be724640691081071a59c7cda4bc1e01a8e0ada9cbc38ce4ee04f42e bytes=14330
exit=0, /usr/bin/time wall=4:21.95, max_rss=28064072 KiB
```

首行显示 `max_op_in_compute_supernode=108`、`sched_batch_max_ops=2048`、
`sched_batch_max_estimated_lines=8192`、`sched_batch_target_count=64`、`sched_batches_per_cpp=1`、
`emit_parallelism=4`、`storage_ref_aliases=0(xs_default)`。所有实验 policy（DP、post-DP、Kahn、
fanin、terminal/shared-input、deferred/cohort、word-pack、full-active）均显示
`cpp-default` 或 `off`；`direct_single_writer_state_reads` 与
`pure_event_compute_word_bypass` 也显示 `cpp-default`，没有回退到早期 0/0 配置。

## 2. Static identity

activity-schedule absolute stats：

```text
supernodes/compute/commit = 63709/63241/468
dag_edges                  = 527990
boundary_values            = 1000463
boundary_activation_edges  = 1983326
compute/commit value pairs = 1721698/261628
```

`activity_schedule_supernode_stats.json` SHA 为
`6c41b8b25d83e05d402dbeb6164553bdd10903b8c8e67efae8cfd3cf6542257c`、bytes=`5382`；
`grhsim_emit_stats.json` SHA 为
`9dd1bdddd01606507b2e3425917f260ca3ac8c5b88c55fa21408bffb17080a8b`、bytes=`418`。
两者与 Stage33 strict fresh output 均 `cmp=0`。control 生成源码/header 为 `134` 个、
`1,356,643,748 B`；strict 为 `134` 个、`1,356,609,139 B`（`-34,609 B`），这只是静态
边界，不替代 walltime。

## 3. O3 and link

O3 使用清除外部 flags 后的 `CXX=clang++ CXXFLAGS='-std=c++20 -O3'`：

```text
build/logs/xs/stage33_current_default_control_o3_clang_20260719.log
sha256=b9967c7325dddad18ad875a1babfa5d8b53c8547d058744132d6e04e4be17d62 bytes=24912
exit=0, wall=9:27.46
libgrhsim_SimTop.a sha256=d257613a74a33dd2c9abe501373bd573f1ce053ffe29103d2cbab0410b779a90 bytes=99249366
```

独立 difftest link 同样在新 `BUILD_DIR`、`NUM_CORES=1`、ChiselDB/Constantin/waveform 关闭，
并清除 `GRHSIM_MODEL_CXXFLAGS/EMU_OPTIMIZE/PGO_*` 外部污染：

```text
build/logs/xs/stage33_current_default_control_emu_link_20260719.log
sha256=e46ba70f56a6c70598389c9dca8e955bc8937ee633fda32cc05888c07b900394 bytes=7021
exit=0, wall=16.20 s
```

control `emu` 是解引用后的 ELF target（目录中的 `emu` 是 symlink）：

```text
sha256=f1aa76bdd79977e8089adffc5416ae4a1d2d2d296a79bafe208957be65531006
stat -L bytes=93671816
.text=87095345 .rodata=5647080 .eh_frame=706144 .data=152 .bss=14688
```

与 strict target 的对应值为 SHA `b195d2e533a4dd818ebb56c57f59af54df1ee69dc4fc9b3cc60c76be133bba51`、
bytes=`93659528`、`.text=87083985`；两者均来自子模块 `f17e90e` 的生成代码。

## 4. Performance boundary

本文不把 control/strict 的任何单次功能或历史 walltime 当作 A/B 结论。后续 formal 必须对
control、strict 和 Stage7+ candidate 分别创建目标 NUMA first-touch 的独立 `/dev/shm` inode，
通过 whole-node 30 秒 pre/runtime gate、placement、PMU、scheduler、affinity、ASLR、功能和
唯一正 `Host time spent` 检查；最终只按 50k walltime 的绝对值比较。cycles、instructions、
BAE、DAG 和 ELF size 仅作解释。
