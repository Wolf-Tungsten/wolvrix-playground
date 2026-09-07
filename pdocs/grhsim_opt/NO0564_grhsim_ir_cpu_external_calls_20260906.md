# NO0564 CPU external-call emission

## Audit and Scope

Added `make audit_grhsim_cpu_emit GRHSIM_AUDIT_MODEL=...` to inspect operation kinds, event/procedure metadata and DPI signatures through the existing project build path. `ptmp/grhsim_gate50_call_audit.log` records the gate50 checkpoint audit: 6,527 DPI calls, 7,235 event-gated `fwrite` tasks and one event-gated `finish`. Assertion RTL uses stderr descriptor `32'h80000002`.

The agreed DPI policy is unchanged: compute-side execution, optional event metadata, and no purity/removability inference from presence or absence of results.

## Implementation

- Replaced the `core.dpi.call` and `core.system.task` no-op emitter branches with guarded execution.
- DPI declarations and arguments follow the legacy C-linkage ABI: scalar values, string input `const char*`, wide input by const reference, output/inout via caller-owned typed temporaries. Calls consume the IR's input/output/inout grouping and preserve declaration order at the C call site.
- Call results remain in their existing persistent boundary slots when disabled or without an event. Changed return/output/inout values activate mapped consumers. Wide padding and narrow signed normalization are handled explicitly; no wide array-return helper was added.
- Event histories are sampled outside the condition guard and staged through the existing history publication path. Multiple events form one OR guard, not multiple external calls.
- Added double representation for Real ports and DPI values, alongside existing typed String handles.
- Emission validates external signatures, grouped arity, compatible types, one-bit guards/history and conflicting symbols before writing artifacts. Unpacked-array DPI ABI remains an explicit unsupported error.
- System task argument conversion/formatting reuses the legacy runtime. display/write/strobe/fdisplay/fwrite, info/warning/error and fatal/finish/stop are emitted; standard stdout/stderr descriptor forms are supported. Strobes flush at convergence; initial timed tasks complete only after an actual trigger. Terminal tasks flush and exit, not throw-and-continue.
- Final-process tasks, unsupported names, array task arguments and unsupported file handles are explicit errors, not dropped effects. General file I/O, finalization, system functions and general array initialization are not claimed complete.

## Focused Gate

`make test_grhsim_cpu_emit WOLF_ENV_SOURCED=1` passed after the signed-width repair. Log: `ptmp/grhsim_cpu_calls_test2.log`.

- New O0 ASan/UBSan external-call test: 384 samples across three resets, with return/void eventless calls, posedge return/output/inout calls, negedge void calls, mixed multi-event void calls, enabled/disabled event sampling and retained results.
- Typed coverage includes 129-bit input/output/inout with deliberately nonzero padding, String input/output, Real input/output, signed 1-bit return/output and signed 5-bit inout normalization. A clocked state captures the DPI return value.
- Captured stderr verifies actual `fwrite` text. Captured stdout verifies timed-initial execution only once and deferred strobe output. Subprocess tests verify finish exit 7 and fatal exit 11 with the fatal message.
- Existing O0 startup/storage regression and four Verilator/UBSan suites still pass (4,104 / 4,196 / 3,072 / 2,048 samples). Leak scanning remains disabled in the traced environment as previously documented.

## Next Gate

Update bindings, generate a fresh gate51 model, compile/link through the project Makefile and inspect startup with the actual external calls enabled. Then close whichever real runtime discrepancy is exposed. A successful bounded run without instruction progress is still not CoreMark 50k completion.
