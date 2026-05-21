# NO0116/NO0117: commit scalar table segment fix and range compression

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


目标：

- 修复 direct scalar commit table 在 fallback segment 上没有生效的问题。
- 在 NO0117 中进一步把等差 slot 序列映射到已有 range helper，验证是否能把结构收益转成 CoreMark 50k runtime 收益。

验证公共配置：

- `C1+C2+C4 dynamic` 主体。
- `WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD=1`
- `WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN=1`
- `WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_SIBLING_MERGE=1`
- `WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE=0`
- `WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE=0`
- CoreMark 命令带 `--diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`。

NO0116 fresh emit：

- 输出目录：`tmp/no0116_xs_emit_commit_scalar_table_segment_fix/grhsim_emit`
- `activity-schedule`: `191458ms`
- `write_grhsim_cpp`: `40819ms`
- `compute_supernodes`: `74430`
- `commit_supernodes`: `515`
- commit scalar table 诊断：
  - `candidates=1238762`
  - `accepted=1231479`
  - `reject_memory=4889`
  - `reject_wide=2380`
  - `reject_next_slot=14`
- `apply_commit_scalar_state_write_table`: `4646`
- direct scalar commit body: `254339`

NO0116 build/runtime：

- model build real: `256.84s`
- difftest emu build: 成功。
- CoreMark 50k 退出码：`0`
- 未出现 difftest mismatch。
- `Guest cycle spent`: `50001`
- `Host time spent`: `363258ms`
- 折算速度：约 `137.6 cycles/s`

NO0116 进度点：

| model cycles | host ms | cumulative cycles/s |
| ---: | ---: | ---: |
| `10000` | `27973` | `357` |
| `20000` | `111625` | `179` |
| `30000` | `190180` | `158` |
| `40000` | `270985` | `148` |
| `50000` | `363246` | `138` |

NO0117 fresh emit：

- 输出目录：`tmp/no0117_xs_emit_commit_scalar_range/grhsim_emit`
- `activity-schedule`: `192934ms`
- `write_grhsim_cpp`: `41266ms`
- total real: `260.91s`
- `compute_supernodes`: `74430`
- `commit_supernodes`: `515`
- supernodes: `74945`
- DAG edges: `485905`
- boundary values: `1151073`
- boundary activation edges: `2216514`
- commit scalar table 诊断：
  - `candidates=1238762`
  - `accepted=1231479`
  - `reject_memory=4889`
  - `reject_wide=2380`
  - `reject_next_slot=14`
- `apply_commit_scalar_state_write_table`: `3733`
- `apply_commit_scalar_state_write_*_range`: `918`
- direct scalar commit body: `254339`

NO0117 build/runtime：

- model build real: `258.75s`
- model build user/sys: `5718.08s` / `57.93s`
- difftest emu build: 成功。
- CoreMark 50k 退出码：`0`
- 未出现 difftest mismatch。
- `Guest cycle spent`: `50001`
- `Host time spent`: `358605ms`
- 折算速度：约 `139.4 cycles/s`

NO0117 进度点：

| model cycles | host ms | cumulative cycles/s |
| ---: | ---: | ---: |
| `10000` | `32112` | `311` |
| `20000` | `108188` | `185` |
| `30000` | `186682` | `161` |
| `40000` | `266822` | `150` |
| `50000` | `358593` | `139` |

对比：

| 指标 | NO0109 | NO0116 | NO0117 |
| --- | ---: | ---: | ---: |
| `activity-schedule` | `187654ms` | `191458ms` | `192934ms` |
| `write_grhsim_cpp` | `40499ms` | `40819ms` | `41266ms` |
| model build real | `303.60s` | `256.84s` | `258.75s` |
| 50k `Host time spent` | `369976ms` | `363258ms` | `358605ms` |
| 50k throughput | `135.1 cycles/s` | `137.6 cycles/s` | `139.4 cycles/s` |

判断：

- NO0116 的 segment fix 是有效改进：build 时间相比 NO0109 降低约 `15.4%`，50k runtime 快约 `1.8%`。
- NO0117 的 range compression 没有带来 build 收益，model build 比 NO0116 慢 `1.91s`，约 `0.7%`；但 50k runtime 从 `363258ms` 降到 `358605ms`，快 `4653ms`，约 `1.28%`。
- NO0117 是当前已测最佳 CoreMark 50k 点：约 `139.4 cycles/s`。收益仍远小于最终 5x 目标，说明后续应继续攻击高频 runtime path，而不是只压缩 commit scalar 代码体积。

