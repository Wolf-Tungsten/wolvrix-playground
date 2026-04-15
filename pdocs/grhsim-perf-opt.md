# GrhSIM Perf Opt

## 0. Tracking Start

- Record time: `2026-04-15 15:08:46 CST`
- Purpose: track GrhSIM XiangShan performance evolution step by step
- Rule: record baseline first, then append one optimization at a time with before/after data

## 1. Current Baseline Scope

This document records the latest available XiangShan GrhSIM performance baseline before the next optimization round.

Data sources:

- Timing trace log: [`build/logs/xs/xs_wolf_grhsim_20260415_133811.log`](/workspace/gaoruihao-dev-gpu/wolvrix-playground/build/logs/xs/xs_wolf_grhsim_20260415_133811.log)
- Active-supernode trace log: [`build/logs/xs/xs_wolf_grhsim_20260415_105814.log`](/workspace/gaoruihao-dev-gpu/wolvrix-playground/build/logs/xs/xs_wolf_grhsim_20260415_105814.log)
- Current generated schedule files: [`build/xs/grhsim/grhsim_emit`](/workspace/gaoruihao-dev-gpu/wolvrix-playground/build/xs/grhsim/grhsim_emit)

## 2. Current Generated-Code Scale

- Schedule batch count: `4051`
- Current emitted `sched_*.cpp` total line count: `18,039,608`
- Initial full activation supernode count observed in runtime trace: `84,314`

Interpretation:

- Current XiangShan GrhSIM is still a very large generated C++ simulator.
- Even after splitting into many `sched_*.cpp`, the total generated schedule code size remains very large.

## 3. Current XiangShan Runtime Characteristics

### 3.1 Eval-Level Timing Baseline

From `160` traced eval invocations:

- `total median = 35,423 us`
- `batches median = 30,839.5 us`
- `commit median = 3,447.5 us`
- `executed supernodes median = 4,666`

By fixed-point rounds:

- `1-round eval`
  - count: `52`
  - `total median = 19,205 us`
  - `batches median = 19,112 us`
  - `commit median = 92 us`
  - `executed supernodes median = 4,664`
- `2-round eval`
  - count: `106`
  - `total median = 40,169.5 us`
  - `batches median = 30,988.5 us`
  - `commit median = 6,935 us`
  - `executed supernodes median = 4,696`
- `3-round eval`
  - count: `2`
  - `total median = 89,905.5 us`
  - `batches median = 77,276.5 us`
  - `commit median = 12,627 us`

Interpretation:

- `eval_batch_*()` is the dominant hotspot.
- `commit_state_updates()` is the secondary hotspot, especially in `2-round` and `3-round` evals.
- Runtime cost is not dominated by initialization or output refresh in the measured window.

### 3.2 Activity Pattern Baseline

From `534` traced eval invocations:

- `seeded=4664` in `532` evals
- `seeded=4723` in `1` eval
- `seeded=84314` in `1` eval

Round histogram:

- `1 round = 52`
- `2 rounds = 478`
- `3 rounds = 4`

Peak active supernode histogram:

- `peak_round_active=4664` in `532` evals
- `peak_round_active=4723` in `1` eval
- `peak_round_active=84314` in `1` eval

Interpretation:

- After the first full eval, the simulator usually runs on a stable hot subset of about `4.6k` active supernodes.
- The active set is sparse relative to the full `84k+` supernode graph.
- Most evals need `2` fixed-point rounds, not `1`.

## 4. Current Performance Diagnosis

Current baseline diagnosis:

- XiangShan GrhSIM does not mainly suffer from “too many active supernodes”.
- The more important issue is that runtime still spends most time inside scheduled combinational evaluation.
- In the current measured baseline, the hot path is `eval_batch_*()`, not waveform, not output refresh, and not prologue logic.
- The active working set is sparse, but combinational propagation cost is still high enough to dominate per-eval runtime.

