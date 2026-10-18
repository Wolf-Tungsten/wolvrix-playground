# AheadBtb target correction isolation

`rtl/AheadBtbTargetCorrect.sv` extracts the combinational logic at
`ptmp/xs/rtl/rtl/AheadBtb.sv:525-605`: position/attribute hit checks, priority
encoding, eight conditional 22-bit target terms, the target comparison, and the
bank 0 correction write enable. The packed train interface keeps the fields
read by this logic. This is a cone extracted into its own module, not a replay
of the full AheadBtb with SRAMs and training registers.

`tb.v` drives the train interface through scalar inputs. All ways receive the
same target and attributes, while the hit mask selects a way. The first vector
uses the key cycle-10286 values: way 4, position 26, branch type 3, RAS action 2,
and equal target low bits `0x13b5`. Other, unselected entries are simplified;
the target high bits are a synthetic value because the logic only reads `[21:0]`.

From the repository root:

```sh
make -C testcase/xs-bugcase/CASE_026 run
```

This builds Verilator and the GrhSIM IR CPU model from the same SV and executes
both in one harness. It succeeds only if all vectors match and the
reference/oracle and hit-selection controls agree. `reproduce` retains the
historical mode that succeeds only when the cycle-10286 bug appears; it should
fail with the fixed implementation.

All generated code, binaries, IR files, and `results.csv` go under
`ptmp/xs-bugcase/CASE_026/`. The case uses the installed repository Python
binding; it does not install packages or rebuild Wolvrix. Build concurrency is
limited to two jobs per generated Makefile. The GrhSIM model is regenerated
on each invocation so a previous model cannot hide a binding change. After
editing Wolvrix, rebuild the binding through the repository's `make py_install`
before running this case.

Before the 2026-10-18 fix: 72 vectors, 51 mismatches, zero reference/oracle or
hit-selection control errors. The first vector produced
`needCorrectTarget ref=0 grhsim=1 writeBank0 ref=0 grhsim=1`. Equal targets
above 1 spuriously requested correction; targets that differed only above bit 0
could also miss a required correction.

After fixing the ingest width boundaries and rebuilding the binding:

```text
[SUMMARY] vectors=72 mismatches=0 reference_or_control_errors=0 trace_10286=matched
[PASS] isolated AheadBtb target correction matches Verilator
```

The cycle-10286 vector now gives `needCorrectTarget ref=0 grhsim=0
writeBank0 ref=0 grhsim=0`. The final `verify-extraction run` check returned 0
in 3.64 seconds with peak RSS 232,208 KiB (about 227 MiB). Before/after CSVs
and the final log are saved under `ptmp/xs-target-width-fix/` as
`case026-before.csv`, `case026-after.csv`, and `case026-after.log`.

If the original generated RTL is present, `make -C
testcase/xs-bugcase/CASE_026 verify-extraction` checks that the position checks
through target-comparison expression match the original source verbatim.
This check passed in the final verification.
Normal build and replay do not require that RTL or the full XiangShan tree.
