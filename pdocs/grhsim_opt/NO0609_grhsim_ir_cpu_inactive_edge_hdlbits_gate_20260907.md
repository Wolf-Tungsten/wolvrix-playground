# Inactive-edge sampling HDLBits gate

- Date: 2026-09-07
- Precondition: [NO0607](./NO0607_grhsim_ir_cpu_inactive_edge_sampling_implementation_20260907.md).

Full HDLBits ingest/IR/CPU/GrhTB regression exited 0, covering all 162 DUTs.
The log has 162 ordered DUT entries and ends with dut_162 passing all prediction
and training scenarios. No failure/error/mismatch entry was found.

```sh
make --no-print-directory run_all_hdlbits_grhsim_ir_tests \
  SKIP_PY_INSTALL=1 WOLF_ENV_SOURCED=1 PYTHON="$PWD/.venv/bin/python" \
  TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" > ptmp/grhsim_ir_hdlbits_inactive_edge.log 2>&1
```

Fresh artifacts: ptmp/hdlbits-grhsim-ir-1FWZUs. This run uses both NO0605's
shared-history scheduling correction and NO0607's sampling-only emitter.
It does not reuse previous generated DUTs or change DPI/event semantics.

Gate59's full independent O3 build is still running. No performance simulation
has started concurrently with it. Actual 10k/50k runtime and final performance
remain pending; the earlier gate57 50k is not evidence for the new emitter.
