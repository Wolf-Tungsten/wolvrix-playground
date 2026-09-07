# Gate61 10k functional gate

- Date: 2026-09-07
- Serial pairs: [NO0631](./NO0631_grhsim_ir_cpu_gate61_1k_serial_pairs_20260907.md).

## Actual Run

The candidate's independent 10000-cycle run through the existing
run_xs_wolf_grhsim_ir_emu Makefile target completed with exit 0. Log:
ptmp/grhsim_gate61_o3_10000.log. Configuration remains coremark-2-iteration.bin,
NEMU difftest, seed 0, waveform off and 1000-cycle progress. No other simulation
or compilation overlapped the run; code and binaries were unchanged.

| Metric | Result |
| --- | ---: |
| Host time | 178709 ms |
| Instructions | 458 |
| cycleCnt / guest cycles | 9996 / 10001 |
| IPC | 0.045818 |
| Sampled commit PC | 0x80001cdc |
| Trap / limit PC | 0x800027c6 |

All ten strictly ordered progress records at 1000..10000 cycles match the first
ten in ptmp/grhsim_legacy_50000_serial_gate59.log after removing host_ms. The
extractor accepts the UART text preceding the 9k/10k progress records; no
non-line-start samples were lost. The three terminal records match
ptmp/grhsim_gate60_o3_10000.log after ANSI removal. NEMU was enabled at first
commit and reported no mismatch.

## Identity and Decision

Emitter SHA-256 remains
c50567fdc958e1be02db11e8975af171405d12112754edf92884a7535dc30480;
schedule remains
7f7f253903d2c7ffe6a79fc7f8f19cba5f353a5a80a00d107932ba5f1b53fd64.
Candidate executable:
314c2a9cdcd2050fc14a95a9135a123b9ca9c00ff992c41d205fe21a7c8b481c.
Preserved gate60 executable:
49d364aae00ebff82d92b1ed348dde26249b2a2dc25c8b98696e46619d5f0f2a.

Retain the dense history-range scan: it has its own full CPU/HDLBits gate,
independent mapping roundtrip and full O3 build, repeated 11.5-13.5% short-window
improvement and an actual 10k functional gate. Preserve gate59/gate60/gate61
artifacts. All sessions are now terminal; no probe remains active.

This 10k time is not a new paired legacy denominator and is not the 50k window.
The overall legacy+5% gate is still unsatisfied, and gate61 has no actual 50k
proof. Re-measure the remaining compute/commit costs before selecting the next
candidate; do not carry over gate60's phase proportions as current evidence.
DPI compute placement, optional events, void calls, independent histories and
the materialized schedule remain constraints for further work.
