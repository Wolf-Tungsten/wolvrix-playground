# NO0134: commit supernode cap1024 build-positive runtime-negative

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


背景：

- NO0128 perf 中热点分散在大量 `eval_commit_batch_*`，且一些热点 commit batch 文件达到约 `60k` 行：
  - `grhsim_SimTop_sched_923.cpp`: `61392`
  - `grhsim_SimTop_sched_979.cpp`: `61182`
  - `grhsim_SimTop_sched_939.cpp`: `62840`
- 实验目标：只降低 commit supernode 粒度，把 `max_op_in_commit_supernode` 从 `4096` 改为 `1024`，测试更小 commit batch 是否改善 instruction cache / frontend / generated code layout。

配置：

- schedule 仍沿用 NO0128 的 C1+C2 配置。
- 额外设置：
  - `WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE=1024`

fresh XiangShan emit/build/runtime：

- fresh emit dir：
  - `tmp/no0134_xs_commit_cap1024/grhsim_emit`
- schedule 结构：
  - `compute_supernodes=74430`
  - `commit_supernodes=721`
  - `dag_edges=488448`
  - `boundary_values=1151073`
  - `boundary_activation_edges=2225424`
- 对比 NO0128：
  - `commit_supernodes`: `515 -> 721`
  - `dag_edges`: `485905 -> 488448`
  - `boundary_activation_edges`: `2216514 -> 2225424`
  - BAE 增加 `8910`，约 `0.40%`
- emit timing：
  - `activity-schedule=207730ms`
  - `write_grhsim_cpp=47510ms`
  - `total=285208ms`
- 代码行数变化：
  - 原 NO0128 热 commit batch：
    - `sched_923.cpp`: `61392`
    - `sched_979.cpp`: `61182`
    - `sched_939.cpp`: `62840`
  - NO0134 对应文件：
    - `sched_923.cpp`: `14604`
    - `sched_979.cpp`: `16359`
    - `sched_939.cpp`: `12497`
  - 最大 sched 文件仍约 `78k` 行，主要来自其它 compute/sched 文件。
- model build：
  - `real 151.25s`
  - `user 3742.60s`
  - `sys 63.46s`
  - 成功链接 `tmp/no0134_xs_commit_cap1024_emu/grhsim-compile/emu`
- CoreMark 20k:
  - 命令包含 `--diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`
  - 退出码：`0`
  - 未出现 difftest mismatch。
  - 进度：
    - 10k: `host_ms=37100`
    - 20k: `host_ms=132172`
  - `Guest cycle spent`: `20001`
  - `Host time spent`: `132180ms`

判断：

- commit cap1024 对 build time 有明显正收益：NO0128/NO0131 约 `256-259s`，NO0134 为 `151.25s`。
- runtime 明确负向：20k 从 NO0128 的 `109998ms` 退化到 `132180ms`，慢约 `20.2%`。
- 拆小 commit supernode 降低了单个热点 commit batch 文件大小，但增加了 commit supernode、DAG edge 和 BAE，调度/activation 成本抵消并超过代码布局收益。
- 按实验门禁，20k 已明显负向，不继续跑 50k。
- 可作为降低编译时间的可选构建实验，但不适合作为 runtime 优化方向。