## 5. Baseline Notes For Future Comparisons

When recording the next optimization step, always append:

- exact code change
- exact measurement time
- exact command
- generated code size change
- XiangShan eval timing deltas
- XiangShan active-supernode pattern deltas
- whether the hotspot share moved away from `eval_batch_*()`

## 6. Optimization Step 1: GSim-Style Active Flag Packing

- Record time: `2026-04-15`
- Goal: reduce hot-path activity-management overhead and let batch dispatch skip work by active-flag bytes instead of per-batch counters

Code changes:

- `supernode_active_curr_` changed from `kSupernodeCount` bytes to `ceil(kSupernodeCount / 8)` bytes
- activity flag is now bit-packed in `uint8_t`, one byte per `8` supernodes
- all emitted activation sites now use direct `|= mask` updates
- emitted code no longer calls per-supernode activation/deactivation helper functions on the hot path
- `active_count_` is updated by `popcount(new_bits)` when a byte gains newly active bits
- each schedule batch now records an active-flag-word span
- `eval()` now skips a batch by scanning only the corresponding active-flag-word range
- `commit_state_updates()` automatically uses the same mask-based activation emission, so the old activation helper overhead is removed there too

Emitter/runtime API changes:

- removed old helper style:
  - `grhsim_activate_supernode`
  - `grhsim_deactivate_supernode`
  - `grhsim_activate_supernodes`
  - `grhsim_is_supernode_active`
- added new helper style:
  - `grhsim_active_mask_entry`
  - `grhsim_popcount_u8`
  - `grhsim_has_any_active_flag_words`

Validation completed:

- build: `cmake --build wolvrix/build -j8`
- test: `ctest --test-dir wolvrix/build --output-on-failure -R emit-grhsim-cpp`
- end-to-end smoke: `make --no-print-directory run_hdlbits_grhsim DUT=001 SKIP_PY_INSTALL=1 WOLVRIX_GRHSIM_WAVEFORM=0`

Validation result:

- emitter target builds successfully
- `emit-grhsim-cpp` test passes
- HDLBits GrhSIM smoke test passes

Pending measurement:

- XiangShan GrhSIM has not been re-emitted and re-measured yet after this active-flag packing step
- the next comparison should focus on:
  - eval median
  - batch time median
  - commit median
  - executed supernode median
  - whether sparse activity now skips batches more effectively

## 7. XiangShan Perf Sample After Active-Flag Packing

- Record time: `2026-04-15`
- Emit log: [`build/logs/xs/xs_wolf_grhsim_build_20260415_152927.log`](/workspace/gaoruihao-dev-gpu/wolvrix-playground/build/logs/xs/xs_wolf_grhsim_build_20260415_152927.log)
- Run log: [`build/logs/xs/xs_wolf_grhsim_20260415_163500_perf.log`](/workspace/gaoruihao-dev-gpu/wolvrix-playground/build/logs/xs/xs_wolf_grhsim_20260415_163500_perf.log)

Command used:

- build:
  - `NOOP_HOME=/workspace/gaoruihao-dev-gpu/wolvrix-playground/testcase/xiangshan make -C testcase/xiangshan/difftest emu BUILD_DIR=/workspace/gaoruihao-dev-gpu/wolvrix-playground/build/xs/grhsim GEN_CSRC_DIR=/workspace/gaoruihao-dev-gpu/wolvrix-playground/testcase/xiangshan/build/generated-src NUM_CORES=1 WITH_CHISELDB=0 WITH_CONSTANTIN=0 GRHSIM=1 GRHSIM_MODEL_DIR=/workspace/gaoruihao-dev-gpu/wolvrix-playground/build/xs/grhsim/grhsim_emit WOLVRIX_GRHSIM_WAVEFORM=0`
