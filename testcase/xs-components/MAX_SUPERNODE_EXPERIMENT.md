# Supernode Experiment Status

Old max-supernode experiment results have been removed. The current checked-in
analysis tracks the default `testcase/xs-components` configuration only.

Use:

```bash
make -C testcase/xs-components stat
make -C testcase/xs-components cosim COSIM_TRACE=0
```

Current default result:

| Flow | Final supernodes | Supernode edges | Static instructions | `.text*` bytes |
|---|---:|---:|---:|---:|
| GSIM | 10 | 16 | 2,861 | 13,784 |
| GrhSIM | 123 | 391 | 6,301 | 29,210 |

Ratios:

```text
GrhSIM / GSIM supernodes          = 12.300x
GrhSIM / GSIM supernode edges     = 24.438x
GrhSIM / GSIM static instructions = 2.202x
GrhSIM / GSIM .text* bytes        = 2.119x
```

Current interpretation:

- The default GrhSIM activity schedule emits many small supernodes
  (`ops_median=6`, `ops_max=9`).
- The extra static instructions are dominated by value-change checks,
  active-bit propagation, and control branches between those supernodes.
- The current cosim passes after aligning all models to sample immediately
  after the rising edge, so this document describes a partition/code-shape
  difference rather than a behavior mismatch.

If max-supernode experiments are run again, record them as new data generated
from the current scripts rather than carrying over the removed historical
numbers.
