# TNO0263: SimpleTES gen38 schema-v4 replay rebase and continuation

Date: 2026-08-31

## 1. Stage conclusion

The post-g158 auto research tree was rolled back to generation 38, whose historical
headline was `+2.223038%`. The old schema-v3 checkpoint was not edited in place. Its
exact candidate was copied into a standalone seed, and the accepted node030 retest
from [TNO0261](./TNO0261_simpletes_post_g158_gen38_best_node030_retest_20260830.md)
was authenticated from the original files and replayed through the current schema-v4
gates from [TNO0262](./TNO0262_simpletes_schema_v4_single_group_stability_gates_20260831.md).

The new active root is therefore:

```text
control walltime          43,504.00 ms
candidate walltime        42,959.00 ms
absolute reduction           545.00 ms
walltime improvement          1.252758367%
combined score                1.012686515049233
evaluation schema             4
measurement source            validated-schema3-raw-replay
failed stability gates        []
```

This replaces the historical `1.0227358081756464` score only in the new active
research tree. The old tree, including its later branches, remains immutable and is
not used for selection. A fresh migrated-root continuation is now running on node030
with GPT `gpt-5.6-sol/max`, four generation workers and one evaluation worker.

## 2. Why the old checkpoint was not rewritten

The stopped checkpoint was:

```text
SimpleTES/checkpoints/grhsim_simtop_50k/
  g158_native_mirrored_gpt56sol_max_fresh_20260827_195900/
    2026-08-27/instance-9733393b/db_state_014436
```

It contains `49/64 valid` and schema-v3 metrics. Generation 38 already has later
branches whose selection was influenced by the inflated `+2.223038%` measurement.
Changing only its score would leave those biased descendants active; after replacing
the score, generation 49 at `1.014194036` would also rank above the corrected gen38
score. Relabeling every schema-v3 node as schema-v4 would be worse: the earlier nodes
never passed the new block-shift, spread, cycles/wall and task-clock gates.

The current launcher correctly rejects the old checkpoint because its evaluator
result schema is `3`, while the current contract requires `4`. The migration instead
creates a new database containing only the exact gen38 candidate as its initial root.
The old checkpoint remains read-only lineage evidence and cannot influence RPUCG.

## 3. Candidate and rollback budget

The migrated candidate identity is:

```text
old node id             6de5b2426b1a49ec9c762d5dafb6a94d
old generation/chain   38 / 3
candidate digest       e04bcaa5660bdb801115320c7d9101310357b1641998d03d5df36c3125e85cd5
candidate mode         default-path
patch SHA-256          f0000783cb75e01cc9126252fdaf6cac5c32edd6f5310459033625e482f2e4ce
seed SHA-256           49e8efeffd805d4a4d0aa6d30712f9ee87f12c76438722d4f589247283ae6750
parent pin             6e2436e37286264e9f03f114d14d81bae4ed313b
Wolvrix pin            054c6a7c09b007a12eb36fdb49fcb659a1bfc590
```

Generations `0..38` represent `39` consumed attempts. Seven generation IDs
(`0,1,6,7,12,14,16`) failed, leaving `32` evaluated generated nodes and `30` valid
candidates before and including gen38. The earlier expansion's cumulative target was
`128 attempts / 64 valid`, so the migrated run receives only the remaining budget:

```text
remaining attempts      128 - 39 = 89
remaining valid target   64 - 30 = 34
```

The new SimpleTES database starts its physical counters at zero because old
schema-v3 nodes are not imported. The `89/34` limits preserve the intended cumulative
`128/64` accounting while refunding neither work before gen38 nor invalidating the
new schema contract.

## 4. Preserved measurement evidence

The accepted source attempt is:

```text
attempt id
  01788103779520559120-3329484-87e7e74504274cf796b149d8bfe650c6

evidence root
  build/gen38_node030_retest_20260830/
    accepted_01788103779520559120/
```

The source runtime/evaluation/complete/proof SHA-256 values remain:

```text
runtime     f0a56ab76064b05836b434dd5d37283858f93d4a7af9a4f10cf80d3e693a89ed
evaluation  4bf23014e579162638e7301de6409ddf362d8ea63b1713549d64f17cc5ed1aa2
complete    d6b4ae0b9251edf6c599029f460d1a25f30c075e53e4b9233a06830b0c82d383
proof       7b7fd44879802cb056bd6645518f09904a93c55844fb11077ce95e94afa5c8bc
manifest    931f90365cd84cd5b79d20caa36feae4ef90bcd59f72972b709bfd8fdaf1b048
```

Schema-v3 did not persist the `task-clock` value/unit needed by schema-v4. Before
migration, all eight accepted perf CSVs plus their audit, emu and monitor logs were
copied from node030 `/tmp` into `raw_samples/` on NFS. The two matching ELFs were also
preserved in `binaries/`; control is `83,517,504` bytes with SHA
`1c3170f8...10c8`, and candidate is `83,693,560` bytes with SHA
`401c76c2...ea3b`. The complete bundle is about `190 MiB`.

