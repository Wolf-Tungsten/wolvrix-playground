# Gate59 10k functional gate

- Date: 2026-09-07
- Runtime candidate: [NO0611](./NO0611_grhsim_ir_cpu_gate59_1k_serial_pairs_20260907.md).

## Actual Runtime

The independent gate59 10000-cycle CoreMark/NEMU simulation exited 0. All
builds and other simulations had completed before it started.

```sh
make --no-print-directory run_xs_wolf_grhsim_ir_emu WOLF_ENV_SOURCED=1 \
  XS_GRHSIM_IR_BUILD=ptmp/xs_gate59 XS_SIM_MAX_CYCLE=10000 \
  XS_WAVEFORM=0 XS_WAVEFORM_PATH= XS_LOG_DIR="$PWD/ptmp" \
  XS_PROGRESS_EVERY_CYCLES=1000 TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" \
  RUN_ID=20260907_gate59_o3_10000 > ptmp/grhsim_gate59_o3_10000.log 2>&1
```

| Field | Result |
| --- | --- |
| instrCnt | 458 |
| cycleCnt / guest cycles | 9996 / 10001 |
| Final sampled commit PC | 0x80001cdc |
| Cycle-limit/trap PC | 0x800027c6 |
| IPC | 0.045818 |
| Seed | 0 |
| Host time | 248674 ms |
| Difftest | Enabled after first instruction; no mismatch |
| Exit reason | Cycle limit, not complete CoreMark program termination |

## Comparison

Progress records were extracted by the EMU_PROGRESS marker, not only at line
starts: guest UART text can precede a progress record on the same line. The
reference ptmp/grhsim_legacy_50000_serial_gate57.log has all 50 strictly ordered
thousand-cycle samples. Gate59's ten strictly ordered samples match its first
ten samples exactly after excluding host_ms and terminal color sequences.

The three terminal functional records (exit reason/PC, instruction/cycle/IPC,
seed/guest cycles) match the previously verified gate58 10k log exactly. This
checks both the startup segment and the subsequent instruction advancement,
including 238 instructions at 9k and 458 at 10k.

Gate58's older 10k was 358864 ms, but those two 10k runs are not a fresh paired
performance experiment. The controlled-in-sequence evidence remains the two
1k pairs in NO0611 (about 30.1%/30.6% lower elapsed time). Neither result proves
the plan's full 50k legacy +5% performance requirement.

## Remaining Work

Gate59 has not yet passed an actual 50k window. The 50k proof still belongs to
gate57 only. Continue with the preserved independent gate59 executable and
measure full-window correctness/performance; do not transfer old verification
or claim overall completion from this 10k result. Subsequent optimization must
still address the substantial remaining gap to legacy.

All sessions started for this stage are terminal. No source changes, new builds
or simulations were made after this runtime result. Root/wolvrix whitespace
checks passed; no commit was created. DPI phase/events and ingest policy stayed
unchanged throughout.
