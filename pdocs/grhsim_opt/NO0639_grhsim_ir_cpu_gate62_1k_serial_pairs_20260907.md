# Gate62 1k serial pairs

- Date: 2026-09-07
- Build: [NO0638](./NO0638_grhsim_ir_cpu_gate62_full_o3_build_20260907.md).

Four ordinary-binary runs used make run_xs_wolf_grhsim_ir_emu, each ending
with exit 0 before the next started. Configuration: 1000 cycles,
coremark-2-iteration.bin, NEMU difftest, seed 0, waveform off and progress
every 1000 cycles. No build or other simulation overlapped these measurements.

| Execution order | Gate61 host ms | Gate62 host ms | Reduction |
| --- | ---: | ---: | ---: |
| Gate61 then gate62 | 18655 | 18632 | 0.123% |
| Gate62 then gate61 | 18951 | 18880 | 0.375% |

All four runs have identical one-sample progress and three-record terminal
data after removing host_ms and ANSI: 3 instructions, commit PC=0x10000008,
trap/limit PC=0, cycleCnt=996, guest=1001, IPC=0.003012. NEMU was enabled
at first commit and reported no mismatch. Progress extraction selects
`[EMU_PROGRESS] host_cycles=`; the separate progress-enabled banner is not
a sample.

Logs in ptmp: grhsim_gate62_pair1_base_1000.log,
grhsim_gate62_pair1_candidate_1000.log,
grhsim_gate62_pair2_candidate_1000.log and
grhsim_gate62_pair2_base_1000.log.

The differences are too small to establish a meaningful speedup. There is no
visible short-window regression in these pairs. Retain the candidate for the
plan's true-change activation invariant, without calling it a measured
performance improvement. The small 1k window has only three retired instructions
and cannot establish behavior or performance in the later CoreMark workload.

After both pairs ended, the same Makefile route started the candidate's own
10000-cycle run, log ptmp/grhsim_gate62_o3_10000.log. Its terminal result is
pending. Candidate 50k and final legacy+5% remain unproven; gate61 remains intact.
