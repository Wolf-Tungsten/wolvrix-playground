# Chisel FIRRTL / GRH IR Alignment

This note describes the current default `testcase/xs-components` build only.
Old coarse-partition, matched-supernode, and macro-node experiment results have
been removed.

The source flow is:

```text
src/main/scala/XsComponents.scala
  -> build/chisel-fir/XsComponents.fir
  -> build/chisel-sv/XsComponents.sv
```

Current default static result:

```text
gsim   supernodes=10  supernode_edges=16  instructions=2861 text_size_bytes=13784
grhsim supernodes=123 supernode_edges=391 instructions=6301 text_size_bytes=29210
```

So the current default GrhSIM / GSIM ratios are:

```text
supernodes          = 12.300x
supernode edges     = 24.438x
static instructions = 2.202x
.text* bytes        = 2.119x
```

## FIRRTL Shape

The Chisel-generated FIRRTL contains:

| FIRRTL form | Count |
|---|---:|
| `regreset` | 3 |
| `connect` | 325 |
| `node` | 799 |
| `wire` | 12 |
| `mux(...)` | 59 |
| `eq(...)` | 55 |
| `lt(...)` | 129 |
| `geq(...)` | 258 |
| `and(...)` | 131 |
| `cat(...)` | 21 |
| `bits(...)` | 124 |
| `shl(...)` | 8 |

The dominant source of logic is still the vector mask/tail region:

- `body128 = VecInit((0 until 128).map(i => i.U >= startBytes && i.U < vlBytes)).asUInt`
- `tail128 = VecInit((0 until 128).map(i => i.U >= vlBytes)).asUInt`
- `maskEn = VecInit((0 until 16).map(... io.maskUsed(i / scale) ...)).asUInt`

CIRCT emits packed SystemVerilog arrays for this region, while both simulators
eventually lower the same compare-heavy mask logic into C++.

## GSIM Graph Shape

Current GSIM final stats:

| GSIM metric | Value |
|---|---:|
| Final nodes | 746 |
| Graph-partition supernodes | 12 |
| Emitted supernodes | 10 |
| Emitted supernode edges | 16 |
| Unique `ENode`s under node-owned trees | 4,289 |
| Mean unique `ENode`s per `Node` | 5.75 |
| Median unique `ENode`s per `Node` | 6 |
| P90 unique `ENode`s per `Node` | 6 |
| P99 unique `ENode`s per `Node` | 32 |
| Max unique `ENode`s per `Node` | 64 |

The important unit mismatch remains: GSIM partitions coarse `Node*` members,
and each `Node` may own a non-trivial expression tree. A single GSIM supernode
therefore hides many expression-level operations inside fused C++ expression
bodies.

At GSIM graph-partition supernode granularity:

| Metric | Median | P90 | Max |
|---|---:|---:|---:|
| `Node*` members | 7 | 78 | 405 |
| Unique owned `ENode`s | 28 | 356 | 2,385 |

## GrhSIM Graph Shape

Current GrhSIM activity-schedule stats:

| GrhSIM metric | Value |
|---|---:|
| Activity-schedule supernodes | 123 |
| DAG edges | 391 |
| Ops per supernode mean | 6.699 |
| Ops per supernode median | 6 |
| Ops per supernode P90 | 8 |
| Ops per supernode P99 | 9 |
| Ops per supernode max | 9 |
| DAG out-degree mean | 3.179 |
| DAG out-degree median | 1 |
| DAG out-degree P90 | 7 |
| DAG out-degree P99 | 9 |
| DAG out-degree max | 81 |

With the default `GRHSIM_SUPERNODE_MAX_SIZE=8`, GrhSIM deliberately emits many
small compute supernodes. This exposes many intermediate values as
schedule-visible slots, so the generated C++ must compare old/new values and
activate downstream supernodes when a slot changes.

## Native Code Shape

Current generated model size:

| Flow | Model C++ files | Model C++ LOC | Model objects | Static instructions | `.text*` bytes |
|---|---:|---:|---:|---:|---:|
| GSIM | 1 | 3,286 | 1 | 2,861 | 13,784 |
| GrhSIM | 14 | 6,936 | 14 | 6,301 | 29,210 |

Main generated functions:

| Flow | Function | Symbol size |
|---|---|---:|
| GSIM | `SXsComponents::subStep0()` | `0x3159` bytes |
| GrhSIM | `GrhSIM_XsComponents::eval_compute_batch_0()` | `0x6b0c` bytes |
| GrhSIM | `GrhSIM_XsComponents::eval_commit_batch_1()` | `0x00c7` bytes |
| GrhSIM | `GrhSIM_XsComponents::eval()` wrapper | `0x020e` bytes |

The largest mnemonic deltas match this structure:

| Mnemonic | GSIM | GrhSIM | Main cause |
|---|---:|---:|---|
| `cmp` | 231 | 971 | old/new checks and predicates |
| `je` | 25 | 409 | per-value change branches |
| `jne` | 15 | 364 | per-value change branches |
| `test` | 30 | 375 | active-mask and predicate tests |
| `or` | 189 | 678 | active-bit propagation and packed masks |
| `and` | 210 | 579 | mask construction and predicate logic |
| `shl` | 72 | 275 | packed bit construction |
| `lea` | 172 | 28 | GSIM gets more fused arithmetic lowering |
| `setbe` | 126 | 0 | compare lowering difference |

## Sampling Semantics

The current cosim testbench samples at the same visible point for all three
models:

1. Apply the current inputs.
2. Settle low clock.
3. Raise the clock.
4. Sample immediately after the rising-edge model evaluation.
5. Drop the clock for the next cycle.

With this sampling point, the current result is:

```text
[PASS] xs-components cosim cycles=258 checked reference=gsim=grhsim
```

The previous mismatch was a testbench sampling-phase issue, not a functional
GrhSIM/GSIM disagreement.

## Conclusion

For this DUT, the current default models are behaviorally aligned but
structurally different. GSIM keeps more expression work inside coarse
`Node`/expression-tree bodies, while GrhSIM's default small supernodes expose
more intermediate values to the activity scheduler. That produces more
supernodes, more supernode edges, and roughly `2.2x` the static model
instruction count in the default configuration.
