# Local activity word structure alignment

- Date: 2026-09-07
- Scope: generated compute structure, following legacy activeWordFlags.
- Status: implemented; full CPU regression running, runtime benefit unmeasured.

## Evidence and design

Legacy emitActivationStatements directs later bits in the current word into
local activeWordFlags, while current/earlier bits and other words remain global.
Its word dispatch loads/clears global activity, consumes local bits in order,
then ORs unconsumed local bits back. IR previously reloaded global cpu_flags
for every supernode test/clear. Source census of gate63 compute tasks found
2510273 activation statements and 1856799 unique word writes within contiguous
activation runs, leaving 653474 statically mergeable writes. This is not an
instruction count: the optimizer may already combine adjacent ORs.

The IR emitter now uses the same local-byte protocol. Activation receives the
current supernode as an explicit emitter context. Only later bits of the same
word use cpu_active_word; other targets retain global writes, merged by offset.
Helper chunks receive the same local byte by reference along with their frame.
DPI result publication also receives this context without changing call guards,
event history sampling or compute-phase placement. Domain arms are unchanged.

## Invariants and verification plan

- No partition, task order, active ID or mapping changes.
- A later same-word activation is visible during the current word dispatch.
- Current/earlier bits remain queued globally and are not overwritten on exit.
- Cross-word activation and domain arms retain their original storage/phase.
- All helper chunks share one local byte; there is no per-helper activity copy.
- Reserve cpu_active_word against public port collisions.

Wide-activity generated tests now cover both inline and split-helper emission,
each in tracked/local modes, with structural checks for shared local activity.
Existing multiclock, DPI, memory and state tests remain required. Current log:
ptmp/grhsim_local_activity_cpu_tests.log. Gate65 artifacts preserve the preceding
helper-only implementation for independent comparisons. No runtime speedup is
claimed from the static census or this source edit.
