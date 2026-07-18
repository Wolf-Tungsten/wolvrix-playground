# TNO0144 Stage 32 same-batch activation cohort probe plan

日期：2026-07-19

状态：计划实现一个 C++ default-off、no-mutation 的 final-emitter
`same_batch_activation_cohort_policy=probe`。probe 不再用“fire 相同”推断可共享，而是
从最终 EmitModel 的真实 activation producer 反向构造 exact source signature，并在
batch 入口/出口记录 pending pattern。首个 pinned witness 是 batch12 的
SN10999..11049：51 个连续 pure-compute body 只有一个普通 activation source，理论可将
51 条 BAE 降为 1 条，并减少 958,750 次 50k member guard test。probe walltime 不作性能
结论；只有入口/出口 equivalence 闭合后才另立 strict 文档和未插桩 50k candidate。

## 1. 当前基线与 GSIM 对照边界

Stage32 仍以当前仓库 C++ 默认生成配置为 control：NO0300、ASLR 关闭、native hybrid
直接在 C++ 默认开启、commit cap=`8192`。Stage31 的 12/13-pair deferred-activation
policy 都显式关闭。

当前 default GrhSIM 与历史 same-FIR GSIM 的绝对差距为：

| simulator | Host time | instructions |
| --- | ---: | ---: |
| current-default GrhSIM | 74,384.00 ms | 164,223,544,840.125 |
| same-FIR GSIM | 30,943.5 ms | 80,070,645,161 |

instructions 绝对差为 `84,152,899,679.125`，GrhSIM 是 `2.050983x`；walltime 是
`2.403865x`。GSIM 样本早于 fresh page-local 双 NUMA formal protocol，只用于定位历史
gap，不能替代 Stage32 的正式 walltime。

静态 dispatch 并不是 GrhSIM 比 GSIM 更大：

| field | GSIM | GrhSIM |
| --- | ---: | ---: |
| active-word tests | 10,558 | 8,398 |
| bit tests | 84,457 | 63,709 |
| step/batch methods | 329 | 97 |
| `.text` | 48,912,198 B | 87,095,345 B |

历史 50k active-supernode fire 为 GSIM=`766,585,701`、映射到 current schedule 的
GrhSIM约 `744,760,805`，GrhSIM 已少 `21,824,896`（`-2.847%`）。机器码全局归因中
GrhSIM compute excess `60.50B` 主要来自 direct payload `+27.400B`、generic runtime
helper `+22.675B` 和 change tracking `+7.250B`；dispatch 只有 `+2.025B`，activation
propagation 反而 `-0.275B`。因此 cohort 是可测的小优化，不是当前 84.15B instruction
gap 的主解释。

关键现存产物：

```text
GrhSIM emu
  build/xs_activity_stage23_cap8192_cpp_default_20260718/grhsim/grhsim-compile/emu
  sha256=31ab2b820cbce126199b7baef5d9f15909f6db1e39bb72d1b140bc398924ba65
GSIM emu
  build/xs_gsim_no0255_current_20260710/gsim/gsim-compile/emu
  sha256=1b3b4ec741cdd0b2f131e6b384979743e82625f85e7e341bcb988a0607fdbf60
global normalized attribution
  build/logs/xs_perf/no0403/global_normalized_category_compare.tsv
  sha256=d32648580e22bfb7c0bd60a660970cc945eb31a320cdecf0a9c3357785d53b10
```

## 2. Pinned production witness

current-default generated source 已直接证明：

- batch12 的 SN10999..11049 是 51 个连续 ordinary compute body；
- active ID 连续为 `10602..10652`，跨 7 bytes：
  `1325:0xfc`、`1326..1330:0xff`、`1331:0x1f`；
- 每个 body 是 `72 compute + 36 const = 108 ops`，无 source/sink，总 op=`5,508`；
- 51 个 body 的唯一普通 activation producer 是 SN6969/batch7 产生的
  `ValueId=1539803:0`；
