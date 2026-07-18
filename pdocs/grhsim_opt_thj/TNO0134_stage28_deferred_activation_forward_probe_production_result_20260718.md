# TNO0134 Stage 28 deferred-activation forward probe production result (2026-07-18)

## 1. Scope and control

This stage tested the emitter-aware, read-only activation-forward probe planned
in [TNO0133](./TNO0133_stage28_deferred_activation_forward_probe_plan_20260718.md).
The baseline was the current native C++ default: NO0300 with ASLR disabled,
cap8192, native hybrid state-read defaults, terminal pushforward off, shared-input
peer off, and active-mask gap packing at its C++ default (`off`).  The probe was
enabled only with:

```text
deferred_activation_forward_policy=probe
deferred_activation_forward_profile_path=build/logs/xs_perf/activity_stage19_table_runtime_profile_20260717/fire_50000.tsv
```

The fire profile SHA256 is
`4106fafbea0871724206d81fc5cda19088656d0e185a15c80ea5e9fe7655b11c`.
It contains `63,241` compute rows; `485` commit rows were ignored by the
fail-closed parser.  The production probe log is
`build/logs/xs/xs_wolf_grhsim_build_activity_stage28_deferred_activation_forward_probe_20260718.log`,
SHA256
`85839487b6b1aeb6ee86b3871babc4e253b29d92c94c4355ba7988779e06d12f`,
size `100,018` bytes, with all `64` reported candidate rows preserved.

The probe does not mutate graph, schedule, consumer fanout, active IDs, value
slots, batches, generated C++, or session data.  Against the Stage23 control,
the file set was identical (`137` non-object generated files) and the byte
mismatch count was exactly `0`.  The activity stats SHA256 was
`6c41b8b25d83e05d402dbeb6164553bdd10903b8c8e67efae8cfd3cf6542257c` for both
control and probe; the emit stats SHA256 was
`9dd1bdddd01606507b2e3425917f260ca3ac8c5b88c55fa21408bffb17080a8b` for both.

## 2. Production candidate funnel

The absolute candidate counts were:

| field | value |
| --- | ---: |
| raw source/target pairs | `490,406` |
| pairs with at least two shared values | `246,859` |
| exact eligible after order/head/purity/exclusive/profile gates | `3,864` |
| evaluated by private lowering | `3,864` |
| selected by the bounded probe | `128` |
| selected shared values | `4,021` |
| candidate scan limit | `4,096` |
| selection limit | `128` |
| scan truncated | `false` |
| physical supernode tests saved | `0` |

Reject counts were recorded as absolute values, not percentages:

```text
rejected_multiplicity=243547
rejected_phase_or_order=0
rejected_input_head=10286
rejected_state_head=137165
rejected_memory_head=10152
rejected_event_head=5215
rejected_target_kind=0
rejected_nonexclusive=75953
rejected_profile=0
rejected_fire_necessary=4224
rejected_accounting=0
rejected_overlap=277
rejected_limit=3459
```

The exclusive gate is important: every removed shared value had exactly one
boundary consumer, the candidate target, and output/inout, waveform, event,
state and memory-row heads were excluded.  Thus the probe did not treat raw BAE
as an equivalent count of runtime writes.

## 3. Emitter-aware absolute accounting

The private lowering was recomputed with the same deferred direct/aggregate
choice, branchless/guarded threshold (`32` entries and the existing statement
threshold), active-mask entries, and 1/2/4/8-byte chunk planner.  The complete
control and selected-candidate totals were:

