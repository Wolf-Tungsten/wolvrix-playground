# NO0560 CPU wide state writes

## Implementation

Gate48 compiled tasks 1-62 and failed in task_63. This increment fixes the actual write-side errors rather than casting wide arrays to scalars:

- `memWrite`, `memFill` and `memWriteSeq` now pass `(base, byteOffset)` to `cpu_at<T>`, matching the existing ABI and preserving the element byte stride.
- Wide register/latch masked writes and memory masked writes reuse legacy `grhsim_apply_masked_words_inplace`. The destination is staged state, so successive disjoint-mask writers preserve prior staged updates. No wide return-value helper was added.
- `memWriteSeq` now tests its explicit event edges before performing the ordered stores. It still stages event history every visit. When addresses coincide, the last enabled operand triple wins as specified; independent ops do not gain arbitrary priority.

## Verification

`make test_grhsim_cpu_emit WOLF_ENV_SOURCED=1` passed. Log: `ptmp/grhsim_cpu_wide_state_test2.log`.

The emitted model is compiled with UBSan and compared with Verilator. Existing multiclock/scalar/wide regressions pass (4,104 / 4,196 / 3,072 samples). A new 2,048-sample, 129-bit state fixture covers register and latch masks, zero/all/random masks including the partial high word, two disjoint-mask register/memory writers, four independently read memory addresses, event-controlled fill, ordered same-address/different-address writes, and data/address changes without a clock edge.

The fixture uses zero initial state. It does not prove general array literal/readmem/random initialization support. Full XiangShan rebuild and CoreMark 50k remain required.

## XiangShan Check

Fresh gate49 generation passed through `make xs_wolf_grhsim_ir`: eight CPU mapping passes, C++ emission, fresh checkpoint load and stable round-trip all succeeded (86,357 ms total). Log: `ptmp/grhsim_gate49.log`. Model output: `ptmp/xs_emit_make_gate49`.

The generated Makefile then compiled `grhsim_SimTop_task_63.o`, `grhsim_SimTop_task_64.o` and `grhsim_SimTop_task_73.o` successfully with clang O0, reusing the same generation. Logs: `ptmp/grhsim_gate49_task63.log` and `ptmp/grhsim_gate49_commit_tasks.log`. This directly clears gate48's task_63 failures and checks two additional large commit files; it is not a full-model build. Earlier tasks from gate48 do not substitute for a full current-generation link.

Next: continue the generated Makefile build using gate49's retained objects, integrate the emu and run the functional simulation gates. Do not re-emit into its nonempty directory. No complete emu link, general array-init support, O3 performance result or CoreMark 50k claim is made here.
