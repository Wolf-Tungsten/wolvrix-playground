# Inactive-edge sampling-only implementation gate

- Date: 2026-09-07
- Design: [NO0606](./NO0606_grhsim_ir_cpu_inactive_edge_sampling_design_20260907.md).
- Status: implemented; local regression passed, full-model generation and
  HDLBits gates pending at this record.

## Changes

cpu_emit.cpp::commitEdgePossibility collects actual op event operands, retaining
the edge direction and deduplicating at most eight terms. taskBody emits a
sampling-only return path when no edge is possible, including individual
samples and the existing private batches. The ordinary commit body remains
unchanged. This is not a schedule rule, fullpass or event-history optimization.

Tests inspect generated task markers for all three edge domains in cpu_chain
(input, derived and mixed-edge), and reject markers in general or conflicting
history fallback tasks. Separate emission fixtures cover eight versus nine
distinct event operands. Existing executable fixtures exercise both branches
through repeated falling/rising clocks, asynchronous reset, gated clocks,
memory writes, masks, and visible history checks.

## Results

```sh
make --no-print-directory test_grhsim_cpu_schedule test_grhsim_cpu_emit WOLF_ENV_SOURCED=1 > ptmp/grhsim_cpu_inactive_edge_test.log 2>&1
make --no-print-directory test_grhsim_cpu_emit WOLF_ENV_SOURCED=1 > ptmp/grhsim_cpu_inactive_edge_limit_test.log 2>&1
```

Both commands exited 0. First full CPU run: 28.01 s; after adding the emission
limit fixtures, 28.10 s. The schedule suite also passed. Runtime details are
preserved in ptmp/grhsim_cpu_inactive_edge_test_details.log.

- Shared-history independent G scoreboard: 4636 evals, four init cycles.
- Private non-E commits: 4612 evals, 4612 real void DPI calls, four init cycles.
- CPU/Verilator chain: 4136 samples; scalar: 4196; wide: 3072; wide state: 2048.
- CDC: 10756 samples, 1182 simultaneous edges, 20 asynchronous resets.
- Dual RAM: 9731 samples, 293 simultaneous edges, 424 changed writes, 15 resets.
- Fallback-domain batching: 18 candidates, 6 private rejections, 12 states/2 batches.

The project package was then installed using make py_install with explicit
project .venv Python and PIP_CACHE_DIR/TMPDIR/CCACHE_DIR under ptmp; exit 0,
log ptmp/grhsim_inactive_edge_install.log. No manually assembled build commands.

## Next Gates

Independent generation is running through make xs_wolf_grhsim_ir into
ptmp/xs_emit_make_gate59 and ptmp/xs_ir_gate59{,_roundtrip}.json, with harness
root ptmp/xs_gate59. Full HDLBits uses a fresh ptmp/hdlbits-grhsim-ir-1FWZUs
directory. Logs are ptmp/grhsim_gate59_generation.log and
ptmp/grhsim_ir_hdlbits_inactive_edge.log. Previous models remain untouched.

No full-model runtime or performance conclusion is claimed. Actual 50k and
the legacy +5% performance requirement remain open.
