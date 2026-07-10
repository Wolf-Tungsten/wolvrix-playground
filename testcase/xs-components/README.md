# XiangShan Component Matrix

This testcase isolates 100 standalone medium/large, stateful
XiangShan-derived components for GSIM vs GrhSIM performance analysis.  Every
case is generated as its own Scala source file under `src/main/scala/cases/` and
is self-contained: it imports Chisel, defines its own IO bundle and local helper
logic, and does not extend or call a shared xs-components case template.

`cases.json` records the real XiangShan source file used as the origin for each
case, the extracted DUT top, scale, and benchmark TB.

Run the full matrix:

```bash
make -C testcase/xs-components matrix
```

Run one case:

```bash
make -C testcase/xs-components CASE=XsReal000PipelineLoadunitLarge one
```

Outputs are under `testcase/xs-components/build/<case>/`:

- `chisel-fir/<case>.fir`: FIRRTL source for GSIM.
- `chisel-sv/<case>.sv`: SystemVerilog source for GrhSIM.
- `gsim/model/`: generated GSIM C++ model.
- `grhsim/model/`: generated GrhSIM C++ model.
- `tb/<case>_bench.log`: co-simulation verification and benchmark log.
- `stats/model_stats.json`: per-case performance and static model stats.
- `build/matrix/results.csv`: one-row-per-case matrix summary.

The cases intentionally contain register-backed tables and per-cycle state
updates, so runtime profiles have nonzero state source and sink work rather than
collapsing to pure combinational compute.
