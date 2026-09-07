# CPU history scan HDLBits gate

- Date: 2026-09-07
- Candidate: [NO0628](./NO0628_grhsim_ir_cpu_gate61_generation_20260907.md).

make run_all_hdlbits_grhsim_ir_tests completed with exit 0. All 162 DUTs have
their passing GrhTB record, with no skips. The independent generated models and
harnesses are in ptmp/hdlbits-grhsim-ir-IajCyN; log:
ptmp/grhsim_gate61_hdlbits.log. The run used the installed candidate, local
Python and SKIP_PY_INSTALL=1, with caches/temporary files inside ptmp.

Emitter SHA-256:
c50567fdc958e1be02db11e8975af171405d12112754edf92884a7535dc30480.

This broad regression complements the dense, fragmented, sparse and derived
history-scan executable scoreboards in NO0627. XiangShan O3 compilation is
still running in its original session; no performance simulation has started.
The candidate's actual 10k/50k and runtime benefit remain unverified.
