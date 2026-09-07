# NO0562 CPU startup storage repair

## Root Cause and Implementation

- The String layout is a pointer-sized handle (8 bytes), not inline `std::string` storage. The old emitter both skipped construction and overwrote neighboring slots by assigning a full string object there.
- Kept the canonical mapping unchanged. `cpu_at<std::string>` now dereferences a string pointer handle. Object, boundary and input-shadow handles point into a model-owned typed string array; local handles point to automatic strings whose scope spans all helper chunks of their supernode. This follows legacy's separation of typed string storage from raw logic storage.
- Constructor binding makes handles valid before use. Repeated `init()` clears the owned strings and rebinds handles after raw arenas are zeroed. C++ RAII handles normal and exceptional cleanup; no per-access allocation or inline string placement in undersized slots is introduced.
- String states and arrays of strings are rejected explicitly until their semantic initialization/commit and aggregate-handle representation are implemented. They cannot accidentally use raw memcpy state publication.
- Array initialization writes zero directly to destination memory with `memset`, removing the aggregate temporary responsible for the O0 init stack overflow. This preserves the existing zero-only array behavior; it does not implement general literals, readmem or random array initialization.
- DPI/system-task scheduling policy is unchanged. Their still-skipped runtime emission is not accepted as functional completion.

## Focused Gate

`make test_grhsim_cpu_emit WOLF_ENV_SOURCED=1` passed, log `ptmp/grhsim_cpu_startup_test2.log`.

- New generated-Makefile O0 startup regression: 8 MiB stack, 16 MiB byte-array state, boundary and local strings, multi-helper local lifetime, string input shadows and multiple outputs, empty/short/long strings, 16 repeated initializations, 768 string samples and destruction of four models.
- Memory endpoints are written nonzero and verified cleared after reinitialization. No stack-limit increase is used.
- AddressSanitizer and UBSan passed. LeakSanitizer is unavailable under the current traced execution environment; its initial attempt failed (`ptmp/grhsim_cpu_startup_test.log`). The test Makefile exposes `CPU_STARTUP_ASAN_OPTIONS`; this environment defaults to `detect_leaks=0`. This is not a passing leak-scan claim.
- Existing Verilator/UBSan comparisons remain green: multiclock 4,104 samples, scalar 4,196, wide compute 3,072, wide state 2,048.
- The root Makefile now places generated emitter-test artifacts under `ptmp/cpu_emit_tests/`.

## Next Gate

Update bindings through `make py_install`, emit into a fresh gate50 directory, compile/link through the existing project Makefile, and retry XiangShan startup at the default stack limit. Full-model runtime, DPI execution, general array initialization and CoreMark 50k remain unverified.
