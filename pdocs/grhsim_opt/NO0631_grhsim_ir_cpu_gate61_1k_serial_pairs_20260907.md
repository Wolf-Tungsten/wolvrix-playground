# Gate61 1k serial pairs

- Date: 2026-09-07
- Build: [NO0630](./NO0630_grhsim_ir_cpu_gate61_full_o3_build_20260907.md).

All four ordinary-binary runs used the existing run_xs_wolf_grhsim_ir_emu
Makefile target with 1000 cycles, coremark-2-iteration.bin, NEMU difftest,
seed 0, waveform off and 1000-cycle progress. Each exited 0 before the next
started. No build or other simulation overlapped these measurements.

| Execution order | Gate60 host ms | Gate61 host ms | Reduction |
| --- | ---: | ---: | ---: |
| Gate60 then gate61 | 21910 | 18958 | 13.473% |
| Gate61 then gate60 | 21643 | 19153 | 11.505% |

Logs in ptmp: grhsim_gate61_pair1_base_1000.log,
grhsim_gate61_pair1_candidate_1000.log, grhsim_gate61_pair2_candidate_1000.log
and grhsim_gate61_pair2_base_1000.log.

The 1000-cycle progress record and three terminal records in each pair compare
identically after removing host_ms and ANSI: 3 instructions, commit PC=0x10000008,
trap/limit PC=0, cycleCnt=996, guest=1001, IPC=0.003012. NEMU was enabled at first
commit and no mismatch occurred. Implementation and both executable fingerprints
remain unchanged from the build and restored baseline.

The history scan has a repeatable short-window benefit of 11.5-13.5% over gate60;
retain both measurements. This does not establish 50k performance or the final
legacy+5% gate. After the pairs completed, the same Makefile route started an
independent gate61 10k run, log ptmp/grhsim_gate61_o3_10000.log. Its terminal
result is pending at this record, and gate61 has no actual 50k proof yet.
