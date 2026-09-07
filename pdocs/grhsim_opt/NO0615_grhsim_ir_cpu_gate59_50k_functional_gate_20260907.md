# Gate59 50k functional gate

- Date: 2026-09-07
- Runbook: [NO0613](./NO0613_grhsim_ir_cpu_gate59_50k_runbook_20260907.md).
- Intermediate checkpoint: [NO0614](./NO0614_grhsim_ir_cpu_gate59_20k_checkpoint_20260907.md).
- Status: actual gate59 50k functional window passed; performance comparison pending.

## Terminal Evidence

The original make run_xs_wolf_grhsim_ir_emu process ran the complete 50000-cycle
window and exited 0. Log: ptmp/grhsim_gate59_o3_50000.log.

| Field | Result |
| --- | --- |
| Final host/model cycle sample | 50000 / 50000 |
| instrCnt | 73580 |
| cycleCnt / guest cycles | 49996 / 50001 |
| Final sampled commit PC | 0x800012f8 |
| Cycle-limit/trap PC | 0x80001312 |
| IPC | 1.471718 |
| Seed | 0 |
| Host time | 1371764 ms |
| Difftest | Enabled after first instruction; no mismatch |
| Process exit | 0, cycle limit |

All 50 strictly ordered thousand-cycle records match the existing serial legacy
50k reference after excluding host_ms and terminal control sequences. Progress
was extracted by marker, including records preceded by guest UART text.
All three terminal functional lines also match: exit reason/PC, counters/IPC,
and seed/guest cycles. This is not only an endpoint-PC comparison.

The cpu_emit.cpp, cpu_schedule.cpp and executable SHA-256 values were rechecked
after completion and exactly match the runbook. No implementation changes,
rebuild, restart, profiling probe or parallel simulation occurred during the run.

## Scope and Performance

Gate59 now has its own actual 50k correctness evidence; it does not inherit the
gate57 result. Cycle-limit success is not complete CoreMark program termination.
The runtime is still far from the required legacy +5% target, but a fresh serial
legacy measurement is needed for the current denominator.

After IR exited, the existing legacy binary was started through the run-only
Makefile target with the same image/NEMU/seed/limit/waveform/progress settings.
Log: ptmp/grhsim_legacy_50000_serial_gate59.log. It is still running at this
record. No build overlaps that measurement. Overall goal remains active.
