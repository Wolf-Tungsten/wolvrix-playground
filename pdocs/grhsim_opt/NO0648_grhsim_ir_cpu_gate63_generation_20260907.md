# Gate63 generation and stable-history coverage

- Date: 2026-09-07
- Implementation: [NO0647](./NO0647_grhsim_ir_cpu_stable_history_skip_implementation_20260907.md).

## Generation

The preceding project-local make py_install completed successfully; its log is
ptmp/grhsim_gate63_py_install.log. Source fingerprints match NO0647. Independent
generation, fresh-session checkpoint load and stable roundtrip exited 0 in
94704 ms. Log: ptmp/grhsim_gate63_generation.log.

```sh
make --no-print-directory xs_wolf_grhsim_ir WOLF_ENV_SOURCED=1 \
  PYTHON="$PWD/.venv/bin/python" XS_WOLF_DEPS= XS_GRHSIM_IR_BUILD=ptmp/xs_gate63 \
  XS_WOLF_GRHSIM_IR_FLAT_GRH_JSON=build/xs/grhsim/wolvrix_xs_pre_reg_to_mem.json \
  XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=1 \
  XS_WOLF_GRHSIM_IR_JSON=ptmp/xs_ir_gate63.json \
  XS_WOLF_GRHSIM_IR_ROUNDTRIP_JSON=ptmp/xs_ir_gate63_roundtrip.json \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=ptmp/xs_emit_make_gate63 \
  XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0 XS_LOG_DIR="$PWD/ptmp" \
  RUN_ID=20260907_gate63_generation TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" \
  > ptmp/grhsim_gate63_generation.log 2>&1
```

## Identity and coverage

Both comparisons exited 0: gate62 JSON versus gate63 JSON, and gate63 JSON
versus its fresh-session roundtrip. The complete IR and mapping are unchanged.
Gate63 JSON SHA-256:
c5000e7d65728de36acda15231bb7f4107d8d6e068fd9028c7f3e6302ed86497.

Directory comparison excludes only baseline objects, archive and the unused
gate62_profile.hpp. Exactly 130 commit task sources differ. For every changed
file, removing its single cpu_stable_history_skip entry line yields a
byte-identical gate62 source. Header, driver, runtime, initializers, compute
sources and generated Makefile remain unchanged. Evidence:
ptmp/grhsim_gate63_source_diff.log and ptmp/grhsim_gate63_body_identity.log.

The predicates cover 392009 history members: 95 tasks have one current-value
group and 35 tasks have two groups. Profile hotspot task5636 receives the
predicate with 8192 histories and two current-value groups. These are static
coverage counts, not observed skip counts or evidence of runtime speedup.

The preserved gate62 executable still has SHA-256
0b29bcee26710ee4de444743979228ac9eb761eae579f45f21fb24346f177e1a.
No DPI/event-policy, schedule or history-value changes were made.

## Pending gates

Full HDLBits regression is running through the existing root Makefile target;
log ptmp/grhsim_gate63_hdlbits.log, artifacts ptmp/hdlbits-grhsim-ir-BVXt5e.
Independent gate63 O3 build and actual XS runtime gates have not started.
Final 50k legacy+5% acceptance remains incomplete.
