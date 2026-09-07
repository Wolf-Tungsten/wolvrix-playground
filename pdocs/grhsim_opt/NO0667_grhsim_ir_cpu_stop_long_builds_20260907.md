# Stop long-running builds and correct benchmark isolation

- Date: 2026-09-07
- Latest user instruction: stop the unacceptable 21-hour and 56-minute builds.
- Status: both stopped; host process verification finds no compiler/build processes.

## Termination

Gate64 original session 95253 received Ctrl-C and returned exit 130. It had
advanced to task23, but did not complete/link. Preserve partial artifacts and
ptmp/grhsim_gate64_full_o3_build.log; this is an intentionally aborted experiment,
not evidence of compiler failure or runtime benefit.

Host-level process inspection discovered the old gate26 process group 2925931.
Its root make PID was 2925932; nested build PIDs were 2926323,2926482,2926764,
2926765, with clang++ PID 2926826 compiling grhsim_SimTop_task_60.cpp. Root
elapsed time was 77725 seconds and clang elapsed time 77620 seconds with
99.9% CPU. It referenced the old /tmp/xs_emit_make_gate26 model directory.
SIGTERM was sent to the verified process group 2925931. A subsequent host-level
ps query for clang++,clang,cc1plus,g++,gcc,make,ninja,cmake returned no processes;
the explicit seven-PID query also returned none. No source, binary or log files
were deleted. Gate66 build and functional sessions were already terminal.

## Performance record correction

Earlier isolation claims checked known execution sessions, not all host build
processes, and missed the long-lived gate26 compiler. In particular, NO0656's
claim that neither 50k run overlapped a build is invalid. The observed elapsed
times 879581/154286 ms and their ratio 5.700977 remain recorded observations,
but are NOT a clean isolated benchmark. Other earlier claims of no concurrent
build load during this surviving process's lifetime likewise require review.
Functional log comparisons remain valid. Gate66's 10k run was already explicitly
classified as build-overlapped and unsuitable for performance comparison.

Do not silently rewrite historical records: this entry supersedes their
isolation assertions. Future performance runs require host-level verification
that no old build/compiler process remains, not merely checking known session
handles. No further build, simulation or benchmark is started in this turn.
The user stop instruction takes precedence over earlier instructions to await
gate64 or proceed automatically to timing pairs. New candidate timing and the
final performance gate remain unverified.
