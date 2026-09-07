# GrhSIM IR CPU phase/domain implementation plan

- Date: 2026-09-05
- Parent: [CPU multiclock/activity plan](../draft/grhsim_ir/grhsim-ir-cpu-backend-multiclock-activity-plan-20260905.md)
- Milestone: M5.0 implementation and structural gate. The full objective remains the
  `xs_wolf_grhsim_ir` CoreMark 10k/50k difftest and performance gates, followed by the
  multiclock differential tests and performance report required by the parent plan.

## Starting evidence

The current implementation contains the independent model, lowering, pass manager,
and streaming JSON. `BackendMapping` only carries a header and generic parameters;
there is no CPU partition, schedule, layout, emitter, or simulator. The existing
`xs_wolf_grhsim_ir` target stops after lowering and a stable JSON round trip.
An existing XiangShan IR checkpoint is available at
`build/xs/grhsim-ir/xiangshan_grhsim_ir.json`.

## Implementation

1. Add a typed CPU payload owned by the model's mapping container. Preserve the
   identity/revision checks, clone rebinding, and semantic-mutation invalidation.
2. Register `cpu.st.split-phase` and `cpu.st.form-event-domains` as BackendMapping
   passes. Each pass adds only its own partition layer and leaves model semantics
   unchanged. Publish a new mapping only after successful construction.
3. Group commit ops by sorted, deduplicated `(edge, value)` pairs. Classify domains
   as input or derived; latch/no-event groups have general scan semantics. Preserve
   per-op event histories and multiple state writers. Chunk size defaults to 4096,
   matching the current legacy configuration.
4. Validate topology, coverage, phase purity, and domain membership after each pass.
   Store the typed payload as a schema-specific JSON mapping row extension and
   verify it again on load. Partition-only mappings remain `complete=false`.
5. Run the two passes in the XiangShan IR checkpoint script and test the C++ and
   Python entry points.

The current authoritative core dialect also defines `memAssign` and `memWriteSeq`.
They are state writers and must join commit, extending the draft's four-op list.
This classification does not claim that their runtime emission is implemented.

## Gates

- Unit tests: multiple input clocks, opposite edges, derived clock, duplicate and
  permuted event sets, latch/general, commit chunk limits, compute side effects,
  clone/invalidation, empty design, invalid pass order, and malformed mapping.
- Streaming JSON: stable store/load/store including CPU mapping; existing unmapped
  checkpoints still load.
- XiangShan structural gate: load the existing checkpoint, run both passes, require
  exactly one input posedge domain, and round-trip the mapped checkpoint.
- Existing GrhSIM IR tests and Python/session smoke.

## Remaining requirements

Full legacy phase parity and HDLBits domain auditing are separate M5.0 gates.
Compute node construction/coarsening, word/function packing, CPU layout/schedule,
code emission, runtime, simulator build targets, 10k/50k difftest, HDLBits simulation,
Verilator multiclock comparison, and performance parity remain pending. Structural
checks cannot establish simulation correctness or the 50k performance criterion.
