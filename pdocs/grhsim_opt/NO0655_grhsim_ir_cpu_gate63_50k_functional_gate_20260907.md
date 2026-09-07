# Gate63 50k functional gate

- Date: 2026-09-07
- Runbook: [NO0653](./NO0653_grhsim_ir_cpu_gate63_50k_runbook_20260907.md).
- Checkpoint and pause request: [NO0654](./NO0654_grhsim_ir_cpu_gate63_20k_checkpoint_20260907.md).

The original gate63 ordinary O3 process completed its actual 50000-cycle run
with exit 0. It was not restarted, rebuilt, instrumented or shortened, and no
other build or simulation overlapped it. Log: ptmp/grhsim_gate63_o3_50000.log.

| Metric | Result |
| --- | ---: |
| Host time | 879581 ms |
| Retired instructions | 73580 |
| cycleCnt / guest cycles | 49996 / 50001 |
| IPC | 1.471718 |
| Final sampled commit PC | 0x800012f8 |
| Trap / limit PC | 0x80001312 |

Exactly fifty strictly ordered thousand-cycle progress samples and three
terminal records were checked. All match the preserved legacy 50k reference
ptmp/grhsim_legacy_50000_serial_gate62.log after removing only progress host_ms,
UART prefixes and terminal ANSI escapes. Diff exited 0; the empty report is
ptmp/grhsim_gate63_50k_reference_diff.log. The enabled banner is not a sample.
NEMU was enabled at first commit and no mismatch, assertion failure or abort
was reported.

The executable remains
25980aaec27d340e8356180d96c109656565e3392d50aaeb0fd9c7ab8b51d56c;
cpu_emit.cpp remains
4aca24b14230bbacab8963187b93d56d1c46a17cefd6713d93f5dfc9ea0ad66a;
cpu_schedule.cpp remains
7f7f253903d2c7ffe6a79fc7f8f19cba5f353a5a80a00d107932ba5f1b53fd64.

After the IR process reached its successful terminal result, the paired
ordinary legacy 50k run started through make run_xs_wolf_grhsim_emu with
XS_GRHSIM_BUILD=build/xs/grhsim and the same cycle/image/NEMU/seed/waveform/
progress settings. Log: ptmp/grhsim_legacy_50000_serial_gate63.log.
Its result and the actual full-window performance ratio are still pending.

This proves the candidate's 50k-cycle functional window, not completion of
the entire CoreMark program or the plan's legacy+5% performance requirement.
As requested, finish only the paired legacy measurement, report the speed gap
and stop; no further optimization, profiling or build is to start.
