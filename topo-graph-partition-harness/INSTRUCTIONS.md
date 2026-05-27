# Topo Graph Partition Harness Attempt Instructions

This document is the required procedure for one partition-algorithm attempt.
One execution of this document creates exactly one new search-tree node, unless the work is only a bug-fix patch for the current node.

## Scope

Use this procedure when proposing, implementing, tuning, or evaluating one `topo-graph-partition-harness` algorithm idea.

The goal of one attempt is not "try many things". The goal is to test one explicit hypothesis under the fixed harness rules.

## Fixed Rules

- Do not modify fixed checker logic to make an algorithm pass.
- Do not modify score definitions to make an algorithm look better.
- Do not delete or rewrite previous experiment records.
- Do not drop failing cases from the suite.
- Do not use Python for validation, scoring, oracle, or official experiment execution.
- Do not generate cases from inside `topo-graph-partition-harness`.
- Treat `cases/` inputs as user-provided; a new real case is valid only after the user has manually added it.
- Every algorithm attempt must evaluate every current non-final `*.compute-op-dag.json` under `cases/`.
- `cases/final/` is reserved for final acceptance gates and must not be mixed into the routine iteration manifest.
- The routine case list must be frozen as this node's routine manifest before scoring starts.
- Candidate results and baseline results must use exactly the same manifest for the stage being evaluated.
- The full-case score matrix is the source of truth for node decisions; every routine-manifest case must have a
  baseline row, candidate row, delta row, validation status, and run status.
- A node cannot be marked successful because it improves a hand-picked subset.
- A node cannot be marked successful when any required stage case is missing, skipped, unscored, times out, or fails fixed validation.
- A node cannot be marked successful unless the routine aggregate comparison improves versus baseline, and every present final gate also passes.
- A node cannot be marked successful when total improvement is caused by a few wins while material regressions on other
  required cases are ignored or left unexplained.
- A node may name focus cases for diagnosis, but focus cases never change the required scoring set. The routine
  manifest is always the complete non-final case set frozen for the node.
- Overall benefit means the candidate beats the baseline on aggregate metrics computed from every routine-manifest row.
  A subset win, passing smoke case, or hand-picked average is not an overall benefit.
- Do not run oracle unless the user explicitly asks for an oracle run or explicitly asks to refresh an oracle reference.
- Store oracle outputs next to the case under `cases/`, not inside ordinary experiment `runs/`.
- Do not mix unrelated algorithm ideas in one search node.
- If an implementation bug is fixed without changing the hypothesis, record it as a patch attempt under the same node.
- If the algorithm hypothesis changes, create a child node.

## Step 1: Review Graph Algorithms

Before editing code, write a short review note in the new experiment file:

- DAG topological order and quotient graph acyclicity.
- Edge cut, boundary activation edge, and weighted cut.
- Capacity-constrained graph partitioning.
- Hypergraph partitioning vs graph partitioning.
- Greedy agglomerative clustering failure modes.
- Branch-and-bound lower bounds.
- Incremental cycle detection for directed quotient graphs.
- Local search move legality under size and DAG constraints.

The note must explain which concepts affect this attempt.

## Step 2: Choose Parent Node

Open `memory/search_tree.md` and inspect all four sections before choosing the next action:

- `Active Frontier`
- `Parked Candidates`
- `Closed Nodes`
- `Family Ledger`

Select exactly one parent or one activation source:

- Use an active frontier node when extending a promising idea.
- Use a parked candidate when the next child idea is already known but has not been activated yet.
- Use a closed node only when the new attempt directly addresses its recorded rejection or exhaustion reason.
- Use `root` only for a first baseline or a truly independent algorithm family.

Tree-search intent:

- Prefer depth on the current best-supported frontier node when the last result suggests one local fix or one sharper
  hypothesis.
- Prefer a sibling or cousin node when the parent idea looks broadly right but one specific mechanism failed.
- Prefer a new root child only when every current frontier direction is exhausted, mutually contradicted, or dominated by
  a different algorithm family.

Record:

```text
parent: Sxxxx
family: <family name>
search_move: local repair | constraint refinement | objective shift | family switch
reason: why this parent is being extended
```

If the current active frontier has no live extension path, do not stop. Generate
the next node using this order:

