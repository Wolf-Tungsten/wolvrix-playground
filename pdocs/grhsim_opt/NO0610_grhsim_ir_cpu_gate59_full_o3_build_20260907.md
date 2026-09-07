# Gate59 full O3 build

- Date: 2026-09-07
- Generation: [NO0608](./NO0608_grhsim_ir_cpu_gate59_generation_20260907.md).
- HDLBits: [NO0609](./NO0609_grhsim_ir_cpu_inactive_edge_hdlbits_gate_20260907.md).

## Result

The full independent model and harness build exited 0, producing all 6255 model
objects, the archive, and ptmp/xs_gate59/emu/emu. No source/object was copied
from the preserved baselines and no build was restarted on quiet output.

```sh
/usr/bin/time -v make --no-print-directory xs_wolf_grhsim_ir_build_emu \
  VM_BUILD_JOBS=8 GRHSIM_MODEL_CXXFLAGS='-std=c++20 -O3' WOLF_ENV_SOURCED=1 \
  XS_GRHSIM_IR_BUILD=ptmp/xs_gate59 XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=ptmp/xs_emit_make_gate59 \
  TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" CCACHE_DIR="$PWD/ptmp/cpu_emit_ccache" \
  > ptmp/grhsim_gate59_full_o3_build.log 2>&1
```

| Metric | Gate59 | Gate58 |
| --- | ---: | ---: |
| Wall | 16:51.93 | 16:46.94 |
| User seconds | 6460.19 | 6396.31 |
| System seconds | 384.88 | 384.40 |
| Maximum RSS KiB | 930464 | 923916 |
| Model archive bytes | 182956358 | 182872038 |
| emu bytes | 164242592 | 164234400 |

The final outstanding objects were task_5614/task_5615/task_5786. The same
live build session was monitored until they completed and linking succeeded.
The compile and binary-size costs are slightly higher; no improvement is claimed
from code generation alone. HDLBits briefly overlapped this build, so this is
not a tightly controlled compiler benchmark.

## Next Measurement

All builds and HDLBits simulations are terminal. A serial run-only Makefile
comparison starts with gate58, then gate59, using 1000 cycles, seed 0, unchanged
CoreMark/NEMU, no waveform and logs/TMPDIR under ptmp. This short comparison
does not replace actual 10k/50k validation or the final performance requirement.
