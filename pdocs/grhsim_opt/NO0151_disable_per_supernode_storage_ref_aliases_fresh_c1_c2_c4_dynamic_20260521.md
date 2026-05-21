# NO0151: disable per-supernode storage-ref aliases fresh C1/C2/C4 dynamic

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


背景：

- NO0150 perf 20k 显示瓶颈仍是 frontend / branch：
  - `Host time spent=101929ms`
  - `instructions=98.317B`
  - `cycles=580.949B`
  - `IPC=0.17`
  - `stalled-cycles-frontend=86.51%`
  - `branch-misses=38.56%`
- perf report 热点集中在 `eval_commit_batch_*` 和 `apply_commit_scalar_state_write_table`，而非 `grhsim_slice_u64_words`。
- 热点 commit batch 中存在大量 supernode 入口处的 `auto &... = grhsim_value_storage_ref(...)` alias 声明。该 alias 默认在每个 active supernode 进入时先初始化，可能带来额外代码体积和无条件引用初始化成本。

配置：

- fresh emit / build 目录：`tmp/no0151_xs_no_storage_ref_aliases`
- C1/C2/C4 dynamic 主体，`small_sibling_merge=1`，`small_overlap_merge=0`，`down_merge=0`
- 与 NO0148/NO0150 同源结构。
- 额外关闭：`WOLVRIX_GRHSIM_STORAGE_REF_ALIASES=0`

fresh emit：

- `activity-schedule done 187643ms`
- `write_grhsim_cpp done 40366ms`
- `total done 249791ms`
- `/usr/bin/time`: `real 251.35s`
- 结构：
  - `supernodes=74945`
  - `compute_supernodes=74430`
  - `commit_supernodes=515`
  - `dag_edges=485905`
  - `boundary_values=1151073`
  - `boundary_activation_edges=2216514`
  - `clusters_after_essent_coarsen=3084571`

静态代码变化：

- NO0150 sched lines: `20584797`
- NO0151 sched lines: `17638469`
- NO0150 `grhsim_value_storage_ref` in sched: `1324984`
- NO0151 `grhsim_value_storage_ref` in sched: `1311374`
- NO0151 `grhsim_slice_u64_words`: `71059`
- NO0151 `grhsim_slice_words<1>`: `0`
- 目录大小：NO0150 `2.2G`，NO0151 `1.7G`

build / relink：

- model archive 强制重编：
  - `real 271.02s`
  - `user 6334.52s`
  - `sys 60.62s`
- difftest emu relink：
  - `real 1.23s`
- `libgrhsim_SimTop.a` text 汇总：
  - NO0148: `115953957`
  - NO0150: `107232999`
  - NO0151: `116376639`

CoreMark：

- 命令口径：difftest enabled，`EMU_PROGRESS_EVERY_CYCLES=10000`。
- 20k gate:
  - 10k: `host_ms=25700`
  - 20k: `host_ms=101225`
  - `Host time spent=101232ms`
- 50k:
  - 10k: `host_ms=25175`
  - 20k: `host_ms=99951`
  - 30k: `host_ms=177348`
  - 40k: `host_ms=256723`
  - 50k: `host_ms=347822`
  - `Host time spent=347835ms`
  - 约 `143.75 cycles/s`
  - 退出码 `0`，未出现 difftest mismatch。

对比：

- NO0137 50k: `346589ms`，约 `144.3 cycles/s`
- NO0148 50k: `348214ms`，约 `143.59 cycles/s`
- NO0150 50k: `351253ms`，约 `142.35 cycles/s`
- NO0151 50k: `347835ms`，约 `143.75 cycles/s`

判断：

- 关闭 per-supernode storage-ref alias 显著减少了 sched 源码行数和目录大小，但 `.text` 反而比 NO0150 大约 `9.14MB`，model build 也比 NO0150 慢约 `12.70s`。
- runtime 比 NO0150 快约 `3418ms`，约 `0.97%`；比 NO0148 快约 `379ms`，约 `0.11%`；但仍比 NO0137 慢约 `1246ms`，约 `0.36%`。
- 该实验说明 alias 过度提前声明确实可能伤害热路径，但完全关闭会导致 repeated `grhsim_value_storage_ref` 内联展开和 `.text` 增长。下一步应做 alias 阈值/分层策略，而不是简单全关。

