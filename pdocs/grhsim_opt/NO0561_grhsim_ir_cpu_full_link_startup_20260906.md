# NO0561 Full CPU model link and startup diagnostics

## Makefile Integration

- Added `xs_wolf_grhsim_ir_build_emu` to build/link an already generated model. The existing `xs_wolf_grhsim_ir_emu` still generates first, then invokes the same build recipe. This avoids re-emitting into nonempty directories or manually rebuilding the difftest commands.
- Added `run_xs_wolf_grhsim_ir_emu`, delegating the existing CoreMark/NEMU run recipe with the IR-specific build directory.
- Enabled pipefail on the shared GrhSIM run pipeline. Previously a crashing emu was hidden by a successful tee, producing a false make exit 0. The failure now propagates.

## Full Build Result

`make xs_wolf_grhsim_ir_build_emu` completed with exit 0, reusing `ptmp/xs_emit_make_gate49`, clang O0 and two model build jobs. Driver, all 170 init files and all 514 task files were built or reused, the full library was archived, and difftest linked the emu.

- Build log: `ptmp/grhsim_gate49_full_build.log`.
- Model archive: `ptmp/xs_emit_make_gate49/libgrhsim_SimTop.a` (about 2.4 GiB).
- Executable: `build/xs/grhsim-ir/emu/grhsim-compile/emu` (about 1.2 GiB).
- Runtime entry symlink: `build/xs/grhsim-ir/emu/emu`.

This proves full O0 compilation/linking, not runtime correctness or O3 performance.

## Startup Failures

The new Makefile runtime entry attempted a bounded 100-cycle CoreMark startup, without waveform. It did not reach the cycle progress logs.

1. Default 8 MiB stack: SIGSEGV before `max cycles`. The first run's tee masked the failure; after pipefail, make reported the emu's error 139. Log: `ptmp/grhsim_gate49_smoke100_status.log`.
2. Disassembly shows `cpu_init_59` reserves `0x96c250` bytes (about 9.4 MiB) of stack at O0. Other init chunks also have large frames. Aggregate zero-initialization temporaries are a likely source; init chunking by record count does not bound stack bytes.
3. A diagnostic run through the existing `XS_EMU_PREFIX` with `prlimit --stack=67108864:67108864 -- stdbuf -oL -eL` passes initialization far enough to print `max cycles: 100` and flash setup, then crashes in string assignment. Log: `ptmp/grhsim_gate49_smoke100_stack64.log`. The larger stack is only a diagnostic override, not an accepted fix.
4. `addr2line` resolves the second trace to `std::char_traits<char>::assign`, `GrhSIM_SimTop::cpu_task_61`, `eval`, and `Emulator::Emulator`. The emitter creates raw zero-filled local byte frames and accesses strings via `cpu_at<std::string>` without construction/destruction. String object lifetime must be implemented for the actual storage lifetimes, not approximated by zeroed bytes.

## Remaining Requirements

Remove large aggregate-init stack temporaries and implement nontrivial string lifetimes with tests. Then rerun startup with the normal stack limit. DPI and system-task emission are still skipped, so even a bounded-cycle startup cannot prove CoreMark execution. General array initial values, functional 10k/50k runs with instruction progress/NEMU comparison, and O3/performance parity remain unverified.
