# C910 Bugcase 004 - ct_idu_id_decd comb-loop-elim warning

This case extracts the first `comb-loop-elim` warning from
`build/logs/c910/c910_coremark_20260301_225241.log`. The warning points to
`ct_idu_id_decd.v:776:8`, so the bugcase uses `ct_idu_id_decd` as the top
module and includes its only submodule (`ct_idu_id_decd_special`).

Warning snippet:

```
warning [comb-loop-elim] comb loop detected (values=11, ops=11) \
  srcloc=../../C910_RTL_FACTORY/gen_rtl/idu/rtl/ct_idu_id_decd.v:776:8 \
  status=false-candidate-unresolved
```

## Repro (comb-loop-elim)

Run from repo root:

```
python3 -m pip install --no-build-isolation -e wolvrix
python3 - <<'PY'
import wolvrix

filelist = "testcase/c910-bugcase/CASE_004/filelist.f"
args = ["-f", filelist, "--top", "ct_idu_id_decd"]

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
cd testcase/c910-bugcase/CASE_004
make run
```
