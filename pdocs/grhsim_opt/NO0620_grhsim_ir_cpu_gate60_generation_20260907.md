# Gate60 generation and source identity

- Date: 2026-09-07
- Precondition: [NO0619](./NO0619_grhsim_ir_cpu_string_use_site_implementation_20260907.md).

## Generation

Project-local make py_install completed successfully (log:
ptmp/grhsim_gate60_py_install.log). Independent generation/fresh-session load
and stable roundtrip exited 0 in 93734 ms. Log:
ptmp/grhsim_gate60_generation.log.

```sh
make --no-print-directory xs_wolf_grhsim_ir WOLF_ENV_SOURCED=1 \
  PYTHON="$PWD/.venv/bin/python" XS_WOLF_DEPS= XS_GRHSIM_IR_BUILD=ptmp/xs_gate60 \
  XS_WOLF_GRHSIM_IR_FLAT_GRH_JSON=build/xs/grhsim/wolvrix_xs_pre_reg_to_mem.json \
  XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=1 \
  XS_WOLF_GRHSIM_IR_JSON=ptmp/xs_ir_gate60.json \
  XS_WOLF_GRHSIM_IR_ROUNDTRIP_JSON=ptmp/xs_ir_gate60_roundtrip.json \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=ptmp/xs_emit_make_gate60 \
  XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0 XS_LOG_DIR="$PWD/ptmp" \
  RUN_ID=20260907_gate60_generation TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" \
  > ptmp/grhsim_gate60_generation.log 2>&1
```

## Structural Evidence

cmp of ptmp/xs_ir_gate59.json and ptmp/xs_ir_gate60.json exited 0: the complete
IR and mapping are byte-identical. Generated-directory comparison excluding
baseline objects/archive and unreferenced probe headers reports exactly 48
changed compute task sources. Header, driver, runtime, initializer sources,
commit sources and generated Makefile are unchanged. Comparison log:
ptmp/grhsim_gate60_source_diff.log.

Task 5527's 512 standalone std::string assignments become zero, and source
size falls from 328295 to 251583 bytes. Task 5564 falls only from 3076428 to
3074928 bytes: long literal contents remain in the model, now at use sites.
This is not a claim that strings or actual call operations were removed.

## Pending Gates

The existing xs_wolf_grhsim_ir_build_emu Makefile entry is building an
independent O3 candidate with VM_BUILD_JOBS=8. Log:
ptmp/grhsim_gate60_full_o3_build.log. Baseline directories are unchanged.
HDLBits full regression is also running, log ptmp/grhsim_gate60_hdlbits.log,
artifacts ptmp/hdlbits-grhsim-ir-Wr1pJe. Wait for both terminal results before
serial performance runs. No new 1k/10k/50k runtime gate is established here.