- run:
  - `GRHSIM_TRACE_EVAL_EVERY=100 make --no-print-directory run_xs_wolf_grhsim_emu RUN_ID=20260415_163500_perf XS_SIM_MAX_CYCLE=2000 XS_PROGRESS_EVERY_CYCLES=200 XS_WAVEFORM=0 XS_COMMIT_TRACE=0`

Observed execution summary:

- run stopped at cycle limit `2000`
- final runtime summary:
  - `instrCnt = 3`
  - `cycleCnt = 1996`
  - `IPC = 0.001503`
  - `Host time spent = 161396 ms`
- host-side throughput in this run is only about `12.4 cycles/s`

Observed perf phases:

- early sampled phase (`eval #200` to `#1000`)
  - `batch_us ~= 12.8 ms`
  - `commit_us ~= 0.095 ms`
  - `total_us ~= 19.2 ms`
- later sampled phase (`eval #1100` onward)
  - `batch_us ~= 22.2 ms`
  - `commit_us ~= 0.151 ms`
  - `total_us ~= 28.7 ms`

Steady-state sampled averages (`eval #1300` and later, `29` samples):

- `avg_batch_us = 22237.2`
- `avg_commit_us = 150.9`
- `avg_total_us = 29081.3`
- `avg_exec_batches = 2219.0`
- `avg_skip_batches = 5883.0`
- `avg_checked_flag_words = 18350458.0`

Per-round steady-state averages (`eval #1300` and later):

- round 1
  - `active_in = 4664`
  - `executed_batches = 2066`
  - `skipped_batches = 1985`
  - `checked_flag_words = 4326506`
  - `batch_us = 21620.7`
  - `commit_us = 150.9`
  - `total_us = 24142.0`
  - `active_out = 32`
- round 2
  - `active_in = 32`
  - `executed_batches = 153`
  - `skipped_batches = 3898`
  - `checked_flag_words = 14023952`
  - `batch_us = 616.6`
  - `commit_us = 0.0`
  - `total_us = 4883.6`
  - `active_out = 0`

Interpretation:

- active-flag packing itself is working functionally, and batch skipping is active.
- but the current implementation still linearly scans batch flag ranges for all `4051` batches in every round.
- round 2 only has `32` active supernodes and executes only `153` batches, but it still scans about `14.0M` active-flag words on average.
- this means the current bottleneck has shifted toward batch-range scanning overhead, not commit.
- the sampled log strongly suggests the next optimization should avoid full per-batch range scans in every round, and move toward a cheaper batch-activation representation closer to `gsim`.

## 8. XiangShan Perf Sample With Emit-Time Perf Toggle

- Record time: `2026-04-15`
- Purpose: validate the new emit-time perf switch and capture a clean no-waveform GrhSIM perf sample
- Emit/build log: [`build/logs/xs/xs_wolf_grhsim_build_20260415_183434.log`](/workspace/gaoruihao-dev-gpu/wolvrix-playground/build/logs/xs/xs_wolf_grhsim_build_20260415_183434.log)
- Run log: [`build/logs/xs/xs_wolf_grhsim_perf_20260415_1.log`](/workspace/gaoruihao-dev-gpu/wolvrix-playground/build/logs/xs/xs_wolf_grhsim_perf_20260415_1.log)

Emit/build configuration:

- `WOLVRIX_GRHSIM_WAVEFORM=0`
- `WOLVRIX_GRHSIM_PERF=1`
- emit argument confirmed in log:
  - `--waveform off --perf eval`

Run configuration:

- `RUN_ID=perf_20260415_1`
- `GRHSIM_TRACE_EVAL_EVERY=500`
- `XS_SIM_MAX_CYCLE=5000`
- `XS_PROGRESS_EVERY_CYCLES=1000`
- `WOLVRIX_GRHSIM_WAVEFORM=0`
- command:
  - `RUN_ID=perf_20260415_1 GRHSIM_TRACE_EVAL_EVERY=500 XS_SIM_MAX_CYCLE=5000 XS_PROGRESS_EVERY_CYCLES=1000 WOLVRIX_GRHSIM_WAVEFORM=0 make run_xs_wolf_grhsim_emu`

