# Gate62 full O3 build

- Date: 2026-09-07
- Preconditions: [NO0636](./NO0636_grhsim_ir_cpu_gate62_generation_20260907.md)
  and [NO0637](./NO0637_grhsim_ir_cpu_wide_bitwise_hdlbits_gate_20260907.md).

The existing root xs_wolf_grhsim_ir_build_emu Makefile target compiled all
6255 model objects and linked the independent XiangShan harness successfully.
No direct compiler/build-system commands were used. The build retained
GRHSIM_MODEL_CXXFLAGS='-std=c++20 -O3', VM_BUILD_JOBS=8, project-local TMPDIR
and CCACHE_DIR. Source/model directory: ptmp/xs_emit_make_gate62; harness build:
ptmp/xs_gate62. Log: ptmp/grhsim_gate62_full_o3_build.log.

| Metric | Result |
| --- | ---: |
| Exit status | 0 |
| Wall time | 16:38.06 |
| User / system seconds | 6314.70 / 385.81 |
| Model objects | 6255 |
| Archive bytes | 179388298 |
| Executable bytes, following symlink | 161315168 |

The final three large translation units were tasks 5614, 5615 and 5786.
The original build session was polled until its successful terminal result,
without restarting it. No warning/error diagnostics were found in the log.
The executable entry resolves to ptmp/xs_gate62/emu/grhsim-compile/emu.

Candidate executable SHA-256:
0b29bcee26710ee4de444743979228ac9eb761eae579f45f21fb24346f177e1a.
Emitter remains
88a9605dc090737b48a27a9b8517c021f07376933f7df1592f8915c5b01ff5fb.
Preserved gate61 executable remains
314c2a9cdcd2050fc14a95a9135a123b9ca9c00ff992c41d205fe21a7c8b481c.

After the build terminated, the first ordinary-binary serial 1k baseline run
was started through make run_xs_wolf_grhsim_ir_emu. There is no candidate
runtime or performance result yet. Do not treat compilation as XS 50k proof.
