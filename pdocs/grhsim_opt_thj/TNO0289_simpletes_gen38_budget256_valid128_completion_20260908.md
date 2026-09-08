# TNO0289: SimpleTES gen38 budget-256/valid-128 completion

Date: 2026-09-08

## 1. Stage conclusion

The formal continuation launched in TNO0271 completed normally on node030. It
reached the physical valid limit (`98/98`) before exhausting the physical
generation limit (`136/217`), so the campaign stopped with no valid-evaluation
budget remaining. The final checkpoint is:

```text
SimpleTES/checkpoints/grhsim_simtop_50k/
  gen38_remeasured_schema4_gpt56sol_max_continue89_valid34_node030_20260831_031519/
  2026-08-31/instance-47e6f5d9/db_state_054938
```

The final `run.log` ends with `Valid-candidate limit reached: 98/98` followed by
`Evolution Complete!`; there is no active launcher, main process, or evaluator
left on node030. This is a completed research result, not yet a Wolvrix landing
or default-selection decision.

## 2. Final search accounting

The checkpoint metadata records:

```text
instance id                 6ecec9da
completed evaluations       109
generation attempts         136 / 217
generation failures         22
generation cancellations     4
evaluation failures         0
valid evaluations           98 / 98
best score                  1.0584300645409883
best node                   66dff54b556840979bcc350d42c1dd86
```

The 22 generation failures comprise 10 `CodexExecError` and 12
`TimeoutError`. They did not produce evaluation failures or invalid performance
samples. The earlier deterministic oversized-prompt failure was fixed by the
prompt-rendering bound recorded in TNO0271; no such `input_too_large` failure
occurred in the formal continuation. Runtime infrastructure retries were
handled by the evaluator's existing strict CCD gates and proof-backed artifact
reuse.

## 3. Best candidate and end-to-end result

The best candidate is node
`66dff54b556840979bcc350d42c1dd86` (generation 61, chain 1). Its measured
SimTop 50k headline is the required `Host time spent` walltime:

| quantity | pooled value |
| --- | ---: |
| control walltime | `43,950.25 ms` |
| candidate walltime | `41,524.00 ms` |
| absolute reduction | `2,426.25 ms` |
| relative walltime improvement | `5.5204464138%` |
| combined score | `1.0584300645409883` |

The four samples were run on the same CCD and CPU (`node0:32-39,224-231`, CPU
39), with fixed ASLR, NUMA-local binaries, and mirrored `ABBA+BAAB` placement:

```text
control samples   43,570 / 44,072 / 44,013 / 44,146 ms
candidate samples 41,423 / 41,484 / 41,773 / 41,416 ms
ABBA improvement  5.4026608247%
BAAB improvement  5.6375412607%
pooled order gap  0.2348804360 pp  (< 0.25 pp gate)
```

All stability gates passed: control/candidate spread was `1.310573%`/`0.859744%`
(limit `2%`), role block shifts were `0.588165%`/`0.339563%` (limit `1%`),
cycles order gap was `0.142214 pp`, wall/cycles gain gap was `0.055138 pp`, and
the user-cycles/task-clock delta was `0.043559%`. Function, affinity, fixed-ASLR,
NUMA, PMU scheduling, migration, and terminal-cycle audits all passed.

Relative to the inherited best in TNO0271 (`43,117.75 -> 41,064.00 ms`,
`4.7631195969%`), the endpoint search found a candidate with a nominal
`+0.7573268169` percentage-point larger measured improvement and a score increase
from `1.0500133937` to `1.0584300645`. The control measurements are from
different runtime groups, so this is a search-endpoint comparison, not a clean
causal before/after regression.

## 4. What the search discovered

The final patch is a tightly coupled default-path refinement of the existing
principled hot-input/event machinery. In the selected structurally hot input
seed it:

1. reuses the existing `8/4/2/1` active-mask chunk planner only when the exact
   seed saves at least 128 writes (the best seed had 522 entries, 2,074 bits,
   307 contiguous writes, saving 215 writes);
2. marks only seed-covered entries and their enclosing active-word guards as
   `GRHSIM_LIKELY` under the existing structural conditions;
3. omits a redundant global active-byte clear in proven event-qualified commit
   words; and
4. adds the generated-code `GRHSIM_LIKELY` macro.

The patch does not use SimTop names, variable-name matching, benchmark identity,
or a raw event-count heuristic. Existing R/W/A, g158 ordering, typed state,
MemoryRead/MemoryFill decisions, HS/TRBS, and other native defaults remain the
baseline. The candidate is therefore promising end-to-end evidence, but it still
requires the normal ablation, fresh build/function regression, and independent
50k confirmation before any source landing or default change.

## 5. Reproducibility pointers

- Final metadata and best metrics: `db_state_054938/metadata.json` and
  `db_state_054938/nodes.json`.
- Final score history: `db_state_054938/scores_000109.csv`.
- Generation failure audit: `db_state_054938/failure.json`.
- Formal launcher output: the `launcher_resume_budget217_valid98_promptcap_20260903.log`
  file under the gen38 checkpoint root.

