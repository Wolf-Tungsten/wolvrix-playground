# Gate62 10k functional gate

- Date: 2026-09-07
- Serial pairs: [NO0639](./NO0639_grhsim_ir_cpu_gate62_1k_serial_pairs_20260907.md).

The candidate's actual 10000-cycle run through the existing
run_xs_wolf_grhsim_ir_emu Makefile target exited 0. Configuration remains
coremark-2-iteration.bin, NEMU difftest, seed 0, waveform off and progress
every 1000 cycles. No build or other simulation ran concurrently.

| Metric | Result |
| --- | ---: |
| Host time | 175061 ms |
| Instructions | 458 |
| cycleCnt / guest cycles | 9996 / 10001 |
| IPC | 0.045818 |
| Sampled commit PC | 0x80001cdc |
| Trap / limit PC | 0x800027c6 |

All ten ordered thousand-cycle samples match the first ten in
ptmp/grhsim_legacy_50000_serial_gate59.log after removing host_ms, including
markers preceded by UART output. Three terminal records match
ptmp/grhsim_gate61_o3_10000.log after ANSI removal. NEMU was enabled at first
commit and reported no mismatch. Log: ptmp/grhsim_gate62_o3_10000.log.

The ordinary executable and emitter fingerprints are unchanged:

```text
emu          0b29bcee26710ee4de444743979228ac9eb761eae579f45f21fb24346f177e1a
cpu_emit.cpp 88a9605dc090737b48a27a9b8517c021f07376933f7df1592f8915c5b01ff5fb
```

The prior gate61 10k time was 178709 ms, but those separate runs are not a new
paired performance experiment. This result proves the candidate's own 10k
functional window, not its 50k window or the plan's legacy+5% requirement.
The candidate is retained for true-change activation; no substantial speedup
is claimed from the sub-percent 1k pairs. Proceed to its own actual 50k and a
fresh serial legacy denominator, preserving all earlier references.
