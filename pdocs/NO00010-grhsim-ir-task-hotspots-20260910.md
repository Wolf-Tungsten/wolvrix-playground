# GrhSIM-IR Compute/Commit Function Hotspots

- Date: 2026-09-10
- Status: VALIDATED / DIAGNOSTIC HOTSPOTS; one 50k measurement complete
- Root baseline: `1b20c5c`
- GrhSIM source: `93d55ae7d53d592c5d20e5f83863f1241fb0fcbb`

## Question and method recorded before execution

The full phase measurement attributes 56.1832% of eval time to compute, 38.7506% to commit, and 5.0388% to publication. It does not distinguish evaluator dispatch/guard overhead from task bodies, or identify hot functions. This step collects one statistical CPU profile of the already validated executable, then maps samples to native functions and generic generated task IDs. It implements no simulator optimization and changes no frozen GRH/pass or XiangShan/workload source.

The host has `perf_event_paranoid=4`; the prior frame-init report records that perf sampling was unavailable under this policy. The installed gperftools `libprofiler.so.0` provides in-process SIGPROF CPU-time sampling without kernel perf privileges or adding simulator worker threads. Use it through the existing Make run target's execution prefix, at requested frequency 199 Hz. Interpret flat interrupted-PC samples, not inclusive call stacks, because the production model was not rebuilt with frame pointers or debug information. Resolve PIE addresses using the profile's executable mapping and ELF symbols; account explicitly for external-library and unresolved samples. Periodic sampling, profiler perturbation, signal coalescing, and optimized/inlined code limit attribution. A function's samples do not by themselves identify its source operations or prove an optimization is safe.

Reuse the instrumented-source executable validated in the phase report (full SV generation 606.29 s; 32-job compilation 477.30 s). Both built-in runtime and outer phase timers remain off. Fixed input is XiangShan `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`, CoreMark binary SHA-256 `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`, top SimTop, DIFFTEST/NEMU, 50,000 cycles, CPU 2, `XS_EMU_THREADS=1`, waveform/commit/RAM traces off. Revision and input hash were rechecked. Reuse archived gsim 20.640 s. The same executable's unprofiled Host reference is 287.162 s; retain the conservative preselected 419.92275 s kill deadline from the 279.9485 s best baseline. No generation or compilation is required for this measurement.

## Sampling command

```bash
mkdir -p ptmp/task_hotspots_20260910_01
WOLF_ENV_SOURCED=1 XS_EMU_THREADS=1 EMU_PHASE_TIMING=0 EMU_RUNTIME_PROFILE=0 make --no-print-directory run_xs_wolf_grhsim_ir_emu RUN_ID=task_hotspots_20260910_01 XS_GRHSIM_IR_BUILD=ptmp/phase_profile_50k_20260910_01/flow XS_LOG_DIR=ptmp/task_hotspots_20260910_01/logs XS_SIM_MAX_CYCLE=50000 XS_EMU_THREADS=1 XS_EMU_CPU=2 XS_PROGRESS_EVERY_CYCLES=0 XS_WAVEFORM=0 XS_COMMIT_TRACE=0 XS_RAM_TRACE=0 XS_WAVEFORM_PATH= WOLVRIX_GRHSIM_WAVEFORM=0 XS_EMU_PREFIX="timeout --signal=KILL 419.92275s /usr/bin/time -p -o $PWD/ptmp/task_hotspots_20260910_01/run.time taskset -c 2 env CPUPROFILE=$PWD/ptmp/task_hotspots_20260910_01/cpu.prof CPUPROFILE_FREQUENCY=199 LD_PRELOAD=/lib/x86_64-linux-gnu/libprofiler.so.0" > ptmp/task_hotspots_20260910_01/run.log 2>&1
```

The execution timer includes the taskset/env launcher and emulator, excluding Make setup and any build. Unlike the archived phase run, this prefix does not include stdbuf. The profiler is loaded only into emu. Temporary paths specify execution configuration, not archival evidence.

## Runtime result

The single sampled run completed with exit 0: **Host 283.389 s**, execution wall **283.46 s**, user **283.32 s**, sys **0.05 s**. NEMU difftest was enabled, and the endpoint was **73,580 instructions, cycleCnt 49,996, terminal PC 0x80001312, guest cycles 50,001**. These match both prior phase runs and the scalar-staging baseline. Complete output contained no mismatch, ABORT, bad trap, assertion failure, or segmentation fault. Stop-loss result is NONE against the preselected 419.92275 s threshold.

The sampled Host time is 1.3139% below the same executable's archived unprofiled 287.162 s, and 1.2290% above the best baseline mean 279.9485 s. This does not indicate negative profiling overhead or a speedup: it is one run under a different instrumentation setting, with uncontrolled host drift and a changed launcher. The old scalar runs already span 8.253 s. Keep the 279.9485 s best performance baseline and gsim 20.640 s reference unchanged. Generation and compilation were not rerun; this step reuses the previously validated 606.29/477.30 s build evidence and does not claim new build timing.

