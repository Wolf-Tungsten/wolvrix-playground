# NO0568 CPU first-commit and legacy cold-start comparison

## Actual-Call Runtime Result

The gate53 actual-call model from [NO0567](./NO0567_grhsim_ir_cpu_gate53_calls_runtime_20260906.md) completed the default-stack 1,000-cycle Makefile run with exit 0.

- Command entry: `make run_xs_wolf_grhsim_ir_emu`, `XS_SIM_MAX_CYCLE=1000`, `XS_WAVEFORM=0`, `XS_PROGRESS_EVERY_CYCLES=100`, `RUN_ID=gate53_smoke1000`.
- Logs: `ptmp/grhsim_gate53_smoke1000.log`, `ptmp/xs_wolf_grhsim_gate53_smoke1000.log`.
- RAM/image and NEMU initialized. The runtime printed `The first instruction of core 0 has commited. Difftest enabled.`
- At cycle 600: `instr=1`, `commit_pc=0x10000000`.
- At cycles 700 through 1,000: `instr=3`, `commit_pc=0x10000008`.
- Final counters: `instrCnt=3`, `cycleCnt=996`, guest cycles 1,001. No assertion or NEMU discrepancy was reported. Host time: 382,257 ms, with the new model built at O0.

## Existing Legacy Executable Comparison

After the IR process exited, ran the existing legacy executable through `make run_xs_wolf_grhsim_emu`, explicitly selecting `XS_GRHSIM_BUILD=build/xs/grhsim` with the same image, reference model, seed, 1,000-cycle limit, waveform setting and progress interval. No legacy rebuild or source change was made.

Logs: `ptmp/grhsim_gate53_legacy1000.log`, `ptmp/xs_wolf_grhsim_gate53_legacy1000.log`. Exit 0.

All ten progress samples match in host/model cycle, instruction count, commit PC and trap PC:

| Cycles | Both Routes: Instructions | Both Routes: Commit PC |
| --- | --- | --- |
| 100-500 | 0 | 0x0 |
| 600 | 1 | 0x10000000 |
| 700-1000 | 3 | 0x10000008 |

Both routes finish with `instrCnt=3`, `cycleCnt=996`, guest cycles 1,001. The initial lack of retirement is therefore consistent with this legacy cold-start window, not evidence by itself of a stuck IR backend. This comparison covers sampled progress and the first three instructions; it is not a full-state/waveform equivalence proof.

The existing optimized legacy executable took 734 ms. Comparing that against a new O0 model is not the planned matched-configuration performance gate; the large observed gap makes an optimized new-model build necessary before long runs. Preserve the actual O0 label and do not report performance parity.

## Remaining Work

- Complete general array initialization (literal/fill ranges, random and readmem semantics), which is still approximated by zero initialization in the emitter.
- Build the new model with optimization and verify the flags actually rebuild its objects. The current generated Makefile does not track CXXFLAGS changes as dependencies; use a fresh generated directory or implement flag tracking before claiming an O3 build.
- Reduce the close-to-limit O0 task_61 stack footprint if needed; inspect legacy reusable scratch storage and static string-constant handling when addressing runtime allocation/data movement.
- Require real 10k and 50k XiangShan CoreMark/NEMU runs, HDLBits/multiclock gates and the plan's performance comparison. This 1,000-cycle cold-start gate does not complete the objective.
