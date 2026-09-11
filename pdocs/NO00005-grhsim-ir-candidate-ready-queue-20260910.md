# GrhSIM-IR Candidate: Ready-Queue Dispatcher

- Date: 2026-09-10
- Status: REJECTED / INVALID
- Source experiment: `ptmp/ready_queue_20260910/`

## Hypothesis and change

The activity-guard candidate still calls a large task switch on every convergence round. This candidate replaced that ordered task scan with a priority queue. Runtime active-word and domain-arm offsets were indexed to all owning tasks, and tasks activated after their current schedule position were deferred to the next convergence round. The generated checkpoint also retained all tasks sharing one runtime offset and passed the stable JSON round trip.

The source implementation was reverted after the behavioral check below; the validated activity-guard source remains the repository state.

## Validation

Focused emitter tests passed before the full experiment:

```text
env WOLF_ENV_SOURCED=1 make test_grhsim_cpu_emit
1/1 passed
```

Generation completed through the existing Make target:

```text
env WOLF_ENV_SOURCED=1 PYTHON=.venv/bin/python make xs_wolf_grhsim_ir \
  RUN_ID=ready_queue_20260910_regen2 \
  XS_GRHSIM_IR_BUILD=ptmp/ready_queue_20260910/flow/grhsim-ir \
  XS_LOG_DIR=ptmp/ready_queue_20260910/logs \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=ptmp/ready_queue_20260910/flow/grhsim-ir/model \
  XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0
```

The generator reported `total done 589254ms`, emitted `cpu_task_runtime_begin` and `cpu_tasks_for_runtime`, and verified the checkpoint round trip. The generated model compiled successfully with `VM_BUILD_JOBS=32`; the model and emulator timestamps imply approximately 707 seconds for the build.

The required simulation was then run through `make run_xs_wolf_grhsim_ir_emu` with one emulator thread, CPU 2, a 50,000-cycle limit, and all waveform and trace options disabled. It exited with status 2 at the first cycle:

```text
The simulation stopped. There might be some assertion failed.
Core 0: ABORT at pc = 0x0
Core-0 instrCnt = 0, cycleCnt = 0
Host time spent: 315ms
```

The log contains RTL assertion failures in `Monitor`, `LoadUnit`, `MissQueue`, `MSHR`, and related cache/load pipeline modules. This is a functional failure before any architectural instruction retires, so it is not performance evidence. The earlier single-task runtime-offset map failed with the same zero-cycle signature; retaining all sibling tasks at an offset did not repair the dispatcher.

## Decision

Reject this candidate. No timing comparison or second run is meaningful after the cycle-zero failure. The generated artifacts remain under `ptmp/ready_queue_20260910/` for audit, while the source and focused test are restored to the activity-guard candidate. Future scheduling changes must first preserve the exact first-cycle ordering and RTL assertions before performance measurements are collected.