| metric | control | candidate | delta (candidate-control) |
| --- | ---: | ---: | ---: |
| compute sources | `63,241` | `63,241` | `0` |
| tracked changed values | `752,375` | `748,354` | `-4,021` |
| direct value groups | `140,145` | `140,101` | `-44` |
| deferred groups | `136,969` | `136,859` | `-110` |
| deferred source-value updates | `925,811` | `921,836` | `-3,975` |
| deferred direct groups | `135,682` | `135,572` | `-110` |
| deferred aggregate groups | `1,287` | `1,287` | `0` |
| unconditional forward groups | `0` | `128` | `+128` |
| active-mask entries | `420,843` | `420,817` | `-26` |
| planned chunks | `396,572` | `396,546` | `-26` |
| 1-byte chunks | `372,649` | `372,623` | `-26` |
| 2-byte chunks | `15,155` | `15,155` | `0` |
| 4-byte chunks | `760` | `760` | `0` |
| 8-byte chunks | `186` | `186` | `0` |
| table groups | `119` | `119` | `0` |
| table entries | `10,733` | `10,733` | `0` |
| branchless groups | `265,317` | `265,163` | `-154` |
| guarded groups | `11,797` | `11,797` | `0` |
| conditional mask updates | `327,748` | `327,594` | `-154` |
| local RMW sites | `30` | `30` | `0` |
| global RMW sites | `399,483` | `399,457` | `-26` |
| updated bytes | `418,250` | `418,224` | `-26` |
| estimated activation lines | `549,155` | `549,385` | `+230` |
| aggregate work units | `2,417,244` | `2,409,068` | `-8,176` |

There were no direct/aggregate, branchless/guarded, or table threshold path
flips (`0` in each direction).  The small static work reduction therefore comes
from removing changed-value/deferred updates and 26 global mask entries, while
the synthetic forward calls add 230 estimated lines.  Physical supernode test
count remains exactly zero saved.

## 4. Fire-weighted result and top positive subset

For each selected pair the probe reports a conservative lower bound that charges
the target's operation count on every source fire, and an upper bound that
charges only the measured static work reduction.  Across all 128 selected pairs:

```text
selected_fire_weighted_lower = -71,582,689
selected_fire_weighted_upper =  60,496,519
```

The interval crosses zero by a wide margin, so the full 128-pair selection is
not a strict candidate.  The first five rows are a separate, disjoint subset
whose individual conservative lower bounds are positive; they are recorded here
for the next stage rather than silently mixed into this decision:

| rank | source -> target | active IDs | batches | shared values | source/target fire | static work control -> candidate | lower / upper |
| ---: | --- | --- | --- | ---: | --- | --- | --- |
| 0 | `51194 -> 52335` | `51478 -> 52351` | `53 -> 54` | `54` | `8,221 / 8,313` | `308 -> 198` | `16,442 / 904,310` |
| 1 | `51196 -> 52337` | `52773 -> 53422` | `54 -> 55` | `54` | `8,012 / 8,102` | `302 -> 193` | `8,012 / 873,308` |
| 2 | `51195 -> 52336` | `50520 -> 51576` | `52 -> 53` | `54` | `7,928 / 8,013` | `303 -> 194` | `7,928 / 864,152` |
| 3 | `51197 -> 52338` | `52774 -> 53423` | `54 -> 55` | `54` | `7,786 / 7,865` | `304 -> 195` | `7,786 / 848,674` |
| 4 | `51193 -> 52334` | `51477 -> 52350` | `53 -> 54` | `54` | `7,780 / 7,857` | `303 -> 194` | `7,780 / 848,020` |

For example, rank 0 removes `110` static work units and adds one forward
activation group; its lower bound is still `16,442` after charging `108` target
ops per source fire.  This is sufficient evidence to justify a narrowly scoped
strict experiment, but not the broad 128-pair mutation.  The next stage must
also verify that the follower is pending whenever the leader fires; fire-count
equality alone is not a co-fire proof.

## 5. Decision

No strict graph or emitter mutation, CPP candidate, O3 build, or SimTop run was
made in Stage 28.  This is not a cycles-based decision: no candidate walltime
was produced, and the end-to-end criterion remains SimTop `Host time spent`
walltime.  The full selection was rejected because its conservative
fire-weighted interval crosses zero and its estimated activation lines increase
by `230`.

The probe itself remains default-off in C++ (`off` when the attribute and both
environment variables are unset).  XS only forwards sparse explicit
`WOLVRIX_XS_GRHSIM_DEFERRED_ACTIVATION_FORWARD_*` overrides.  Stage 29 will
consider only the five positive-lower-bound rows above, preserve all baseline
consumer maps and active-ID/batch partitions, and stop before 50k if the
no-mutation co-fire counter or conservative emitter accounting fails.

