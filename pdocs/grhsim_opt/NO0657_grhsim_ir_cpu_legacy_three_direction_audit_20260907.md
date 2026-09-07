# Legacy three-direction audit

- Date: 2026-09-07
- Baseline: NO0656, gate63 / legacy = 879581 / 154286 ms = 5.700977x.
- Scope: partition/block scale, generated structure, helpers. DPI semantics unchanged.

## Partition and packing

| Quantity | Gate63 IR | Actual legacy |
| --- | ---: | ---: |
| Compute nodes | 1501444 | 1092530 |
| Compute operations in nodes | 4690774 | 5625117 |
| Compute supernodes | 44686 | 63241 |
| Maximum operations per compute supernode | 128 | 108 |
| Commit supernodes | 515 | 485 |
| Compute functions | 5569 | 66 |
| Commit functions | 515 | 51 |
| Event domains/keys | 449 | 450 |

Sources: ptmp/grhsim_gate63_mapping_census.json,
ptmp/grhsim_gate63_partition_sizes.json and
build/xs/grhsim/grhsim_emit/activity_schedule_supernode_stats.json.
IR has 5586 logical compute active words, 161 helper chunks, 3819 round seeds.
Compute functions contain 516-1152 operations. Partition scale is comparable;
function packing is not. Gate63 explicitly used target_batch_count=0, disabling
the existing default target-count adjustment (64). This is a candidate
configuration discrepancy, not evidence that the production default is zero.
Test packing separately before attributing dynamic performance to this count.

## Generated structure

Both routes use ordered compute/commit fixed-point execution. Legacy uses
local activeWordFlags; IR repeatedly updates cpu_flags. Legacy also aliases or
inlines many read expressions where IR materializes local/boundary values.
IR shadow/pending/publish supports NBA and multiwriter semantics and cannot
simply be replaced with direct legacy writes. These are static findings, not
measured attribution. Do not compare the legacy scalar state arena alone
against IR total storage: legacy stores memory arrays separately.

## Helpers

Both routes share lib/emit/grhsim_runtime.cpp. Legacy also uses some return-array
mux/slice helpers; their presence alone is not a new regression. IR static
occurrences: mux 5279, replicate 638, slice 113345, not execution counts.
Confirmed unconditional fanout activation follows 42 wide adds, 1 subtract,
26 left shifts and 14 logical right shifts (83 total). The earlier census of
3115 boundary-output left shifts does NOT mean 3115 fanout activations; most
outputs are commit-only values. Repair tracked writes by computing/comparing
each final word in one pointer/out-buffer pass, without whole-array snapshots.
Keep untracked legacy helper paths unchanged and test normalization, unchanged
results, carry/borrow and shift boundaries before XS measurements.
