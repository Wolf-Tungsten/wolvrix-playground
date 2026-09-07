# Compile limit static audit after stopping builds

- Date: 2026-09-07
- Scope: read-only implementation audit following NO0667; no build resumed.
- Status: two missing protections confirmed, not yet repaired.

## Function size limits are not hard limits

lib/grhsim/backend/cpu_partition.cpp:461 computes effectiveOps as
max(maxOps,totalOps/targetCount), and does the same for estimated lines.
Defaults are batch-max-ops=2048, batch-max-estimated-lines=8192 and
target-batch-count=64. With 4981305 operations in the XS model, the operation
threshold becomes 77832 rather than 2048. The target function count therefore
overrides what the option names suggest are maximum sizes. This explains the
packing expansion, not the exact compiler algorithm or elapsed-time growth.

A repair must distinguish a soft function-count target from hard compilation
size bounds. An indivisible active word or supernode that exceeds a bound needs
explicit handling/diagnostics or bounded helper emission, not silent unlimited
growth. Merely setting the count to 64 does not reproduce legacy's expression
structure or compilation cost. No new numeric limit is selected in this audit.

## Generated compiler recipes have no timeout

lib/grhsim/backend/cpu_emit.cpp:239-243 emits a Makefile object rule invoking
the compiler without a time bound. The root XS build-only target does not add
a per-translation-unit timeout either. Thus a pathological translation unit
can retain a compiler indefinitely, as observed with gate26 task60.

Future protection belongs in the Makefile workflow: bounded compiler execution,
clear offending-source diagnostics, and cleanup of the complete process group
on cancellation/timeout. It must preserve logs and all previously verified
candidate artifacts. Before timing, inspect host processes, not only known tool
sessions. Tests must cover the timeout/cleanup path as well as normal completion.

The host compiler/build-process query remains empty after NO0667. This audit
does not restart builds, run tests or simulations, modify implementation code,
claim a packing runtime result, or validate the final performance gate.
