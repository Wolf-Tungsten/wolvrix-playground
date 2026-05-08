# FST ROI Discovery

This directory contains the older C++ prototype.

The active workflow has moved to the skill-local Python helper:

```bash
.venv/bin/python .codex/skills/fst-roi-discovery/fst_roi_discovery.py --help
```

Use the Python helper for current analysis work. The C++ prototype remains here only as historical reference.

Current scope:

- Build a lightweight source index over original SystemVerilog or Chisel sources.
- Read FST hierarchy and signal names.
- Rank candidate RTL regions and waveform signals from a short natural-language hint.
- Emit compact metadata JSON and bulk TSV artifacts.

Current limits:

- It does not yet infer time windows from activity.
- It does not yet read sampled value traces or transition summaries from the FST.
- Signal-path matches are heuristic rankings, not semantic proofs.
- Chisel support is currently source-text-based and does not yet consume FIRRTL or generated-SystemVerilog source breadcrumbs.

The current output is a discovery seed for later alignment work.

## Python Workflow

Preferred interpreter:

```bash
.venv/bin/python
```

Dependency check:

```bash
.venv/bin/python -c "import pylibfst"
```

## Usage

RTL-only discovery:

```bash
.venv/bin/python .codex/skills/fst-roi-discovery/fst_roi_discovery.py \
  --rtl-kind sv \
  --rtl tools/fst_tools/roi_discovery/testdata/lightweight_sample.sv \
  --artifact-prefix tmp/fst_roi/sv_writeback \
  --hint "writeback data"
```

RTL + FST hierarchy discovery:

```bash
.venv/bin/python .codex/skills/fst-roi-discovery/fst_roi_discovery.py \
  --fst /path/to/wave.fst \
  --rtl-kind chisel \
  --rtl path/to/Foo.scala \
  --artifact-prefix tmp/fst_roi/load_retry \
  --hint "load retry path" \
  --limit 12
```

## Artifact Outputs

When `--artifact-prefix PREFIX` is provided, the Python helper writes:

- `PREFIX.metadata.json`: compact metadata with query information and ranked candidates.
- `PREFIX.signals.tsv`: bulk signal rows for machine comparison.

The full workflow uses two producers:

- Python helper: `PREFIX.metadata.json` and `PREFIX.signals.tsv`
- AI analysis layer: `PREFIX.ai.md`

`PREFIX.ai.md` is not produced by the helper script. It should be written by the AI workflow using the agreed `Summary + Structured yaml` format.

The TSV columns are:

- `path`
- `scope`
- `name`
- `width`
- `handle`
- `candidate_rank`
- `candidate_score`
- `candidate_reason`

## Input Guidance

- `--rtl-kind` must be `sv` or `chisel`.
- `--rtl` can be repeated. Pass original RTL first. For Chisel, generated SV or FIRRTL side artifacts can be added later when available.
- `--hint` should describe behavior, module role, interface meaning, or a suspected event instead of raw signal names when exact names are unknown.
- `--fst` is optional. Without it, the tool still returns ranked RTL candidates.

## Output Shape

The helper prints one compact JSON object with:

- `query`: normalized query metadata.
- `candidate_regions`: ranked RTL source anchors.
- `candidate_signals`: ranked waveform paths from FST hierarchy.

Each candidate carries a short `reason` field so downstream prompts can keep only the top few rows and stay token-efficient.

For stable comparison across runs:

- `candidate_regions` are sorted by descending `score`, then by file path, then by line number.
- `candidate_signals` are sorted by descending `score`, then by signal path.
- Treat the emitted signal `path` as one raw hierarchy rendering from the helper, not as a universal canonical name.
- If different FST sources use different separators or renamed scopes, resolve those differences in the AI analysis layer as a hypothesis, not as a parser-level guarantee.
- Prefer comparing only the top few rows instead of the full result set.