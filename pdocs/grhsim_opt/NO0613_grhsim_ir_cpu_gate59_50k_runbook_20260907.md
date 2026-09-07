# Gate59 50k runbook

- Date: 2026-09-07
- Precondition: [NO0612](./NO0612_grhsim_ir_cpu_gate59_10k_functional_gate_20260907.md).
- Status: real 50k run started; no terminal result yet.

## Fixed Candidate

Use the independent gate59 O3 executable without rebuild, profiling probes,
source changes or concurrent build/simulation. Existing 10k success does not
prove this full window. Keep DPI/events/ingest and helper ABI unchanged.

SHA-256 at start:

```text
cpu_emit.cpp     83b8ef7dfb1b6dc0e31c86b73c920fe39da9421fd0a6a5ae293f4d6d6e5e0598
cpu_schedule.cpp 7f7f253903d2c7ffe6a79fc7f8f19cba5f353a5a80a00d107932ba5f1b53fd64
gate59 emu      e3447dc332f3fd6649da7a1b1a59add38733080b62bb376c620c2f0cab057dbd
```

The executable is ptmp/xs_gate59/emu/emu, 164242592 bytes. Model archive is
ptmp/xs_emit_make_gate59/libgrhsim_SimTop.a, 182956358 bytes.

## Run and Compare

```sh
make --no-print-directory run_xs_wolf_grhsim_ir_emu WOLF_ENV_SOURCED=1 \
  XS_GRHSIM_IR_BUILD=ptmp/xs_gate59 XS_SIM_MAX_CYCLE=50000 \
  XS_WAVEFORM=0 XS_WAVEFORM_PATH= XS_LOG_DIR="$PWD/ptmp" \
  XS_PROGRESS_EVERY_CYCLES=1000 TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" \
  RUN_ID=20260907_gate59_o3_50000 > ptmp/grhsim_gate59_o3_50000.log 2>&1
```

The existing reference ptmp/grhsim_legacy_50000_serial_gate57.log contains all
50 ordered thousand-cycle records. Extract by marker even when UART text or
terminal controls precede the marker. Exclude host_ms only from functional
comparison. Expected final record: 73580 instructions, commit PC 0x800012f8,
trap PC 0x80001312. Expected terminal cycleCnt/guest cycles: 49996/50001.

After IR terminates, run the existing legacy executable serially at the same
50000-cycle limit, image, NEMU, seed 0, waveform and progress settings. Compare
all 50 samples plus exit reason, counters/IPC and seed/guest cycles. Use that
fresh serial runtime for the performance denominator, not a concurrent or
historical sample. Do not stop early at 10k/20k or reinterpret cycle-limit
success as complete CoreMark program termination.

This runbook is not a gate result. Overall completion still requires all plan
requirements, including the full-window legacy +5% performance requirement.
