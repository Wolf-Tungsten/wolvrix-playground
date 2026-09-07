# Gate63 50k runbook

- Date: 2026-09-07
- Precondition: [NO0652](./NO0652_grhsim_ir_cpu_gate63_10k_functional_gate_20260907.md).
- Status: actual 50k started; terminal result pending.

Use the same independently built ordinary O3 binary, ptmp/xs_gate63/emu/emu,
already verified at 10k. SHA-256:
25980aaec27d340e8356180d96c109656565e3392d50aaeb0fd9c7ab8b51d56c.
Keep the source and binary unchanged, with no probes, concurrent build or
simulation, and no reduction of the requested cycle limit.

```sh
make --no-print-directory run_xs_wolf_grhsim_ir_emu WOLF_ENV_SOURCED=1 \
  XS_GRHSIM_IR_BUILD=ptmp/xs_gate63 XS_SIM_MAX_CYCLE=50000 \
  XS_WAVEFORM=0 XS_WAVEFORM_PATH= XS_LOG_DIR="$PWD/ptmp" \
  XS_PROGRESS_EVERY_CYCLES=1000 TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" \
  RUN_ID=gate63_o3_50000 > ptmp/grhsim_gate63_o3_50000.log 2>&1
```

Compare all fifty ordered progress samples with the retained legacy reference,
extracting `[EMU_PROGRESS] host_cycles=` after any UART prefix and excluding
only host_ms. Compare the three terminal records after stripping ANSI. Expected
50k terminal: 73580 instructions, cycleCnt 49996, guest 50001, IPC 1.471718,
sampled commit PC 0x800012f8 and trap/limit PC 0x80001312. Partial samples
are checkpoints only; poll the original process until authoritative termination.

After IR exits, run make run_xs_wolf_grhsim_emu with
XS_GRHSIM_BUILD=build/xs/grhsim and the same cycle/image/NEMU/seed/waveform/
progress parameters, writing ptmp/grhsim_legacy_50000_serial_gate63.log.
The existing ordinary legacy executable fingerprint is
c211cf9435d867bb4bbda6df73173389106fa5255a3f8af7635d9879221a88cb.
Only the new terminal measurements establish the full-window IR/legacy ratio.

Gate62 stays preserved at
0b29bcee26710ee4de444743979228ac9eb761eae579f45f21fb24346f177e1a.
Current cpu_emit.cpp and cpu_schedule.cpp fingerprints were rechecked against
NO0649 before starting. DPI/event/ingest semantics and helper ownership remain
unchanged. This is not a functional or performance gate result; final 50k
legacy+5% acceptance and the broader plan remain open.