- source lowering 正好是 `u32@1325=0xfffffffc`、`u16@1329=0xffff`、
  `u8@1331=0x1f`。全量 schedule/table/local/state/eval mask 反查没有第二个写点；
- initial seed 是另一个写点，但它对全部 compute bits 一视同仁；
- 50k source SN6969 和 51 个 member 的 absolute fire 都是 `19,175`。

因此 pinned witness 的静态/动态绝对投影为：

```text
members                         51
body ops                      5508
control BAE                     51
projected BAE                    1
projected BAE saved             50
control active bytes             7
projected active bytes           1
control mask chunks              3
projected mask chunks             1
member body fire             977925
projected member guard saved 958750
```

原始证据：

```text
build/logs/xs_perf/no0401/machine_candidate_rows.tsv
sha256=eaa0cd514c51b3488bbe9933d2d65d5e4c21fc7646b2ad8f9021c4500cf5cb26
bytes=50658703

build/logs/xs_perf/no0311/no0300_grhsim_supernode_fire.tsv
sha256=dce335d4a2c9e4fc27dfd213f13731efa57b62a79181ccc429ad0867699ae740
bytes=1157875

build/xs_activity_stage23_cap8192_cpp_default_20260718/grhsim/grhsim_emit/
  grhsim_SimTop_sched_7.cpp
  sha256=92c6a1d56b1c5b78bdb62b25de28742fa063693eeb41ac783e82f1c09a20d9d2
  bytes=24505091
  grhsim_SimTop_sched_12.cpp
  sha256=1091c46a4a8d0f9c66f14fd3b3a37b19d99a40ac2b2e507dc670db71da45d781
  bytes=18614620
```

## 3. 为什么不能按 fire 直接合并

以“同 batch 且 fire count 相同”分组的宽松上界有 `4,824` 组、可删 `36,724` 个静态
bit tests 和 `407,786,023` 次动态 tests；即使每 test 粗估 3..5 条 host instructions，
也只有 `1.22..2.04B`，约占 current instructions 的 `0.74%..1.24%`。exact source
signature 还会继续压缩这个上界。

几个最大的 loose group 都不能直接采用：

- batch35/fire50050/n296 与 batch58/fire50050/n168 是 pure-event assertion family，已被
  current C++ default `pure_event_compute_word_bypass` 覆盖；
- batch62/fire49999/n441 和 batch63/fire49999/n200 以 state/read/mux materialization
  为主，同一 fire 并不等于同一 activation source；
- commit batch66/fire24999/n149 不属于 compute cohort。

历史 full-word consume 曾使 instructions `-0.717%` 但 walltime 回退约 2%；Stage6
active-ID packing instructions `-1.076%` 也出现 walltime 回退。因此 Stage32 不以宽松
上界或 instructions 直接开默认，仍实际跑 SimTop 50k。

## 4. Exact no-mutation scan

新 option：

```text
same_batch_activation_cohort_policy = off | probe
same_batch_activation_cohort_profile_path = <50k supernode fire TSV>
```

C++ 默认是 `off`，native/Python/XS 只转发显式值；XS 未指定时日志显示
`cpp-default`，不在脚本里为 XiangShan 私设默认。

probe 在 pure-event targeted rebuild 已完成后的 final EmitModel 和 final
`scheduleBatches` 上工作。先反向构造每个 active ID 的真实 activation producer set，首版
只接受 non-empty boundary-ValueId-only signature，并保守拒绝：

- input head、state/direct-state、memory row/dynamic reader；
- event/system task/DPI/side effect、commit 或 unclassified activation；
- source 在同 batch 或 source batch 不早于 target；
- targeted pure-event pack、active-mask gap pack 或 deferred-forward overlay 同时启用；
- 跨 batch、active-ID gap、batch-order gap；probe 的入口/出口 marker 包围 helper 调用，
  strict 是否支持 helper 另行 fail-closed；
- cohort 内 DAG/value edge、extra activation site 或 profile fire mismatch。