Associated generated-model facts:

- `activity-schedule` output:
  - `supernodes = 84314`
  - `ops_mean = 64.796`
  - `ops_median = 71`
  - `ops_p90 = 72`
  - `ops_p99 = 72`
  - `ops_max = 72`
- `write_grhsim_cpp` time: `182649 ms`
- total emit flow time: `307847 ms`
- build completed successfully with:
  - `clang++ -std=c++20 -O3`

Observed eval-end sample summary (`10` samples, `eval #500` to `#5000`):

- `rounds = 2` in all samples
- `peak_active_supernodes = 4664`
- `checked_batches = 21080`
- `executed_batches`
  - min: `1587`
  - max: `1588`
  - mean: `1587.1`
- `skipped_batches`
  - min: `19492`
  - max: `19493`
  - mean: `19492.9`
- `checked_flag_words = 21080`
- `batch_us`
  - min: `15834`
  - max: `15937`
  - mean: `15893.1`
- `commit_us`
  - min: `128`
  - max: `132`
  - mean: `130.4`
- `clear_evt_us = 0`
- `total_us`
  - min: `17074`
  - max: `17176`
  - mean: `17132.6`

Observed per-round sample summary:

- round 1
  - `active_in = 4664`
  - `checked_batches = 10540`
  - `executed_batches`
    - mean: `1574.1`
  - `skipped_batches`
    - mean: `8965.9`
  - `checked_flag_words = 10540`
  - `batch_us`
    - mean: `15858.1`
  - `total_us`
    - mean: `17008.6`
  - `active_out = 32`
- round 2
  - `active_in = 32`
  - `checked_batches = 10540`
  - `executed_batches = 13`
  - `skipped_batches = 10527`
  - `checked_flag_words = 10540`
  - `batch_us`
    - mean: `35.0`
  - `total_us`
    - mean: `55.9`
  - `active_out = 0`

Observed runtime progress:

- `host_cycles=1000`
  - `host_ms=52419`
  - `instr=3`
  - `commit_pc=0x10000008`
- `host_cycles=2000`
  - `host_ms=101930`
  - `instr=3`
  - `commit_pc=0x10000008`

Derived throughput:

- around `19.1` to `19.6 cycles/s` in this sampled window

Interpretation:

- The new emit-time perf switch is working as intended:
  - waveform support stayed off
  - perf trace stayed on
  - generated model still built and linked successfully
- This sampled window is far more stable than the earlier active-word-scan baseline:
  - `checked_batches` is now `21080`, not millions of scanned flag words
  - round-2 cost is now tiny: about `56 us`
  - `commit_state_updates()` is no longer a significant contributor
- The hot path is now overwhelmingly round-1 `eval_batch_*()` execution:
  - about `15.9 ms` of `17.1 ms` total per sampled eval is batch work
- However, this run is still not a valid steady-state CoreMark performance number:
  - by cycle `2000`, only `3` instructions had committed
  - `commit_pc` remained at `0x10000008`
  - so this perf sample represents an early stuck/incorrect execution state, not normal XiangShan progress

Comparison against the previous documented sample:

- previous sample average `total_us`: about `29081.3`
- current sample average `total_us`: about `17132.6`
- previous sample average `batch_us`: about `22237.2`
- current sample average `batch_us`: about `15893.1`
- previous sample round-2 total: about `4883.6 us`
- current sample round-2 total: about `55.9 us`

Current takeaway:

- The active-word dispatch rewrite materially reduced the scheduling overhead.
- The dominant remaining runtime cost in the current stuck execution window is batch evaluation itself, not commit and not activity bookkeeping.
- Any further performance work should be judged only after restoring correct forward progress, because the present sample is taken in an incorrect execution regime.
