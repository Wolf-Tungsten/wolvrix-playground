# Gate59 1k serial pairs

- Date: 2026-09-07
- Build: [NO0610](./NO0610_grhsim_ir_cpu_gate59_full_o3_build_20260907.md).

## Measurements

After all builds and HDLBits simulations finished, four real model runs were
executed serially through make run_xs_wolf_grhsim_ir_emu. All exited 0.

| Order | Build root | Host ms | Log under ptmp |
| --- | --- | ---: | --- |
| 1 | ptmp/xs_gate58 | 37301 | grhsim_gate58_pair59_1000.log |
| 2 | ptmp/xs_gate59 | 26071 | grhsim_gate59_pair58_1000.log |
| 3 | ptmp/xs_gate59 | 26333 | grhsim_gate59_repeat58_1000.log |
| 4 | ptmp/xs_gate58 | 37937 | grhsim_gate58_repeat59_1000.log |

The chronological pairs use opposite A/B order. Improvements are 30.1064% and
30.5876%, respectively. Both outcomes are retained; no best-run selection.
There is no CPU affinity/frequency control, so no formal confidence interval
or precision beyond these observed samples is claimed.

Common Makefile parameters:

```sh
WOLF_ENV_SOURCED=1 XS_SIM_MAX_CYCLE=1000 XS_WAVEFORM=0 XS_WAVEFORM_PATH= \
XS_LOG_DIR="$PWD/ptmp" XS_PROGRESS_EVERY_CYCLES=1000 TMPDIR="$PWD/ptmp/cpu_emit_test_tmp"
```

Each run explicitly selected its build root and unique RUN_ID matching the log
stem prefixed with 20260907_. CoreMark image, NEMU reference and seed 0 stayed
unchanged. No rebuild or concurrent simulation contaminated a timed run.

## Functional Scope

All four runs enabled Difftest after the first instruction and reported no
mismatch. Every thousand-cycle sample and all terminal functional fields agree:
instr=3, commit_pc=0x10000008, trap_pc=0, instrCnt=3, cycleCnt=996, guest=1001,
IPC=0.003012, and cycle-limit exit.

This verifies only the 1k window. The gain is promising enough to retain the
candidate, but does not establish 10k/50k correctness or the final legacy +5%
performance requirement. Build/source-size costs from NO0610 remain recorded.

## Continued Gate

Independent gate59 10k was subsequently started with the same run-only target,
explicit XS_GRHSIM_IR_BUILD=ptmp/xs_gate59, XS_SIM_MAX_CYCLE=10000 and
RUN_ID=20260907_gate59_o3_10000. Log: ptmp/grhsim_gate59_o3_10000.log.
It is still running at this record. The actual 50k gate remains pending.
