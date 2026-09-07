# Gate64 packing generation

- Date: 2026-09-07
- Status: generation passed; O3 build running, performance unmeasured.

Single variable versus gate63: target_batch_count=64 instead of explicit 0.
Source and installed package unchanged. Existing make xs_wolf_grhsim_ir target
loaded build/xs/grhsim/wolvrix_xs_pre_reg_to_mem.json with XS_WOLF_DEPS empty.
Generation/fresh roundtrip exited 0 in 92929 ms. Output:
ptmp/xs_ir_gate64.json, ptmp/xs_ir_gate64_roundtrip.json,
ptmp/xs_emit_make_gate64; log ptmp/grhsim_gate64_generation.log.

Generated 514 task files: 62 compute, 452 commit. Largest task sources include
task60 at approximately 60.9 MB, task73 at 54.1 MB and task61/63/64 at 51 MB;
legacy's largest translation unit is approximately 36 MB. Compile feasibility
and runtime benefit are not yet established.

Both models have identical canonical non-mapping JSON SHA256:
7b3624da5e4c40ae6e31a779dc549fcca51916736dac07d4d0b6df67a23baab3.
Gate64's own roundtrip is byte-identical. Independent O3 build uses existing
make xs_wolf_grhsim_ir_build_emu, XS_GRHSIM_IR_BUILD=ptmp/xs_gate64,
XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=ptmp/xs_emit_make_gate64, VM_BUILD_JOBS=8,
GRHSIM_MODEL_CXXFLAGS='-std=c++20 -O3'. Original session 95253 is still running;
log ptmp/grhsim_gate64_full_o3_build.log. Preserve all baseline artifacts.
