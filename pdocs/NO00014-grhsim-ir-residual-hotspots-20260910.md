# GrhSIM-IR Residual Hotspot Re-Localization (Post edge-snapshot)

- Node: `residual_hotspots_20260910_01`
- Status: VALIDATED / DIAGNOSTIC; both 50k runs PASS with exact endpoint
- Root baseline: `2994d7736d2d8a947df6c1638f5d3defc1f4c76e`; wolvrix baseline: `c8b8676aee27efbf701e62d86c37e3ca86b576e3`.

## Question and plan recorded before execution

The accepted [edge-snapshot node](NO00012-grhsim-ir-candidate-edge-snapshot-20260910.md)
lowered the 50k Host mean to **215.6715 s** (−20.1790% against its final
control). The only function-level profile on this program
([task-hotspots](NO00010-grhsim-ir-task-hotspots-20260910.md)) predates both accepted
optimizations: it measured the scalar-stage executable at compute 56.1832% /
commit 38.7506% / publication 5.0388% of eval time, commit tasks at 35.6047% of
flat samples, and `cpu_write_scalar<bool>` at 6.2184%. Edge-snapshot removed
226,510 repeated payload predicate references concentrated in commit tasks, so
that distribution no longer describes where the remaining 215.6715 s goes.

This node re-localizes the residual costs on the accepted edge-snapshot
executable, without modifying any source. The hypothesis under test for the
next optimization node is that a measurable residual concentration exists
(phase-level or function/task-level) sufficient to bound and select a new
mechanism. This node itself implements no simulator change and claims no
speedup. The measurement questions, fixed before execution:

1. What is the current compute/commit/publication phase split of eval time?
2. Which native functions and generic generated task classes hold the flat
   samples now; did the commit-task share drop as the static change predicts?
3. Which residual category (compute bodies, commit payload writes, history
   work, staging helpers, libc data movement, evaluator) is large enough to
   bound a next mechanism above the 3% acceptance threshold?

## Method and controls recorded before execution

Reuse the exact accepted edge-snapshot executable
(`ptmp/edge_snapshot_20260910_01/flow/emu/emu`, 126,255,688 bytes, verified
present) and its generated model; no generation or compilation is needed or
performed. Code is unchanged, so the archived unprofiled runs on this identical
binary (Host 217.336 / 214.007 s, mean 215.6715 s) remain the performance
reference; the two runs below are diagnostic only and will not be used as
performance evidence or averaged into any baseline.

Preselected simulation stop-loss for both runs: 1.5 × 215.6715 =
**323.50725 s** process-group KILL deadline. Any timeout, non-zero exit,
crash, assertion, or NEMU mismatch marks the run INVALID and ends this node
as far as evidence use; failed output may only serve cause analysis.

Fixed configuration, rechecked at entry: XiangShan
`4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`; CoreMark SHA-256
`c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`; top SimTop,
DIFFTEST/NEMU; 50,000 cycles; CPU 2 via taskset; explicit `XS_EMU_THREADS=1`;
waveform/commit/RAM trace off; host reports 32 CPUs. Root and wolvrix
worktrees were clean at entry. The required endpoint for a valid run is
73,580 instructions, cycleCnt 49,996, terminal PC `0x80001312`, guest cycles
50,001 — identical to the accepted runs.

Two sequential runs on the same executable:

- **Run A (phase split)**: `EMU_RUNTIME_PROFILE=1`, no CPU profiler. The
  built-in phase instrumentation ships in this executable since the
  phase-profile node; enabling it adds clock reads, so its Host time is
  diagnostic. It yields eval/compute/commit/publication totals.
- **Run B (flat profile)**: gperftools `CPUPROFILE` at requested 199 Hz via
  `LD_PRELOAD=/lib/x86_64-linux-gnu/libprofiler.so.0`, with
  `EMU_RUNTIME_PROFILE=0` so phase clock reads do not pollute the sampled
  distribution. Flat interrupted-PC attribution only; no inclusive stacks.

Analysis uses the existing read-only analyzer through
`make analyze_grhsim_cpu_profile` (reader tests first via
`make test_grhsim_cpu_profile`), with the same PIE/ELF mapping rule validated
in the task-hotspots node, against this node's emu binary and generated
evaluator. Old-vs-new percentages are compared descriptively; host drift and
sampling limits are acknowledged, and no causal claim is made from single
diagnostic runs. Temporary artifacts stay under
`ptmp/residual_hotspots_20260910_01/`.

## Results

### Runs

Run A (phase split, `EMU_RUNTIME_PROFILE=1`):