The replayed samples remain fixed to `C,B,B,C,B,C,C,B`:

| index | role | walltime (ms) | cycles:u | task-clock (ms) |
| ---: | --- | ---: | ---: | ---: |
| 1 | control | `43,491` | `157,278,565,050` | `43,505.16` |
| 2 | candidate | `43,044` | `155,753,161,646` | `43,055.44` |
| 3 | candidate | `42,963` | `155,421,543,713` | `42,974.74` |
| 4 | control | `43,587` | `157,609,229,943` | `43,599.99` |
| 5 | candidate | `42,986` | `155,525,410,375` | `42,998.79` |
| 6 | control | `43,527` | `157,406,128,816` | `43,541.39` |
| 7 | control | `43,411` | `157,051,213,756` | `43,424.37` |
| 8 | candidate | `42,843` | `154,982,260,903` | `42,855.30` |

## 5. Replay contract and verification

SimpleTES commit `e79733f685ce8841c2f3512de5dc3b7394c9e79b` adds an explicit
`--initial-evaluation-replay` contract. It is not a general score-import mechanism:

- manifest, source attempt, proof, candidate, full pins, generated/build/toolchain
  fingerprints and every raw perf CSV are SHA-bound;
- paths must remain inside the bundle and may not traverse symlinks;
- JSON and perf input is read once through bounded `O_NOFOLLOW` file descriptors,
  and the same bytes are hashed, decoded and audited;
- `runtime.audit_perf_stat` reconstructs task-clock and PMU data, after which the
  current schema-v4 assessment and scoring functions run normally;
- the initial claim is fail-closed and stored in an owner-only `0700` directory;
- a failed/in-progress replay cannot become a finite score-zero root, while a
  completed claim stops affecting every later generated candidate;
- replay and resume are mutually exclusive, and proposal limits above the normal
  fresh ceiling require the separate explicit `--extend-replay-budget` flag.

Independent validation completed before launch:

```text
focused replay tests       4 passed
full GrhSIM bench tests    119 passed
full SimpleTES tests       303 passed (24 existing deprecation warnings)
py_compile                 PASS
git diff --check           PASS
real manifest replay       score 1.012686515049233, failed gates []
exact launcher dry-run     PASS
independent security review PASS
```

The replayed schema-v4 stability values are:

```text
wall order gap                    0.045689922 pp
control/candidate block shift     0.160904744% / 0.207174282%
control/candidate sample spread   0.404560500% / 0.467887986%
cycles order gap                  0.076849044 pp
wall/cycles gain gap              0.035181481 pp
cycles:u/task-clock proxy delta   0.039091904%
```

All are below their strict current limits.

## 6. Node selection and launch

Immediately before launch, node030 passed the strict three-second whole-CCD gate on
`node1:128-135,320-327`, CPU/sibling `128/320`, with mean/min idle
`99.896875%/99.67%`. The runtime still discovers and gates placement independently for
every real candidate; this snapshot is only the launch-time host selection evidence.

The first launcher PID `339686` used the playground Python and stopped before model
preflight or instance creation with `ModuleNotFoundError: simpletes`. Its log is kept
as `launcher_failed_wrong_python.log`, SHA-256
`1df72bc6b11de8f15119f8c4cab723bf4931c6b0eca545219718c3cadaf2cbca`.
No replay claim or research budget was consumed. The same intended run was restarted
with `SimpleTES/.venv/bin/python`.

The active run is:

```text
host                    node030
launcher PID            344161
main PID                347689
instance                47e6f5d9
model / effort          gpt-5.6-sol / max
config / auth           ~/.codex/config.thj.toml / ~/.codex/auth.thj.json
generation/eval workers 4 / 1
generation/eval timeout 10,800 / 21,600 s
remaining budget        89 attempts / 34 valid
infra retries           8
build jobs              4
```

Output root:

```text
SimpleTES/checkpoints/grhsim_simtop_50k/
  gen38_remeasured_schema4_gpt56sol_max_continue89_valid34_node030_20260831_031519/
```

Toolchain and repository-grounded GPT capability preflights passed. At
`2026-08-31 03:18:49 +0800`, the log recorded initial score `1.012687` and started all
five workers. Four concurrent Codex generation subprocesses were observed. The claim
state is `completed`, binds the expected and observed full candidate digest, records
source attempt `017881...`, score `1.012686515049233`, improvement
`1.252758367%` and evaluation schema `4`.

No new generated candidate had completed SimTop 50k when this launch record was
written. Subsequent candidates continue through the ordinary fresh build, function,
fixed-ASLR, same-CCD/CPU `ABBABAAB`, NUMA, PMU and schema-v4 walltime path. Search
scores remain research evidence only; any production landing still requires ablation
and fresh before/after regression.
