# Gate59 50k serial performance

- Date: 2026-09-07
- Functional gate: [NO0615](./NO0615_grhsim_ir_cpu_gate59_50k_functional_gate_20260907.md).
- Status: actual 50k correctness passed; full-window performance requirement failed.

## Fresh Serial Comparison

The gate59 IR process completed before the legacy process started. Both used
the existing run-only Makefile paths, unchanged CoreMark image/NEMU, seed 0,
50000-cycle limit, waveform disabled and thousand-cycle progress. No build or
other simulation ran concurrently with either measurement.

Legacy command:

```sh
make --no-print-directory run_xs_wolf_grhsim_emu WOLF_ENV_SOURCED=1 \
  XS_GRHSIM_BUILD=build/xs/grhsim XS_SIM_MAX_CYCLE=50000 \
  XS_WAVEFORM=0 XS_WAVEFORM_PATH= XS_LOG_DIR="$PWD/ptmp" \
  XS_PROGRESS_EVERY_CYCLES=1000 RUN_ID=20260907_legacy_50000_serial_gate59 \
  TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" > ptmp/grhsim_legacy_50000_serial_gate59.log 2>&1
```

Both processes exited 0 with Difftest enabled and no mismatch. Comparing the
two new logs yields exactly 50 ordered and identical functional progress records,
plus identical exit reason/PC, counters/IPC and seed/guest-cycle terminal lines.
Final instrCnt=73580, cycleCnt=49996, guest=50001 and limit PC=0x80001312.

## Performance Result

| Metric | Value |
| --- | ---: |
| Gate59 IR 50k host ms | 1371764 |
| Fresh serial legacy 50k host ms | 155030 |
| IR / legacy elapsed time | 8.848378 |
| IR overhead | 784.838% |
| Legacy times 1.05 | 162781.50 ms |
| Additional IR reduction needed for that threshold | 88.1334% |

The plan's 50k legacy +5% requirement is explicitly not met. The functional
50k window is now proven for the current candidate, but overall completion must
not be claimed. Cycle-limit success is not entire CoreMark program completion.

Gate57's historical IR 50k was 2073729 ms; gate59 is lower, consistent with the
earlier local optimization evidence. Those IR runs are not a fresh paired
gate57/gate59 experiment. The denominator above is the new serial legacy run,
not the historical legacy sample. This is one full-window pair without fixed
CPU affinity/frequency or uniform rebuild of both backends, sufficient to show
the large gap but not a fine-grained statistical confidence result.

## Next Investigation

Preserve ptmp/xs_gate59/emu/emu and its generated model as the newly verified
50k baseline. Obtain a fresh gate59 compute/commit/publish profile before
choosing another optimization; gate57's phase proportions are no longer valid
after the sampling-only branch. Collect round and pending counts alongside
timing, restore a normal binary after probes, and keep all work on Makefile
paths with logs/temporary outputs under ptmp.

Wide-value activation and remaining commit/publish work are candidates for
measurement, not established causes. Runtime helpers must continue to follow
legacy pointer/out-buffer/in-place patterns. Do not change DPI/event/ingest
semantics or introduce fullpass to close this report.

All sessions are terminal. Source/executable fingerprints remained unchanged
through the IR run, whitespace checks passed, and no commit was made. The
active goal is not blocked and remains incomplete because performance work
and same-scope revalidation are still required.
