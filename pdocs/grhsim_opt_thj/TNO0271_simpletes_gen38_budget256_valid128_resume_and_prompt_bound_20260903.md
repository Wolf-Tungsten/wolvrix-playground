# TNO0271: SimpleTES gen38 cumulative budget-256/valid-128 resume and prompt bound

Date: 2026-09-03

## 1. Stage conclusion

The schema-v4 gen38 continuation from
[TNO0263](./TNO0263_simpletes_gen38_schema_v4_replay_rebase_launch_20260831.md)
ended normally after reaching its physical `34/34` valid target. The exact final
state is `instance-47e6f5d9/db_state_211206`; it contains `40` generation attempts,
`2` generation failures, `3` stop-time cancellations, `36` completed database
nodes, `34` generated valid candidates and no evaluation rejection.

The cumulative campaign target has now been doubled from `128 attempts / 64 valid`
to `256 attempts / 128 valid`. Because the schema-v4 migrated tree deliberately
excluded `39 attempts / 30 valid` already consumed before and including historical
gen38, its physical limits are extended from `89/34` to `217/98`. From the exact
final state this leaves at most `177` additional generation attempts and exactly
`64` additional valid evaluations.

A deterministic Codex request-size failure was exposed by the first diagnostic
resume and fixed before the formal continuation. SimpleTES commit
`1109dfb7015704d136132110660b33a9f2900baa` now bounds only the prompt rendering of
large nested metric values; full evaluator evidence remains unchanged in the
checkpoint. The formal resume is running on node030 with GPT `gpt-5.6-sol/max`,
four generation workers and one evaluation worker.

No new candidate has completed evaluation at the time of this launch record. The
inherited best remains:

```text
best node                 858d0782222a41f9ac6d147b8606384b
combined score            1.0500133937268654
control walltime          43,117.75 ms
candidate walltime        41,064.00 ms
absolute reduction         2,053.75 ms
walltime improvement          4.7631195969%
ABBA/BAAB order gap            0.168198 pp
failed stability gates    []
```

This remains search evidence rather than a production landing decision.

## 2. Cumulative budget accounting

The migration in TNO0263 started a fresh schema-v4 database but did not refund
work from the old schema-v3 route:

```text
historical work through gen38       39 attempts / 30 valid
old cumulative target              128 attempts / 64 valid
old migrated physical limit         89 attempts / 34 valid
completed in migrated database      40 attempts / 34 valid
new cumulative target              256 attempts / 128 valid
new migrated physical limit        217 attempts / 98 valid
remaining from db_state_211206      177 attempts / 64 valid
```

Thus a naive physical `89->178 / 34->68` extension would not double the
cumulative campaign. The formal monotonic resume records the correct extension:

```text
generations  89 -> 217
valid        34 -> 98
```

The resume keeps the same four chain histories, selector state, best node,
schema-v4 measurement contract and pinned evaluation baseline:

```text
parent pin    6e2436e37286264e9f03f114d14d81bae4ed313b
Wolvrix pin   054c6a7c09b007a12eb36fdb49fcb659a1bfc590
```

The current target checkout contains later RepCut and documentation work, but its
allowed GrhSIM emitter source is byte-equivalent to the pinned baseline. Candidate
patches are still applied to and measured from the pinned clone by the evaluator.

## 3. Deterministic oversized-prompt diagnosis

The first resume passed the toolchain and repository-grounded GPT capability
preflights, loaded the exact checkpoint, and started all workers. Its first chain-3
request then failed before model inference:

```text
provider maximum       1,048,576 characters
gen43 actual input     1,093,102 characters
error code             input_too_large
```

The failure was not caused by the candidate program, which is only `13,126`
characters. The exact gen43 prompt contained five RPUCG inspirations with:

```text
diagnostics             788,201 characters
samples                 219,903 characters
combined              1,008,104 characters (92.2% of the prompt)
candidate patch text     43,198 characters
other prompt text        41,800 characters
```

The dominant nested field was `diagnostics.runtime_retry_attempts`, where every
rejected attempt again carried eight raw sample records. A prior failure at gen35
had the same chain-3 cause and reached `1,162,667` characters. Other requests were
accepted at `643,618`, `677,393`, `728,075` and `850,161` characters, but those
sizes also wasted context on audit payload rather than optimization reasoning.

