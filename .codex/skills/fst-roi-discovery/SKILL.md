---
name: fst-roi-discovery
description: Narrow a large FST waveform against original RTL with a Python helper stored alongside this skill. Use when asked to discover likely modules, signals, or local waveform ROI from vague behavioral hints.
---

# FST ROI Discovery

## Intake

- Require the user to specify the original RTL kind: `sv` or `chisel`.
- Ask for one or more original RTL files or source roots. Do not start from GRH, JSON IR, or derived repcut outputs.
- Ask for the FST path when waveform-side narrowing is required.
- Accept vague hints such as behavior, stage name, transaction role, or failure symptom. Exact signal names and exact time windows are optional.
- For Chisel, prefer original Scala sources first. If the repo also has generated SystemVerilog or FIRRTL with source-location breadcrumbs, include those paths as extra context.

## Dependency Check

- Prefer the workspace virtualenv Python when it exists, for example `.venv/bin/python`.
- Before any analysis, verify that the Python helper and `pylibfst` are usable:

```bash
.venv/bin/python .codex/skills/fst-roi-discovery/fst_roi_discovery.py --help
```

- Then verify `pylibfst` is importable in the Python you will use:

```bash
.venv/bin/python -c "import pylibfst"
```

- If `.venv/bin/python` does not exist, use `python3` explicitly and report which interpreter was used.
- If either check fails, stop and report the concrete Python or dependency error. Do not silently fall back to another parser path.

## Discovery Flow

- Start with RTL-only discovery when the user has not provided an FST yet.
- Run the helper with repeated `--rtl` arguments, the required `--rtl-kind`, and a short behavioral `--hint`.
- Add `--fst` when waveform hierarchy should be searched for likely signal paths.
- For every run, call the Python helper in this skill directory and pass `--artifact-prefix`.
- Before any comparison, deduplication, or summary, keep the raw FST names and let the AI perform name reconciliation explicitly.
- Keep `--limit` small, usually `8` to `16`, so the output stays token-efficient.
- Use the tool output to select a small set of source windows and signal paths before any deeper manual reasoning.

Example:

```bash
.venv/bin/python .codex/skills/fst-roi-discovery/fst_roi_discovery.py \
  --fst /path/to/wave.fst \
  --rtl-kind sv \
  --rtl path/to/top.sv \
  --rtl path/to/pipe_stage.sv \
  --artifact-prefix tmp/fst_roi/writeback_retry \
  --hint "writeback retry corruption" \
  --limit 10
```

## Artifact Files

- Every run must persist these three files with the same prefix, produced by two different programs:
  - Python helper: `<prefix>.metadata.json`
  - Python helper: `<prefix>.signals.tsv`
  - AI skill: `<prefix>.ai.md`
- File responsibilities:
  - `metadata.json`: query context, top ranked RTL regions, top ranked signal candidates, and artifact bookkeeping.
  - `signals.tsv`: machine-oriented bulk signal rows exported by the Python helper for fast diff, filtering, and downstream scripting.
  - `ai.md`: AI-side interpretation result for human review and run-to-run semantic comparison.
- Treat `metadata.json` as the retained interpretation context for the run.
- Treat `signals.tsv` as the high-volume comparison surface. Do not try to stuff the full TSV content back into the chat response.
- Treat `ai.md` as the persisted semantic judgment of the run. This file should be diffed against other `ai.md` files when comparing two analyses.
- If `--fst` is absent, still emit the two files. In that case `signals.tsv` may contain only the header row.
- The AI skill must write `ai.md` after reading the helper outputs. Do not rely on the chat transcript as the only copy of the interpretation.

## AI-Side Name Reconciliation

- Do not ask the Python helper to collapse all FST names into one fixed canonical rule. There is no universally correct renaming rule across wrappers, generated nets, flattened scopes, and mixed toolchains.
- Treat the helper output as raw evidence, not as a final naming truth.
- The AI should reconcile names only at analysis time, using soft evidence such as:
  - leaf token overlap
  - nearby hierarchy words
  - sibling signal families
  - width or bus-shape consistency
  - nearby RTL source anchors
  - known Chisel or SystemVerilog naming habits