## 6. Verification record

The following gates passed after the event-head fixture was added:

| gate | result |
| --- | --- |
| `WOLVRIX_TEST_DEFERRED_ACTIVATION_FORWARD=1` focused emitter test | PASS |
| `ctest --test-dir wolvrix/build -R '^emit-grhsim-cpp$' --output-on-failure` | `1/1 PASS` (`291.34 s`) |
| Python emitter option tests | `12/12 PASS` |
| XS option tests | `22/22 PASS` |
| submodule and parent `git diff --check` | PASS |
| control/probe generated artifact byte identity | `137` files, `0` mismatches |

## 7. r2 勘误与字段语义修正（2026-07-18）

The first production pass above was a draft: it printed only `64` of the
`128` selected rows and called an IR-op-based quantity a conservative bound.
The corrected r2 production run supersedes those two reporting details while
leaving the control/probe artifact identity and all lowering totals unchanged.

The corrected raw log is
`build/logs/xs/xs_wolf_grhsim_build_activity_stage28_deferred_activation_forward_probe_r2_20260718.log`,
SHA256
`94f8a5f064b1bece779e1a2cbcc502357458ca977c9a49c8d9168832aa297ca7`,
size `275,502` bytes. It contains `192` candidate rows: all `128` selected
rows plus `64` near-selected rows. The control/probe artifact comparison is
still `137` files with `0` byte mismatches; activity stats SHA remains
`6c41b8b25d83e05d402dbeb6164553bdd10903b8c8e67efae8cfd3cf6542257c`, and emit
stats SHA remains
`9dd1bdddd01606507b2e3425917f260ca3ac8c5b88c55fa21408bffb17080a8b`.

All fields formerly named `fire_weighted_lower`/`fire_weighted_upper` are now
interpreted as `fire_weighted_work_proxy_lower`/`fire_weighted_work_proxy_upper`.
They are heuristic comparisons, not conservative runtime bounds. The corrected
full-selection values are:

```text
global_control_work_units=2417244
global_candidate_work_units=2409068
global_work_units_delta=-8176
selected_fire_weighted_work_proxy_lower=-71582689
selected_fire_weighted_work_proxy_upper=60496519
```

The exact corrected funnel is:

```text
raw_pairs=490406
shared_value_pairs=246859
exact_eligible=3864
accounted=3864
static_positive=3864
selected=128
selected_values=4021
reported_rows=192
branchless_changed_sources=128
guarded_changed_sources=0
table_changed_sources=0
physical_supernode_tests_saved=0
```

The proxy-positive selected subset contains `13` disjoint candidates and `691`
shared values. Its absolute proxy summary is:

```text
static_saved_units=1396
target_ops=1382
fire_weighted_work_proxy_lower=98106
fire_weighted_work_proxy_upper=9734846
```

The 13 source/target pairs are:

```text
51194 -> 52335
51196 -> 52337
51195 -> 52336
51197 -> 52338
51193 -> 52334
57291 -> 57901
57289 -> 57899
57290 -> 57900
57294 -> 57904
57293 -> 57903
57292 -> 57902
10635 -> 27668
35026 -> 38043
```

These 13 rows are only the input to the next dynamic no-mutation co-fire
counter. Their positive proxy does not justify a strict change, CPP/O3 build,
or 50k run by itself. The old draft statements in Sections 4 and 5 that call
the quantity “conservative” or say that five rows are sufficient for strict are
superseded by this correction; the broad 128-row selection remains rejected,
and Stage 29 must establish `leader_fire`, `follower_pending`, and
`leader_without_follower=0` before any strict candidate is considered.

## 8. Corrected verification record

After the r2 reporting fixes and focused-test registration:

| gate | result |
| --- | --- |
| regular `emit-grhsim-cpp` CTest | PASS |
| Stage28 focused CTest (`emit-grhsim-cpp-deferred-activation-forward`) | PASS (`0.35 s`) |
| combined CTest regex | `2/2 PASS` (`293.30 s`) |
| Python emitter option tests | `12/12 PASS` |
| XS option tests | `22/22 PASS` |
| submodule and parent `git diff --check` | PASS |
