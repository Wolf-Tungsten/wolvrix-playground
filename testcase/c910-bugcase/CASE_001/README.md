# C910 Bugcase 001 - inout + multidriven-guard conflict

This case mirrors the `sim_top -> soc -> apb -> gpio` inout chain from C910.
The top `sim_top` connects an `inout` port to a plain `wire`, which triggers
an inout binding with a default oe=0 constant in the parent graph. When
`multidriven-guard` detects that the inout oe value is already driven in the
parent graph before flattening, which would later conflict in `hier-flatten`.

## Repro (hier-flatten)

Run from repo root:

```
python3 -m pip install --no-build-isolation -e wolvrix
python3 - <<'PY'
import wolvrix

filelist = "testcase/c910-bugcase/CASE_001/filelist.f"
args = ["-f", filelist, "--top", "sim_top"]

design, _read_diags = wolvrix.read_sv(None, slang_args=args)
# xmr-resolve first to match the C910 pipeline
for name in ["xmr-resolve", "multidriven-guard", "hier-flatten"]:
    design.run_pass(name)
PY
```

Expected: `multidriven-guard` reports an inout already-driven error for the oe
mapping (before `hier-flatten`).

## Makefile

```
cd testcase/c910-bugcase/CASE_001
make run
```
