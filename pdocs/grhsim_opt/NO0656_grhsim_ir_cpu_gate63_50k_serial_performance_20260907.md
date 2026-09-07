# Gate63 50k serial performance

- Date: 2026-09-07
- Functional gate: [NO0655](./NO0655_grhsim_ir_cpu_gate63_50k_functional_gate_20260907.md).
- Status: actual 50k functionality passed; legacy+5% performance failed.

## Fresh serial comparison

The gate63 IR process exited 0 before the ordinary legacy process started.
Both used existing run-only Makefile targets with coremark-2-iteration.bin,
NEMU difftest, seed 0, 50000-cycle limit, waveform off and thousand-cycle
progress. Neither measurement overlapped another build or simulation.

```sh
make --no-print-directory run_xs_wolf_grhsim_emu WOLF_ENV_SOURCED=1 \
  XS_GRHSIM_BUILD=build/xs/grhsim XS_SIM_MAX_CYCLE=50000 \
  XS_WAVEFORM=0 XS_WAVEFORM_PATH= XS_LOG_DIR="$PWD/ptmp" \
  XS_PROGRESS_EVERY_CYCLES=1000 RUN_ID=legacy_50000_serial_gate63 \
  TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" \
  > ptmp/grhsim_legacy_50000_serial_gate63.log 2>&1
```

Both processes exited 0. Each log contains exactly fifty ordered samples
and three terminal records, all functionally identical after removing progress
host_ms/UART prefixes and terminal ANSI. NEMU was enabled and reported no
mismatch. Final state: 73580 instructions, cycleCnt 49996, guest 50001,
IPC 1.471718, sampled commit PC 0x800012f8, trap/limit PC 0x80001312.
IR log: ptmp/grhsim_gate63_o3_50000.log. The full comparison exited 0;
its empty report is ptmp/grhsim_gate63_50k_serial_diff.log.

## Speed gap

| Metric | Result |
| --- | ---: |
| Gate63 IR host time | 879581 ms |
| Fresh serial legacy host time | 154286 ms |
| IR / legacy elapsed time | 5.700977 |
| IR overhead | 470.098% |
| Legacy times 1.05 | 162000.30 ms |
| Further IR time reduction required | 81.5821% |
| Further speedup required to reach that threshold | 5.429502x |

The 50k functional window passes but the plan's performance gate does not.
This is not completion of the entire CoreMark program. Gate62's historical
1024849 ms versus gate63's 879581 ms is a 14.1746% reduction, not a fresh
gate62/gate63 50k A/B pair. Controlled short-window evidence remains NO0651.
There is no fixed CPU affinity/frequency control or uniform fresh rebuild of
both routes; the large gap is conclusive, while fine statistical claims are not.

All three executable fingerprints remain unchanged:

```text
gate63 25980aaec27d340e8356180d96c109656565e3392d50aaeb0fd9c7ab8b51d56c
gate62 0b29bcee26710ee4de444743979228ac9eb761eae579f45f21fb24346f177e1a
legacy c211cf9435d867bb4bbda6df73173389106fa5255a3f8af7635d9879221a88cb
```

## Updated user direction

All measurement sessions are terminal and the complete performance report
has been presented. The user subsequently superseded the earlier pause
request: first report performance, then investigate and fix in three directions:

1. Partition/block effectiveness and order-of-magnitude parity with legacy.
2. Overall emitted C++ structural parity with legacy.
3. Poorly implemented helpers, using the legacy pointer/out-buffer strategy.

Preserve the verified gate63 model/binary for comparisons. No DPI/event-policy
change is authorized. Continue this targeted audit from concrete generated
artifacts and source evidence, then repair identified causes; the active goal
and final performance gate remain incomplete.
