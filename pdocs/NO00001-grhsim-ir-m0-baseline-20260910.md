# GrhSIM-IR XiangShan CoreMark 50k M0 Baseline

- Date: 2026-09-10
- Status: BASELINE / VALIDATED
- Root revision: `d3d2d5ed483e44f4d498465ec12d40155c84ef1d`
- GrhSIM submodule revision: `b9931ed852532d161fea06d0ee0b5bbe07c43466`
- XiangShan revision: `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`
- Input: `ready-to-run/coremark-2-iteration.bin`, SHA-256 `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`
- Top: `SimTop`; cycles: 50,000; `DIFFTEST` enabled; waveform, commit trace, and RAM trace disabled

## Method

Both models used the same CoreMark image, top, cycle limit, and NEMU reference. The runs used CPU 2 and `XS_EMU_THREADS=1`; `nproc` was 32. Build and run phases were invoked through the repository Makefile targets:

```text
make xs_gsim_emu XS_VM_BUILD_JOBS=32
make run_xs_gsim_emu XS_SIM_MAX_CYCLE=50000 XS_EMU_THREADS=1 XS_EMU_CPU=2 XS_WAVEFORM=0 XS_COMMIT_TRACE=0 XS_RAM_TRACE=0
make xs_wolf_grhsim_ir XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=1 XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0
make xs_wolf_grhsim_ir_build_emu VM_BUILD_JOBS=16 XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0
make run_xs_wolf_grhsim_ir_emu XS_SIM_MAX_CYCLE=50000 XS_EMU_THREADS=1 XS_EMU_CPU=2 XS_WAVEFORM=0 XS_COMMIT_TRACE=0 XS_RAM_TRACE=0
```

The GrhSIM-IR generation interval was 87.993 s and the C++ build interval was 502.33 s. Both were below the 1,800 s hard limit. The gsim emitter reported 762.815 s for its generation timer and wrote 329 C++ translation units; its Makefile build completed successfully with 32 jobs. Each model was run once for this baseline.

## Results

| Model | Generation (s) | Compile (s) | Simulation (s) | Exit | Instructions | `cycleCnt` | Terminal PC |
|---|---:|---:|---:|---:|---:|---:|---|
| gsim | 762.815 (emitter timer) | PASS, 32 jobs | 20.640 | 0 | 73,584 | 49,998 | `0x8000131e` |
| GrhSIM-IR pack 0 | 87.993 | 502.33 | 304.197 | 0 | 73,580 | 49,996 | `0x80001312` |

Both logs reported difftest initialization and completed without a mismatch. The GrhSIM-IR run was 14.738x the gsim simulation time, or 1,373.7% slower using `(304.197 / 20.640 - 1) * 100`.

The fixed GrhSIM-IR model contains 4,530,736 operations, 4,285,682 values, 508,487 states, 5,749 generated C++ files, and 5,595 scheduled task files. A source audit found active-word logic in 5,081 task files, so most scheduled calls enter a task whose first work is an activity-byte test. The evaluator calls all 5,595 tasks on every convergence round in pack 0. This is the hotspot evidence used for the M1 candidates.

## Analysis and limits

The baseline establishes equivalent architectural checkpoints but not equal instruction counts: the two backends stop at the same 50,000 guest-cycle limit and expose different terminal cycle accounting. The repeated timing noise of the host was not characterized at M0, so later candidates use the same CPU binding and at least one independent rerun. The measured GrhSIM-IR runtime is far above the approximately 40 s target; M0 therefore does not satisfy the performance goal.

## Decision

Keep this run as the fixed comparison point. Candidate experiments must preserve the input identity and the single-threaded simulation settings above, and must not modify frozen GRH IR/passes, XiangShan sources, or tests.
