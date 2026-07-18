# TNO0133 Stage 28 deferred-activation forward probe plan (2026-07-18)

## 1. Baseline and question

Stage 27 did not produce a sufficiently large activity-schedule opportunity.  The
next probe returns to the generated activation schedule, but measures the cost
that the emitter actually lowers.  In the current native C++ default (NO0300,
ASLR disabled), the relevant absolute baseline is:

| item | value |
| --- | ---: |
| compute supernodes | `63,241` |
| commit supernodes | `468` |
| compute activation edges / BAE | `1,983,326` |
| DAG edges | `527,990` |
| compute batches | `66` |
| commit batches | `31` |
| active-mask helper count | `0` |

The existing emitter already groups several values produced by one source into
one deferred activation condition.  Therefore a source-to-target pair with 71
schedule edges does not imply 71 active-mask writes: it can be 71 changed-value
ORs followed by one conditional mask update.  The Stage 28 question is whether a
pure compute target with an exact source/activation relationship can instead be
activated once, unconditionally, when its source supernode fires.  The physical
supernodes, operation partition, active IDs, value slots and batches must remain
unchanged.

The initial static examples motivating the probe are `51848 -> 62545` (71
shared values, compute fires `150103` and `150104` in the 50k profile) and
`51848 -> 62874` (25 shared values, compute fires `150103` and `150103`).  These
fire counts are clues only; equal counts do not prove co-fire or zero misses.

## 2. Candidate contract

The probe considers only a final `level-id` schedule and only compute-to-compute
activation sites.  A candidate source `S` and target `T` must satisfy all of the
following static conditions:

1. Every removed `(value,T)` activation is also an activation from `S`; the
   target has no state-read, memory-row, event, side-effect, unclassified or
   other special activation head.
2. `active_id(S) < active_id(T)`, both nodes are in the same ordinary compute
   lowering path, and no source can forward activation across a commit/event
   boundary or into an earlier batch.
3. The baseline consumer fanout remains untouched while the normal emitter model
   is built.  The probe then makes a private copy of boundary/input activation
   maps and re-runs deferred grouping, direct/aggregate selection, active-mask
   entry/chunk/table planning and seed grouping on that copy.
4. The synthetic forward operation is emitted only in the ordinary compute
   variant.  Full-pass, initial seed and commit paths are not changed.
5. Candidate selection is disjoint and deterministic.  It is default-off and
   read-only; no graph, schedule, session, generated CPP or baseline statistics
   may change when the probe is enabled.

The emitter must account for active-byte identity and contiguous 2/4/8-byte
chunks.  A one-byte BAE reduction can be neutral or negative if it leaves a
chunk, crosses the 32-entry table threshold, or merely changes a mask in an
already-written byte.  The physical SN test/branch count saved by this scheme is
explicitly zero.

## 3. Required measurements

For every selected or near-selected candidate, record absolute baseline and
private-candidate values, not only percentages:

- source/target supernode IDs, active IDs, active bytes, batches, CPP files and
  operation counts;
- shared schedule values, input/inout heads and all excluded special heads;
- deferred groups, direct/aggregate groups, active-mask entries, 1/2/4/8-byte
  chunks, table entries and branch/guard sites;
- synthetic forward local/global entries, chunks and estimated lines;
- net RMW/chunk/byte/estimated-line delta and the number of physical SN tests
  saved (`0`);
- source and target fire counts from the Stage 19 50k TSV profile, plus a
  conservative fire-weighted lower/upper bound.  A profile that cannot be read
  completely is fail-closed and cannot select a candidate.

If static accounting leaves a positive margin, a no-mutation runtime counter may
be added to the probe build.  It must report `leader_fire`,
`follower_pending`, and `leader_without_follower`; the last value must be zero.
Only then may a strict candidate be generated.

## 4. Verification and decision gate

Focused tests must cover exact source/target matching, state/event/special-head
rejection, same-byte and chunk-threshold accounting, deterministic selection,
invalid profile fail-closed behavior and off/probe identity.  Production probe
logs must include SHA256 of the generated control/candidate stats and absolute
baseline values above.

If the conservative fire-weighted net is not positive, stop without CPP/O3 or
SimTop.  Otherwise build a strict candidate, run 100/10k/50k functional gates,
and use fresh page-local dual-NUMA A/B/A and BAAB measurements.  All runs use
fresh `/dev/shm` inodes, target-NUMA first-touch, `numactl
--physcpubind/--membind`, `taskset`, `setarch x86_64 -R`, whole-node idle/runtime
admission, and `/proc/<pid>/numa_maps` placement checks.  The final end-to-end
decision is `Host time spent` walltime; cycles, instructions and static RMW
counts are diagnostic only.

The C++ option remains the sole default source and stays `off` until a strict
candidate wins the walltime gate.  XS may pass a sparse explicit probe override
but must not duplicate the C++ default.

## 5. 增量勘误（2026-07-18）

The fire-weighted quantities in the preceding plan are **work-proxy
heuristics**, not conservative runtime bounds. They multiply an emitter work
unit count by source fire and subtract a target IR operation count; IR operation
count is not an upper bound on target runtime cost. A positive proxy therefore
cannot authorize strict mutation. Stage 28 must first use a dynamic no-mutation
co-fire counter, and only a separately validated candidate may proceed to
functional testing and SimTop `Host time spent` walltime.