The profiler printed:

```text
PROFILE: interrupts/evictions/bytes = 56397/49177/4298648
```

The completed profile file contains 53,273 weighted stack records, **56,397 flat samples**, and a **5,025 microsecond** sampling period. Summed sample weights exactly equal the profiler's interrupt count; `56397 * 5025 / 1e6 = 283.394925 s` is nominal sampled CPU time. Evictions are profile aggregation-table flushes, not an additional sample population; no dropped-sample quantity is inferred from that field. Flat attribution uses only the first interrupted PC of each record and does not add caller frames. The profiler measures from library startup through normal process shutdown, a slightly different scope from emulator Host timing.

## Analysis implementation and validation

Added the read-only `analyze_grhsim_cpu_profile` Make target and a small Python analyzer for this installed profiler's 64-bit little-endian v0 format. It requires a complete header and end record, valid appended memory maps, the exact expected sample count, and a consistent main executable load base. ELF LOAD virtual addresses must equal file offsets for its intentionally narrow PIE mapping rule; `readelf -lW` verified this executable satisfies that rule. `nm -n -S -C --defined-only` supplies native function bounds. Samples outside those bounds are retained as unresolved; external mappings are retained by library name without guessing private symbols.

The analyzer reads task calls from the existing generated evaluator's contiguous compute/commit segments and checks exact coverage against generated task files: **5,595 tasks = 5,081 compute + 514 commit**. Task IDs classify observations in this fixed generated model; they are not module-name selectors or optimization rules. The analyzer makes no use of workload/module names. Two focused reader tests verify weighted leaf-only attribution and rejection of truncated, unsupported, or malformed profiles. All script execution goes through Make:

```bash
WOLF_ENV_SOURCED=1 make --no-print-directory test_grhsim_cpu_profile > ptmp/task_hotspots_20260910_01/reader-test.log 2>&1
WOLF_ENV_SOURCED=1 make --no-print-directory analyze_grhsim_cpu_profile GRHSIM_CPU_PROFILE=ptmp/task_hotspots_20260910_01/cpu.prof GRHSIM_CPU_PROFILE_BINARY=ptmp/phase_profile_50k_20260910_01/flow/emu/emu GRHSIM_CPU_PROFILE_MODEL=ptmp/phase_profile_50k_20260910_01/flow/model/grhsim_SimTop.cpp GRHSIM_CPU_PROFILE_SAMPLES=56397 > ptmp/task_hotspots_20260910_01/analysis.log 2>&1
```

Both Make invocations exited 0. The two unit tests passed; the actual-profile analysis reported `PASS: profile terminator, mappings, ELF layout, task coverage, symbol bounds, sample totals`. This validates input accounting and the mapping used for this executable; it is not a general profiler-format or unwinding certification. There is no inclusive-call-tree claim.

## Flat sample results

Percentages below use all 56,397 samples as denominator. These are sampled PC locations, not the same accounting as elapsed phase timers: out-of-line helpers and libc calls appear separately, while inlined work remains in its containing function.

| Native location | Samples | Percent |
|---|---:|---:|
| Compute task functions | 26,711 | 47.3624% |
| Commit task functions | 20,080 | 35.6047% |
| Other main-executable functions/helpers | 5,223 | 9.2611% |
| External mappings | 2,563 | 4.5446% |
| Main evaluator | 1,718 | 3.0463% |
| Main executable, no bounded function match | 86 | 0.1525% |
| No matching mapping | 16 | 0.0284% |
| Total | 56,397 | 100% |

Unresolved/unmapped PCs account for 102 samples (0.1809%). Of the external samples, 2,562 are in libc; their private function names were not resolved, so they cannot be assigned to memcpy, memset, memcmp, or another operation from this profile alone.

| Selected hottest native function or mapping | Samples | Percent |
|---|---:|---:|
| `cpu_write_scalar<bool>` | 3,507 | 6.2184% |
| libc mapping, all sampled PCs | 2,562 | 4.5428% |
| `eval()` | 1,718 | 3.0463% |
| Commit task 5141 | 890 | 1.5781% |
| Commit task 5121 | 576 | 1.0213% |
| Commit task 5130 | 549 | 0.9735% |
| Commit task 5135 | 546 | 0.9681% |
| Commit task 5140 | 535 | 0.9486% |
| Commit task 5134 | 531 | 0.9415% |
| Commit task 5136 | 528 | 0.9362% |
| Commit task 5137 | 523 | 0.9274% |
| Commit task 5131 | 519 | 0.9203% |
| Commit task 5129 | 512 | 0.9079% |
| `cpu_stage_bytes` | 406 | 0.7199% |
| `cpu_stage_cell` | 357 | 0.6330% |

