# CASE_027: folded struct-array partial writes

XiangShan `WriteBuffer_54.entries` has packed dimensions `[0:0][3:0]`.
Ingest folds its 7-bit `setIdx` leaf into 28-bit scalar storage. Previously,
assigning one struct element padded that 7-bit leaf to 28 bits before splicing
it into its slot. The resulting 49-bit concat was truncated back to 28 bits,
clearing neighboring slots. The 8-bit `wayMask` leaf failed similarly.
The same folded storage also exposed a read bug: after consuming a packed
dimension, scalar member reads kept the old total width, so the next nested
dimension used an incorrect stride.

The shared fixture is
`wolvrix/tests/ingest/data/ingest_struct_array_fieldwise.sv`, top
`ingest_struct_array_partial_write`. It reduces the problem to three 1x4 arrays:
constant-index writes, dynamic-index writes, and writes through a nested struct
member. Scalar C++ arrays provide independent expected values for every lane;
no Verilator reference is built. The checks cover reset, hold, repeated updates
and simultaneous writes to all slots, including a nested array field. Both
whole-struct reads and explicit scalar-field reconstruction are checked for
512 cycles and 10,240 lane/field comparisons.

```sh
make -C testcase/xs-bugcase/CASE_027 run
```

Artifacts are written to `ptmp/xs-bugcase/CASE_027/`. The GrhSIM model is regenerated
on each invocation. Before the fix, the ingest-only regression reports a 49-bit
partial-write concat where the largest leaf storage is 32 bits.
With only the write fix applied, explicit member reads fail at cycle 1;
consuming each array dimension must also narrow the scalar leaf width.
