# Private stable-history task skip design

- Date: 2026-09-07
- Evidence: [NO0645](./NO0645_grhsim_ir_cpu_gate62_phase_task_profile_20260907.md).

## Predicate and proof

For DomainGatedCommit tasks containing only supported edge-triggered
regWrite/memWrite/memFill/memWriteSeq, check every event history against its
current sampled event value. Require all histories to be unsigned two-state
one-bit states stored in one byte, with exactly one object reference each.
This rejects shared histories, ordinary writers, readers/observers and
histories used as payload states. Limit to eight distinct current ValueIds
and at least sixteen history members; small/unsupported tasks keep the old path.

If all histories equal their current event values, every posedge/negedge guard
is false and every history sample equals its visible value. The task has no
payload write and no history change. Private ownership excludes an earlier
pending writer whose value would need to be overwritten; layout and schedule
verification exclude overlapping states or duplicate task execution. Returning
before the original body therefore changes neither visible state, E(S),
activation, publication nor fixed-point rounds. This is not history freezing:
one differing history makes the predicate fail and preserves the entire old
guard/sampling body, including false-enable and opposite-edge sampling.

General/AlwaysScanCommit, DPI/system tasks and non-private history tasks never
use the predicate. No event is removed or shared and no schedule/mapping policy
changes. Existing sampling-only and dense edge-rejection branches remain as
fallbacks when the new predicate is false.

## Data movement and validation

Use read-only pointer access, following legacy buffer ownership and the prior
history scan. Per current value, contiguous history bytes can use memchr for
the opposite boolean; sparse bytes use constexpr offset tables and a loop.
Never scan gaps as if they were histories, allocate dynamic buffers, snapshot
wide values, or cache a representative history. Grouping is emitter-local
analysis reconstructed from the model and materialized in generated code.

Add private compact/fragmented/sparse/derived-clock fixtures with distinct
initial histories, mixed edges, held levels, false enables and repeated init.
Retain observed/shared/ordinary-writer fallback regressions, check thresholds
and the generated marker, and run the full CPU/schedule and HDLBits suites.
Only independent XS generation/build and serial ordinary-binary measurements
can establish benefit. Preserve gate62 and keep final 50k/legacy+5% gates open.
