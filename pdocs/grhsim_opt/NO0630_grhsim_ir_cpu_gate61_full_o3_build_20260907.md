# Gate61 full O3 build

- Date: 2026-09-07
- Generation: [NO0628](./NO0628_grhsim_ir_cpu_gate61_generation_20260907.md).
- Broad regression: [NO0629](./NO0629_grhsim_ir_cpu_history_scan_hdlbits_20260907.md).

The independent xs_wolf_grhsim_ir_build_emu Makefile target completed with exit
0, VM_BUILD_JOBS=8 and GRHSIM_MODEL_CXXFLAGS='-std=c++20 -O3'. All 6255 model
objects and the harness were compiled/linked; no baseline objects were copied.
The original session was observed until all three final large tasks finished.

| Metric | Result |
| --- | ---: |
| Wall time | 16:35.72 |
| User / system seconds | 6301.44 / 385.99 |
| Archive bytes | 179181250 |
| Executable bytes (dereferenced) | 161143136 |

Log: ptmp/grhsim_gate61_full_o3_build.log. Executable entry:
ptmp/xs_gate61/emu/emu. SHA-256:
314c2a9cdcd2050fc14a95a9135a123b9ca9c00ff992c41d205fe21a7c8b481c.
Emitter SHA-256 remains
c50567fdc958e1be02db11e8975af171405d12112754edf92884a7535dc30480.

Additional source check confirms all 95 changed files have byte-identical
contents after their entry-condition line. Thus history sampling, batching and
the original payload are unchanged, not merely structurally similar.

Archive/executable sizes increase modestly versus gate60; neither size nor build
time establishes runtime benefit. All build and HDLBits sessions are terminal.
The first serial ordinary-binary 1k pair is now running, gate60 baseline first;
opposite-order pairing follows. New 10k/50k and final performance remain pending.
