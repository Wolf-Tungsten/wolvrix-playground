# NO0566 CPU DPI declaration boundary

## Gate52 Generation and Build Failure

After [NO0565](./NO0565_grhsim_ir_cpu_call_condition_20260906.md), gate52 lowering, CPU mapping, C++ emission, fresh checkpoint load and stable round-trip passed. Log: `ptmp/grhsim_gate52_generation.log`; generated model: `ptmp/xs_emit_make_gate52`; checkpoints: `ptmp/xs_ir_gate52.json` and `ptmp/xs_ir_gate52_roundtrip.json`.

`make xs_wolf_grhsim_ir_build_emu` failed while compiling harness `emu.cpp`, before full model build/link. Log: `ptmp/grhsim_gate52_full_build.log`.

The new public model header declared SV-normalized DPI types, colliding with native harness declarations in the same translation unit:

- `xs_assert_v2`: int64_t versus long long.
- `difftest_ram_read/write`: signed versus unsigned 64-bit types.
- `sd_setaddr/read`: signed versus unsigned 32-bit types.

The existing legacy emitter writes `model.dpiDecls` into generated schedule source files, not its public header. The new emitter had widened their visibility unnecessarily.

## Repair and Focused Verification

Moved declarations from the public model header to compute task translation units, following the legacy boundary. The harness is unchanged. The emitted call ABI and SV signed-width normalization are unchanged; this uses the existing host scalar ABI and does not claim portable cross-ABI or general svdpi compatibility.

`make test_grhsim_cpu_emit WOLF_ENV_SOURCED=1` passed. Log: `ptmp/grhsim_cpu_calls_test4.log`. The external-call regression now includes a native uint64_t provider defined in a translation unit that includes the public model header, while the generated task consumes a signed 64-bit IR signature. Negative-input bit patterns and returned high bits are checked. All previous 384-call, terminal-exit, startup/storage and Verilator/UBSan gates remain green.

Next generate gate53, finish the full Makefile build/link and inspect actual-call runtime behavior. Gate52 is a generation gate and harness-compilation failure, not a running model. CoreMark 50k remains incomplete.
