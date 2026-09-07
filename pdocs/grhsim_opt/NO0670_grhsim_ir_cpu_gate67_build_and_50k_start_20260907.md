# Gate67 verification, build, and 50k start

- Date: 2026-09-07
- Candidate: NO0669 emit-shape repairs, including wide grouped publication.
- Status: all local gates and full O3 link passed; fresh serial 50k pair in progress.

Final make test_grhsim_cpu_emit passed in 58.52s, and make
test_grhsim_cpu_schedule passed in 0.01s. This includes both new emit-shape
variants (32768 evaluations/four resets each, ASan/UBSan) and the existing
wide arithmetic, shift, memory, multi-clock and DPI regressions.
make py_install passed with project-local temporary/cache directories.
make run_all_hdlbits_grhsim_ir_tests passed DUT001-162, exit 0;
artifacts: ptmp/hdlbits-grhsim-ir-1R6iqS.

Generation used the existing make xs_wolf_grhsim_ir target, the same flat GRH
checkpoint and target_batch_count=0. Generation/fresh roundtrip took 87075ms;
ptmp/xs_ir_gate67.json is byte-identical to gate63, including mapping.

| Static quantity | Gate66 | Gate67 |
| --- | ---: | ---: |
| Task-source `if(` occurrences | 1515742 | 640218 |
| Task-source global activation writes | 1701385 | 757628 |
| Task-source local activation writes | 155414 | 30720 |
| Total C++ source bytes | 346423197 | 351504933 |

Gate67 has 304228 changed groups, 4116 cell staging sites, and 1939 cached
memory read ports. Source bytes slightly increase; control-flow reduction is
not equivalent to source-size reduction or a measured runtime speedup.

The original make xs_wolf_grhsim_ir_build_emu session 16744 exited 0.
Fresh ordinary -std=c++20 -O3 model/harness build: 6255 model objects,
VM_BUILD_JOBS=8, wall 16:13.07, max RSS 908696 KB. HDLBits overlapped its
early part; this is not an isolated compilation A/B comparison.
Model archive: 174981028 bytes. Actual executable: 155763776 bytes;
ptmp/xs_gate67/emu/emu is a symlink to emu/grhsim-compile/emu.

SHA256:

- emitter: e546c3acfeccd1c51700649a6bd24c7cfcf07533347cfe386dc8dde615d87539
- unchanged schedule: 7f7f253903d2c7ffe6a79fc7f8f19cba5f353a5a80a00d107932ba5f1b53fd64
- gate67 executable: 28aa268fd26805df8ebd7b5e7e824afa163f85d4cc6d96354a392ed5e5ef51b4
- preserved legacy: c211cf9435d867bb4bbda6df73173389106fa5255a3f8af7635d9879221a88cb
- preserved gate63: 25980aaec27d340e8356180d96c109656565e3392d50aaeb0fd9c7ab8b51d56c

After both build/test sessions ended, an unsandboxed host ps query for
clang++,clang,cc1plus,g++,gcc,make,ninja,cmake,emu returned no matching processes.
Started make run_xs_wolf_grhsim_ir_emu with XS_SIM_MAX_CYCLE=50000,
waveform off, progress every 1000, the same coremark-2-iteration image/NEMU,
and default seed. Original session 28552; do not overlap with another run or
build. Await completion, compare all fifty functional samples, then run legacy
with identical settings. No runtime improvement is claimed yet.

Logs under ptmp:

- grhsim_gate67_cpu_final_tests.log
- grhsim_gate67_py_install.log
- grhsim_gate67_generation.log
- grhsim_gate67_hdlbits.log
- grhsim_gate67_full_o3_build.log
- grhsim_gate67_o3_50000.log
