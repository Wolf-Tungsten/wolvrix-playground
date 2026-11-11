# F24 activation edge audit

The F24 same-input GSIM generation completed successfully with 222,593 emitted
supernodes. Its final stats report 1,490,154 boundary activation edges and
1,121,323 unique source-supernode/target-supernode pairs. These two counts use
different units and must not be compared interchangeably with native value edges.

GSIM `boundary_activation_edges` counts distinct `(Node, target supernode)` edges
after removing always-active targets and self edges. It includes scalar conditional
activation and unconditional activation of arrays/memory writers. The per-node-type
map cannot establish which `NODE_OTHERS` nodes are scalar.

Native `activation-stats.json` counts actual emitted publication paths. Its
`value_change_activation_edges` counts distinct targets for each published ValueId,
including input and constant sources. State-change, state-write and event-pulse
activation are separate fields. The value edge count remains per ValueId when
multiple dirty publications share one generated condition.

The state field names do not give an exact conditional/unconditional split.
`state_write_activation_edges` is classified using the configured non-latch
write-activation policy. Small states still publish inside
`if (current != next)` under that policy; large states publish when their write
flag is set, with optional touched-index subscription checks. Therefore the
state-write count mixes small-state value-change edges with large-state write
triggers. Both state fields must be retained in a conservative upper bound on
all conditional publications. Dynamic subscriptions count each possible
`(state, target nonsink owner)` once.

`event_pulse_activation_edges` counts the physical fire-pulse publication route:
the emitter activates its targets whenever the pulse is asserted, including
consecutive asserted rounds. It does not compare the pulse with its prior value.
This differs from ordinary input/value publication and small-state publication,
which compare the new and cached values. Large on-change states also compare
their aggregate or leaf before-images; large on-write states use write triggers.

## Conservative sufficient bounds

The sidecar script `scripts/analyze_f24_activation_edges.py` reads already generated
GSIM C++ files. It recognizes only the exact scalar shapes emitted by
`graph::activateNext`: `bool cond_name = name ^ name$old$ID`, the corresponding
`!=` shape, and `if (name != name$old$ID)` blocks. The `// id=SN` enclosing
supernode guard establishes the source supernode; numeric comments on activation
statements establish the targets. Edges are deduplicated as `(Node ID, target SN)`;
self edges are excluded. Unguarded sources, async `activateAll()`, unconditional
activation and unrecognized forms contribute zero to the confirmed subset.

Let `C` be this confirmed scalar conditional boundary subset, including scalar
register, reader and other source kinds. Let `V`, `Sc`, `Sw` and `P` be native
`value_change_activation_edges`, `state_change_activation_edges`,
`state_write_activation_edges` and `event_pulse_activation_edges` respectively.
Then `U = V + Sc + Sw` upper-bounds all native conditional publication edges:
it keeps the small-state comparisons mixed into `Sw` and also conservatively
includes large-state write triggers. The broader GSIM conditional edge count is
at least `C`, so `2 * U <= 3 * C` is a sufficient numerical bound on the full
conditional publication scope. The stricter test `2 * (U + P) <= 3 * C` includes
physical event-pulse routes as well. `U + P` must equal native
`total_activation_edges`; the script rejects missing, negative or inconsistent
component counts.

The separate compute-subset report retains the earlier conservative test. Let
`N` be all GSIM boundary edges whose source type is not `NODE_OTHERS`. Then
`max(0, C - N)` lower-bounds scalar conditional edges with `NODE_OTHERS` sources.
Subtracting all other source edges also subtracts edges absent from `C`, so the
subtraction cannot inflate the lower bound. All native value edges `V`
upper-bound its compute-to-compute value-publication subset. This separate
test does not cover native state publications.

| Same-input F24 GSIM component | Edges |
| --- | ---: |
| Confirmed scalar conditional boundary subset `C` | 1,462,592 |
| Recognized conditional-variable form | 933,515 |
| Recognized compare-block form | 529,077 |
| Broad conditional native upper-bound limit `floor(1.5 × C)` | 2,193,888 |
| Stricter native limit including physical pulses | 2,193,888 |
| All non-`NODE_OTHERS` boundary edges `N` | 648,540 |
| Compute-source scalar conditional boundary lower bound `C - N` | 814,052 |
| Compute-subset native all-value-edge limit `floor(1.5 × (C - N))` | 1,221,078 |

The JSON exposes these tests under `native.compute_subset`,
`native.broad_conditional` and `native.publications_including_event_pulses`.
The original `native.sufficient_count_inequality_holds` field remains an explicitly
labelled compatibility alias for the compute-subset test only. A false sufficient
inequality leaves that test unresolved; it does not prove that the actual edge
ratio exceeds 1.5.

## Runtime scope and identity assumptions

The full conditional scope compares each runtime's emitted activity-bit routes.
Native targets are nonsink compute owners, which comprise its activity-bit-gated
execution. GSIM targets are any emitted activation-bit supernode; its target
classification need not match native nonsink classification. The GSIM
compute-source lower bound also retains all such targets and does not establish
a matched compute-target subset.

Native sink/event/output phases run through phase scans. Writer enable probes,
dirty-state probes and indexed subscriptions can skip work, but they do not add
value-change activation edges to sink targets. The emitter's activity routing
sites are value publication, input publication, physical fire-pulse publication,
state publication, initial activation and unconditional per-eval external-function
seeding. No additional change-detected sink activation route was found in this
audit. Initialization and per-eval seeds have no changing source value and are
outside both native publication tests, including the test using
`total_activation_edges`.

The numerical comparison requires independent verification of identical frozen
FIRRTL input, intended graph/configuration and the applicability of the runtime
scope above. The analysis script records optional external evidence and never
treats a supplied path as verification. It records
`input_identity_verified_by_this_script: false` and
`quality_gate_certified_by_this_script: false` even when all numerical tests hold.

## Artifacts and reproduction

- Stats: `ptmp/firrtl-ingest/F24/gsim-current-full/build/default-xiangshan/model/SimTop_supernode_stats.json`.
- Stats SHA256: `4a8bf9987603374b1bbc8550ec3aec7d1c3ee1e2b281a26fcb29960c986ee352`.
- Census: `ptmp/firrtl-ingest/F24/activation-audit/gsim-scalar-edges.json`.
- The census records the SHA256 and byte size of every generated C++ input.
- Reproduce through `make analyze_f24_activation_edges`; override
  `F24_ACTIVATION_GSIM_MODEL`, `F24_ACTIVATION_NATIVE_STATS`,
  `F24_ACTIVATION_EVIDENCE` and `F24_ACTIVATION_OUTPUT` for another frozen run.
- Validate recognition, deduplication, state/pulse bounds, exact integer limits,
  component consistency and evidence handling with `make test_f24_activation_edges`.

The first full census took 15.47 seconds and only read the frozen GSIM model.
