# CPU string use-site HDLBits gate

- Date: 2026-09-07
- Candidate: [NO0620](./NO0620_grhsim_ir_cpu_gate60_generation_20260907.md).

The existing make run_all_hdlbits_grhsim_ir_tests target completed with exit 0.
All 162 DUTs have their passing GrhTB record; none were skipped. The run used
the already installed gate60 implementation, project-local Python, and
SKIP_PY_INSTALL=1. Temporary files/cache remained inside ptmp.

- Log: ptmp/grhsim_gate60_hdlbits.log.
- Independent generated models/harnesses: ptmp/hdlbits-grhsim-ir-Wr1pJe.
- Emitter SHA-256: 1efe13e9e6faa87b9e0da116df971d5ca8058eb8ab3be01d4086047d3c186f50.

This broad regression complements the actual constant-string DPI and lifetime
tests in NO0619. It is not a XiangShan runtime or performance gate. Gate60's O3
build continues in the same live session; no candidate benchmark was started
while HDLBits or compilation was running.
