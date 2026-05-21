# NO0152: storage ref alias min touches = 4

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


目的：

- 在 NO0151 全关 alias 后，验证更细粒度策略：只为 touch 次数不少于 4 的 storage ref 生成 per-supernode alias。
- 期望减少低复用 alias 声明带来的 frontend 压力，同时保留高复用引用的局部性。

代码配置：

- `wolvrix/lib/emit/grhsim_cpp.cpp` 新增 `WOLVRIX_GRHSIM_STORAGE_REF_ALIAS_MIN_TOUCHES`。
- 默认值为 `2`，保持既有行为；本次 fresh emit 设置为 `4`。
- 目录：`tmp/no0152_xs_storage_ref_alias_min4`

fresh emit：

- `activity-schedule done 187696ms`
- `write_grhsim_cpp done 40120ms`
- `total done 249224ms`
- `/usr/bin/time`: `real 250.78s`
- 结构：
  - `supernodes=74945`
  - `compute_supernodes=74430`
  - `commit_supernodes=515`

静态代码形态：

- sched lines: `18234338`
- alias 声明估计: `601897`
- `grhsim_value_storage_ref` in sched: `1351680`
- `grhsim_slice_u64_words`: `71059`
- `grhsim_slice_words<1>`: `0`
- 目录大小：`2.0G`
- `libgrhsim_SimTop.a` text 汇总：`116056899`

build / relink：

- model archive 强制重编：
  - `real 260.31s`
  - `user 5887.18s`
  - `sys 58.45s`
- difftest emu relink：
  - `real 1.23s`

CoreMark：

- 命令口径：difftest enabled，`EMU_PROGRESS_EVERY_CYCLES=10000`。
- 20k gate:
  - 10k: `host_ms=23443`
  - 20k: `host_ms=98921`
  - `Host time spent=98928ms`
  - 约 `202.17 cycles/s`
- 50k:
  - 10k: `host_ms=23550`
  - 20k: `host_ms=98419`
  - 30k: `host_ms=176405`
  - 40k: `host_ms=256785`
  - 50k: `host_ms=348551`
  - `Host time spent=348563ms`
  - 约 `143.45 cycles/s`
  - 退出码 `0`，未出现 difftest mismatch。

对比：

- NO0137 50k: `346589ms`，约 `144.3 cycles/s`
- NO0148 50k: `348214ms`，约 `143.59 cycles/s`
- NO0150 50k: `351253ms`，约 `142.35 cycles/s`
- NO0151 50k: `347835ms`，约 `143.75 cycles/s`
- NO0152 50k: `348563ms`，约 `143.45 cycles/s`

判断：

- alias min touches = 4 的 `.text` 介于 NO0148/NO0151 之间，但 runtime 比 NO0151 慢约 `728ms`，比 NO0137 慢约 `1974ms`。
- 说明单纯调 alias 生成阈值没有解决当前 runtime 主瓶颈；它对源码行数、build time 有影响，但对 CoreMark 50k 速度收益不稳定。
- 下一步不应继续在 storage-ref alias 阈值上细调，应回到 perf 指向的 commit batch / scalar state write table / supernode dispatch 热点，减少高频分支和前端取指压力。