1. Activate the best parked candidate if one already captures the next evidence-backed move.
2. Otherwise pick the most informative closed node whose evidence isolates one concrete failure mode.
3. Turn that failure mode into one narrower corrective hypothesis.
4. Create a child of that closed node if the new hypothesis directly repairs the recorded reason for rejection or exhaustion.
5. If no closed node yields a concrete repair, create a new root child for a different algorithm family.

Forbidden recovery patterns:

- Reopening a rejected node unchanged.
- Creating a new node whose hypothesis is only a rewording of an already rejected hypothesis.
- Creating many speculative children at once without evidence from the previous node.

Required frontier-exhaustion note:

When all current nodes have failed, add a short note in the new experiment file:

```text
## Frontier Exhaustion

- exhausted nodes: Sxxxx, Syyyy, ...
- shared failure pattern: ...
- why this new node is not a duplicate: ...
```

## Step 3: Create Search Node

Allocate the next `Sxxxx` id and create a matching experiment id `EXPxxxx`.

Add a provisional entry to `memory/search_tree.md`:

```text
| Sxxxx | Sparent | family | search_move | short hypothesis | in-progress | current execution | EXPxxxx |
```

Create:

```text
memory/experiments/EXPxxxx_<short_name>.md
```

The experiment file must contain:

```text
# EXPxxxx <short name>

## Search Metadata

id: Sxxxx
parent: Sparent
family: <family name>
search_move: <search move>
status: in-progress
activation_reason: ...

## Parent Snapshot

active_frontier_parent: yes | no
activated_from_parked_candidate: yes | no
parent_status_at_start: keep | reject | exhausted | root

## Graph Algorithm Review

...

## Hypothesis

...

## Expected Improvement

...

## Planned Cases

routine_manifest: complete non-final `cases/**/*.compute-op-dag.json`
focus_cases: optional diagnostic list only; not a scoring filter
coverage_gate: every routine-manifest case must have baseline, candidate, validation, score, and delta rows

## Case Manifest

...

## Baseline

...

## Commands

...

## Results

...

## Full-Case Score Matrix

...

## Aggregate Comparison

computed_from: full routine manifest only
overall_benefit: pass | fail
subset_only_improvement: yes | no
regression_budget_status: pass | fail

## Interpretation

...

## Decision

keep | branch | reject

## Search Continuation

search_continuation: ...

## Parked Child Candidates

- hypothesis: ...
  activate_when: ...

## Next Branches

...
```

## Step 4: State Hypothesis

The hypothesis must be falsifiable.

Good:

```text
Prioritizing merges that remove high-weight producer-consumer edges while preserving quotient DAG legality will reduce cut_weight on Level 1 cases without increasing quotient_p99_out_degree by more than 5%.
```

Bad:

```text
Try a smarter merge algorithm.
```

The hypothesis must name:

- Algorithm family.
- One expected metric improvement.
- One risk metric that must not regress.
- Focus case type, if any, used only for diagnosis. It does not limit the required case manifest or scoring scope.

Every new node must name exactly one of these search moves:

- `local repair`: keep the same algorithm family, fix one concrete defect.
- `constraint refinement`: keep the family, tighten legality or scoring-sensitive behavior.
- `objective shift`: keep the family, optimize a different primary heuristic signal.
- `family switch`: start a different algorithm family from `root`.

If the search move cannot be named, the node is too vague and must not be created.

## Step 5: Freeze Case Manifest

Enumerate the routine case set before running:

```bash
find topo-graph-partition-harness/cases -path 'topo-graph-partition-harness/cases/final' -prune -o -name '*.compute-op-dag.json' -print | sort
```

The selected case set is the full command output. Do not filter it by level, size, expected difficulty, or whether the
new algorithm is expected to perform well on it. Small legality cases, sampled cases, routine real cases, and
`XsIcacheReplacerLarge` all participate when present. `cases/final/` does not participate in this routine manifest.

Create and record this routine manifest:

```text
runs/EXPxxxx/routine_case_manifest.txt
```

The manifest must include one row per case:

- stable case slug
- relative path
- graph id
- node count
- edge count
- total node weight
- total edge weight
- graph validation status
- optional oracle reference path, or `oracle: not requested`

