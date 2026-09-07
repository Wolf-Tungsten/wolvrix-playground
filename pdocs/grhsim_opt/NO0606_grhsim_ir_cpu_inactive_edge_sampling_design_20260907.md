# Inactive-edge sampling-only commit design

- Date: 2026-09-07
- Precondition: [NO0605](./NO0605_grhsim_ir_cpu_shared_history_schedule_gate_20260907.md).
- Scope: generated commit task bodies; no IR, schedule, DPI or ingest change.

## Motivation and Reference

Gate57's fresh phase profile measured 21.05 s commit versus 17.98 s compute in
the 1k window. Gate58's serial 1k improvement was only about 6.5%. Preserve both
baselines; the full 50k legacy +5% performance requirement remains unmet.

Legacy grhsim_cpp.cpp::analyzeCommitSupernodeEvent collects and deduplicates
event expressions for aggregate dispatch. Apply the same bounded aggregation
idea, but retain the IR's per-operation history semantics. No wide helper ABI,
return-by-value buffer, fullpass, fine-grained activation mask or allocation is
introduced in the generated runtime.

## Proof and Generated Shape

For each DomainGatedCommit task, collect actual event operands from every
regWrite/memWrite/memFill/memWriteSeq, deduplicating (ValueId, edge). Let P be the
OR of current posedge values and inverted current negedge values. If P is false,
every original edge guard is false, irrespective of the visible histories.

```cpp
if (!P) {
    // Stage individual histories in the original op/event order.
    // Then stage the same private history batches as the normal body.
    return;
}
// Original payload guards, writes, individual samples and history batches.
```

This eliminates payload guard/state reads on the impossible-edge path, not
history sampling. Private batches reuse the existing caller-owned shadow buffer
and pending ABI. Shared/observed histories continue to use ordinary stage.
The false-edge path must never skip a sample merely because visible history
already equals its event: another writer may already have staged a different
value in the same G application.

AlwaysScanCommit tasks, including the conflicting-history fallback introduced
in NO0605, use the original body. Missing/unsupported/empty events or more than
eight distinct event terms also retain the original body. The cap bounds code
size and repeated expression evaluation, without weakening semantics.

## Gates

- Emission checks for input, derived, mixed-edge domains; no sampling-only
  branch in general or shared-history fallback tasks.
- Eight distinct terms accepted; nine terms conservatively use the old body.
- Complete CPU/Verilator suites, shared-history independent G scoreboard,
  non-E state/real void DPI checks, and full HDLBits through Makefile entries.
- Independent gate59 generation and fresh JSON roundtrip. Compare mapping with
  gate58 and inspect coverage without double-counting duplicated source branches.
- Full O3 model build and serial runtime comparison before claiming any gain.

Duplicating sampling code can increase source, binary and compile cost. It is a
candidate, not a demonstrated speedup. Actual 10k/50k and performance gates are
not replaced by structural coverage or small-component tests.