There are **3,367 sampled compute task functions**. The top ten are 5048:173, 5046:156, 5077:155, 5044:149, 5042:142, 5047:139, 5045:137, 5049:136, 5039:130, and 5041:122 samples. Together they contain **1,439 samples = 2.5516% of all samples, 5.3873% of compute-task samples**. No individual compute task exceeds 0.307% of the whole profile. Small per-task sample counts do not support fine-grained ordering claims.

There are **177 sampled commit task functions**. The top ten commit tasks shown above total **5,709 samples = 10.1229% of all samples, 28.4313% of commit-task samples**. Commit work is more concentrated than compute work in this run, but even the hottest commit task accounts for only 1.5781% of total flat samples. Unobserved tasks are not proved inactive; they may execute without being sampled.

## Source and instruction checks

Read-only source/disassembly inspection checked the leading observations against this exact executable. The scalar helper retains the effective-shadow behavior from the validated optimization:

```cpp
current = dirty[state] ? shadow[offset] : visible[offset];
if (current == next) return;
if (!dirty[state]) { enqueue_pending(...); dirty[state] = 1; }
shadow[offset] = next;
```

`nm` identifies a standalone 0x20a-byte bool specialization. Its disassembly saves six registers before testing the dirty byte and comparing the requested value. Leading sampled offsets include +0x24 (938 samples, branch after dirty-byte comparison), +0x1 (862, function prologue), +0x14 (275), and +0x1ef (222, return path). Thus an out-of-line scalar staging helper is a measurable cost even though it skips unchanged writes. Sampling at these instructions does not establish branch frequencies, cache-miss causes, or the fraction of unchanged writes. It does not justify removing the effective-shadow comparison.

Generated commit task 5141 begins with inactive-edge history sampling and many scalar-history writes. Task 5121 begins with a stable-history scan annotated `histories=8192 groups=2`, followed by inactive-edge history handling. Sampled compute task 5048 includes guarded event checks and scalar history updates. These observations make event-history work a concrete area for later semantic analysis, but do not measure its total dynamic cost across all tasks. They must not be turned into module-name-specific rules or permission to remove assertions/test behavior.

The evaluator's samples also include publication code. For example, sampled offset +0x19224 is a branch in an inlined loop over `cpu_targets`; adjacent instructions update next-arm flags. A standalone `cpu_publish` symbol exists, but no flat sample matched it in this run. Zero samples there does not mean publication is free: the earlier phase timer measured it at 5.0388%, and compiler inlining plus external/helper attribution explains why the two accounting methods need not align. Consequently **3.0463% is the observed share of the entire evaluator function, not a pure dispatcher cost**. Its dispatch/guard instructions occupy only part of that bucket, so a dispatcher-only explanation for the roughly sevenfold gap to 40 s is unsupported by this sample.

## Decision and limits

Complete this one search step as a validated diagnostic measurement. It establishes that compute cost is broadly distributed, commit work is relatively more concentrated, and a generic scalar history/staging helper is independently visible. It provides evidence against assuming that the remaining runtime is primarily evaluator dispatch. No simulator optimization was implemented or tested, and no new speedup is claimed.

If work is resumed in a later user-authorized step, the evidence supports examining the semantics and repeated work of event-history sampling/scanning across compute and commit before choosing a transformation. Such work must preserve history visibility, sampling conditions, simultaneous events, and publication/activation semantics. This report does not select or validate that future transformation, and no additional candidate search begins in this execution.

The profile is one periodic sample run at requested 199 Hz, without hardware stall counters or reliable inclusive stacks. Interrupt delivery can coalesce or alias with regular simulator work; percentages are diagnostic approximations. Private libc symbols remain unresolved. Inlined helpers cannot be separated from their containing tasks with this binary alone. The comparison has uncontrolled noise, so profiled time is not a replacement performance baseline. The absolute about-40 s objective remains unmet; the overall goal remains incomplete.

## Archive

References: [phase measurement](NO00009-grhsim-ir-phase-profile-20260910.md), [scalar baseline](NO00008-grhsim-ir-candidate-scalar-stage-elision-20260910.md), [frame-init report](NO00002-grhsim-ir-candidate-frame-init-20260910.md), [analyzer](../scripts/grhsim_cpu_profile.py), [reader tests](../scripts/test_grhsim_cpu_profile.py), [Makefile](../Makefile), and [goal](grhsim-ir-xiangshan-coremark-50k.goal.md)/[index](grhsim-ir-xiangshan-coremark-50k.index.md). The new analysis tools, this self-contained report, and index are committed together in the containing root archive. All links are to tracked files or files added in that archive. No profile binary or generated model is included. Per the user's explicit instruction, stop after this one search step and its archive; do not start a follow-up candidate.
