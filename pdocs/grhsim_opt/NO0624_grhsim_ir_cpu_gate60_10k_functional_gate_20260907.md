# Gate60 10k functional gate

- Date: 2026-09-07
- Short-window result: [NO0623](./NO0623_grhsim_ir_cpu_gate60_1k_serial_pairs_20260907.md).

## Actual Run

The candidate's independent 10000-cycle Makefile run completed with exit 0.
Log: ptmp/grhsim_gate60_o3_10000.log. It used coremark-2-iteration.bin, NEMU
difftest, seed 0, waveform off and 1000-cycle progress. No compilation or other
simulation overlapped the run; no code or binary was changed during it.

| Metric | Result |
| --- | ---: |
| Host time | 205321 ms |
| Instructions | 458 |
| cycleCnt | 9996 |
| Guest cycles | 10001 |
| IPC | 0.045818 |
| Sampled commit PC | 0x80001cdc |
| Trap / limit PC | 0x800027c6 |

All ten strictly ordered progress records at 1000 through 10000 cycles match
the first ten records in ptmp/grhsim_legacy_50000_serial_gate59.log after
removing host_ms. Extraction accepts UART/ANSI prefixes and includes the 9k
and 10k records after actual instruction execution begins. The three terminal
records match ptmp/grhsim_gate59_o3_10000.log after stripping ANSI. NEMU was
enabled at first commit and reported no mismatch.

## Identity and Remaining Work

Emitter SHA-256 before/after:
1efe13e9e6faa87b9e0da116df971d5ca8058eb8ab3be01d4086047d3c186f50.
Candidate executable:
49d364aae00ebff82d92b1ed348dde26249b2a2dc25c8b98696e46619d5f0f2a.
Schedule remains gate59's
7f7f253903d2c7ffe6a79fc7f8f19cba5f353a5a80a00d107932ba5f1b53fd64.
The preserved gate59 executable remains
e3447dc332f3fd6649da7a1b1a59add38733080b62bb376c620c2f0cab057dbd.

All sessions are terminal. Keep the use-site string optimization: it has full
CPU/HDLBits coverage, independent full-model generation/build, repeatable
16.4-18.0% short-window improvement and its own 10k functional gate. The 10k
time is not a new paired legacy performance denominator. Gate60's actual 50k
and final legacy+5% threshold remain unverified; the overall goal is open.

Next work must measure the remaining costs on this candidate rather than
reuse the pre-string phase proportions as current evidence. Continue to
preserve DPI compute placement, optional events, actual void calls and history
sampling. Any new implementation should remain a separately measured candidate;
retain gate59 and gate60 artifacts as ordinary-binary references.
