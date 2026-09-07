# Gate59 generation and source identity

- Date: 2026-09-07
- Precondition: [NO0607](./NO0607_grhsim_ir_cpu_inactive_edge_sampling_implementation_20260907.md).

## Generation

The independent gate59 Makefile flow exited 0 in 90843 ms, including CPU
mapping, C++ emission, checkpoint storage, fresh-session loading, and stable
roundtrip. Log: ptmp/grhsim_gate59_generation.log.

```sh
make --no-print-directory xs_wolf_grhsim_ir WOLF_ENV_SOURCED=1 \
  PYTHON="$PWD/.venv/bin/python" XS_WOLF_DEPS= XS_GRHSIM_IR_BUILD=ptmp/xs_gate59 \
  XS_WOLF_GRHSIM_IR_FLAT_GRH_JSON=build/xs/grhsim/wolvrix_xs_pre_reg_to_mem.json \
  XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=1 \
  XS_WOLF_GRHSIM_IR_JSON=ptmp/xs_ir_gate59.json \
  XS_WOLF_GRHSIM_IR_ROUNDTRIP_JSON=ptmp/xs_ir_gate59_roundtrip.json \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=ptmp/xs_emit_make_gate59 \
  XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0 XS_LOG_DIR="$PWD/ptmp" \
  RUN_ID=20260907_gate59_generation TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" \
  > ptmp/grhsim_gate59_generation.log 2>&1
```

The explicit empty XS_WOLF_DEPS avoids reinstalling the already updated project
package. It does not bypass model generation or fresh-session verification.

## Identity and Coverage

- cmp of ptmp/xs_ir_gate58.json and ptmp/xs_ir_gate59.json exited 0: complete
  IR and CPU mapping are byte-identical.
- Recursive generated-directory comparison, excluding old objects/archives,
  reports exactly 514 changed task sources. Header, runtime, driver, initializers,
  compute tasks and generated Makefile are unchanged.
- Exactly 514 task sources contain the cpu_inactive_edge_sample marker.
- The source comparison is preserved as ptmp/grhsim_gate59_source_diff.log.
- task_5570 grew from 2717943 to 2791383 bytes. task_5615 and task_5786 each
  have two actual event operands in the aggregated condition. No common-clock
  assumption replaces their disjunction.

Private history batch markers appear in both generated branches. Do not count
both copies as increased unique batching coverage. This is a code-shape gate,
not a runtime speedup or new full-model functional gate.

## Full Build Started

The existing build-only Makefile entry is running with jobs=8 and O3 into an
independent ptmp/xs_gate59/emu directory. Log:
ptmp/grhsim_gate59_full_o3_build.log. Baseline gate57/gate58 artifacts remain
unchanged. HDLBits is still in progress; performance runs must wait for both
the build and other simulations to finish.
