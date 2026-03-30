# C910 Bugcase 002 - BUFGCE latch self-hold loop

This case isolates the C910 `BUFGCE` implementation that creates a
self-hold latch. After lowering, the latch is represented as a
combinational feedback loop, which triggers `comb-loop-elim` warnings.

## Repro (comb-loop-elim)

Run from repo root:

```
python3 -m pip install --no-build-isolation -e wolvrix
python3 - <<'PY'
import wolvrix

filelist = "testcase/c910-bugcase/CASE_002/filelist.f"
args = ["-f", filelist, "--top", "sim_top"]

# Match the C910 pipeline stages that lead into comb-loop-elim.
design, _read_diags = wolvrix.read_sv(None, slang_args=args)
for name in ["xmr-resolve", "multidriven-guard", "blackbox-guard",
             "latch-transparent-read", "hier-flatten", "comb-loop-elim"]:
    design.run_pass(name)
PY
```

## Makefile

```
cd testcase/c910-bugcase/CASE_002
make run
```
