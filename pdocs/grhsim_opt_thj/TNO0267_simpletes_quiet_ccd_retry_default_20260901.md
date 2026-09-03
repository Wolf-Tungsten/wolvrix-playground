# TNO0267: SimpleTES quiet-CCD retry default expansion

Date: 2026-09-01

## Scope

The GrhSIM SimTop 50k evaluator now defaults `GRHSIM_INFRA_RETRIES` to `99`.
The variable counts retries after the first runtime attempt, so one already-built
evaluator invocation may make up to `100` complete runtime attempts before it
returns a structured retryable-infrastructure outcome to the SimpleTES engine.

This change does not relax dynamic CCD discovery, fixed-CCD quiet-window, NUMA,
ASLR, PMU, stability, or functional gates. An explicit
`GRHSIM_INFRA_RETRIES=<n>` still overrides the default and permits `n + 1`
runtime attempts.

## Active-run boundary

The active node030 launcher and main processes were inspected before the change.
Both inherited the explicit environment value `GRHSIM_INFRA_RETRIES=8` and
therefore continue to use at most `9` runtime attempts per evaluator invocation.
Changing the source default cannot safely update an existing process environment,
so the active research run was not restarted or modified. A future launch or
resume that omits the variable will use the new default; explicitly setting it to
`99` has the same effect.

## Implementation and verification

- SimpleTES commit: `252cedc` (`bench: increase quiet-CCD retry default`).
- Added a regression that removes the environment override and verifies exactly
  `100` retryable runtime calls plus `1/100` and `100/100` diagnostics.
- Focused retry tests: `3 passed`.
- Full SimpleTES tests: `304 passed`, with `24` existing deprecation warnings.

No SimTop performance measurement was required because this changes only how long
the evaluator retains already-built artifacts while waiting for a valid runtime
environment; accepted measurement and scoring semantics are unchanged.
