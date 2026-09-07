# NO0559 CPU wide comparison and shift amount

## Changes

Gate47 reached task_10 and failed on wide comparisons using scalar casts and a 512-bit shift amount passed to size_t.

- Added pointer-based `grhsim_compare_extended_words`, following legacy high-to-low word comparison and sign handling. It masks source padding and extends one word at a time, without wide cast arrays or allocations. Narrow operands use real uint64_t locals.
- CPU comparisons with either input wider than 64 bits now use that helper. Signed comparison/extension applies only if both inputs are signed; mixed signedness zero-extends.
- Scalar and wide-result shift emission use legacy `grhsim_index_words` to saturate a wide shift amount. Nonzero upper words cannot wrap into an in-range low-word shift.
- No DPI/event classification changes.

## Verification

`make test_grhsim_cpu_emit WOLF_ENV_SOURCED=1` passed; final log: `ptmp/grhsim_cpu_compare_shift_test_final.log`.
The generated C++/Verilator comparison runs under UBSan. In addition to the existing 4,104 multiclock and 4,196 scalar samples, the 3,072 wide samples now cover all six unsigned and signed comparison relations, unequal signed widths (129/67), scalar signed and mixed-signedness operands, and 512-bit shift amounts (low word, bit 64, bit 511) for left/logical-right/arithmetic-right shift. Negative signed values and equality after sign extension are included.

Additional deterministic checks cover unsigned comparison of signed 8-bit -1 against 129-bit 0/254/255/256 and masking unused bits of a 65-bit operand. `make py_install` passed; log: `ptmp/grhsim_py_install_compare_shift.log`.

## Full Gate48 Result

The existing `xs_wolf_grhsim_ir_emu` Makefile target ran with clang O0 and one build job. It completed mapping, C++ emission, fresh-load and stable round-trip. Driver, all 170 init files, and tasks 1-62 compiled, including task_10 where gate47 failed. Log: `ptmp/grhsim_gate48.log`; generated model: `ptmp/xs_emit_make_gate48`.

The build exited 2 at task_63 with new state-write failures:

- Wide memory element access emits `cpu_at<T>(cpu_mem + index * stride)` with one argument; `cpu_at` requires pointer and offset.
- Wide register mask merging emits scalar uint64_t casts of wide arrays. It needs per-word mask merging against staged state, not a scalar cast or unmasked assignment.

Those write-path gaps remain unfixed in gate48 and need legacy out-buffer implementation plus masked/multiwriter tests. No emu link, CoreMark 10k/50k or O3 performance parity is proven.
