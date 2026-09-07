# GrhSIM IR CPU compute partition implementation plan

- Date: 2026-09-06
- Predecessor: [phase/domain gate](./NO0529_grhsim_ir_cpu_phase_domain_gate_20260905.md)
- Parent: [multiclock/activity plan](../draft/grhsim_ir/grhsim-ir-cpu-backend-multiclock-activity-plan-20260905.md)
- Scope: the four remaining partition-tree passes in M5.1. The full goal remains
  the independent IR CoreMark 50k simulation and all parent-plan validation gates.

## Design

1. `cpu.st.build-compute-nodes`: derive producers and a compact use index from the
   model. Topologically sort compute operations, rejecting combinational cycles.
   Build bounded cones in reverse order, stopping at shared values and commit
   consumers. A producer joins a consumer node only when all its consumers belong
   to that node. Side effects do not get absorbed into a downstream consumer.
2. `cpu.st.merge-compute-supernodes`: port legacy's out1/in1/sibling contraction
   rules and uniform-weight DP objective. Rank chain candidates by distinct crossing
   values, cap op counts, and reject a contraction batch if its quotient is cyclic.
   The DP minimizes distinct incoming value activations plus one unit per segment.
   Use legacy's three-small-delta-iterations tail stop above 100k clusters.
3. `cpu.st.pack-active-words`: assign contiguous compute active IDs, pack eight
   supernodes per word, and record helper ranges for large estimated bodies.
4. `cpu.st.pack-emit-functions`: pack complete words and domain-local commit
   supernodes using op and estimated-line limits with a target-count adjustment.
   Keep functions and TU packing distinct; TU emission is still pending.

Each pass grows one level and publishes a replacement typed mapping only after
construction. None rewrites semantic operations. Intermediate graphs and union-find
state are local to a pass; later passes reconstruct dependencies from model + tree.

## Adaptation from legacy

The legacy node builder may clone state reads and rewrite operands. Those actions
are incompatible with a BackendMapping pass that must preserve semantic revision
and own every op once. The new builder retains boundary-guided cone construction
without cloning. The default node cap is 128, matching the default supernode cap,
so the later merge pass does not need to split node leaves or alter an earlier layer.
Larger explicit node caps are allowed; an oversize node remains a standalone
supernode and can be split into emitted helpers by the word pass.

Line estimates are deterministic IR size estimates. Their agreement with actual
emitted C++ and the 50k performance criterion will be measured when emission exists.
There is no fullpass path.

## Gates

- Dense coverage and exact stage topology, ordered node op dependencies, contiguous
  active IDs, eight-lane word boundaries, complete helper ranges, and function
  containment verified after each pass and after JSON loading.
- C++ cases: users before definitions, independent cones, shared/derived clocks,
  opposite edges, empty models, an explicit combinational cycle, op limits,
  coarsen plus DP packing, helper coverage, and corrupted activity/order metadata.
- Full XiangShan checkpoint: build all six partition stages, retain the 449 observed
  event domains, and require stable mapping store/load/store. Record partition sizes,
  crossing edges, wall time, and RSS.
- Rebuild Python bindings and verify the actual Make/Python checkpoint route.

## Remaining Work

DataLayout, SchedulePlan, emitter/runtime, build/run integration, HDLBits simulation,
multiclock Verilator comparison, CoreMark 10k/50k difftest, and performance analysis
remain required. This gate cannot establish simulation or performance parity.
