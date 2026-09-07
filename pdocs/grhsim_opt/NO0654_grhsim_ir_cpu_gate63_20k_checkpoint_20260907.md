# Gate63 20k checkpoint

- Date: 2026-09-07
- Runbook: [NO0653](./NO0653_grhsim_ir_cpu_gate63_50k_runbook_20260907.md).

The original 50000-cycle process passed host cycle 20000 with 14121 retired
instructions, commit PC 0x8000043a, trap PC 0x80000440 and host_ms 322929.
Its first twenty ordered progress samples match the retained legacy 50k
reference after removing only host_ms and UART prefixes. The following 21k
sample also matches. No NEMU mismatch has been reported.

Log: ptmp/grhsim_gate63_o3_50000.log. The original process handle was polled
and remains active. It is continuing to the requested 50k limit unchanged;
no rebuild, probe, concurrent simulation or shortened limit was introduced.
This checkpoint is not a terminal functional or performance result.

## User-requested pause

The user requested stopping after this measurement and reporting the current
speed gap. Complete the ongoing IR 50k and its paired serial legacy 50k,
compare complete functional/terminal records and actual elapsed times, then
stop. Do not start further profiling, optimization, tests, builds or simulations
beyond that paired measurement. Report absolute times, the IR/legacy ratio
and the remaining gap to legacy+5%. The goal is not complete merely because
work pauses.