Do not change the case set after seeing failures. If a case is invalid, record why and fix the case or checker separately.
If the routine case set changes after the manifest is frozen, this node's routine evaluation is stale; either rerun
baseline and candidate on the new manifest, or close the node as invalid and create a new node.
Do not create or export new cases as part of an algorithm attempt; ask the user to add the case first.

Before continuing, write the routine manifest into the experiment file under `## Case Manifest`. This is the contract for
all later score matrices in the node.

## Step 6: Establish Baseline

Every node needs a comparison baseline over exactly the same routine manifest.

Allowed baselines:

- the parent node's recorded full-case score matrix, if it used the same manifest and score schema
- a dedicated baseline node, if it used the same manifest and score schema
- a fresh baseline run for this node, recorded before candidate interpretation

Disallowed baselines:

- a baseline that covers only a subset of the routine manifest
- a baseline from a stale case set
- a baseline with missing score rows
- an oracle result used as a direct replacement for algorithm baseline scoring

If no valid baseline exists, run or create a baseline first. Until every routine-manifest case has a baseline score row,
the node cannot be marked `keep`, regardless of candidate results.

The baseline record must include a machine-checkable score path for each case:

```text
runs/EXPxxxx/baseline/<case-slug>/score.json
```

If the baseline comes from a parent or dedicated baseline node, copy or reference the exact score path in the experiment
file. Do not summarize the baseline as a single aggregate number; later decisions require per-case deltas.

## Step 7: Implement

Implement only the code needed for this node.

Allowed areas:

- `algorithms/<algorithm>.cpp`
- algorithm registration files
- algorithm-specific config parsing
- tests or cases for this attempt

Restricted areas:

- `lib/validate_graph.cpp`
- `lib/validate_partition.cpp`
- `lib/score_partition.cpp`
- schema files

Restricted areas may be changed only if the current task is explicitly about harness infrastructure, not algorithm exploration. Such changes require their own search node or infrastructure task record.

## Step 8: Run Fixed Checks

Run the fixed checks for every case from the frozen routine manifest. Use a distinct run directory per node and case:

```text
runs/EXPxxxx/<case-slug>/
```

For each case, run:

```bash
topo-graph-partition-harness/build/bin/tgp_validate_graph --graph <case>
topo-graph-partition-harness/build/bin/tgp_run_experiment --algorithm <name> --graph <case> --config <config> --out-dir runs/EXPxxxx/<case-slug>
topo-graph-partition-harness/build/bin/tgp_validate_partition --graph <case> --partition <run-dir>/result.json
topo-graph-partition-harness/build/bin/tgp_score_partition --graph <case> --partition <run-dir>/result.json --out <run-dir>/score.json
```

Every case must produce `result.json`, `score.json`, and `log.md`. A missing score, failed validation, timeout without a
recorded result, or skipped case makes the search node invalid until fixed. Do not replace failed cases with a filtered
subset; the routine manifest remains the required coverage set.

After running a case, immediately append its status to the experiment file:

```text
| case | graph_validate | run_status | partition_validate | score_path | runtime_ms | notes |
| ...  | pass           | pass       | pass               | ...        | ...        | ...   |
```

Use explicit failure categories such as `graph-invalid`, `algorithm-timeout`, `partition-invalid`, `score-missing`, or
`run-crash`. A failed row still counts as a manifest row; it must not disappear from the matrix.

For oracle-backed cases, also run or reference:

```bash
oracle: not requested
```

If the user explicitly requests an oracle run, write the oracle reference next to the case:

```bash
topo-graph-partition-harness/build/bin/tgp_oracle \
  --graph <case-dir>/<case>.compute-op-dag.json \
  --max-node-weight <n> \
  --threads <n> \
  --checkpoint <case-dir>/<case>.oracle.ckpt \
  --out <case-dir>/<case>.oracle.json
```

For `XsIcacheReplacerLarge`, only when explicitly requested:

```bash
topo-graph-partition-harness/build/bin/tgp_oracle \
  --graph topo-graph-partition-harness/cases/real/XsIcacheReplacerLarge.compute-op-dag.json \
  --max-node-weight 128 \
  --threads <n> \
  --time-limit-sec <n> \
  --checkpoint topo-graph-partition-harness/cases/real/XsIcacheReplacerLarge.oracle.ckpt \
  --out topo-graph-partition-harness/cases/real/XsIcacheReplacerLarge.oracle.json
```

