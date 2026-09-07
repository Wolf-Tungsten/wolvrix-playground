# Gate62 50k serial performance

- Date: 2026-09-07
- Functional gate: [NO0643](./NO0643_grhsim_ir_cpu_gate62_50k_functional_gate_20260907.md).
- Status: actual 50k correctness passed; full-window performance requirement failed.

## Fresh serial comparison

The gate62 IR process terminated before the legacy process started. Both used
the existing run-only Makefile targets, coremark-2-iteration.bin, NEMU difftest,
seed 0, the 50000-cycle limit, waveform off and thousand-cycle progress.
No compilation or other simulation overlapped either measurement.

The fresh legacy command was:

```sh
make --no-print-directory run_xs_wolf_grhsim_emu WOLF_ENV_SOURCED=1 \
  XS_GRHSIM_BUILD=build/xs/grhsim XS_SIM_MAX_CYCLE=50000 \
  XS_WAVEFORM=0 XS_WAVEFORM_PATH= XS_LOG_DIR="$PWD/ptmp" \
  XS_PROGRESS_EVERY_CYCLES=1000 RUN_ID=legacy_50000_serial_gate62 \
  TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" \
  > ptmp/grhsim_legacy_50000_serial_gate62.log 2>&1
```

Both processes exited 0 with NEMU enabled and no mismatch. The two current
logs contain exactly 50 ordered, identical functional samples and identical
three-record terminals: 73580 instructions, cycleCnt=49996, guest=50001,
IPC=1.471718, limit PC=0x80001312. The final sampled commit PC is 0x800012f8.
IR log: ptmp/grhsim_gate62_o3_50000.log.

## Performance result

| Metric | Value |
| --- | ---: |
| Gate62 IR 50k host ms | 1024849 |
| Fresh serial legacy 50k host ms | 155179 |
| IR / legacy elapsed time | 6.604302 |
| IR overhead | 560.430% |
| Legacy times 1.05 | 162937.95 ms |
| Additional IR reduction needed for that threshold | 84.1013% |

The plan's performance gate is explicitly not met. Functional success at the
50000-cycle limit is not completion of the entire CoreMark program or proof
that all activity-plan requirements are complete.

Gate59's historical IR 50k took 1371764 ms; this candidate took 1024849 ms after
the intervening string/history/bitwise changes. That is not a fresh gate59/
gate62 pair and does not isolate the bitwise change. Its own 1k paired benefit
was below 0.4%, so no meaningful isolated speedup is claimed. This full-window
pair has no fixed CPU affinity/frequency or uniform rebuild of both backends;
the large gap is conclusive, but fine statistical claims are not justified.

## Retained state and next investigation

Keep the verified gate62 ordinary binary and generated model as the new 50k
reference, preserving gate59/gate60/gate61 artifacts. SHA-256:

```text
gate62 emu   0b29bcee26710ee4de444743979228ac9eb761eae579f45f21fb24346f177e1a
gate61 emu   314c2a9cdcd2050fc14a95a9135a123b9ca9c00ff992c41d205fe21a7c8b481c
legacy emu   c211cf9435d867bb4bbda6df73173389106fa5255a3f8af7635d9879221a88cb
cpu_emit.cpp 88a9605dc090737b48a27a9b8517c021f07376933f7df1592f8915c5b01ff5fb
schedule.cpp 7f7f253903d2c7ffe6a79fc7f8f19cba5f353a5a80a00d107932ba5f1b53fd64
```

All fingerprints remained stable through the runs, all sessions are terminal,
and root/wolvrix whitespace checks passed. No production code changed in this
build-and-runtime stage, and no commit was made. The goal remains active.

Next re-measure gate62 compute/commit/publish costs and activation/round counts
before choosing a further change. The earlier gate61 phase split is historical.
The retained legacy generated set_runtime_profile_enabled/dump_runtime_profile
methods are no-op stubs, so EMU_RUNTIME_PROFILE alone would not provide useful
model attribution; inspect or instrument the generated route before relying
on that switch. Preserve/restorably verify ordinary binaries after any probes.

Wide arithmetic/shift true-change activation and the remaining full-plan
acceptance audit are still open. Local-frame initialization and constant
materialization are investigation candidates, not proven causes or approved
blanket removals. Preserve legacy pointer/out-buffer helper strategy, current
DPI/event/history semantics, Makefile-only workflows and project-local outputs.
