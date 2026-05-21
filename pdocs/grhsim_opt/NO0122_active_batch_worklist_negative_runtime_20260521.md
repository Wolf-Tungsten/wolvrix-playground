# NO0122: active batch worklist negative runtime result

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


实验目的：

- 延续 NO0121 的 batch skip 方向，但避免每轮在 `eval()` 里重扫 batch 覆盖的 active word。
- 在 activation 写入路径中维护 `schedule_batch_active_` worklist 标记：
  - active word 被置位时，标记它关联的 schedule batch。
  - `eval()` 只检查每个 batch 的 1-byte pending 标记；pending 时调用 batch，并在调用前清零。
  - 同 word local activation 也标记当前 word 关联 batch，保持原有 word 内执行语义。
- 该实验通过环境变量 `GRHSIM_EMIT_ACTIVE_BATCH_WORKLIST=1` 打开；默认路径不变。

实现与验证：

- 代码改动：
  - `wolvrix/lib/emit/grhsim_cpp.cpp`
  - `wolvrix/tests/emit/test_emit_grhsim_cpp.cpp`
- 局部验证：
  - `cmake --build wolvrix/build --target emit-grhsim-cpp -j$(nproc)`：通过。
  - `ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'`：通过。
  - `python3 -m pip install --no-build-isolation -e wolvrix`：通过。

NO0122 fresh emit：

- 输出目录：`tmp/no0122_xs_emit_active_batch_worklist/grhsim_emit`
- 开关：`GRHSIM_EMIT_ACTIVE_BATCH_WORKLIST=1`
- `activity-schedule`: `612528ms`
- `write_grhsim_cpp`: `41032ms`
- `compute_supernodes`: `63392`
- `commit_supernodes`: `515`
- `dag_edges`: `975745`
- `boundary_activation_edges`: `2460976`
- 源码目录体积：约 `2.0G`
- 生成文件确认：
  - `grhsim_SimTop_active_batches.cpp`
  - `schedule_batch_active_`
  - `mark_active_word_batches`

注意：

- NO0122 的 activity schedule 结构与 NO0118 不完全一致：
  - NO0118：`compute_supernodes=74430`，`dag_edges=485905`，`BAE=2216514`
  - NO0122：`compute_supernodes=63392`，`dag_edges=975745`，`BAE=2460976`
- 因此 NO0122 不是严格只改 worklist 的 clean A/B；它仍可作为“active batch worklist + 当前 schedule 形态”的完整真实性能烟测。

NO0122 build/runtime：

- model build：
  - `real 161.77s`
  - `user 4421.89s`
  - `sys 61.51s`
- difftest emu build：
  - `real 7.52s`
  - 成功链接 `tmp/no0122_xs_emit_active_batch_worklist_emu/grhsim-compile/emu`
- CoreMark 50k：
  - 命令包含 `--diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`
  - 退出码：`0`
  - 未出现 difftest mismatch。
  - `Guest cycle spent`: `50001`
  - `Host time spent`: `651563ms`
  - 折算速度：约 `76.7 cycles/s`

NO0122 50k 进度点：

| model cycles | host ms | cumulative cycles/s |
| ---: | ---: | ---: |
| `10000` | `72679` | `138` |
| `20000` | `209452` | `95` |
| `30000` | `348718` | `86` |
| `40000` | `490719` | `82` |
| `50000` | `651541` | `77` |

对比 NO0118：

| 指标 | NO0118 | NO0122 |
| --- | ---: | ---: |
| `activity-schedule` | `191465ms` | `612528ms` |
| `write_grhsim_cpp` | `40062ms` | `41032ms` |
| `compute_supernodes` | `74430` | `63392` |
| `dag_edges` | `485905` | `975745` |
| `boundary_activation_edges` | `2216514` | `2460976` |
| model build real | `255.51s` | `161.77s` |
| 50k `Host time spent` | `358037ms` | `651563ms` |
| 50k throughput | `139.7 cycles/s` | `76.7 cycles/s` |

判断：

- worklist 版本让 model build 明显变快，但 runtime 严重退化，50k 比 NO0118 慢 `293526ms`，约 `82.0%`。
- 退化的直接现象是 10k 后 cumulative throughput 持续下降，说明每周期维护/检查 batch active 标记、以及当前 schedule 图形态带来的热路径开销，没有被 batch skip 收益抵消。
- 该方向不应作为当前主线继续推进；若未来要重试，必须先做 clean A/B，让 schedule 结构与 NO0118 完全一致，只单独比较 worklist emitter。
- 当前已测最佳仍是 NO0118。