```bash
WOLF_ENV_SOURCED=1 XS_EMU_THREADS=1 EMU_PHASE_TIMING=0 EMU_RUNTIME_PROFILE=1 make --no-print-directory run_xs_wolf_grhsim_ir_emu RUN_ID=residual_hotspots_20260910_01_phase XS_GRHSIM_IR_BUILD=ptmp/edge_snapshot_20260910_01/flow XS_LOG_DIR=ptmp/residual_hotspots_20260910_01/logs XS_SIM_MAX_CYCLE=50000 XS_EMU_CPU=2 XS_PROGRESS_EVERY_CYCLES=0 XS_WAVEFORM=0 XS_COMMIT_TRACE=0 XS_RAM_TRACE=0 XS_WAVEFORM_PATH= WOLVRIX_GRHSIM_WAVEFORM=0 XS_EMU_PREFIX="timeout --signal=KILL 323.50725s /usr/bin/time -p -o $PWD/ptmp/residual_hotspots_20260910_01/phase.time taskset -c 2 stdbuf -oL -eL" > ptmp/residual_hotspots_20260910_01/phase.log 2>&1
```

Run B (flat profile, `EMU_RUNTIME_PROFILE=0`, gperftools 199 Hz):

```bash
WOLF_ENV_SOURCED=1 XS_EMU_THREADS=1 EMU_PHASE_TIMING=0 EMU_RUNTIME_PROFILE=0 make --no-print-directory run_xs_wolf_grhsim_ir_emu RUN_ID=residual_hotspots_20260910_01_cpu XS_GRHSIM_IR_BUILD=ptmp/edge_snapshot_20260910_01/flow XS_LOG_DIR=ptmp/residual_hotspots_20260910_01/logs XS_SIM_MAX_CYCLE=50000 XS_EMU_CPU=2 XS_PROGRESS_EVERY_CYCLES=0 XS_WAVEFORM=0 XS_COMMIT_TRACE=0 XS_RAM_TRACE=0 XS_WAVEFORM_PATH= WOLVRIX_GRHSIM_WAVEFORM=0 XS_EMU_PREFIX="timeout --signal=KILL 323.50725s /usr/bin/time -p -o $PWD/ptmp/residual_hotspots_20260910_01/cpu.time taskset -c 2 env CPUPROFILE=$PWD/ptmp/residual_hotspots_20260910_01/cpu.prof CPUPROFILE_FREQUENCY=199 LD_PRELOAD=/lib/x86_64-linux-gnu/libprofiler.so.0" > ptmp/residual_hotspots_20260910_01/cpu.log 2>&1
```

| Run | Exit | Host s | Exec wall s | NEMU | Endpoint | Stop-loss (323.50725 s) |
|---|---|---:|---:|---|---|---|
| A: phase on | 0 | 213.140 | 213.17 | enabled, no mismatch | 73,580 instr / cycleCnt 49,996 / PC 0x80001312 / guest 50,001 | NONE |
| B: CPU profile | 0 | 219.161 | 219.19 | enabled, no mismatch | identical | NONE |

Both runs reproduce the accepted architectural endpoint exactly and no
mismatch, ABORT, bad trap, assertion, or segmentation fault appears in either
log. The run A Host time is 1.1738% below the archived unprofiled mean
215.6715 s on the identical binary despite enabled instrumentation; as in the
task-hotspots node, this reflects uncontrolled host drift between sessions,
not negative instrumentation overhead or a speedup. Run B is 1.6180% above
that mean. Neither diagnostic run changes the performance baseline: the
archived 217.336 / 214.007 s unprofiled pair remains the reference.

### Phase split (Run A)

```text
[grhsim-cpu-phase] evals=100102 rounds=201258 eval_ns=212888382915 compute_ns=149718879541 commit_ns=52378768570 publish_ns=10708381571
```

Rounds per eval are 201,258 / 100,102 = **2.010529**, identical to the
pre-optimization measurement; the convergence structure is unchanged.

| Phase | Old (scalar-stage build, on run) | New (edge-snapshot build) | Share old | Share new | Absolute change |
|---|---:|---:|---:|---:|---:|
| Compute segment | 164.1240 s | 149.7189 s | 56.1832% | **70.3274%** | −8.7770% |
| Commit segment | 113.1995 s | 52.3788 s | 38.7506% | **24.6039%** | −53.7288% |
| Publication | 14.7195 s | 10.7084 s | 5.0388% | **5.0300%** | −27.2502% |
| Residual | 0.0801 s | 0.0824 s | 0.0274% | 0.0387% | — |
| Total eval | 292.1230 s | 212.8884 s | 100% | 100% | −27.1237% |

