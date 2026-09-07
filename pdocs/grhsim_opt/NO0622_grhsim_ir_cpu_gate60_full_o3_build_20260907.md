# Gate60 full O3 build

- Date: 2026-09-07
- Generation: [NO0620](./NO0620_grhsim_ir_cpu_gate60_generation_20260907.md).
- Broad regression: [NO0621](./NO0621_grhsim_ir_cpu_string_use_site_hdlbits_20260907.md).

The independent existing xs_wolf_grhsim_ir_build_emu Makefile target completed
with exit 0, VM_BUILD_JOBS=8 and GRHSIM_MODEL_CXXFLAGS='-std=c++20 -O3'. The
same session was observed through the final three large tasks; it was not
restarted and no old object files were transplanted.

| Metric | Result |
| --- | ---: |
| Wall time | 16:44.10 |
| User / system seconds | 6354.90 / 385.13 |
| Model object files | 6255 |
| Model archive bytes | 179022346 |
| Executable bytes (dereferenced) | 160998512 |

Log: ptmp/grhsim_gate60_full_o3_build.log. The entry
ptmp/xs_gate60/emu/emu is a symlink to the candidate's own
ptmp/xs_gate60/emu/grhsim-compile/emu, not to the baseline.
Executable SHA-256:
49d364aae00ebff82d92b1ed348dde26249b2a2dc25c8b98696e46619d5f0f2a.
Emitter SHA-256 remains
1efe13e9e6faa87b9e0da116df971d5ca8058eb8ab3be01d4086047d3c186f50.

Compared to gate59, archive/executable sizes shrink, but that is not runtime
performance evidence. All compilation and HDLBits sessions are terminal. The
first ordinary-binary serial 1k pair has started, baseline first; follow with
the opposite order. No gate60 10k/50k or performance parity is established yet.
