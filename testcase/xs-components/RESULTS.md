# Current Results

This document records the current default `testcase/xs-components` result. Old
coarse-partition and macro-node experiment data has been removed.

Commands:

```bash
make -C testcase/xs-components cosim COSIM_TRACE=0
make -C testcase/xs-components stat
```

The DUT source is:

```text
src/main/scala/XsComponents.scala
  -> build/chisel-fir/XsComponents.fir
  -> build/chisel-sv/XsComponents.sv
```

## Cosim

The testbench drives the C++ reference model, GSIM, and GrhSIM with the same
vectors. Inputs are first settled at low clock, then the clock is raised, and
outputs are sampled immediately after the rising-edge `eval()` / `step()`.

Current result:

```text
[PASS] xs-components cosim cycles=258 checked reference=gsim=grhsim
```

This means the current default GSIM and GrhSIM generated models are aligned at
the testbench's visible cycle point.

## Static Model Stats

The static instruction counts are disassembly counts from generated model
object files only. They exclude the final simulator harness/runtime code. Code
size is the sum of `.text` and `.text.*` section sizes in those object files.

| Flow | Final supernodes | Supernode edges | Model C++ files | Model C++ LOC | Model objects | Static instructions | `.text*` bytes |
|---|---:|---:|---:|---:|---:|---:|---:|
| GSIM | 10 | 16 | 1 | 3,286 | 1 | 2,861 | 13,784 |
| GrhSIM | 123 | 391 | 14 | 6,936 | 14 | 6,301 | 29,210 |

Ratios:

```text
GrhSIM / GSIM supernodes          = 123 / 10    = 12.300x
GrhSIM / GSIM supernode edges     = 391 / 16    = 24.438x
GrhSIM / GSIM static instructions = 6301 / 2861 = 2.202x
GrhSIM / GSIM .text* bytes        = 29210 / 13784 = 2.119x
```

## Mnemonic Shape

Largest percent-share deltas in the current default build:

| Mnemonic | GSIM | GrhSIM | Observation |
|---|---:|---:|---|
| `mov` | 823 / 28.77% | 910 / 14.44% | GrhSIM has more total code, so `mov` share drops despite a higher count. |
| `cmp` | 231 / 8.07% | 971 / 15.41% | GrhSIM emits many value/control checks. |
| `je` | 25 / 0.87% | 409 / 6.49% | Change-detect and active-propagation branches. |
| `lea` | 172 / 6.01% | 28 / 0.44% | GSIM gets more fused address/arithmetic lowering. |
| `jne` | 15 / 0.52% | 364 / 5.78% | Change-detect and active-propagation branches. |
| `test` | 30 / 1.05% | 375 / 5.95% | Active-mask and predicate checks. |
| `xor` | 152 / 5.31% | 52 / 0.83% | Different lowering of fused expressions. |
| `setbe` | 126 / 4.40% | 0 / 0.00% | Compare lowering differs. |
| `or` | 189 / 6.61% | 678 / 10.76% | Active-mask propagation and packed bit construction. |
| `and` | 210 / 7.34% | 579 / 9.19% | Mask construction and predicate logic. |

## Interpretation

The current default GrhSIM model is behaviorally aligned with GSIM, but it is
not structurally close at the object-code level. The dominant difference is the
activity-scheduled graph shape:

- GSIM emits `10` final supernodes and `16` emitted supernode edges.
- GrhSIM emits `123` activity-schedule supernodes and `391` DAG edges.
- GrhSIM's default `max-compute-node-in-compute-supernode=8` keeps supernodes small
  (`ops_mean=6.699`, `ops_median=6`, `ops_max=9`).

The extra static code is therefore expected in the current default setting: many
small GrhSIM supernodes require more old/new checks, active-bit updates, and
branching between supernodes. The cosim pass confirms that this is a
code-shape/partitioning difference, not a functional mismatch for this DUT.