## Step 9: Record Results

Record raw commands and key metrics for every routine-manifest case. The experiment file must include a full-case score
matrix with exactly one row per routine `*.compute-op-dag.json` case. The row count must equal the frozen manifest row
count before any decision is made.

Per candidate row:

- `cut_weight`
- `cut_edges`
- `parts`
- `quotient_edges`
- `quotient_avg_out_degree`
- `quotient_p99_out_degree`
- `runtime_ms`
- oracle status: `not requested`, `referenced <path>`, or `generated <path>`
- oracle incumbent, lower bound, and gap only when an oracle reference exists
- validation status

Per baseline/delta row:

- baseline `cut_weight`
- baseline `cut_edges`
- baseline `quotient_edges`
- baseline `quotient_p99_out_degree`
- baseline `runtime_ms`
- delta for each primary metric
- relative delta for `cut_weight` and `quotient_p99_out_degree`

Required full-case matrix shape:

```text
| case | baseline_cut | candidate_cut | cut_delta | baseline_q_edges | candidate_q_edges | q_edges_delta | baseline_p99_out | candidate_p99_out | baseline_runtime_ms | candidate_runtime_ms | validation | run_status |
| ...  | ...          | ...           | ...       | ...              | ...               | ...           | ...              | ...               | ...                 | ...                  | pass       | pass       |
```

Also record aggregate metrics over the full case set. These aggregate rows must be computed from the same matrix, not
from a second ad hoc list:

- `sum_cut_weight`
- `sum_cut_edges`
- `sum_quotient_edges`
- `max_runtime_ms`
- `geomean_runtime_ms`
- count of cases improved, unchanged, and regressed versus the parent or baseline
- worst relative regression for `cut_weight`
- worst relative regression for `quotient_p99_out_degree`
- validation failures, if any

Aggregate metrics must be computed from all routine-manifest rows. A summary computed from only passing, easy, small, or improved
cases is invalid.

If a run fails, record the failing command and error category. Do not silently skip it.

Default aggregate success gate:

- `candidate_sum_cut_weight < baseline_sum_cut_weight`.
- All candidate partitions pass fixed validation.
- No required case has missing score, timeout, crash, or stale baseline.
- Candidate and baseline matrices both cover exactly the frozen routine manifest; row count and case ids match.
- Aggregate values are recomputed from the full matrix, including cases with unchanged or regressed scores.
- `candidate_sum_quotient_edges`, worst `quotient_p99_out_degree` regression, and `max_runtime_ms` stay within the
  regression budget declared in `## Expected Improvement`.
- Any per-case cut regression must be listed in `## Interpretation` with a concrete reason and a follow-up decision.

If `candidate_sum_cut_weight` improves only after excluding one or more manifest cases, the node is rejected. If a focus
case improves but the full routine aggregate does not improve, the node is also rejected or branched; it cannot be kept
as a successful node.

## Step 10: Run Final Gate

Only run this step if the routine-manifest evidence would otherwise justify `keep`.

Enumerate the final gate set:

```bash
find topo-graph-partition-harness/cases/final -name '*.compute-op-dag.json' | sort
```

Create and record this manifest when one or more final cases are present:

```text
runs/EXPxxxx/final_case_manifest.txt
```

For each final case, run:

```bash
topo-graph-partition-harness/build/bin/tgp_validate_graph --graph <case>
topo-graph-partition-harness/build/bin/tgp_run_experiment --algorithm <name> --graph <case> --config <config> --out-dir runs/EXPxxxx/final/<case-slug> --time-limit-sec 600
topo-graph-partition-harness/build/bin/tgp_validate_partition --graph <case> --partition <run-dir>/result.json
topo-graph-partition-harness/build/bin/tgp_score_partition --graph <case> --partition <run-dir>/result.json --out <run-dir>/score.json
```

Final gate requirements:

