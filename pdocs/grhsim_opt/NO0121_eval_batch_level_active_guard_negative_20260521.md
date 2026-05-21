# NO0121: eval batch-level active guard negative result

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


实验目的：

- perf 20k 采样显示热点被拆散到大量 `eval_compute_batch_*` / `eval_commit_batch_*`，而不是单个 helper：
  - `emu` DSO 占约 `99.48%`。
  - `apply_commit_scalar_state_write_table` 为最高单符号，但 self 仅约 `1.30%`，children 约 `2.68%`。
  - 大量 `eval_commit_batch_*` 分散在 `0.5%` 到 `1.1%` 区间。
- 因此尝试在 `eval()` 调用 batch 前生成 batch-level active guard：
  - 若该 batch 覆盖的 activity word/mask 全为空，则跳过 batch 方法调用。
  - batch 内原有 active word clear 和 supernode dispatch 逻辑不变。

实现与验证：

- 在 `wolvrix/lib/emit/grhsim_cpp.cpp` 临时加入 `emit_eval_batch_active_guard` / `GRHSIM_EMIT_EVAL_BATCH_ACTIVE_GUARD` 开关。
- 注意：Python `wolvrix` 扩展需要重新 `pip install --no-build-isolation -e wolvrix`，否则 `scripts/wolvrix_xs_grhsim.py` 会使用旧 emitter。
- 局部验证：
  - `cmake --build wolvrix/build --target emit-grhsim-cpp -j$(nproc)`：通过。
  - `ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'`：通过。

NO0121 fresh emit：

- 输出目录：`tmp/no0121_xs_emit_eval_batch_guard/grhsim_emit`
- 开关：`GRHSIM_EMIT_EVAL_BATCH_ACTIVE_GUARD=1`
- `activity-schedule`: `190118ms`
- `write_grhsim_cpp`: `41336ms`
- total real: `260.15s`
- `compute_supernodes`: `73382`
- `commit_supernodes`: `515`
- supernodes: `73897`
- `eval()` batch-level guards: `1004`

NO0121 build/runtime：

- model build real: `264.83s`
- model build user/sys: `5938.77s` / `62.47s`
- difftest emu build: 成功。
- CoreMark 20k 退出码：`0`
- 未出现 difftest mismatch。
- `Guest cycle spent`: `20001`
- `Host time spent`: `114786ms`

NO0121 20k 进度点：

| model cycles | host ms |
| ---: | ---: |
| `10000` | `24077` |
| `20000` | `114779` |

判断：

- batch-level guard 确实生成并生效，但 20k runtime 明显慢于 NO0118 的 `107531ms`，也慢于 NO0118 perf 复测的 `112624ms`。
- 负收益原因大概率是 guard 本身要在每轮扫描大量 active word，且很多 compute batch guard 包含长 OR 链；跳过的 batch 调用成本不足以抵消 guard 成本。
- 该实验不继续跑 50k，已回退，不纳入当前最佳代码；当前最佳仍为 NO0118。

