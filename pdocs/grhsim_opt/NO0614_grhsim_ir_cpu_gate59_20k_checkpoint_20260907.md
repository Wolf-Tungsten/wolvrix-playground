# Gate59 20k checkpoint

- Date: 2026-09-07
- Runbook: [NO0613](./NO0613_grhsim_ir_cpu_gate59_50k_runbook_20260907.md).
- Status: same real 50k process remains live; this is an intermediate checkpoint.

The gate59 run reached 20000 host/model cycles with 14121 instructions,
commit PC 0x8000043a, trap PC 0x80000440, and host_ms=524172. Its first twenty
strictly ordered thousand-cycle samples all match the existing legacy 50k
reference, excluding host timing and terminal control sequences. It has since
advanced to 21k/14987 instructions with the same matching prefix.

Log: ptmp/grhsim_gate59_o3_50000.log. Difftest is enabled and no mismatch has
been reported. No rebuild, restart, profiler or parallel simulation was added.
The original 50000-cycle limit is unchanged. Completion and the fresh serial
legacy performance comparison remain pending; this checkpoint does not close
the requested 50k gate or the overall plan.
