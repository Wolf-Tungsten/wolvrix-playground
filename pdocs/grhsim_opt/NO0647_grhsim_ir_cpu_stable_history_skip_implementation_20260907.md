# Private stable-history task skip implementation

- Date: 2026-09-07
- Design: [NO0646](./NO0646_grhsim_ir_cpu_stable_history_skip_design_20260907.md).

## Implementation

The emitter records private unsigned one-byte histories while performing its
existing reference-count/history analysis. Eligible DomainGatedCommit tasks
receive a read-only entry predicate grouped by current ValueId. Contiguous
groups use memchr for the opposite boolean; sparse groups use exact constexpr
offset lists. Only when every history matches does the task return before the
unchanged original guard/sampling body. At least sixteen history members and
at most eight distinct current values are required.

There is no new runtime helper ABI, dynamic allocation, wide-value snapshot,
history merge/cache, schedule change, or DPI/event change. The existing edge
possibility/sampling-only paths and history batching remain intact. Shared,
observed, ordinarily written and signed histories keep their original paths.

Files changed: wolvrix/lib/grhsim/backend/cpu_emit.cpp,
wolvrix/tests/grhsim/test_cpu_emit.cpp,
wolvrix/tests/grhsim/data/cpu_history_scan_main.cpp and
wolvrix/docs/grhsim_ir/backends/cpu.md.

## Tests

Existing root make test_grhsim_cpu_schedule and test_grhsim_cpu_emit targets
exited 0. The first complete suite took 44.49s, the memory extension 50.00s,
and the final threshold/signed extension 51.82s.

Seven new eligible runtime variants each passed 4632 samples / four resets:
compact, fragmented, sparse and derived register histories; sparse memWrite;
derived memFill; and fragmented/derived memWriteSeq. The sequence case has
two enabled same-address writes whose last value must win. Each model is
serialized and independently reloaded before emission, then compiled/run under
ASan/UBSan through the existing fixture Makefile.

An eighth runtime variant checks signed-history fallback with the same sample
count. Original observed-history variants remain unchanged and explicitly
reject the new skip marker. Existing shared/ordinary-writer histories and
AlwaysScanCommit regressions also reject it. Structural tests cover 14/16
history-member thresholds and 8/9 current-value limits, exact sparse tables,
and retention of the original sampling-only path.

The scoreboard covers distinct initial histories (only the final posedge
history initially mismatches), held levels with changed data, false-enable
sampling, mixed edges, repeated eval and repeated init. The original CPU,
multiclock, DPI, memory and wide-operation suites all still pass.

Logs: ptmp/grhsim_gate63_cpu_tests.log,
ptmp/grhsim_gate63_cpu_tests_initial_detail.log,
ptmp/grhsim_gate63_cpu_tests_final.log,
ptmp/grhsim_gate63_cpu_tests_memory_detail.log,
ptmp/grhsim_gate63_cpu_tests_complete.log,
ptmp/grhsim_gate63_cpu_tests_complete_detail.log.

Emitter SHA-256:
4aca24b14230bbacab8963187b93d56d1c46a17cefd6713d93f5dfc9ea0ad66a.
The schedule is unchanged and the restored gate62 reference remains
0b29bcee26710ee4de444743979228ac9eb761eae579f45f21fb24346f177e1a.

## Pending gates

Project-local make py_install is running before independent gate63 generation
and HDLBits. No XS candidate build/runtime or performance improvement is
proven yet. Preserve gate62; the final 50k legacy+5% gate remains incomplete.
