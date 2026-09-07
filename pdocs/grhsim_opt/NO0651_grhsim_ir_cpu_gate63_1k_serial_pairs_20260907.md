# Gate63 1k serial pairs

- Date: 2026-09-07
- Build: [NO0650](./NO0650_grhsim_ir_cpu_gate63_full_o3_build_20260907.md).

Four ordinary-binary runs used the existing make run_xs_wolf_grhsim_ir_emu
target. Each exited 0 before the next started. Configuration: 1000 cycles,
coremark-2-iteration.bin, NEMU difftest, seed 0, waveform off, progress every
1000 cycles. No build or other simulation overlapped these measurements.

| Execution order | Gate62 host ms | Gate63 host ms | Reduction |
| --- | ---: | ---: | ---: |
| Gate62 then gate63 | 18487 | 15075 | 18.456% |
| Gate63 then gate62 | 18094 | 14553 | 19.570% |

All four one-sample progress and three-record terminal results are identical
after removing only progress host_ms and terminal ANSI escapes: 3 instructions,
commit PC 0x10000008, trap/limit PC 0, cycleCnt 996, guest 1001,
IPC 0.003012. NEMU difftest enabled at first commit and reported no mismatch.
Sample extraction requires `[EMU_PROGRESS] host_cycles=`, excluding the
separate progress-enabled banner. Comparison evidence:
ptmp/grhsim_gate63_serial_pairs_identity.log.

Logs in ptmp: grhsim_gate63_pair1_base_1000.log,
grhsim_gate63_pair1_candidate_1000.log,
grhsim_gate63_pair2_candidate_1000.log and
grhsim_gate63_pair2_base_1000.log.

This establishes a short-window improvement for the private stable-history
skip candidate, not the final workload speedup. The 1k window has only three
retired instructions and cannot prove later CoreMark behavior or legacy+5%.
After both pairs completed, the same ordinary candidate started its actual
10000-cycle run through the existing Makefile target. Log:
ptmp/grhsim_gate63_o3_10000.log. Its terminal result and candidate 50k remain
pending. Gate62 is preserved unchanged.
