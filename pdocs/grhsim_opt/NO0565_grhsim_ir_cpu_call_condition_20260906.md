# NO0565 CPU external-call condition parity

## Gate51 Failure

After [NO0564](./NO0564_grhsim_ir_cpu_external_calls_20260906.md), fresh gate51 lowering and CPU mapping passed, but the new emitter preflight rejected a real XiangShan call condition: `CPU external call condition must be one-bit logic`.

Log: `ptmp/grhsim_gate51_generation.log`. The Makefile workflow exited nonzero. No output model directory was created, so there is no gate51 build/runtime result.

## Correction

The one-bit restriction was stricter than legacy: `validateDpicCall` and system-task validation use `isValidLogicConditionValue`, and execution uses `truthyLogicValueExpr`. Multi-bit logic is a valid call condition and must be interpreted as any nonzero bit, not only bit zero.

The CPU emitter now accepts logic conditions of any supported width and uses the existing `grhsim_reduce_or_words` helper for wide conditions. Event values and their history states still require one bit. Updated the core/CPU documentation to distinguish call-condition width from event width. This corrects the one-bit-guard statement in NO0564; phase/event policy did not change.

## Regression

`make test_grhsim_cpu_emit WOLF_ENV_SOURCED=1` passed. Log: `ptmp/grhsim_cpu_calls_test3.log`.

The external-call fixture now deliberately uses `0x100` for its enabled 32-bit condition and bit 128 alone for its enabled 129-bit condition. Eventless void DPI and event-gated fwrite use the wide condition; other DPI calls use the 32-bit condition. All 384 samples, terminal exit checks, startup/storage regression and existing Verilator comparisons remain green.

The next fresh generation uses gate52; gate51 failure evidence is preserved. Full-model execution with actual calls and CoreMark 50k remain unverified.
