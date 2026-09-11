# GrhSIM-IR Candidate: Local Frame Initialization

- Date: 2026-09-10
- Status: REJECTED
- Base GrhSIM revision: `b9931ed852532d161fea06d0ee0b5bbe07c43466`
- Root revision: `d3d2d5ed483e44f4d498465ec12d40155c84ef1d`

## Hypothesis

The emitter initialized every active compute supernode frame with `std::byte cpu_local[N]{};`. Removing the value initialization could avoid clearing a large temporary frame on each active invocation. This is a generic emitter change, independent of module names. The safety argument was that the CPU mapping verifier orders every compute operand before use, wide emitters write every output word, strings are explicitly constructed, and persistent/boundary storage remains initialized separately.

## Method

The experiment changed only `wolvrix/lib/grhsim/backend/cpu_emit.cpp` and was checked with the existing generated-model suite:

```text
make test_grhsim_cpu_emit
make xs_wolf_grhsim_ir XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=1 XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0
make xs_wolf_grhsim_ir_build_emu VM_BUILD_JOBS=32
make run_xs_wolf_grhsim_ir_emu XS_SIM_MAX_CYCLE=50000 XS_EMU_THREADS=1 XS_EMU_CPU=2 XS_WAVEFORM=0 XS_COMMIT_TRACE=0 XS_RAM_TRACE=0
```

The fixed input was XiangShan `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`, top `SimTop`, CoreMark binary SHA-256 `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`, CPU 2, and `XS_EMU_THREADS=1`. Generation, compile, and simulation were each bounded by `timeout --signal=KILL 1800s`; no timeout occurred. The generated-model test passed in 60.90 s.

## Results

| Measurement | Result |
|---|---:|
| Generation | 86.12 s, PASS |
| C++ compile (`VM_BUILD_JOBS=32`) | 466.12 s, PASS |
| 50k simulation | 305.17 s, exit 0 |
| Instructions / cycles / terminal PC | 73,580 / 49,996 / `0x80001312` |
| Generated C++ / object files | 5,749 / 5,749 |
| Generated C++ bytes / object bytes | 1,298,330,416 / 148,004,544 |

Difftest was enabled and no mismatch was reported. Relative to the 304.197 s pack-0 baseline, the runtime change was `(305.17 / 304.197 - 1) * 100 = +0.320%`, a small regression rather than a benefit. A requested `perf` profile could not run because the host has `perf_event_paranoid=4`; this is a profiling-environment limitation, not a simulation failure.

## Analysis and decision

The functional checks and all phase limits passed, but removing frame initialization did not reduce runtime. The result is rejected after one measurement; the frame allocation strategy is restored in the retained emitter. No further parameter tuning is justified without new evidence.
