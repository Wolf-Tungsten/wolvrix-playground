# SimpleTES function-gate locale fix

## Failure and root cause

The native-B Astra run in [TNO0300](./TNO0300_simpletes_native_b_astra_fresh_launch_20260909.md)
completed its initial control build, all 32 focused tests, and its 100-cycle
function gate. However, its 10k gate returned retryable infrastructure errors
at `2026-09-09 23:51:32` and `2026-09-10 00:26:24` (+08:00).

The simulation reached the expected cycle limit. The failure was in parsing:
the engine inherited `LANG=en_US.UTF-8` without `LC_ALL`, and Difftest calls
`setlocale(LC_NUMERIC, "")` in `common.cpp`, then uses grouped `%'` integer
formats for counters and elapsed time. Its log therefore contained:

```text
Core-0 instrCnt = 458, cycleCnt = 9,996, IPC = 0.045818
Seed=0 Guest cycle spent: 10,001
Host time spent: 3,892ms
```

The strict function gate expects `9996`, `10001`, and an ungrouped integer
walltime. All three checks were affected. This was not a model API failure
or evidence of a simulation functional regression. The trusted 50k runtime
already enforced `LC_ALL=C`; its preceding evaluator function-gate path did
not. Repeating the same build under the same environment could not resolve
the formatting mismatch.

## Implementation and regression

SimpleTES commit `9d19a65c18c7605efe4ffb1d144c11cbc2061f0d`:

- `_clean_subprocess_env()` forces `LC_ALL=C` after merging extra settings.
- `_run_sourced()` reasserts `LC_ALL=C` after sourcing `env.sh`, so repository
  setup cannot silently restore grouped output before the command executes.
- Four new parameterized cases cover inherited and explicit foreign locale
  values, parent-environment preservation, and locale overrides in `env.sh`.
  Actual subprocess formatting is checked for `9996 / 10001 / 3956`.
- The existing trusted-runtime environment test now also verifies that
  sourced and caller-provided foreign locales cannot override its C locale.

Focused bench/runtime suite: `165 passed in 7.98s`.
Full SimpleTES suite: `330 passed in 20.53s`, with 29 existing
`datetime.utcnow()` deprecation warnings. `git diff --check` passed.

The fix does not relax counter, exit-status, negative-log, ASLR, or runtime
stability checks. It does not change Wolvrix code/defaults, baseline pins,
the candidate seed, measurement schema, model, credentials, or budgets.

## node030 same-binary functional verification

A separate functional probe copied the existing control ELF/image/NEMU to
fresh diagnostic paths. Source-before/copy/source-after hashes were equal,
so this did not race an in-place binary replacement or modify research
artifacts. The exact ELF SHA-256 was:

```text
47ee2c6b8ba860567b0050b1e594a77ced6a63984b832bf6fd16c749d725812c
```

The legacy `en_US.UTF-8` launch reproduced grouped output with exit status 0.
The fixed evaluator, even when its caller environment explicitly requested
`en_US.UTF-8`, passed both fixed-ASLR 100- and 10000-cycle function gates.
Raw 10k outputs included:

| Probe | cycleCnt | Guest cycles | Host time |
| --- | --- | --- | --- |
| Legacy locale | `9,996` | `10,001` | `4,019ms` |
| Fixed evaluator | `9996` | `10001` | `3963ms` |

These are functional checks on a build-active host, not quiet-CCD paired
performance measurements. Their timing difference is not a speedup result;
no new 50k walltime or performance claim is made here.

Artifacts relative to the workspace root:

```text
build/locale_fix_20260910/verify_locale.py
build/locale_fix_20260910/real-emu-p9e8biq2/report.json
build/locale_fix_20260910/real-emu-p9e8biq2/legacy_10000.log
build/locale_fix_20260910/real-emu-p9e8biq2/locale_probe_function_100.log
build/locale_fix_20260910/real-emu-p9e8biq2/locale_probe_function_10000.log
```

The report contains the actual artifact identities and patched evaluator
SHA-256 `6aca1b15ebc6b5e168d312c9ed78d1b48b5270012a94b8699fa17ec440fd01af`.
The diagnostic snapshot remains on node030 at
`/tmp/simpletes-locale-probe-v0ak1rou`.

## Live-run application boundary

At `2026-09-10 00:45:12 +08:00`, original engine PID `2152149` and instance
`ed572ae5` were still running. No process was stopped or restarted. Current
evaluator PID `3114098`, started at `00:26:54`, was still building control
and had imported the old evaluator before this fix.

The engine launches a fresh Python evaluator and imports the shared source
on every outer retry. Thus the next naturally started evaluator will load
the committed fix without restarting the engine. The current already-imported
evaluator may first fail the old function gate once more. This is not an
in-place replacement of a Python function inside a running process.

No clone `env.sh`, process memory, control proof, or checkpoint was edited to
bypass this boundary. Because the old failure precedes publication of
`control_artifacts.json`, proof-backed runtime-only reuse is not yet available:
the next evaluator still follows normal control build preparation. At this
snapshot the research has no initial score, `0/64` generation attempts and
`0/32` valid candidates. The separate functional probe above verifies the
fix, but is not claimed as completion of the live initial evaluation.