- If a readable presentation path is useful, the AI may render one with `.` as a display separator, but that display form is not an identity key and must not replace the raw FST path.
- When two different raw paths may refer to the same semantic signal, record that as a hypothesis with an explicit confidence level instead of forcing a hard equivalence.
- When confidence is low, keep both paths separate and say why the mapping is ambiguous.

## Output Contract

- Always return exactly two sections in this order:
  1. `Summary`: 2 to 4 short lines of natural language.
  2. `Structured`: one fenced `yaml` block.
- Do not add any extra headings, prose blocks, or appendix after the YAML block.
- The chat response summarizes the run, but it does not replace the two persisted artifact files.
- Persist the exact same content to `<prefix>.ai.md`; that file is the authoritative AI interpretation artifact.
- In `Summary`, state only:
  - the most relevant RTL region family
  - the most relevant signal family
  - the main missing input, if any
- In `Structured`, use this exact key order so results from different runs are easy to diff:

```yaml
rtl_kind: sv|chisel
hint: <original user hint>
scope:
  fst_provided: true|false
  user_pinned_signals: []
  user_pinned_windows: []
  rtl_inputs: []
candidate_regions:
  - rank: 1
    inferred: true
    symbol: <module_or_signal_name>
    kind: module|instance|io|state|flow|assign|decl
    container: <enclosing module/class or "">
    file: <repo-relative path>
    line: <1-based line>
    score: <integer>
    reason: <short phrase>
candidate_signals:
  - rank: 1
    inferred: true
    raw_path: <original fst path or null>
    display_path: <ai-rendered readable path or raw_path>
    alias_hypothesis: <likely semantic name or null>
    confidence: low|medium|high
    width: <integer|null>
    score: <integer>
    reason: <short phrase>
missing_inputs:
  - <missing item>
next_probe:
  action: <single next command or investigation step>
  target: <file|signal|window>
```

- Formatting rules:
  - `candidate_regions` and `candidate_signals` must be sorted by descending `score`.
  - Keep at most 5 `candidate_regions` and 8 `candidate_signals`.
  - Use repo-relative paths in `file`.
  - Use `[]` for empty lists and `null` for unknown scalar values.
  - Mark user-provided items with `inferred: false`; mark discovered items with `inferred: true`.
  - For `candidate_signals`, `raw_path` is the only stable identity key inside one run.
  - `display_path` is for readability only.
  - `alias_hypothesis` is an AI judgment, not a guaranteed equivalence class.
  - `next_probe.action` must contain exactly one next step, not a menu of options.

## Current Limits

- The current Python helper ranks RTL regions and waveform hierarchy candidates only.
- It does not yet infer precise time windows from toggle activity.
- It does not read sampled value traces, transition counts, or per-cycle signal values out of the FST yet.
- It does not prove semantic equivalence between RTL names and waveform paths; the matches are heuristic rankings, not ground truth.
- FST name reconciliation has no fixed canonical rule here. Any aliasing across different raw paths is an AI-side hypothesis and can be wrong.
- For Chisel, it currently relies on lightweight source retrieval only. It does not yet use FIRRTL `fileinfo`, generated SystemVerilog comments, or a source map to recover exact origin links.
- It does not expand broad behavioral hints into a full subsystem investigation plan; it only returns the top local candidates.
- It does not compute minimal source windows automatically. The caller still needs to choose the final excerpt range around returned anchors.
- If FST hierarchy names are heavily renamed or flattened, signal ranking quality can drop sharply; report that risk instead of overstating confidence.
- If the user needs cycle-window inference, value-level alignment, or exact Chisel-origin mapping, say that the next implementation slice is required instead of pretending the feature already exists.
- When any of these limits blocks a confident answer, record the gap in `missing_inputs` and make `next_probe` target the smallest additional artifact or command that would reduce uncertainty.