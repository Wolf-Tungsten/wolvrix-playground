# GSIM vs GrhSIM Performance Root Cause

This testcase compares the same isolated XiangShan-shaped DUTs with the same
C++ benchmark harness. It does not modify either simulator.

## Reproduction

Baseline matrix:

```bash
make -C testcase/xs-components matrix
```

Supernode-size sweep for the two worst baseline cases:

```bash
for c in XsAgeMatrixMedium XsPlruLarge; do
  for n in 8 16 32 64 128; do
    make -C testcase/xs-components CASE=$c BUILD_DIR=build-sweep/op$n \
      GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE=$n \
      BENCH_VECTORS=100000 BENCH_VERIFY=2048 one
  done
done
```

Additional PLRU sweep to close the remaining gap at cap 128:

```bash
for n in 256 512; do
  make -C testcase/xs-components CASE=XsPlruLarge BUILD_DIR=build-sweep/op$n \
    GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE=$n \
    BENCH_VECTORS=100000 BENCH_VERIFY=2048 one
done
```

Each run verified 2048 vectors before benchmarking.

## Baseline Matrix

Default GrhSIM uses `GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE=8`.

| Case | Kind | GSIM ms | GrhSIM ms | Slowdown | GSIM supernodes | GrhSIM supernodes | Instr ratio |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| XsBranchAluSmall | branch-alu | 2.164 | 3.260 | 1.51x | 4 | 24 | 1.77x |
| XsVectorMaskMedium | vector-mask | 9.997 | 32.330 | 3.23x | 1 | 167 | 2.09x |
| XsAgeMatrixMedium | scheduler-age | 5.018 | 36.735 | 7.32x | 1 | 157 | 2.51x |
| XsPlruLarge | replacement | 24.201 | 200.678 | 8.29x | 3 | 191 | 2.26x |
| XsStoreMergeLarge | store-merge | 3.619 | 7.924 | 2.19x | 1 | 29 | 1.28x |

The largest runtime slowdowns are larger than the static instruction growth.
That points to scheduling and supernode-boundary overhead, not only emitted code
size.

## Default GrhSIM Schedule Shape

| Case | GrhSIM supernodes | DAG edges | Boundary activation edges | Mean ops/supernode | Median ops/supernode | Max ops/supernode |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| XsBranchAluSmall | 24 | 41 | 52 | 6.7 | 7.0 | 8 |
| XsVectorMaskMedium | 167 | 584 | 613 | 6.5 | 7 | 8 |
| XsAgeMatrixMedium | 157 | 541 | 545 | 6.1 | 5 | 8 |
| XsPlruLarge | 191 | 643 | 937 | 6.9 | 7 | 8 |
| XsStoreMergeLarge | 29 | 97 | 148 | 7.1 | 8 | 8 |

The default cap keeps most compute supernodes at 5-8 operations. Wide
combinational cones are therefore split into many small scheduled units, with
hundreds of inter-supernode activation edges.

## Sweep Evidence

| Case | Max ops | GSIM ms | GrhSIM ms | Slowdown | GrhSIM supernodes | DAG edges | Boundary activation edges | Mean ops/supernode | GrhSIM instr | Instr ratio |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| XsAgeMatrixMedium | 8 | 4.285 | 38.875 | 9.07x | 157 | 541 | 545 | 6.1 | 3685 | 2.51x |
| XsAgeMatrixMedium | 16 | 4.573 | 16.364 | 3.58x | 67 | 280 | 372 | 14.3 | 2510 | 1.71x |
| XsAgeMatrixMedium | 32 | 4.630 | 7.512 | 1.62x | 35 | 123 | 222 | 27.4 | 2048 | 1.40x |
| XsAgeMatrixMedium | 64 | 5.020 | 6.031 | 1.20x | 19 | 65 | 167 | 50.5 | 1795 | 1.22x |
| XsAgeMatrixMedium | 128 | 4.341 | 4.963 | 1.14x | 9 | 25 | 91 | 106.6 | 1577 | 1.08x |
| XsPlruLarge | 8 | 23.097 | 195.755 | 8.48x | 191 | 643 | 937 | 6.9 | 7637 | 2.26x |
| XsPlruLarge | 16 | 23.358 | 164.103 | 7.03x | 90 | 344 | 818 | 14.6 | 6385 | 1.89x |
| XsPlruLarge | 32 | 23.865 | 128.912 | 5.40x | 46 | 186 | 743 | 28.6 | 6081 | 1.80x |
| XsPlruLarge | 64 | 23.070 | 95.773 | 4.15x | 25 | 74 | 569 | 52.6 | 5523 | 1.63x |
| XsPlruLarge | 128 | 24.637 | 71.622 | 2.91x | 13 | 31 | 408 | 101.2 | 5339 | 1.58x |
| XsPlruLarge | 256 | 23.221 | 50.277 | 2.17x | 7 | 12 | 294 | 188.0 | 5187 | 1.53x |
| XsPlruLarge | 512 | 23.264 | 26.409 | 1.14x | 5 | 6 | 149 | 263.2 | 4507 | 1.33x |

The DUT, benchmark harness, compiler optimization level, and verification count
stay fixed while only the GrhSIM compute-supernode cap changes. GSIM time stays
roughly stable. GrhSIM time tracks the reduction in GrhSIM supernodes and
activation boundaries.

## Conclusion

The main root cause is over-fragmentation in GrhSIM's activity schedule for wide
combinational cones. With the default cap of 8 operations per compute supernode,
GrhSIM emits many tiny supernodes. This creates scheduler/activation overhead at
each boundary and prevents the C++ compiler from optimizing across the larger
combinational cone.

`XsAgeMatrixMedium` is the cleanest proof: raising the cap from 8 to 128 reduces
GrhSIM supernodes from 157 to 9 and lowers runtime from 38.875 ms to 4.963 ms,
nearly matching GSIM. The remaining instruction ratio is only 1.08x.

`XsPlruLarge` follows the same pattern after extending the sweep: raising the
cap from 8 to 512 reduces GrhSIM supernodes from 191 to 5 and lowers runtime
from 195.755 ms to 26.409 ms, nearly matching the 23.264 ms GSIM run. Boundary
activation edges drop from 937 to 149. The emitted instruction count remains
1.33x GSIM, but that residual code-size difference no longer creates a large
runtime gap once the schedule is coarsened.

## Suggested Next Experiments

1. Profile the generated `grhsim_XsPlruLarge_sched_*.cpp` path to separate
   boundary activation overhead from per-operation emitted-code overhead.
2. Consider a GrhSIM scheduling heuristic that permits larger supernodes for
   pure combinational cones while keeping smaller units where activity pruning
   has a measurable benefit.
