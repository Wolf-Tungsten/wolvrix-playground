# Gate62 50k runbook

- Date: 2026-09-07
- Precondition: [NO0640](./NO0640_grhsim_ir_cpu_gate62_10k_functional_gate_20260907.md).
- Status: real 50k run started; no terminal result yet.

Use ptmp/xs_gate62/emu/emu, the independent O3 ordinary binary verified at
10k. SHA-256: 0b29bcee26710ee4de444743979228ac9eb761eae579f45f21fb24346f177e1a.
There are no profiling probes. Do not rebuild or modify the candidate, run
another simulation concurrently, or shorten the cycle limit.

```sh
make --no-print-directory run_xs_wolf_grhsim_ir_emu WOLF_ENV_SOURCED=1 \
  XS_GRHSIM_IR_BUILD=ptmp/xs_gate62 XS_SIM_MAX_CYCLE=50000 \
  XS_WAVEFORM=0 XS_WAVEFORM_PATH= XS_LOG_DIR="$PWD/ptmp" \
  XS_PROGRESS_EVERY_CYCLES=1000 TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" \
  RUN_ID=gate62_o3_50000 > ptmp/grhsim_gate62_o3_50000.log 2>&1
```

Compare all 50 strictly ordered progress records against the existing legacy
50k reference. Extract `[EMU_PROGRESS] host_cycles=` even after UART/ANSI;
exclude only host_ms from functional comparison. Expected final instructions:
73580; sampled commit PC=0x800012f8; trap/limit PC=0x80001312;
cycleCnt=49996; guest=50001. Preserve intermediate evidence but wait for the
original process handle to terminate; an observation timeout is not failure.

After IR terminates, use make run_xs_wolf_grhsim_emu with
XS_GRHSIM_BUILD=build/xs/grhsim and the same 50000-cycle/image/NEMU/seed/
waveform/progress configuration. Log the fresh serial denominator to
ptmp/grhsim_legacy_50000_serial_gate62.log. Compare all samples and three
terminal records, then calculate the actual full-window IR/legacy ratio.

This runbook is not a gate result. The full goal still includes the plan's
50k performance no worse than legacy+5%. A successful cycle-limit run does
not claim completion of the entire CoreMark program. DPI/event/ingest and
legacy helper constraints remain unchanged.
