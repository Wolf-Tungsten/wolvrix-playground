# GrhSIM IR CPU compute partition gate

- Date: 2026-09-06
- Plan: [NO0530](./NO0530_grhsim_ir_cpu_partition_plan_20260906.md)
- Result: all six partition-tree passes pass C++/Python and XiangShan checkpoint
  gates. M5.1 simulation and the overall CoreMark 50k objective remain incomplete.

## Code

`wolvrix/lib/grhsim/backend/cpu_partition.cpp` implements the four new passes:
boundary-guided compute nodes, out1/in1/sibling coarsening plus activation-cost DP,
active words with helper ranges, and function packing. `cpu.cpp` verifies exact
stage hierarchy, topological compute order, contiguous active IDs, aligned words,
helper coverage, and domain-local commit function containment. JSON persists the
new stages and optional activity annotations while still accepting old phase/domain
rows. The XiangShan script now invokes all six passes.

Every pass operates on a typed mapping owned by the model. No semantic op or value
is cloned, reordered in its model table, or rewritten. No schedule is passed through
session state. The mapping still has `complete=false`: layout, schedule, and runtime
are not yet present.

## Tests

```bash
cmake --build wolvrix/build --target grhsim-cpu-mapping-tests grhsim-ir-tests -j 8
ctest --test-dir wolvrix/build -R 'grhsim-(ir|cpu-mapping)-tests' --output-on-failure
.venv/bin/python -m pip install --no-build-isolation --no-deps --no-index -e wolvrix
```

Both CTest targets pass, most recent runtime 0.02 seconds. Added cases cover
definition/use order independent of model table order, 82 one-op nodes, coarsen + DP
packing into 21 four-op supernodes, 82 one-op supernodes packed into 11 words,
word-preserving function limits, helper coverage, malformed active IDs, empty
models, multiclock fixtures, per-stage JSON round trips, and a combinational cycle
that fails without corrupting the input mapping.

The installed Python pipeline was exercised with explicit node/supernode/helper/
function limits, including `target_batch_count=0`. It writes
`wolvrix/build/artifacts/grhsim/cpu_python_partition_20260906.json` successfully.
Full CTest and simulation suites were not rerun in this increment.

## XiangShan Structure

Input: `build/xs/grhsim-ir/xiangshan_grhsim_ir.json`.

| Quantity | Result |
| --- | ---: |
| Compute ops | 4,690,774 |
| Commit ops | 290,531 |
| Compute nodes | 1,501,444 |
| Coarsening iterations | 7 |
| Clusters after coarsening | 997,373 |
| Compute supernodes after DP | 44,686 |
| Boundary value-target pairs before merging | 5,275,884 |
| Boundary value-target pairs after merging | 2,510,273 |
| Active words | 5,586 |
| Compute functions | 62 |
| Commit functions | 452 |
| Supernodes with helpers / helper chunks | 66 / 161 |
| Event domains | 449 |

The before/after edge count is a count of distinct `(value, target partition)`
pairs crossing compute partitions, not unique partition-pair edges or runtime
activation samples. No simulated performance claim follows from this reduction.

| Op-count distribution | p50 | p90 | max |
| --- | ---: | ---: | ---: |
| Compute node | 1 | 5 | 128 |
| Compute supernode | 120 | 128 | 128 |
| Function, both phases | 5 | 75,561 | 77,824 |

Large compute function sizes result from the documented target-count adjustment;
the actual generated-code compile cost still needs measurement when emit exists.

Gate command:

```bash
wolvrix/build/bin/grhsim-cpu-mapping-tests \
  build/xs/grhsim-ir/xiangshan_grhsim_ir.json \
  wolvrix/build/artifacts/grhsim/cpu_xs_partition_20260906.json
```

Includes all tests, full checkpoint load, six passes, store, reload, second store,
and byte comparison: exit 0, 35.87 seconds, peak RSS 2,639,172 KiB. Log:
`wolvrix/build/artifacts/grhsim/cpu_xs_partition_20260906.log`.
Statistics are independently read from the stored mapping using:

```bash
wolvrix/build/bin/grhsim-cpu-mapping-tests --inspect \
  wolvrix/build/artifacts/grhsim/cpu_xs_partition_20260906.json
```

Output: `wolvrix/build/artifacts/grhsim/cpu_xs_partition_20260906_stats.log`.

## Actual Make Route

```bash
make --no-print-directory xs_wolf_grhsim_ir \
  WOLF_ENV_SOURCED=1 XS_WOLF_DEPS= PYTHON="$PWD/.venv/bin/python" \
  XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=1 \
  XS_WOLF_GRHSIM_IR_FLAT_GRH_JSON=build/xs/grhsim/wolvrix_xs_pre_reg_to_mem.json \
  XS_WOLF_GRHSIM_IR_JSON=wolvrix/build/artifacts/grhsim/cpu_xs_make_partition_20260906.json \
  XS_WOLF_GRHSIM_IR_ROUNDTRIP_JSON=wolvrix/build/artifacts/grhsim/cpu_xs_make_partition_20260906_roundtrip.json \
  RUN_ID=20260906_cpu_partition
```

`XS_WOLF_DEPS=` skips an editable install already completed just before this run.
This is a resume from existing flat GRH, not a fresh run of the nine frontend passes.
Exit 0, 60.14 seconds, peak RSS 28,329,240 KiB, including the legacy GRH load/lowering.
The four new pass times including verification are 1,810 / 13,715 / 1,189 / 1,184 ms.

- Main log: `build/logs/xs/xs_wolf_grhsim_ir_20260906_cpu_partition.log`.
- Resource log: `wolvrix/build/artifacts/grhsim/cpu_xs_make_partition_20260906.time`.

The C++ mapped JSON, C++ round trip, Make output, and fresh-session Make round trip
all have the same SHA-256:

```text
db013c7a4fa2fef58eef6fcac3dd7c84a5a5a108677174a9b3d32e9f6818aad8
```

## Remaining Work

Next code stages are `cpu.st.layout-data` and `cpu.st.build-schedule`, followed by
`cpu.st.emit-cpp` and the simulator build/run route. Still required: full legacy
phase/HDLBits domain audit, HDLBits simulation, multiclock Verilator comparisons,
CoreMark 10k/50k difftest, and performance parity/report. The domain-count discrepancy
and event-history semantics described in [NO0528](./NO0528_grhsim_ir_xiangshan_event_domain_audit_20260905.md)
remain part of the runtime implementation work, not grounds to mark the goal complete.
