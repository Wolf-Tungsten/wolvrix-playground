# NO0558 CPU direct concat and narrow operand regression

## Evidence and Scope

- Gate45: clang reports stack exhaustion in task_2 and crashes compiling task_7. The precise crash cause is not proven by a compiler backtrace.
- `value()` already reads the local or boundary frame; it does not recursively inline producers. The concat expression builder nests a helper call per operand. The longest task_7 line has 86,180 characters.
- Previous narrow pointer conversion reinterpreted bool/uint32_t storage as uint64_t storage. This can read adjacent values, violate alignment and aliasing, and must not be accepted merely because generated code compiles.

## Implementation

- Follow legacy `emitDirectWideConcatOperation` and `emitWideConcatInsertStatements`: construct a wide result with bounded-depth insertion statements, rather than nested array-return expressions.
- Reuse existing by-reference `grhsim_insert_words` and `grhsim_insert_scalar_words`. Local results write into their allocated frame slot; boundary results use a caller-owned local buffer and compare before publishing and activating consumers. Input/output slots do not overlap in the current canonical layout.
- Pointer arithmetic/bitwise/shift helpers receive a truncated uint64_t local for narrow inputs. Wide inputs still pass `.data()`. No reinterpretation of narrow storage, heap allocation or wide return-value helper was added.
- DPI/event policy is unchanged. The existing emitter's unimplemented DPI/system-task emission remains a separate runtime gap.

## Verification

`make test_grhsim_cpu_emit WOLF_ENV_SOURCED=1` builds and runs the existing CPU emitter regression suite through a dedicated Makefile entry. Compiler caches and temporary files are under `ptmp/`.

Passing log: `ptmp/grhsim_cpu_wide_regression4.log`. Verilator comparisons with UBSan cover 4,104 multiclock samples, 4,196 scalar samples and 3,072 wide samples. Wide cases include 1,024-operand concat, mixed 28/129/28-bit concat, 28-to-448-bit shift, narrow-input wide add, scalar replication, wide parity, shifts at word/width boundaries, and output padding. Concat fanout/change detection is also covered; the generated fixture contains the boundary comparison and activation path.

Full XiangShan gate47 uses the existing `xs_wolf_grhsim_ir_emu` target, clang O0 and one build job. Log: `ptmp/grhsim_gate47.log`; output: `ptmp/xs_emit_make_gate47`. Lowering/mapping, C++ emission, fresh-load and stable round-trip passed. The longest task_7 source line decreased from 86,180 to 4,300 characters. Driver, all 170 initialization files and tasks 1-9 compiled successfully, including the previous task_7 crash point. The make session exited 2 at task_10. No emu/10k/50k or performance parity claim follows from these tests.

## Next Actual Failures

Gate47 task_10 diagnostics identify two outstanding emitter cases:

- Lines 24,175 / 24,184 / 108,756 / 109,016 / 109,877: 224/222/352/67/81-bit comparison operands are passed to scalar `grhsim_cast_u64` and scalar compare. Wide comparison lowering must preserve signedness, operand extension, and partial-word masking.
- Line 110,018: a 512-bit shift amount is passed directly to a size_t parameter of the pointer shift helper. Shift amounts with nonzero high words must saturate to an out-of-range shift, not silently truncate to their low word.

These remain unfixed in this gate. Do not retry gate47's nonempty output directory through the emit target, and do not infer runtime correctness from the successful subset of compiled tasks.
