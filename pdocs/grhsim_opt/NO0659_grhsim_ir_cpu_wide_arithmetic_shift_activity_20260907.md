# Wide arithmetic and shift activity repair

- Date: 2026-09-07
- Audit: NO0657. XS baseline coverage: 83 unconditional fanout sites.
- Status: implementation and CPU tests passed; XS benefit unmeasured.

## Implementation

Tracked two-state wide add/sub/shl/lshr/ashr outputs now use pointer/out-buffer
helpers that return whether any final normalized word changed. Arithmetic
follows the shared legacy carry/borrow loops; shifts follow the same word
indexing, saturation and sign-fill semantics. Comparison happens immediately
before each word write, without whole-value snapshots, return arrays, initial
zero fill or allocation. Left shift traverses high-to-low, right shift low-to-high;
arithmetic right shift reads the original sign before writing. Exact input/output
alias tests pass, although emitted layout slots are distinct.

Untracked local or commit-only outputs retain the original shared legacy helpers.
No shared runtime, mapping, scheduler, DPI/event or state-publication change.
New helper names are reserved against port collisions. Backend documentation
defines parameters and a saturated 129-bit arithmetic-shift example.

## Verification

Existing make test_grhsim_cpu_emit exited 0, complete suite 66.14 seconds.
Tracked and local generated models each passed 4480 helper cases, 8192 model
evaluations and four resets under ASan/UBSan through fixture Makefiles.
Widths: 65,127,128,129,192,448,4097. Cases include random/patterned inputs,
carry/borrow chains, unequal input word counts, unchanged results, first/last
word changes, padding cleanup, exact aliases, shifts 0/1/63/64/65/127/128,
width-1/width/width+1/65536/SIZE_MAX and wide shift operands. Values and change
booleans are checked against the shared legacy pointer helpers. Generated
source checks require tracked calls and absence of them on the local path.
Existing multiclock, state, DPI and bitwise regressions remain passing.
make test_grhsim_cpu_schedule also exited 0.

Logs: ptmp/grhsim_wide_activity_cpu_tests.log,
ptmp/grhsim_wide_activity_schedule_tests.log. Gate64 remains an independent
packing-only candidate generated before this source edit; do not attribute
its eventual performance to this helper repair. Installation, full HDLBits,
independent XS generation/build and serial runtime validation remain pending.
