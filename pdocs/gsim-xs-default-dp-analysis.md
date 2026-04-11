# GSIM XiangShan Default DP Analysis

This note records one instrumented `gsim` run on `ready-to-run/SimTop-xiangshan-default.fir`.

## Command

```bash
cd tmp/gsim
build/gsim/gsim \
  --dump-dp-analysis \
  --stop-after=GraphPartition \
  --dir build/ir-stats/default-xiangshan-dp \
  --supernode-max-size=2 \
  --cpp-max-size-KB=8192 \
  ready-to-run/SimTop-xiangshan-default.fir
```

## Runtime

- elapsed: `682.92 s`
- peak RSS: `65786812 KB`

## Pre-DP

`Pre-DP` is sampled at stage `RemoveDeadNodes3`, which is the last point before `graphPartition`.

- nodes: `1980652`
- enodes: `9469863`

Per-node owned-tree ENode distribution:

- mean: `4.785`
- median: `4`
- p90: `5`
- p99: `9`
- max: `270850`

Here "owned-tree ENode" means the number of unique `ENode*` reachable from all `ExpTree*` fields directly attached to one scheduled `Node`.

## Post-DP

`Post-DP` is sampled at stage `GraphPartition`.

- supernodes: `132754`
- nodes: `1980652`
- enodes: `9469863`

Per-supernode node-count distribution:

- mean: `14.920`
- median: `2`
- p90: `23`
- p99: `165`
- max: `10188`

Per-supernode ENode-count distribution:

- mean: `71.356`
- median: `16`
- p90: `96`
- p99: `710`
- max: `273107`

Here "supernode ENode" means the number of unique `ENode*` reachable from all `ExpTree*` fields owned by the `Node`s inside that supernode.

## Raw Artifacts

- run log: `tmp/gsim/build/ir-stats/default-xiangshan-dp/run.log`
- analysis summary: `tmp/gsim/build/ir-stats/default-xiangshan-dp/dp-analysis.txt`
