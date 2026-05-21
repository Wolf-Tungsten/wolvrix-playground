# NO0143: inline commit scalar table runtime gate

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


背景：

- NO0128/NO0137 perf 中最高单个具名 helper 仍是：
  - `GrhSIM_SimTop::apply_commit_scalar_state_write_table(...)`
  - self 约 `1.1%`。
- 源码中已经存在默认关闭的 `emit_inline_commit_scalar_tables` 路径，单测覆盖了形态，但此前没有记录 XiangShan runtime。
- 本轮用已有 checkpoint 快速验证该方向：
  - `WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1`
  - `WOLVRIX_XS_GRHSIM_POST_STATS_JSON=tmp/grhsim_default_xiangshan_coremark_20260418/wolvrix_xs_post_stats.json`
  - `WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD=1`
  - `WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN=1`
  - `WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE=0`
  - `WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE=0`
  - `WOLVRIX_XS_GRHSIM_EMIT_INLINE_COMMIT_SCALAR_TABLES=1`

验证：

- 代码路径已由 `emit-grhsim-cpp` 单测覆盖：
  - 默认 commit table helper 形态。
  - specialized commit table 形态。
  - inline commit table 形态。
- 本轮未修改源码，只做 XiangShan emit/build/runtime gate。

XiangShan emit/build/runtime：

- emit dir：
  - `tmp/no0143_xs_inline_commit_scalar_tables/grhsim_emit`
- schedule 结构：
  - `supernodes=81650`
  - `compute_supernodes=81117`
  - `commit_supernodes=533`
  - `dag_edges=772030`
  - `boundary_values=1377242`
  - `boundary_activation_edges=2729127`
  - `compute_compute_value_pairs=2348835`
  - `compute_commit_value_pairs=380292`
- emit timing：
  - `read_json_file=24711ms`
  - `activity-schedule=217593ms`
  - `write_grhsim_cpp=45512ms`
  - `total=287818ms`
  - `real 289.60s`
- 静态代码形态：
  - `apply_commit_scalar_state_write_table(`：`2`，只剩声明/定义。
  - `AnyStateChanged`：`29487`
  - `grhsim_emit` 目录大小：`2.5G`
- model + emu build：
  - `real 312.53s`
  - `user 8426.78s`
  - `sys 82.13s`
- CoreMark 20k：
  - 10k: `host_ms=29245`
  - 20k: `host_ms=117523`
  - `Guest cycle spent=20001`
  - `Host time spent=117531ms`
  - 退出码 `0`，未出现 difftest mismatch。

判断：

- inline commit table 成功消除了 table helper 调用，但 20k runtime 明显负向：
  - NO0128 20k：`109998ms`
  - NO0137 20k：`97854ms`
  - NO0143 20k：`117531ms`
- 该方向没有过 20k 门禁，不继续跑 50k。
- 原因很可能是把小 table helper 内联到大量 commit batch 后增加了代码体积、I-cache/front-end 压力和寄存器压力；消掉约 `1%` self helper 不足以抵消这些损失。
- 后续不应继续沿 commit scalar table inline/specialize 方向投入；如果要继续看 commit 热点，应转向减少 commit activation/BAE 或改变 batch 调度粒度，而不是展开 helper。

