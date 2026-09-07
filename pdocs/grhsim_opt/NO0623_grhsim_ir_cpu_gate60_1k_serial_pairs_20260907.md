# Gate60 1k serial pairs

- Date: 2026-09-07
- Build: [NO0622](./NO0622_grhsim_ir_cpu_gate60_full_o3_build_20260907.md).

## Measurements

All four runs used the existing run_xs_wolf_grhsim_ir_emu Makefile target,
1000 cycles, coremark-2-iteration.bin, NEMU difftest, seed 0, waveform off and
1000-cycle progress. No build or other simulation ran alongside them. Each
command exited 0 before starting the next.

| Execution order | Gate59 host ms | Gate60 host ms | Reduction |
| --- | ---: | ---: | ---: |
| Gate59 then gate60 | 26283 | 21547 | 18.019% |
| Gate60 then gate59 | 26187 | 21899 | 16.375% |

Logs in ptmp: grhsim_gate60_pair1_base_1000.log,
grhsim_gate60_pair1_candidate_1000.log, grhsim_gate60_pair2_candidate_1000.log,
grhsim_gate60_pair2_base_1000.log.

All runs have exactly the 1000-cycle sample with 3 instructions,
commit_pc=0x10000008, trap_pc=0. Terminal records are cycleCnt=996,
IPC=0.003012, guest=1001 and the same cycle-limit exit. Pairwise progress and
three terminal records compare identically after removing ANSI and host_ms.
NEMU was enabled after first commit, with no mismatch.

## Conclusion and Boundary

Moving immutable strings to use sites produces a repeatable ordinary-binary
short-window improvement of 16.4-18.0%, without changing DPI/event policy.
Keep both measurements rather than selecting the faster one. The candidate
does not eliminate the remaining compute/commit cost and this is not a 50k
performance report or proof of the legacy+5% threshold.

After all pairs completed, an independent candidate 10k run was started through
the same Makefile route. Log: ptmp/grhsim_gate60_o3_10000.log. Its terminal result
is pending at this record. Gate59's 50k proof does not transfer to gate60.
