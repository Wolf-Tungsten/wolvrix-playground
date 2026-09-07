# GrhSIM IR XiangShan event-domain audit

- Date: 2026-09-05
- Predecessor: [M5.0 implementation plan](./NO0527_grhsim_ir_cpu_phase_domain_plan_20260905.md)
- Result: the parent plan's expectation of exactly one Edge domain is contradicted
  by the available XiangShan IR and RTL. The runtime must retain multiple domains.

## Evidence

Input: `build/xs/grhsim-ir/xiangshan_grhsim_ir.json`, an existing independent IR
checkpoint with 4,981,305 operations. The CPU passes classify 4,690,774 compute ops
and 290,531 commit ops. Canonicalization uses sorted, deduplicated event pairs and
does not include update conditions, data, masks, or event-history state IDs.

The first structural run failed its explicit one-input-posedge-domain assertion:

```text
input_edge_domains=2 derived_edge_domains=446 general_domains=1
multiwriter_states=132
```

Logs:

- `wolvrix/build/artifacts/grhsim/cpu_xs_m50.log`: initial failed count gate.
- `wolvrix/build/artifacts/grhsim/cpu_xs_m50_domain_audit.log`: complete domain listing
  with event producers, followed by stable JSON round trip and the failed one-domain
  assertion. A diagnostic line immediately before that assertion incorrectly labels
  the successful round trip as one-domain; the assertion and domain listing are the
  authoritative result. The diagnostic has been corrected in the test utility.

Selected observed domains:

| Event set / source | Commit ops |
| --- | ---: |
| `posedge clock` | 176,719 |
| `posedge clock` plus event value 12172 (assign/sliceDynamic) | 7,905 |
| `posedge clock` plus event value 12806 (OR) | 93,363 |
| `posedge rtcClock` | 1 |
| JTAG TCK event value 11798 | 123 |
| General/no-edge | 402 |
| `negedge clock` | 1 |

Many remaining domains have five writes and clocks produced by an AND followed by
assignments. Additional domains combine RTC/JTAG events with reset expressions.
`source=derived` means at least one event value is internal; it does not mean every
event in the domain is a derived clock. Asynchronous resets also appear in keys.

The original RTL independently confirms the distinct clocks/edges:

- `build/xs/rtl/rtl/SDCardHelper.v:16` uses `always @(negedge clock)` for `sd_read`.
- `build/xs/rtl/rtl/XiangShanSim.sv:332` declares `rtcClock`; line 350 updates it from
  `rtcCounter`, and line 509 connects it to `io_rtc_clock`.
- `build/xs/rtl/rtl/XSTop.sv:2533` connects a clock to `io_systemjtag_jtag_TCK`.

## Consequence

Do not merge these event sets merely to satisfy the planned domain count. That
would lose mixed-edge, derived-clock, or asynchronous-reset behavior. M5.0's literal
one-domain acceptance item is not met; the structural implementation instead retains
and validates all 449 observed domains. General-domain scanning is retained for the
402 no-edge writes. The exact count is an observed property of this checkpoint,
not a hard-coded backend rule.

The 132 multiwriter states also disprove the draft's tentative one-write-per-state
assumption. Partitioning retains all writes and preserves their relative order;
this alone does not prove NBA correctness or implement ordered priority merging.

## Runtime questions carried forward

The current core dialect says each application of `G` samples event histories;
the parent CPU draft proposes freezing histories until eval completion. Before
implementing runtime, reconcile that difference using chained-register and derived
clock differential tests: an input edge must not repeatedly advance a pipeline
during fixed-point settling. Also preserve re-armed domains for the next round;
an unconditional round-end clear must not erase next-round arms.

The working-tree pass-system document proposes immutable replacement models, while
the requested CPU plan and existing C++ implementation use `PassKind::BackendMapping`
and revision-controlled in-place mapping updates. This increment follows the requested
plan and existing API. It does not claim implementation of the separate immutable API.