The first resume was stopped cleanly before any generated candidate entered the
evaluator. Its diagnostic `db_state_170447` records one extra generation failure
and four cancellations, but is explicitly excluded from the formal lineage. The
formal restart uses the unchanged pre-launch `db_state_211206`, so the diagnostic
failure consumes no research budget.

## 4. Prompt-only evidence bound

Before `1109dfb`, `simpletes/generator.py` rendered every non-float metric with an
unbounded `str(value)`. It now clips each rendered metric value to `4,096`
characters with a visible marker stating that the full value remains in the
checkpoint. This boundary has three deliberate properties:

- candidate code and all small scalar metrics remain byte-for-byte present in the
  inspiration;
- score, absolute control/candidate walltime, absolute reduction and relative
  improvement remain available to the model;
- raw samples, NUMA/PMU audits, retry histories and complete diagnostics remain
  persisted in `Node.metrics`; only their redundant prompt view is bounded.

Reconstructing the exact four initial requests from the frozen checkpoint changes
their prompt sizes as follows:

| chain | before (chars) | after (chars) | reduction |
| ---: | ---: | ---: | ---: |
| 0 | `677,393` | `109,064` | `568,329` |
| 1 | `643,618` | `125,365` | `518,253` |
| 2 | `728,075` | `110,759` | `617,316` |
| 3 | `1,093,102` | `126,088` | `967,014` |

The worst five independently largest formatted inspirations in the checkpoint now
total `141,018` characters; the largest single formatted inspiration is `33,132`
characters. A five-inspiration generator regression additionally constructs two
large nested fields per node and verifies the final Codex prompt stays below the
`1,048,576`-character provider limit while retaining every candidate and headline
walltime.

Verification before restart:

```text
generator + Codex backend focused tests     87 passed
new generator prompt file                    9 passed
flaky reconnect timeout isolated reruns      3 passed
full SimpleTES suite                        324 passed
py_compile                                  PASS
git diff --check                            PASS
```

One first full-suite run had the existing `0.05 s` fake reconnect subprocess test
miss its deadline. The isolated test then passed three consecutive runs and the
entire `324`-test suite passed on the clean rerun; no code in that path changed.

## 5. Formal node030 resume

At host selection time, no SimpleTES launcher, main process or evaluator was active
on node030-node032. The one-second all-CPU snapshots were:

```text
node030 idle   70.43%
node031 idle    2.09%
node032 idle   81.75%
```

Node030 was retained because it was sufficiently idle and still held the exact
campaign slot/control cache at
`/tmp/simpletes-grhsim-gen38-retest-node030-20260830`. Every real runtime group
continues to discover and strictly gate a fully idle CCD independently; the global
snapshot is not accepted as runtime evidence.

The formal process state observed at `2026-09-03 17:16:29 +0800` is:

```text
host                         node030
launcher PID                 515832
main PID                     531888
instance                     47e6f5d9
resume checkpoint            db_state_211206
loaded attempts/valid        40 / 34
new physical limits          217 / 98
remaining attempts/valid     177 / 64
model / effort               gpt-5.6-sol / max
config / auth                ~/.codex/config.thj.toml / ~/.codex/auth.thj.json
generation/eval workers      4 / 1
generation/eval timeout      10,800 / 21,600 s
ordinary exec retries        2
capacity/transient continue  3 / 3
infrastructure retries       99
SimpleTES commit             1109dfb7015704d136132110660b33a9f2900baa
```

The launcher only spawned `main.py` after both deterministic preflights passed.
All four real generation subprocesses were observed concurrently, the main process
environment contains `GRHSIM_INFRA_RETRIES=99`, and no new `input_too_large` or
`CodexExecError` appeared after the compacted prompts crossed the former failure
window.

Output root and formal launcher log:

```text
SimpleTES/checkpoints/grhsim_simtop_50k/
  gen38_remeasured_schema4_gpt56sol_max_continue89_valid34_node030_20260831_031519/

launcher_resume_budget217_valid98_promptcap_20260903.log
```

The independent `retry_runtime.py` entry remains enabled. After an immutable
build/proof is committed, retryable runtime infrastructure outcomes can therefore
reuse the verified ELF/image/NEMU artifacts from
[TNO0270](./TNO0270_simpletes_automatic_proof_backed_runtime_reuse_20260902.md)
instead of rebuilding the candidate.