相同 `(compute batch, sorted boundary ValueIds)` 的桶按 batch order 切成 active-ID 和
body order 都连续的 run。对 graph symbol 为 `SimTop` 的 production request，probe 必须
找到 pinned row；不能只用 profile 行数识别 production，因为当前 compute fire profile
保留了旧 commit partition 的 `485` 行，而 current-default schedule 本身只有 `468` 个
commit supernode：

```text
batch=12 source_supernode=6969 source_batch=7 value=1539803:0
first_supernode=10999 last_supernode=11049
first_active_id=10602 last_active_id=10652 members=51 ops=5508
```

若任何字段变化，显式 probe fail-closed，而不是静默选择“相似”组。

## 5. Runtime equivalence counters

static exact-source 相同仍不足以证明 bit consumption 时序。probe binary 在目标 compute
batch method 的入口、任何 word load/clear 之前 snapshot cohort bits，并记录：

```text
ordinary_batch_entries
entry_all_off / entry_all_on / entry_partial
entry_active_bit_sum
per_member_entry_pending / mismatch_vs_anchor
ordinary_body_fire
exit_all_off / exit_all_on / exit_partial
per_member_exit_pending
```

probe 只读 bits 和增加 counters，不改 graph/session/model fanout、active IDs、batches、seed
或 body guard；fullpass 不计入 ordinary counters。`all_off/all_on/partial + active_sum` 与
逐 member pending 已能完整裁决本阶段的“只能全关或全开”契约，因此不再额外生成每个
active-count bin 的 histogram，避免重复插桩。100/10k/50k dump 每个 member 的
cohort/batch/ordinal/SN/active ID/word/mask/ops/entry pending/body fire/mismatch/exit pending，
并输出所有 summary 绝对值。

pinned witness 的 50k 合格条件是：

```text
entry_partial=0
exit_partial=0
every member mismatch_vs_anchor=0
entry_pending=ordinary_body_fire=19175 for every member
body_fire_sum=977925
all_on * (51 - 1)=958750 projected guard tests saved
```

probe 插桩 walltime 不进入 performance 结论。

## 6. Strict 前置设计约束

strict 不能简单把 51 个 `activeIdBySupernode` 都改成同一 bit：第一个 body 会消费该 bit，
后 50 个将不会执行。后续 strict 必须：

1. 保留 follower active-ID holes，稳定全局 active layout；
2. 从普通 fanout和 initial seed 同时删除 follower bits；
3. batch 入口一次 snapshot/consume representative bit；
4. 按原 batch/topo 顺序执行全部 51 个 payload；
5. 每个 payload 继续使用原 active ID/word 的 `ActivationEmitContext`，避免改变同 word 的
   local propagation；
6. fullpass 仍无条件执行全部 body，commit 不参与。

只有 runtime probe 证明入口/出口 pending 始终全等，才另立 strict 实现和功能门禁。

## 7. 验证阶梯

1. focused fixture 覆盖跨 byte 的 5-member positive run、initial seed、ordinary/fullpass
   插桩位置、generated harness、missing profile/illegal policy 和 `SimTop` production witness
   fail-closed；production scan 的 reject 绝对计数继续覆盖 input/state/memory/event/source
   order 等大图路径。
2. Python/native/XS 检查 C++ default-off、sparse explicit forwarding 和 invalid value。
3. production default/off 的完整 artifact identity；probe 的 activity/emitter stats identity、
   session no-mutation 和 deterministic instrumented source/static rows。probe 本身必然改变
   generated CPP，不能误写成与 default CPP byte identity。
4. explicit profile O3/link，运行 fixed-ASLR 100/10k/50k，记录所有绝对 counter、功能终点、
   raw log SHA/大小。
5. 若 pinned row partial/mismatch 为 0，再另立 Stage33 strict。strict 必须 fresh O3/link、
   100/10k/50k difftest，以及正确 first-touch/`taskset+numactl`/`setarch -R`/whole-node
   ABBA+BAAB 双 NUMA 50k。
6. 最终 headline 只用 SimTop `Host time spent`。instructions/BAE/guard tests 只解释结果。
