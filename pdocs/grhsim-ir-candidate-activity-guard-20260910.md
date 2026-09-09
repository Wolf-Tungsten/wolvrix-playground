# GrhSIM-IR Candidate: Activity-Driven Task Guard

- Date: 2026-09-10
- Status: VALIDATED / CURRENT BEST, goal target still unmet
- Root source before archival docs: `d3d2d5ed483e44f4d498465ec12d40155c84ef1d`
- GrhSIM source commit: `c3dfad0cc19e29943b65d815ae180fdbd42f1bee`

## Hypothesis and change

Pack 0 schedules 5,595 task calls per convergence round even though 5,081 task files contain activity-word logic. For `ActivityDrivenCompute` tasks, the emitter now wraps the call in a generic OR of the task partition's active-word bytes:

```cpp
if (cpu_flags[word0] || cpu_flags[word1] || ...) cpu_task_N();
```

`DomainGatedCommit` keeps its existing domain-arm guard and `AlwaysScanCommit` remains unconditional. The guard reads the same runtime activity bytes consumed by the task body, so it cannot suppress a task whose scheduled word is active. No module-name matching or frozen IR/pass change is involved.

## Method

The focused generated-shape and sanitizer suite passed in 58.17 s:

```text
make test_grhsim_cpu_emit
make xs_wolf_grhsim_ir RUN_ID=activity_guard_20260910 XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=1 XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0
make xs_wolf_grhsim_ir_build_emu VM_BUILD_JOBS=32
make run_xs_wolf_grhsim_ir_emu RUN_ID=activity_guard_20260910 XS_SIM_MAX_CYCLE=50000 XS_EMU_THREADS=1 XS_EMU_CPU=2 XS_WAVEFORM=0 XS_COMMIT_TRACE=0 XS_RAM_TRACE=0
make run_xs_wolf_grhsim_ir_emu RUN_ID=activity_guard_20260910_rerun XS_SIM_MAX_CYCLE=50000 XS_EMU_THREADS=1 XS_EMU_CPU=2 XS_WAVEFORM=0 XS_COMMIT_TRACE=0 XS_RAM_TRACE=0
```

Both runs used XiangShan revision `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`, top `SimTop`, CoreMark binary SHA-256 `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`, CPU 2, `XS_EMU_THREADS=1`, 50,000 cycles, `DIFFTEST` enabled, and waveform/trace disabled. Generation took 87.709 s and completed a stable JSON round trip. The C++ build completed in approximately 515.7 s from the generated model timestamp to the emu artifact timestamp, with `VM_BUILD_JOBS=32`; both phases were below 1,800 s.

## Results

| Run | Simulation (s) | Exit | Instructions | `cycleCnt` | Terminal PC |
|---|---:|---:|---:|---:|---|
| first | 289.305 | 0 | 73,580 | 49,996 | `0x80001312` |
| independent rerun | 280.093 | 0 | 73,580 | 49,996 | `0x80001312` |
| mean | 284.699 | 0 | same | same | same |

Both runs reported difftest initialization and no mismatch. The first run improved on pack 0 by 4.896%; the rerun improved by 7.924%; the mean improvement is 6.410%, calculated against 304.197 s. The mean remains 13.794x the 20.640 s gsim reference and therefore does not meet the approximately 40 s target.

The emitted model has 5,749 C++ files (5,595 task files), 1,298,508,408 C++ bytes, and 148,141,824 object bytes. The evaluator contains guarded calls for 5,594 of 5,595 tasks; the remaining task is an unconditional commit scan. The IR counts remain 4,530,736 operations, 4,285,682 values, and 508,487 states.

## Analysis, limits, and decision

The exact generated-shape assertion reconstructs active-word offsets from `CpuDataLayout` and checks every activity task, while the existing sanitizer suite covers execution behavior. The two full runs agree on architectural checkpoints; their 3.2% spread shows ordinary host variance, so the mean is the comparison value. The guard is retained as the current best validated candidate, but it is not marked accepted because the absolute target remains far away. A future candidate must address the remaining task-call and generated-code costs without weakening the same equivalence checks.
