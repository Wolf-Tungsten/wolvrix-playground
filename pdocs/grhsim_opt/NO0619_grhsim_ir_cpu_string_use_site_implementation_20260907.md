# CPU immutable string use-site implementation

- Date: 2026-09-07
- Design/evidence: [NO0618](./NO0618_grhsim_ir_cpu_gate59_task_profile_20260907.md).

## Implementation

cpu_emit.cpp collects string core.compute.constant expressions by ValueId,
resolves reads at use sites and skips their standalone assignments and
local/boundary string bindings. The expression uses existing escaping and
std::string value semantics. This follows legacy staticConstStringExpr/valueRef
in avoiding ordinary mutable storage, but does not yet introduce raw-literal
specializations or a shared constant pool. The source model and mapping are
unchanged. Dynamic values, output/inout publication and hold, void calls,
conditions, events and sampling are unchanged; no ingest or phase changes.

The initially active compute graph establishes all consumers. An immutable
constant has no later value changes to propagate; no schedule tables are
removed. Unused reserved slots remain part of the serialized layout.

## Verification

Existing Makefile targets test_grhsim_cpu_schedule and test_grhsim_cpu_emit
passed. The first CPU suite took 27.84 s; after adding local-string lifetime
counts, the final full CPU suite passed in 28.26 s. Logs:

- ptmp/grhsim_gate60_cpu_tests.log
- ptmp/grhsim_gate60_cpu_tests_initial_detail.log
- ptmp/grhsim_gate60_cpu_tests_final.log
- ptmp/grhsim_gate60_cpu_tests_final_detail.log

New regression uses a shared 256-character string plus quote, backslash,
newline, carriage return and tab. A real void DPI observes it on posedge;
a separate inout DPI mutates its copy. Across 384 samples/three resets, counts
equal the existing independently expected posedge count, the shared output
remains immutable, and inout results hold on false guards. Existing dynamic
string/real/wide calls, eventless return/void calls, system tasks, all CPU
multiclock/CDC/RAM/state/history regressions remain covered by the full suite.
Structural checks require both local and boundary constants, no constant-slot
assignments/boundary bindings, exactly the expected dynamic local string
objects and a literal expression at the actual void call site.

Emitter SHA-256:
1efe13e9e6faa87b9e0da116df971d5ca8058eb8ab3be01d4086047d3c186f50.
No helper ABI or legacy implementation changed. git diff --check passed in
both repositories (untracked source files are additionally compiled by tests).

## Remaining Gates

Project-local make py_install is in progress. Next: independent gate60
generation/fresh roundtrip, unchanged IR/mapping comparison, HDLBits full suite,
O3 build and serial 1k baseline/candidate measurements. There is no runtime
speedup claim yet, and gate59's 50k proof cannot establish gate60 correctness.
The overall legacy+5% performance requirement remains unsatisfied.