The commit segment's measured time roughly halved while compute fell only
modestly, consistent with edge-snapshot's payload-predicate elimination being
concentrated in commit tasks and with shared-history removing commit staging
work. Neither optimization touched compute task bodies; the −8.8% compute
change is cross-binary and cross-session, so host drift, code layout, and
second-order scheduling effects (fewer staged history writes → fewer pending
records → fewer armed compute tasks in later rounds) are all plausible
contributors and are not separable here. Publication's share is unchanged at
about 5%. These absolute cross-run deltas are descriptive, not causal
attribution.

### Flat profile (Run B, 43,617 samples, period 5,025 µs, nominal CPU 219.175 s)

`make test_grhsim_cpu_profile` passed (2 tests). The analyzer reported
`PASS: profile terminator, mappings, ELF layout, task coverage, symbol bounds,
sample totals` for this binary (5,595 tasks = 5,081 compute + 514 commit).
Evictions 36,601 are aggregation-table flushes, not dropped samples.

| Category | Old samples | Old share | New samples | New share |
|---|---:|---:|---:|---:|
| Compute task functions | 26,711 | 47.3624% | 24,623 | **56.4528%** |
| Commit task functions | 20,080 | 35.6047% | 9,564 | **21.9272%** |
| Other main-executable functions/helpers | 5,223 | 9.2611% | 5,192 | 11.9036% |
| External mappings (≈ all libc) | 2,563 | 4.5446% | 2,764 | 6.3370% |
| Main evaluator | 1,718 | 3.0463% | 1,409 | 3.2304% |
| Unresolved / unmapped | 102 | 0.1809% | 65 | 0.1490% |
| Total | 56,397 | 100% | 43,617 | 100% |

Total samples fell 22.6608% between runs, tracking the runtime drop
(283.39 s → 219.18 s nominal sampled CPU), so share comparisons are the
meaningful old-vs-new signal; absolute per-function sample-count changes
inherit the total change. Commit-task samples fell from 20,080 to 9,564
(−52.4%) while compute-task samples fell only 7.8% — the flat accounting
confirms the phase-timer shift with an independent measurement method.

| Function / mapping | Old share | New share | Note |
|---|---:|---:|---|
| `cpu_write_scalar<bool>` (out-of-line) | 6.2184% | **8.7076%** | now clearly the dominant single function |
| libc mapping (unresolved within) | 4.5428% | 6.3347% | memcpy/memcmp/memset candidates unresolved |
| `eval()` (entire evaluator incl. inlined publication) | 3.0463% | 3.2304% | not a pure dispatcher cost |
| Commit task 5141 | 1.5781% | **2.2560%** | hottest task; ineligible for both accepted optimizations |
| `cpu_stage_cell` | 0.6330% | 0.9262% | memory staging helper |

`cpu_write_scalar<bool>` sample count rose 3,507 → 3,798 (+8.3%) while total
samples fell 22.7%. Its call-site count only shrank between the two builds
(21,073 → 16,255 sites), so the out-of-line share growth most plausibly
reflects attribution boundaries (work inlined into task bodies in the old
binary now sits inside the per-TU out-of-line instantiation, or vice versa)
plus sampling noise; the data does not establish more dynamic calls. The
function remains the staging fast path: dirty-byte test, current-vs-next
compare, early return. Its 16,255 static call sites split 13,763 in compute
(assert/history sampling) vs 2,492 in commit — 84.7% compute-side.

Task-level concentration:

- Compute: 3,229 sampled tasks (old 3,367); top ten = 1,613 samples =
  3.6981% of all samples, 6.5508% of compute samples (old 2.5516% / 5.3873%).
  The hottest compute tasks remain the assert/DPI class: 5048, 5046, 5077,
  5045, 5039, 5057, 5049, 5047, 5062, 5076 — the same class as before, each
  ~500 guard→DPI→history-sample repetitions. No individual compute task
  exceeds 0.50% of the profile; per-task fixes cannot move this bucket.
- Commit: 150 sampled tasks (old 177); top ten = 3,090 samples = 7.0844% of
  all, 32.3087% of commit samples (old 28.4313%). Concentration rose because
  one outlier remains: task 5141 alone holds 984 samples (2.2560% of all,
  10.2886% of commit samples). Task 5121, formerly 1.0213%, fell to 0.5480%
  after its 226,510 repeated predicate references collapsed into one snapshot.

### Residual cost structure and next-direction bounds

