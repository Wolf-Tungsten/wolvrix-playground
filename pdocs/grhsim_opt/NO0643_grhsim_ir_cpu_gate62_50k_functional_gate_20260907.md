# Gate62 50k functional gate

- Date: 2026-09-07
- Runbook: [NO0641](./NO0641_grhsim_ir_cpu_gate62_50k_runbook_20260907.md).
- Intermediate checkpoint: [NO0642](./NO0642_grhsim_ir_cpu_gate62_20k_checkpoint_20260907.md).
- Result: the candidate's actual 50000-cycle functional window passed.

The original make run_xs_wolf_grhsim_ir_emu process completed with exit 0,
without rebuilding, changing the 50000-cycle limit, or running another build
or simulation concurrently. Configuration remained the ordinary O3 candidate,
CoreMark image, NEMU difftest, seed 0, waveform off and thousand-cycle progress.
Log: ptmp/grhsim_gate62_o3_50000.log.

| Metric | Result |
| --- | ---: |
| Host time | 1024849 ms |
| Retired instructions | 73580 |
| cycleCnt / guest cycles | 49996 / 50001 |
| IPC | 1.471718 |
| Final sampled commit PC | 0x800012f8 |
| Trap / limit PC | 0x80001312 |

Exactly 50 strictly ordered thousand-cycle progress records match
ptmp/grhsim_legacy_50000_serial_gate59.log after excluding host_ms. Three
terminal records (limit reason/PC, counters/IPC, seed/guest cycles) also match
after ANSI removal. Extraction includes markers preceded by UART text, and
excludes the progress-enabled banner. NEMU was enabled at first commit and
reported no mismatch.

Post-run fingerprints remain unchanged:

```text
gate62 emu   0b29bcee26710ee4de444743979228ac9eb761eae579f45f21fb24346f177e1a
cpu_emit.cpp 88a9605dc090737b48a27a9b8517c021f07376933f7df1592f8915c5b01ff5fb
legacy emu   c211cf9435d867bb4bbda6df73173389106fa5255a3f8af7635d9879221a88cb
```

After the IR process terminated, the existing run_xs_wolf_grhsim_emu Makefile
target started the fresh serial legacy 50000-cycle measurement, log
ptmp/grhsim_legacy_50000_serial_gate62.log. Its terminal result and the paired
performance ratio are pending. The historical reference is used above only
for functional checking, not as the new performance denominator.

This verifies the requested 50k-cycle CoreMark simulation window for gate62;
it is not completion of the entire CoreMark program. The full activity-plan
goal is still incomplete: the legacy+5% performance gate is not established,
and remaining implementation/acceptance gaps must not be hidden by this pass.
