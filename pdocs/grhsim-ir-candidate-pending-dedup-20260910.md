# Pending Record Deduplication

- Node: `pending_dedup_20260910_01`
- Status: REJECTED
- Root baseline: `3eb2eac`; wolvrix baseline: `c8b8676aee27efbf701e62d86c37e3ca86b576e3`.

## IDEA

Publication iterates `cpu_pending` and applies each pending record's target
range. The hypothesis was that multiple writes to one state might leave
duplicate records, allowing a second record to be folded into the first and
reducing publication work. The proposed mechanism was to coalesce descriptors
by dirty key before publication, retaining the last shadow value and its
consumer notifications. It would cover scalar, wide and memory-cell writes
without matching module names. It must preserve visible/shadow separation,
ordered masked writes and notifications for every changed cell.

The search clue was the earlier [phase profile](grhsim-ir-phase-profile-20260910.md):
publication occupied 5.04% of eval time at `93d55ae`. That is an old profile,
not evidence of duplicate records or a current runtime bound. Even removing
all publication could save only that fraction of eval time in that old run;
deduplication would remove a subset. The exploratory target was greater than
3% end-to-end reduction. The prerequisite was reachable duplicate records for
the same dirty key between publications. If all insertion paths already
enforce uniqueness, the hypothesis is falsified before implementation.

## BASELINE and falsification

The [CPU emitter](../wolvrix/lib/grhsim/backend/cpu_emit.cpp) at the baseline
commit has exactly four `cpu_pending.push_back` sites:

| Helper | Dirty key | Insertion condition and later writes |
|---|---|---|
| `cpu_stage<T>` | state index | Append only when clean; return the existing shadow reference when dirty |
| `cpu_write_scalar<T>` | state index | Return if the effective value equals next; otherwise append only when clean, then update shadow |
| `cpu_stage_bytes` | state index | Append only when clean; return the same shadow buffer when dirty |
| `cpu_stage_cell` | memory base plus row | Append only when that cell is clean; later writes reuse its shadow buffer |

Each insertion sets the corresponding dirty bit. `planMemoryCells` allocates
disjoint cell-key ranges after the state-index range, and `stageCell` supplies
the base for the target memory. Distinct rows therefore legitimately have
distinct records; this hypothesis concerns duplicate keys, not duplicate
consumer target ranges across different keys.

The only dirty-bit clearing sites are initialization and publication.
Initialization also empties the queue. Publication consumes the pending
records, compares visible and shadow bytes, copies changes and activates
consumers, clears each consumed key, and then empties the queue. Its loop does
not call staging helpers. The eval driver calls publication after executing
the scheduled tasks in each convergence round. Under the required
single-thread execution, induction over those four insertion paths gives at
most one pending record per dirty key between publications. This is a static
invariant, not an assumption about the CoreMark workload.

For example, a scalar write sequence `0 -> 1 -> 1 -> 0` starts with an empty
queue. The first change inserts one record, the repeated value adds none, and
restoration updates the existing shadow while retaining that single record.
Publication sees no final value change and empties the queue. Likewise, writes
to memory rows 2, 2, 3 create two records (one per row), not three.

The tracked [scalar fixture](../wolvrix/tests/grhsim/data/cpu_scalar_stage_main.cpp)
already asserts a queue size of one after repeated writes, retains that one
record on restoration, checks visible state is not published early, and
checks that publication clears both queue and dirty state. These assertions
were inspected here; they were not rerun and are not a new test PASS claim.
The four-path source audit is the basis for the early rejection.

## Reproduction and scope

The inspection can be repeated from the repository root with these read-only
commands (no build, generation or test workflow is invoked):

```bash
git rev-parse HEAD
git -C wolvrix rev-parse HEAD
git -C wolvrix status --short
git -C testcase/xiangshan rev-parse HEAD
sha256sum testcase/xiangshan/ready-to-run/coremark-2-iteration.bin
rg -n 'cpu_pending|cpu_dirty|memoryDirtyBases_|dirtyBytes_' wolvrix/lib/grhsim/backend/cpu_emit.cpp
sed -n '158,179p' wolvrix/lib/grhsim/backend/cpu_emit.cpp
sed -n '1690,1710p' wolvrix/lib/grhsim/backend/cpu_emit.cpp
sed -n '1750,1770p' wolvrix/lib/grhsim/backend/cpu_emit.cpp
sed -n '1788,1820p' wolvrix/lib/grhsim/backend/cpu_emit.cpp
sed -n '17,40p' wolvrix/tests/grhsim/data/cpu_scalar_stage_main.cpp
```

The source submodule was clean at the recorded commit. Input identity was
rechecked: XiangShan `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`, CoreMark
SHA-256 `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`.
Only this report and the goal index differ from the root baseline.

No runtime experiment was launched, so there are no RUN_IDs, Make commands,
CPU allocations, timing intervals, exit-status measurements, performance
ratios or independent repeats for this node. No build/simulation deadline
was armed because falsification preceded those steps. The archived
edge-snapshot 215.6715 s mean remains the best measured result, and the gsim
20.640 s reference is unchanged; neither is a new measurement here.

## Final decision

**REJECTED.** The existing dirty-bit invariant prevents the duplicate records
needed by this optimization. Static coverage for eliminating same-key
duplicate descriptors is zero, so the proposed mechanism has no removable
work. This does not rule out sharing consumer notifications across different
states or cells, which would be a different hypothesis.

The goal explicitly permits early rejection when evidence falsifies a
hypothesis. `IMPLEMENTED`, full-generation/compilation gates, focused test
execution, 50k validation, performance measurement and independent repeat
were not performed. There were zero implementation refinements. No new
performance benefit or completed M4 is claimed.

The retained implementation remains wolvrix
`c8b8676aee27efbf701e62d86c37e3ca86b576e3`; this report and the index are the
only files in the containing root archive commit. No generated code, logs,
profile, waveform or binary belongs to that archive. The initial archive
attempts failed because the sandbox exposes `.git` read-only; final archival
uses the environment's escalation mechanism and is complete only after Git
confirms the commit.

This closes the third node since shared-history (shared-history,
edge-snapshot, pending-dedup). The current best mean remains 215.6715 s,
175.6715 s above the approximate 40 s target. History sharing and edge
snapshots have measured gains; pending deduplication is already implemented
as a runtime invariant and should not receive further refinements. The next
node should obtain current cost evidence for compute or payload work and
test a mechanism with reachable coverage, rather than extend this queue
screen. The broader program remains open.

References: [goal/index](grhsim-ir-xiangshan-coremark-50k.goal.md),
[accepted edge-snapshot baseline](grhsim-ir-candidate-edge-snapshot-20260910.md),
and the tracked source, fixture and phase report linked above.
