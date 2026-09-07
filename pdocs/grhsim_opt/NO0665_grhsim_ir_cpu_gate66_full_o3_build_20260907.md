# Gate66 full O3 build

- Date: 2026-09-07
- Candidate: NO0664, helpers plus local activity/mask coalescing.
- Status: full build/link passed; controlled runtime comparison pending.

Original make xs_wolf_grhsim_ir_build_emu session 5934 exited 0 without restart.
All 6255 generated model objects and the XS harness linked successfully.
Wall time 23:27.59; reported maximum RSS 908904 KB. Gate64's packing-only
build overlapped, so this is not a controlled compile-time A/B measurement.
Log: ptmp/grhsim_gate66_full_o3_build.log.

Model archive ptmp/xs_emit_make_gate66/libgrhsim_SimTop.a: 181474552 bytes.
Actual executable ptmp/xs_gate66/emu/emu: 163201984 bytes, SHA256:
5e1c7db9a41bb09ae452b0427bd61b00ab71e5cb38bb3650ec080909ee2721d5.
Gate63 remains unchanged:
25980aaec27d340e8356180d96c109656565e3392d50aaeb0fd9c7ab8b51d56c.
The small binary-size change must not be read as a runtime speedup.

While the original gate64 build is still running, an existing run-only Makefile
target started a gate66 10000-cycle FUNCTIONAL check with NEMU, seed 0,
waveform off and progress every 1000 cycles. Session 44439; log
ptmp/grhsim_gate66_functional_10000_build_overlap.log. This run's host time is
not performance evidence because it overlaps a build. Await completion and
compare ordered functional samples/terminal records. Ordinary-binary timing
pairs remain serial and must wait for all build load to finish.