Combining both measurement methods (phase timers attribute out-of-line helper
time to the calling phase; the flat profile attributes it to the helper
symbol), the residual 215.6715 s decomposes as:

1. **Compute-phase work ≈ 70.3% of eval (149.7 s in Run A)**, flat across
   3,229 tasks. The only concentrated generic pattern is the assert/DPI task
   class (~39 tasks × ~500 assertions): per-assertion event-guard machinery
   (boundary clock byte reloaded ~2× per assertion, ~1,008 loads per task per
   pass) plus one 6-argument out-of-line `cpu_write_scalar<bool>` history
   sample per assertion. That helper holds 8.71% of all samples; with 84.7%
   of its call sites compute-side, the compute-side staging fast path alone
   bounds roughly 7% of runtime, before counting the in-task guard/reload
   machinery that tops the compute ranking. A generic mechanism (per-task
   hoisting of invariant event loads; specialized history-sample path that
   preserves shadow/publish semantics) has the largest bounded coverage of
   any identified direction, on the order of 10% as an upper bound.
2. **Commit-phase work ≈ 24.6% (52.4 s)**, now dominated by the 18 commit
   tasks ineligible for the accepted optimizations, above all task 5141
   (2.26% of all samples): 4,094 payload guards each re-evaluating a 2-term
   edge predicate with 2 history-byte loads, 212 byte-pair `memcpy` pattern
   fills, and 48 statically duplicated sample pairs. Extending snapshot
   eligibility to IR-shared histories proven stable during commit, or a
   semantic dedup of identical stage sequences, bounds about 3-4% total.
3. **Publication ≈ 5.0% (10.7 s)** plus an unresolved share of the 6.33% libc
   bucket (publish-time `memcmp`/`memcpy` per pending record, batch fills).
   Bounded at roughly 5-8% total, at the cost of touching the pending-record
   ABI; the pending-dedup node already proved the dirty-bit invariant forbids
   record dedup, so only copy/arming-path restructuring remains.
4. **Evaluator ≈ 3.2% flat**, including inlined publication and the per-round
   fixed seeding (1,716 flag stores + 5,595 guarded calls × 201,258 rounds).
   Not a primary target.

The rejected directions (ready queue/dispatch, frame-zeroing removal,
activity-mask packing, pending record dedup) stay excluded; nothing in this
measurement rehabilitates them.

## Decision

**VALIDATED as a diagnostic node.** Both 50k runs exited 0 with NEMU enabled
and reproduced the exact accepted endpoint (73,580 instructions, cycleCnt
49,996, PC 0x80001312, guest cycles 50,001); the preselected 323.50725 s
stop-loss was never approached. No source was modified, no optimization is
claimed, and the performance baseline is unchanged: edge-snapshot remains the
best at mean **215.6715 s** with its archived controls. The node's three
pre-registered questions are answered:

1. Phase split is now compute **70.3274%** / commit **24.6039%** /
   publication **5.0300%** of eval time (was 56.18 / 38.75 / 5.04).
2. The dominant single function is out-of-line `cpu_write_scalar<bool>` at
   **8.7076%** of flat samples; the hottest task is commit **5141** at
   2.2560%; commit-task share fell 35.6047% → 21.9272%, confirming the
   accepted optimizations' commit concentration with an independent method.
3. The largest residual category with a generic trigger is the compute-side
   scalar staging/history-sampling path (helper 8.71% + assert-class guard
   machinery topping the compute ranking), bounded near 10%; the un-shared
   commit outlier class bounds 3-4%; publication bounds ~5%.

Recommended next node: a semantic mechanism on the scalar history-sampling /
staging fast path — e.g. per-task invariant event-load hoisting and/or a
specialized history-sample emission that preserves the shadow, dirty-bit,
pending-record, and publication semantics exactly (the dirty-bit invariant
that falsified pending-dedup applies and must be re-proven for any record
elision). Falsification criterion for that node: static site counts and a
matching-source control, acceptance >3% beyond noise per the standing gate.

Archive: this report, the [goal index](grhsim-ir-xiangshan-coremark-50k.index.md),
and the reused tools ([analyzer](../scripts/grhsim_cpu_profile.py),
[reader tests](../scripts/test_grhsim_cpu_profile.py), [Makefile](../Makefile))
are the only tracked artifacts; no code, script, or submodule change occurred
in this node, so the root commit contains documentation only and the wolvrix
pointer stays at `c8b8676aee27efbf701e62d86c37e3ca86b576e3`. Generated models,
logs, profiles, and binaries remain untracked under `ptmp/`.
