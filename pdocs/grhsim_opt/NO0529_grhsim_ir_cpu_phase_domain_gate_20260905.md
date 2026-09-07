# GrhSIM IR CPU phase/domain structural gate

- Date: 2026-09-05
- Plan: [NO0527](./NO0527_grhsim_ir_cpu_phase_domain_plan_20260905.md)
- Domain-count correction: [NO0528](./NO0528_grhsim_ir_xiangshan_event_domain_audit_20260905.md)
- Result: code, C++ tests, Python entry point, and XiangShan mapping round trip pass.
  This is a structural gate, not a simulation or performance-parity gate.

## Implemented

- `wolvrix/include/grhsim/ir/model.hpp`: typed CPU partition mapping in the model;
  `lib/grhsim/ir/model.cpp`: replacement, clone rebinding, and existing semantic
  invalidation support. Mapping remains incomplete until layout/schedule exist.
- `wolvrix/lib/grhsim/backend/cpu.cpp`: phase/domain passes, canonical event grouping,
  configurable commit chunks, write-shape checks, and stage-aware tree validation.
- `wolvrix/lib/grhsim/io/json.cpp`: streaming CPU mapping payload with strict enum
  parsing and load-time mapping verification.
- `scripts/wolvrix_xs_grhsim_ir.py`: invokes both CPU passes after lowering/verify.
- `wolvrix/docs/grhsim_ir/backends/cpu.md`: authoritative partition annotation and
  persistence definitions; planned schedule fields explicitly distinguished from
  the currently implemented partition-only stages.

## C++ and Python

```bash
cmake --build wolvrix/build --target grhsim-cpu-mapping-tests wolvrix_python -j 8
ctest --test-dir wolvrix/build -R 'grhsim-(ir|cpu-mapping)-tests' --output-on-failure
.venv/bin/python -m pip install --no-build-isolation --no-deps --no-index -e wolvrix
```

Both CTest targets pass (0.03 seconds). Coverage includes two input clocks, a
derived clock, opposite edges, duplicate/permuted event sets, latch/general,
chunk-size limits, side-effect classification, empty models, missing prerequisites,
clone/invalidation, JSON round trip, and malformed partition membership/edges.
The Python smoke loads the small existing IR fixture, runs both passes using
`max_op_in_commit_supernode=2`, and stores
`wolvrix/build/artifacts/grhsim/cpu_python_m50.json` successfully.

Full CTest, HDLBits simulation, multiclock Verilator comparison, and CoreMark
simulation were not run in this increment.

## XiangShan C++ checkpoint gate

```bash
wolvrix/build/bin/grhsim-cpu-mapping-tests \
  build/xs/grhsim-ir/xiangshan_grhsim_ir.json \
  wolvrix/build/artifacts/grhsim/cpu_xs_m50_verified.json
```

- Compute ops: 4,690,774; commit ops: 290,531.
- Domains: 2 input, 446 derived, 1 general; 132 states have multiple writers.
- All ops are covered exactly once with verified phase and domain membership.
- Full domain/producer audit and resource usage:
  `wolvrix/build/artifacts/grhsim/cpu_xs_m50_verified.log`.
- Load, both passes, store, reload, second store, and byte comparison: 16.47 seconds;
  peak RSS 1,136,280 KiB. These are compiler/checkpoint measurements, not simulator
  runtime results.

## Actual Make route

```bash
make --no-print-directory xs_wolf_grhsim_ir \
  WOLF_ENV_SOURCED=1 XS_WOLF_DEPS= PYTHON="$PWD/.venv/bin/python" \
  XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=1 \
  XS_WOLF_GRHSIM_IR_FLAT_GRH_JSON=build/xs/grhsim/wolvrix_xs_pre_reg_to_mem.json \
  XS_WOLF_GRHSIM_IR_JSON=wolvrix/build/artifacts/grhsim/cpu_xs_make_m50.json \
  XS_WOLF_GRHSIM_IR_ROUNDTRIP_JSON=wolvrix/build/artifacts/grhsim/cpu_xs_make_m50_roundtrip.json \
  RUN_ID=20260905_cpu_m50
```

`XS_WOLF_DEPS=` skips the redundant editable install, which was completed immediately
before this command. The test resumes an existing flat GRH checkpoint; it does not
claim a fresh run of the nine frontend passes.

`[EXIT] xs_wolf_grhsim_ir 0` is recorded in
`build/logs/xs/xs_wolf_grhsim_ir_20260905_cpu_m50.log`.
The two CPU passes take 266 ms and 359 ms, including their manager verification.
The whole command takes 40.80 seconds with peak RSS 28,328,756 KiB; the large peak
includes loading legacy GRH and constructing the independent IR.
Resource log: `wolvrix/build/artifacts/grhsim/cpu_xs_make_m50.time`.

The C++ mapped checkpoint, its round trip, the Make output, and its fresh-session
round trip all have identical SHA-256:

```text
3c451fc3eae6e86a1b32126d76378fa2e16a18a99ab641f0aca51643ccc6bc27
```

## Remaining acceptance

M5.0's literal single-domain count is contradicted by the RTL and is not claimed
as passed. Full legacy phase parity, HDLBits domain auditing, compute node/DP
coarsening, active words/functions, layout/schedule, C++ runtime emission, simulator
build/run targets, HDLBits simulation, multiclock differential tests, CoreMark
10k/50k difftest, and the 50k performance report remain open. The full user goal
remains active.
