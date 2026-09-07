# CPU emit shape repairs

- Date: 2026-09-07
- User authorization: repair the three diagnosed emit defects, then rerun CoreMark 50k.
- Candidate: gate67; old gate26/gate64 builds stay stopped and all prior artifacts stay preserved.
- Status: implementation and focused verification; no performance result yet.

The reference is actual legacy source: state-read aliases in sched_7.cpp,
grouped changed flags and masked activation in the same function, and addressed
memory writes/reader activation in sched_72.cpp. Function caps are not the fix.

Implementation in wolvrix/lib/grhsim/backend/cpu_emit.cpp:

1. Alias compute-only logic state reads with projected state fanout. Preserve
   every direct commit operand and domain event snapshot. Union direct users
   into state publication targets and coalesce activity-word masks. Retain the
   semantic IR, storage mapping and scheduler contract.
2. Group identical logic-result fanout within each supernode/helper chunk.
   Accumulate changed without per-result control flow and publish masked
   activation at the block end. Wide in-place helpers join these groups.
   DPI guards, results, side effects and histories remain unchanged.
3. Stage and publish memory cells, not arrays. A per-row dirty byte indexes the
   existing shadow arena; only the first write copies a visible row and queues
   it. Fill/masked/sequence writes share this row so last-write and masks retain
   their ordering. Cache each memRead's actual byte offset in compute; publish
   activates only matching row readers. Reset all caches on init. This preserves
   the IR's deferred commit semantics rather than introducing early memory writes.

Existing CPU suite passed in 52.20s. Added inline/helper tests passed with the
scalar grouping implementation in 58.43s: 32768 evaluations and four resets per
variant under ASan/UBSan, old-state register capture, fill plus masked plus
sequence writes, same-row cancellation, different rows, out-of-bounds writes.
An initial source assertion incorrectly rejected batched history staging; it
was corrected to inspect only the memory state ID. No runtime failure occurred.
Final suite including wide grouped publication is pending.

All execution uses existing Makefile targets. Logs/artifacts are under ptmp.
Keep target_batch_count=0 for the fresh timing pair so the three emitter fixes
are measured without an additional packing change. No clean speedup is claimed
from old timings: the forgotten gate26 compilation invalidated their isolation.
After verification and a new ordinary O3 link, run IR and legacy CoreMark 50k
serially, with the same image/NEMU/seed/progress/waveform settings and no build
overlap. Compare all progress samples and terminal functional records.
