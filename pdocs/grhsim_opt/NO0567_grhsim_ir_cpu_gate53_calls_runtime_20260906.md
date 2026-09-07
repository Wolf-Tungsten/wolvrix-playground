# NO0567 Gate53 actual-call runtime gate

## Generation and Harness Compilation

After the declaration-boundary repair in [NO0566](./NO0566_grhsim_ir_cpu_dpi_declaration_boundary_20260906.md), `make py_install` passed (`ptmp/grhsim_cpu_call_declarations_install.log`).

Fresh `make xs_wolf_grhsim_ir` completed in about 86 seconds with exit 0, including lowering, all CPU passes, actual-call C++ emission, fresh-load and stable round-trip.

- Generated model: `ptmp/xs_emit_make_gate53`.
- Checkpoints: `ptmp/xs_ir_gate53.json`, `ptmp/xs_ir_gate53_roundtrip.json`.
- Generation log: `ptmp/grhsim_gate53_generation.log`.

`make xs_wolf_grhsim_ir_build_emu` uses two jobs and `GRHSIM_MODEL_CXXFLAGS='-std=c++20 -O0'`. The harness compiled past the gate52 header conflicts without changes to its native headers. Driver and all 170 initialization translation units also compiled. At initial record creation, task compilation is still running around task_61; no full-link or runtime result is claimed yet.

Build log: `ptmp/grhsim_gate53_full_build.log`.

## Runtime Gate Criteria

First run the existing IR Makefile runtime entry with a bounded cycle limit and the default stack. Inspect actual assertion output and difftest instruction/PC counters. A cycle-limit exit without instruction progress or comparison evidence is not CoreMark completion. General array initialization, 10k/50k NEMU gates and optimized performance parity remain required.

## Full Build and 100-Cycle Result

The full gate53 O0 build completed with exit 0: all 514 tasks and 170 init files were included, the model library was archived (about 2.4 GiB), and emu linked (about 1.2 GiB). No native harness headers were changed.

`make run_xs_wolf_grhsim_ir_emu` with `XS_SIM_MAX_CYCLE=100`, waveform disabled and the default stack completed with exit 0. Logs: `ptmp/grhsim_gate53_smoke100.log` and `ptmp/xs_wolf_grhsim_gate53_smoke100.log`.

- RAM/image and NEMU initialization are now observed, unlike the no-op-call gate50 startup.
- Progress reached host/model cycle 100. Final difftest `cycleCnt=96`, `instrCnt=0`; guest cycles 101; host time 54,836 ms.
- No assertion, segmentation fault or unsupported-system-task error was reported. The O0 task_61 prologue reserves `0x7a6f48` bytes (about 7.65 MiB), close to the default stack limit; this remains a stack-margin concern, although this startup passed without an override.
- This proves bounded startup with actual external calls and updated difftest cycle data, not instruction execution or NEMU functional comparison.

## Incremental Check on 2026-09-07

A 1,000-cycle run is in progress under `RUN_ID=gate53_smoke1000`, log `ptmp/grhsim_gate53_smoke1000.log`. Early progress still has zero instructions. Historical [NO0250](./NO0250_simtop_event_fullpass_order_fix_20260710.md) reports an early refill failure at about cycle 8,354; zero instructions during a much shorter window alone cannot establish a new backend failure. After the bounded run, compare its cold-start counters with the existing legacy executable through the normal Makefile entry before drawing that conclusion.

The bounded run subsequently completed and reached its first three committed instructions with NEMU enabled. A same-window legacy check matched all sampled cycle/instruction/PC counters. Full results and limits are archived in [NO0568](./NO0568_grhsim_ir_cpu_first_commit_20260907.md).
