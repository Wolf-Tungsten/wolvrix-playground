# XiangShan Component Extracts

This testcase compares GSIM and GrhSIM on one Chisel-generated DUT.

The only source design is:

```text
src/main/scala/XsComponents.scala
```

It is a standalone extract of recurring XiangShan-shaped logic:

- branch compare / invert logic
- ALU logic, fixed shifts, and rotates
- vector byte mask and tail mask generation
- mask expansion by `vsew`

Run:

```bash
make -C testcase/xs-components compare
make -C testcase/xs-components cosim
make -C testcase/xs-components stat
```

The flow is:

```text
Chisel source
  -> build/chisel-fir/XsComponents.fir -> GSIM
  -> build/chisel-sv/XsComponents.sv   -> GrhSIM
```

Useful targets:

```bash
make -C testcase/xs-components chisel-fir
make -C testcase/xs-components chisel-sv
make -C testcase/xs-components gsim
make -C testcase/xs-components grhsim
make -C testcase/xs-components stats
make -C testcase/xs-components stat
make -C testcase/xs-components cosim COSIM_CYCLES=256 COSIM_TRACE=0
```

Outputs:

- `build/chisel-fir/XsComponents.fir`: Chisel/CIRCT FIRRTL input for GSIM
- `build/chisel-sv/XsComponents.sv`: Chisel/CIRCT SystemVerilog input for GrhSIM
- `build/gsim/model/`: GSIM C++ model
- `build/grhsim/model/`: GrhSIM C++ model
- `build/tb/xs_components_cosim_tb`: C++ testbench that drives the reference model, GSIM, and GrhSIM with the same vectors
- `build/tb/xs_components_cosim.log`: per-cycle aligned trace, or only pass/fail output when `COSIM_TRACE=0`
- `build/stats/gsim.json`: objdump mnemonic stats for GSIM model objects
- `build/stats/grhsim.json`: objdump mnemonic stats for GrhSIM model objects
- `build/stats/compare.json`: total instruction ratio and mnemonic deltas
- `build/stats/model_stats.json`: GSIM/GrhSIM supernode counts, supernode edge counts, instruction counts, and `.text*` code size in bytes

The reported instruction counts are static disassembly counts from model object
files. They intentionally exclude final simulator harness/runtime code.
The reported code size is the sum of `.text` and `.text.*` section sizes in the
generated model object files.

The cosim testbench samples all models at the same visible cycle point:
current inputs are applied, the low clock phase is settled, the clock is raised,
and outputs are checked immediately after the rising-edge `eval()` / `step()`.
The standalone reference model uses the same rising-edge sampling convention.
