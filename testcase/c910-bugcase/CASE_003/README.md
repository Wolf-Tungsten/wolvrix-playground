# C910 Bugcase 003 - APB 1-to-X matrix pready data chain

This case isolates the slice-chain pattern from
`csky_apb_1tox_matrix.v` where a wide vector is built by OR-ing a
new slice with the previous slice. In RTL this is a forward-only chain,
not a real combinational loop, but comb-loop-elim can conservatively
report a loop if slice indices are not resolved.

## Repro (comb-loop-elim)

Run from repo root:

```
PYTHONPATH=wolvrix/app/pybind python3 - <<'PY'
import wolvrix

filelist = "testcase/c910-bugcase/CASE_003/filelist.f"
args = ["-f", filelist, "--top", "sim_top"]

pipeline = [
    "xmr-resolve",
    "multidriven-guard",
    "blackbox-guard",
    "latch-transparent-read",
    "slice-index-const",
    ("hier-flatten", ["-sym-protect", "hierarchy"]),
    "comb-loop-elim",
]

design, _read_diags = wolvrix.read_sv(None, slang_args=args)
for spec in pipeline:
    if isinstance(spec, tuple):
        design.run_pass(spec[0], args=list(spec[1]))
    else:
        design.run_pass(spec)
PY
```

## Makefile

```
cd testcase/c910-bugcase/CASE_003
make run
```
