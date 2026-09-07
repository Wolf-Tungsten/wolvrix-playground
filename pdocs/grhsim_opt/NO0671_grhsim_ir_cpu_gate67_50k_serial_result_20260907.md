# Gate67 CoreMark 50k serial result and checkpoint

- Date: 2026-09-07
- Candidate: NO0669/NO0670, three emit-shape repairs.
- Status: functional gates passed; performance gap remains open.
- User requested recording progress and a commit after this test pair.

## Fresh measurements

| Ordinary O3 executable | Host time | Relative elapsed time |
| --- | ---: | ---: |
| Gate67 IR CPU | 659545 ms | 5.538159895 |
| Retained legacy | 119091 ms | 1.000000000 |

The IR candidate takes 453.8160% more time; its throughput is 18.0565% of
legacy's for this window. The three emit defects are repaired, but this is
not near legacy parity and does not meet the broader legacy+5% objective.
Do not infer a clean before/after speedup from gate63's old 879581/154286ms
pair: its no-concurrent-build premise was invalidated in NO0667.

Both runs use CoreMark coremark-2-iteration.bin, NEMU difftest, seed 0,
50000 cycles, waveform/commit trace off, and progress every 1000 cycles.
Gate67 original session 28552 exited 0 before the legacy run-only Makefile
target started in session 8956, which also exited 0. All earlier build and
HDLBits sessions had completed; host process checks before the IR run and
between runs reported no compilers/build tools/emulators. No builds or other
simulations were started during this pair. Additional IR/mapping regression
checks for the commit were run only after both measurements finished.

## Functional identity

All fifty ordered progress records match after removing only host_ms and
extracting the progress tag after any UART prefix. Three ANSI-normalized
terminal records also match:

- limit PC: 0x80001312
- instrCnt=73580, cycleCnt=49996, IPC=1.471718
- Seed=0, Guest cycle spent=50001

Final sampled commit PC is 0x800012f8. Both progress and terminal diffs exited
0 and produced empty difference logs. Gate67 also matches all fifty progress
records of the retained historical functional reference.

Artifacts remain under ptmp:

- grhsim_gate67_o3_50000.log
- grhsim_legacy_50000_serial_gate67.log
- grhsim_gate67_50k_serial_progress_identity.log
- grhsim_gate67_50k_serial_terminal_identity.log
- grhsim_gate67_50k_historical_identity.log

Executable fingerprints remain exactly those in NO0670. No probes, extra
instrumentation, source changes or binary replacements occurred during runs.

## Checkpoint scope

Verification: CPU emitter 58.52s, schedule 0.01s, HDLBits 162/162, same IR
JSON and stable roundtrip, full O3 link 16:13.07, NEMU/50k identity above.
The added make test_grhsim_cpu_mapping target also passed both IR and mapping
suites (0.01s each; ptmp/grhsim_gate67_mapping_commit_tests.log).

The CPU backend foundation, shared legacy runtime extraction and CPU tests
were still uncommitted before these repairs. The checkpoint includes these
direct dependencies so the emitter commit is buildable, plus the Makefile/
script integration and HDLBits backend selector. Submodule commits are
recorded by one parent-repository checkpoint; no push is requested.

Do not include ptmp/build outputs, vrt/, unrelated PHR analysis, or the
pre-existing draft README/simulation-model deletions. Preserve these unrelated
worktree changes. The CPU progress documents and their numbered history are
included without rewriting old measurement records.

Remaining scope: packing stays at the prior explicit target_batch_count=0
(5569 compute/515 commit functions); this pair isolates emitter changes and
does not demonstrate default-64 large-function compilation parity. Read
aliases retain unused layout slots, grouping is per supernode/helper chunk,
and cell staging retains deferred multiwriter publication. Further performance
work needs fresh attribution, not a claim that the overall legacy gap is fixed.

Submodule checkpoints created after verification:

- wolvrix: dda0ce3, CPU backend and legacy-aligned emission (66 files).
- testcase/hdlbits: e9221bb, IR backend Makefile selector (one file).

The parent checkpoint records both revisions and this result. Neither
submodule nor parent is pushed by this task.
