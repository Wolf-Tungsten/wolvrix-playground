# GrhSIM-IR Candidate: Target Batch Packing

- Date: 2026-09-09
- Status: REJECTED / SCREENING INCOMPLETE
- Root revision: `d3d2d5ed483e44f4d498465ec12d40155c84ef1d`
- GrhSIM source revision: `b9931ed852532d161fea06d0ee0b5bbe07c43466`

## Hypothesis

The default pack-0 emitter creates one task translation unit for nearly every scheduled task. Setting `XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=64` should reduce translation-unit count and C++ compile/link overhead without changing IR semantics or runtime scheduling.

## Method and screening evidence

The candidate used the normal Makefile workflows and the fixed XiangShan/CoreMark input:

```text
make xs_wolf_grhsim_ir XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=64
make xs_wolf_grhsim_ir_build_emu VM_BUILD_JOBS=16 XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=64
```

Generation from the fixed flat GRH completed in 594.922 s, below the 1,800 s limit. It emitted 680 C++ files totaling 1,264,304,419 bytes, compared with 5,749 files and 1,298,411,798 bytes for pack 0. The build attempt produced 169 object files before it was stopped without an emu executable; no complete compile timing, simulation, exit status, or difftest result exists. Because no executable was produced, this candidate has no valid performance comparison.

## Analysis and decision

The structural reduction is real: the target count changes the source-file count by 88.2% and source bytes by 2.6%. It did not, however, pass the required compile-and-run screening gate. The incomplete build is recorded as a failed screening result, not as a timeout or a speed claim. The direction is rejected for this iteration; revisiting it requires a bounded build that completes and an equivalent 50k run.
