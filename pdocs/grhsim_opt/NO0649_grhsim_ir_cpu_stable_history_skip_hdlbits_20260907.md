# Stable-history skip HDLBits gate

- Date: 2026-09-07
- Candidate: [NO0647](./NO0647_grhsim_ir_cpu_stable_history_skip_implementation_20260907.md).
- XS generation: [NO0648](./NO0648_grhsim_ir_cpu_gate63_generation_20260907.md).

## Result

The existing root Makefile full HDLBits IR regression exited 0. The log
contains exactly 162 ordered passing records, DUT 001 through DUT 162, with
no missing or duplicate case IDs. No failure, compiler-error or sanitizer-error
diagnostics were found. Artifacts: ptmp/hdlbits-grhsim-ir-BVXt5e.
Log: ptmp/grhsim_gate63_hdlbits.log.

```sh
make --no-print-directory run_all_hdlbits_grhsim_ir_tests WOLF_ENV_SOURCED=1 \
  PYTHON="$PWD/.venv/bin/python" SKIP_PY_INSTALL=1 \
  TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" CCACHE_DIR="$PWD/ptmp/cpu_emit_ccache" \
  > ptmp/grhsim_gate63_hdlbits.log 2>&1
```

This checks the current installed candidate through the IR HDLBits path;
it is not an XS runtime or performance gate. The targeted stable-history
sanitizer and shared/observed-history fallback tests remain the evidence
reported in NO0647, not an inference from these small HDLBits designs.

## Handoff state

Generation and HDLBits sessions both reached successful terminal results;
no build or simulation session remains running. Emitter and schedule still
match their recorded SHA-256 fingerprints:

- cpu_emit.cpp: 4aca24b14230bbacab8963187b93d56d1c46a17cefd6713d93f5dfc9ea0ad66a
- cpu_schedule.cpp: 7f7f253903d2c7ffe6a79fc7f8f19cba5f353a5a80a00d107932ba5f1b53fd64

Both root and wolvrix tracked whitespace checks passed. Gate63 generated
model is ready at ptmp/xs_emit_make_gate63. Its independent harness has not
been built: ptmp/xs_gate63/emu does not exist. The next step is the existing
xs_wolf_grhsim_ir_build_emu target with VM_BUILD_JOBS=8 and
GRHSIM_MODEL_CXXFLAGS='-std=c++20 -O3', followed by serial ordinary gate62/gate63
comparisons and actual candidate runtime gates. Preserve all prior candidates.
No gate63 performance improvement or final legacy+5% acceptance is claimed.
