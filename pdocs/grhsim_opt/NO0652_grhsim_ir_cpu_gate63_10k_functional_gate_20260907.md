# Gate63 10k functional gate

- Date: 2026-09-07
- Short-window gate: [NO0651](./NO0651_grhsim_ir_cpu_gate63_1k_serial_pairs_20260907.md).

The same ordinary O3 candidate completed an actual 10000-cycle run through
the existing Makefile route with exit 0. No build or other simulation ran
alongside it. Log: ptmp/grhsim_gate63_o3_10000.log.

```sh
make --no-print-directory run_xs_wolf_grhsim_ir_emu WOLF_ENV_SOURCED=1 \
  XS_GRHSIM_IR_BUILD=ptmp/xs_gate63 XS_SIM_MAX_CYCLE=10000 XS_WAVEFORM=0 \
  XS_PROGRESS_EVERY_CYCLES=1000 XS_LOG_DIR="$PWD/ptmp" \
  RUN_ID=20260907_gate63_o3_10000 TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" \
  > ptmp/grhsim_gate63_o3_10000.log 2>&1
```

| Metric | Result |
| --- | ---: |
| Host time | 143683 ms |
| Retired instructions | 458 |
| cycleCnt / guest cycles | 9996 / 10001 |
| IPC | 0.045818 |
| Commit PC | 0x80001cdc |
| Trap / limit PC | 0x800027c6 |

All ten ordered 1000-cycle progress samples and three terminal records match
the ordinary gate62 10k reference, ptmp/grhsim_gate62_o3_10000.log. Extraction
removes the UART prefix before `[EMU_PROGRESS] host_cycles=` and only its
host_ms field; terminal comparison strips ANSI escapes. The separate enabled
banner is excluded. Sample count, order and terminal count were checked
explicitly. The diff exited 0; its empty report is retained at
ptmp/grhsim_gate63_10k_functional_diff.log. NEMU was enabled at first commit
and no mismatch, assertion failure or abort was reported.

Candidate executable remains
25980aaec27d340e8356180d96c109656565e3392d50aaeb0fd9c7ab8b51d56c;
gate62 remains 0b29bcee26710ee4de444743979228ac9eb761eae579f45f21fb24346f177e1a.
Emitter and schedule fingerprints still match NO0649. No probes or source
changes were introduced during the build/run gates.

This is a 10k-cycle functional window, not CoreMark program completion or a
50k gate. No fresh paired 10k baseline was measured, so the new host time is
not presented as a controlled 10k performance ratio. The controlled 1k pairs
remain the only new comparative timing evidence.

All build and simulation sessions are terminal. Preserve gate63 for the next
actual 50k run, then measure a fresh serial legacy denominator with the same
functional comparisons. Candidate 50k and the final legacy+5% gate remain
unproven. Wide arithmetic/shift true-change activation and the complete plan
acceptance audit are still pending; this record does not close the goal.
