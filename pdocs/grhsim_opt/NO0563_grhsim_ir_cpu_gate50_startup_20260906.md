# NO0563 Gate50 full-model startup verification

## Generation

After the storage repair in [NO0562](./NO0562_grhsim_ir_cpu_startup_storage_20260906.md), `make py_install` completed successfully. Log: `ptmp/grhsim_cpu_startup_install.log`.

`make xs_wolf_grhsim_ir` generated a new model in `ptmp/xs_emit_make_gate50` from `build/xs/grhsim/wolvrix_xs_pre_reg_to_mem.json`. It completed lowering, every CPU mapping pass, C++ emission, fresh checkpoint load and stable round-trip, exit 0. Generation took about 86 seconds.

- Log: `ptmp/grhsim_gate50_generation.log`.
- Checkpoints: `ptmp/xs_ir_gate50.json`, `ptmp/xs_ir_gate50_roundtrip.json`.
- The old gate49 model was not overwritten.

## Stack Evidence During Build

`make xs_wolf_grhsim_ir_build_emu` uses two jobs and `GRHSIM_MODEL_CXXFLAGS='-std=c++20 -O0'`; model compiler is clang++. Log: `ptmp/grhsim_gate50_full_build.log`.

All 170 init translation units compiled. `objdump -d -C ptmp/xs_emit_make_gate50/grhsim_SimTop_init_59.o` shows the entry reserves `0x2870` bytes (10,352 bytes), down from gate49's `0x96c250` bytes (9,880,144 bytes). The large aggregate-init stack temporary is absent at O0, without relying on optimization or a raised stack limit.

At this record's initial creation, task compilation is still running. Compilation of the init files and source inspection of local string bindings are not evidence of successful full-model execution. Link and runtime results will be appended separately.

## Full Build Result

The same build completed with exit 0: driver, all 170 init files and all 514 task files compiled, `libgrhsim_SimTop.a` was archived (about 2.4 GiB), and difftest linked `build/xs/grhsim-ir/emu/grhsim-compile/emu` (about 1.2 GiB). No compiler optimization increase or manual build command was needed.

## Default-Stack Startup Result

`make run_xs_wolf_grhsim_ir_emu WOLF_ENV_SOURCED=1 XS_SIM_MAX_CYCLE=100 XS_WAVEFORM=0 XS_WAVEFORM_PATH= XS_LOG_DIR="$PWD/ptmp" XS_PROGRESS_EVERY_CYCLES=10 RUN_ID=gate50_smoke100 TMPDIR="$PWD/ptmp/cpu_emit_test_tmp"` completed with exit 0.

- Wrapper log: `ptmp/grhsim_gate50_smoke100.log`.
- Runtime log: `ptmp/xs_wolf_grhsim_gate50_smoke100.log`.
- Default stack was 8192 KiB (`ulimit -s`); runtime used the normal `stdbuf` prefix, with no `prlimit` override.
- Passed initialization and the previously failing task_61 string assignments, then reported progress through `host_cycles=100 model_cycles=100`.
- Terminated at the requested cycle limit, guest cycles 101, host time 51,858 ms. This is a startup measurement at O0, not a performance-parity result.
- Every progress record has `instr=0`, `commit_pc=0x0`, `trap_pc=0x0`; the final difftest counters also remain zero.

## Functional Boundary and Next Work

The two startup crashes are resolved for this full-model check. The target of real XiangShan CoreMark 50k remains incomplete: `compute()` still skips `core.dpi.call` and `core.system.task`, and arrays still have zero-only initialization. A longer cycle-limit run in this condition cannot demonstrate CoreMark or NEMU parity and was not started.

Next implement actual DPI/system-task execution without changing their compute-side classification or optional event metadata. Consume the declared `DpiSignature`, preserve conditional results in boundary slots, propagate changed return/output/inout results, and sample the event history using the existing schedule contract. Reference legacy's explicit call guard and typed ABI emission; do not infer purity or removability from absence of a return value. Add focused external-call tests before another full-model build, then close general array initialization and require real instruction progress before the 10k/50k functional and performance gates.
