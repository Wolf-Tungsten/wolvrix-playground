# Memory staging and activation structure audit

- Date: 2026-09-07
- Scope: follow-up to the user's generated-C++ structure comparison.
- Status: static discrepancy confirmed; no memory semantic change implemented.

## Concrete difference

IR memWrite/memWriteSeq stages storageBytes(array), not one addressed cell.
cpu_stage_bytes copies the entire object on its first staged write, and the
pending publication compares/copies that object and activates its state fanout.
Gate63 generated sources contain 4116 memory staging sites across 832 unique
array states, totaling 24067092 bytes of unique array storage. Maximum staged
array size is 1048576 bytes, e.g. grhsim_SimTop_task_5602.cpp:3007 stages state
236940 at object offset 2853384. These are static counts, NOT bytes copied per
cycle: event/enables, repeated writers and actual changes determine execution.

Actual legacy grhsim_SimTop_sched_72.cpp:4208 onward compares/writes the
addressed memory element and calls activate_memory_row_readers_0 on a change.
The helper in grhsim_SimTop_state.cpp uses row offsets to select readers.
Thus legacy can avoid both whole-array data movement and activation of readers
of unrelated rows. IR currently retains whole-state fanout granularity.

## Constraints on a repair

Directly adopting legacy visible-state writes would weaken IR's existing
multiwriter/NBA contract. A cell-granular pending scheme must preserve ordered
masked writes, repeated writes to the same cell, different cells, memWriteSeq,
memFill interaction and original visible-state reads until publication. Row
fanout also requires accurate constant/dynamic-address reader tracking and a
conservative fallback. Measure memory staging/publish attribution before
expanding the implementation; this change is deliberately not mixed into
gate65 helper-only or gate66 helper-plus-local-activity candidates.

The earlier scalar-arena comparison is not a total-memory comparison: legacy
memory arrays are separate fields. The observed 25 MB IR object arena alone
cannot establish a 25x total-state storage regression.