- `cases/final/` must stay empty until the user adds a real full-Xiangshan compute DAG.
- Final gate timeout budget is 600 seconds per case.
- Timeout, missing score, failed validation, or missing baseline on a final case means the node fails acceptance.
- Record runtime and score deltas versus the baseline for every final case.
- Final gate scores must use the same full-case matrix format, but under a separate `## Final Gate Score Matrix`.
- If no final case exists yet, record `final gate: pending user-provided case` and do not invent a surrogate.

## Step 11: Decide

Choose exactly one:

- `keep`: hypothesis is supported and should remain on active frontier.
- `branch`: mixed result; create specific child hypotheses.
- `reject`: evidence contradicts the hypothesis or cost is unacceptable.

The decision must include evidence, not just opinion.

Decision rules:

- `keep` requires routine-manifest validation success, net aggregate improvement versus the parent or baseline over the
  frozen routine manifest, and a passing final gate for every present final case.
- `keep` requires the full-case score matrix row count to match the frozen manifest row count.
- `keep` requires the baseline matrix and candidate matrix to contain identical case ids for the evaluated stage.
- `keep` is forbidden when only focus cases improve and the full routine aggregate is flat or worse.
- `keep` is forbidden if any routine or final case has an unexplained material regression in `cut_weight`, quotient
  complexity, or runtime budget.
- `keep` is forbidden if aggregate improvement disappears when all routine-manifest cases are included.
- `branch` is for mixed routine-manifest results where the aggregate improves but regressions identify a specific child
  hypothesis.
- `reject` is required for skipped cases, missing scores, failed fixed checks, final-gate timeout, or subset-only improvements.
- If no parent/baseline score exists for a required case in either stage, first create or reference a baseline node; do
  not claim success without a comparison point.

Search-tree continuation rules:

- `keep` must nominate the next most valuable child question, even if that child is not executed yet.
- `branch` must produce 1 to 3 explicit child hypotheses, each tied to one observed regression, one ambiguity, or one
  promising unexplored mechanism.
- `reject` must still state whether the next node should be a `local repair`, `objective shift`, or `family switch`.
- If the node produced no actionable next hypothesis, mark the local direction exhausted.
- If all local directions under the current parent are exhausted, the next attempt must climb to the nearest ancestor with
  an untried child idea; if none exists, create a new root child.
- Any non-activated child hypothesis must be written into `Parked Candidates` instead of being left only in prose.

The experiment file must end this section with:

```text
search_continuation: one of
- child of Sxxxx: <hypothesis>
- sibling under Sparent: <hypothesis>
- new root child: <hypothesis>
- none; direction exhausted
```

## Step 12: Update Search Tree

Update `memory/search_tree.md`:

- Move the node out of `in-progress` in `Active Frontier`.
- Add or update `next_action` for any surviving `keep` node.
- Write deferred child ideas into `Parked Candidates` with `activate_when` and `source_experiment`.
- Move rejected or exhausted nodes to `Closed Nodes` with reason and continuation.
- Update the affected algorithm family row in `Family Ledger`.

Search-tree maintenance rules:

- The active frontier must contain only nodes whose hypotheses are still live candidates for extension.
- A rejected or exhausted node must not remain in the active frontier.
- `Parked Candidates` must contain only hypotheses that are specific enough to execute later without re-deriving them.
- When a node yields child hypotheses, add only the best next child as `in-progress`; leave the others in
  `Parked Candidates` until chosen.
- When all children under one parent are rejected or exhausted, reflect that in the parent row or experiment note so the
  next attempt does not return there by accident.
- When starting a new root child because the frontier is exhausted, record which prior families were exhausted and why in
  `Family Ledger`.
- `Family Ledger` state must be one of `active`, `stalled`, `exhausted`, or `superseded`.

A search node without an experiment file and search-tree update is invalid.

## Output Contract

At the end of one execution, the repository must contain:

- One new or updated `memory/experiments/EXPxxxx_*.md`.
- One updated `memory/search_tree.md`.
- Any code changes for exactly one hypothesis.
- Run artifacts under `runs/<run-id>/`.
- Oracle artifacts under `cases/` only when explicitly requested by the user.
- A clear decision: `keep`, `branch`, or `reject`.

If implementation cannot proceed because harness infrastructure is missing, create an infrastructure blocker record instead of pretending the algorithm was evaluated.
