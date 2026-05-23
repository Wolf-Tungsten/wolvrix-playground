# XiangShan Component Matrix

This testcase isolates a small matrix of XiangShan-shaped components for GSIM
vs GrhSIM performance analysis. It does not modify either simulator.
`cases.json` records the source paths, extracted DUT top, scale, and benchmark
TB for each case.

Cases:

- `XsBranchAluSmall`: branch compare plus ALU shift/rotate datapath, from `BranchUnit` and `Alu`.
- `XsVectorMaskMedium`: vector byte mask and tail mask generation, from `ByteMaskTailGen` and vector memory helpers.
- `XsAgeMatrixMedium`: issue/load replay age selection, from issue queue and load queue age detectors.
- `XsPlruLarge`: replacement policy candidate selection, from utility and coupledL2 replacers.
- `XsStoreMergeLarge`: store-buffer byte merge and cross-16-byte masks, from `Sbuffer` and `StoreQueue`.

Run the full matrix:

```bash
make -C testcase/xs-components matrix
```

Run one case:

```bash
make -C testcase/xs-components CASE=XsVectorMaskMedium one
```

Outputs are under `testcase/xs-components/build/<case>/`:

- `chisel-fir/<case>.fir`: FIRRTL source for GSIM.
- `chisel-sv/<case>.sv`: SystemVerilog source for GrhSIM.
- `gsim/model/`: generated GSIM C++ model.
- `grhsim/model/`: generated GrhSIM C++ model.
- `tb/<case>_bench.log`: co-simulation verification and benchmark log.
- `stats/model_stats.json`: per-case performance and static model stats.
- `build/matrix/results.csv`: one-row-per-case matrix summary.

All cases use the same standalone IO ABI and C++ benchmark. The Chisel source
in `src/main/scala/XsComponents.scala` is a copied and reduced extract of the
named XiangShan logic shapes, changed only enough to remove the full XiangShan
parameter graph and make each module independently simulatable.
