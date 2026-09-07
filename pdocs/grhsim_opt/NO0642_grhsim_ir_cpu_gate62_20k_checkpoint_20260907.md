# Gate62 20k checkpoint

- Date: 2026-09-07
- Runbook: [NO0641](./NO0641_grhsim_ir_cpu_gate62_50k_runbook_20260907.md).
- Status: the original 50000-cycle process is still running, not a terminal gate.

The same ordinary gate62 run reached 20000 model/host cycles with 14121 retired
instructions, sampled commit PC=0x8000043a, trap PC=0x80000440 and
host_ms=385179. All twenty ordered thousand-cycle progress records match the
first twenty legacy reference records after removing only host_ms. NEMU has
not reported a mismatch. Log: ptmp/grhsim_gate62_o3_50000.log.

The original process handle was polled and remains live. The configured limit
is still 50000 cycles. No candidate rebuild, code change, alternate simulator
or concurrent compilation was introduced. Keep waiting for this process's
terminal status; this checkpoint does not establish 50k correctness or the
full-window performance ratio. The fresh serial legacy measurement follows
only after the IR process ends.
