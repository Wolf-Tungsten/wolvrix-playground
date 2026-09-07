# CPU history-range edge rejection implementation

- Date: 2026-09-07
- Design: [NO0626](./NO0626_grhsim_ir_cpu_history_scan_design_20260907.md).

## Changes

cpu_emit.cpp now collects history offsets alongside each actual (ValueId, edge)
term in commitEdgePossibility. Eligible one-byte unsigned boolean groups with
at least 16 unique histories are sorted into exact contiguous ranges. Scanning
is enabled only when average range length is at least four. One range emits a
direct std::memchr; multiple ranges use a constexpr offset/size array and an
early-return loop. No heap allocation, copied wide value, mutable edge cache,
representative history or helper ABI change is introduced.

The aggregate remains conservative and only chooses the pre-existing
sampling-only branch. Normal guards, ordering, private batches, direct-write
eligibility, shared-history fallback, schedule, model and DPI policy are unchanged.
The backend reference documentation now specifies this optimization and bounds.

## Verification

make test_grhsim_cpu_schedule test_grhsim_cpu_emit exited 0; the complete CPU
emitter suite took 35.15 s. Logs: ptmp/grhsim_gate61_cpu_tests.log and
ptmp/grhsim_gate61_cpu_tests_detail.log. Four new executable variants each pass
4632 samples/four resets under ASan/UBSan:

- Dense single ranges with a match only at the last posedge-history byte.
- Four disjoint eight-byte ranges, excluding intervening state bytes.
- Fully sparse ranges, exercising the original level-only fallback.
- A derived event combined with the other input clock, posedge/negedge OR.

The independent scoreboard retains distinct initial histories, checks all 32
registers and observed history values, mixes enables/data with fixed clocks,
simultaneous clock changes and repeated evaluations. Structural cases verify
15/16-history thresholds; existing eight/nine-event limits, general/shared
fallback, multiclock CDC/RAM, void/return DPI and string tests remain passing.
No compiler warnings/errors occurred. Both repositories pass git diff --check.

Emitter SHA-256:
c50567fdc958e1be02db11e8975af171405d12112754edf92884a7535dc30480.

## Remaining Gates

Project-local make py_install is running before independent gate61 generation
and HDLBits. Gate60 is restored and retained as the ordinary-binary reference.
The new scan's full-model coverage and actual runtime benefit are not yet
measured; CPU unit success is not the XiangShan 50k or legacy+5% gate.
