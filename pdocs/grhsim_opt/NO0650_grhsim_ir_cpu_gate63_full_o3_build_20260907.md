# Gate63 full O3 build

- Date: 2026-09-07
- Preconditions: [NO0648](./NO0648_grhsim_ir_cpu_gate63_generation_20260907.md)
  and [NO0649](./NO0649_grhsim_ir_cpu_stable_history_skip_hdlbits_20260907.md).

The existing root xs_wolf_grhsim_ir_build_emu Makefile target completed the
independent candidate build and harness link with exit 0. The original session
was polled through completion without restarting. No compiler/build-system
commands were invoked directly. Log: ptmp/grhsim_gate63_full_o3_build.log.

```sh
/usr/bin/time -v make --no-print-directory xs_wolf_grhsim_ir_build_emu \
  WOLF_ENV_SOURCED=1 PYTHON="$PWD/.venv/bin/python" \
  XS_GRHSIM_IR_BUILD=ptmp/xs_gate63 \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=ptmp/xs_emit_make_gate63 VM_BUILD_JOBS=8 \
  GRHSIM_MODEL_CXXFLAGS='-std=c++20 -O3' \
  TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" CCACHE_DIR="$PWD/ptmp/cpu_emit_ccache" \
  > ptmp/grhsim_gate63_full_o3_build.log 2>&1
```

| Metric | Result |
| --- | ---: |
| Exit status | 0 |
| Wall time | 16:38.27 |
| User / system seconds | 6173.72 / 386.41 |
| Model objects | 6255 |
| Archive bytes | 181565350 |
| Executable bytes, following symlink | 163291768 |

The final long-running translation units were tasks 5614, 5615 and 5786.
No warning/error diagnostics were found. Executable entry
ptmp/xs_gate63/emu/emu resolves to its own emu/grhsim-compile/emu.
Candidate SHA-256:
25980aaec27d340e8356180d96c109656565e3392d50aaeb0fd9c7ab8b51d56c.
The preserved gate62 executable remains
0b29bcee26710ee4de444743979228ac9eb761eae579f45f21fb24346f177e1a.

After successful build termination, the first ordinary gate62 baseline 1k
run started through make run_xs_wolf_grhsim_ir_emu. Two opposite-order serial
gate62/gate63 pairs will separate this candidate's short-window behavior
from the previous measurements. No candidate runtime or speedup is established
by compilation; actual 10k/50k and final legacy+5% gates remain pending.
