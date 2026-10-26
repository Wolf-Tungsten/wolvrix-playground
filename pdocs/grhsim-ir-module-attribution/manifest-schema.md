# GrhSIM supernode origin manifest schema (v1)

Producer: `scripts/grhsim_supernode_origin_stats.py` (`--manifest OUT.json`).
The manifest attributes each General-phase CPU-backend supernode of a GrhSimModel
JSON checkpoint to the RTL module instance paths its ops came from, as recorded by
the per-op `origin_modules` parameter. It is the static join table between
generated-code/runtime supernode numbering and source module names.

```json
{
  "schema": "grhsim-supernode-origin-manifest/v1",
  "model": "<source path>",
  "supernode_count": N,
  "module_table": ["<path>", ...],
  "kind_table": ["<opType>", ...],
  "supernodes": [
    {"ordinal": 0, "category": "NonSink|SmallSinkEscape|SmallSinkEvent|Unknown",
     "phase": "General",
     "op_count": K,
     "ops": [[opId, kindIdx, width, [modIdx, ...]], ...],
     "groups": [{"kind_idx": k, "width": w, "origins": [modIdx, ...], "count": n}, ...]
    }
  ]
}
```

## Field-by-field

| field | type | meaning |
| --- | --- | --- |
| `schema` | string | Constant `"grhsim-supernode-origin-manifest/v1"`. Consumers must check it before reading anything else. |
| `model` | string | Filesystem path of the GrhSimModel JSON checkpoint the manifest was built from (as passed via `--model`). Informational; not a stable identity. |
| `supernode_count` | int | Number of General-phase supernodes = length of `supernodes`. |
| `module_table` | string[] | Interned origin module instance paths (`$`-joined, e.g. `u_core$u_exu$u_alu`). Ops and groups reference entries by zero-based index (`modIdx`). First occurrence order. Empty when no op carries `origin_modules`. |
| `kind_table` | string[] | Interned op type names (`OpRef` strings such as `core.compute.xor`). Referenced by zero-based index (`kindIdx` / `kind_idx`). First occurrence order. |
| `supernodes` | object[] | One entry per General-phase supernode, in partition-tree order; the entry's array position equals its `ordinal`. |

Per-supernode fields:

| field | type | meaning |
| --- | --- | --- |
| `ordinal` | int | Supernode ordinal = index of the supernode among the General phase branch's `Supernode` children in CpuPartition tree order. **Joins with (a) the generated C++ function symbol `sn_<ordinal>` and (b) the runtime timing TSV key `supernode_id`.** |
| `category` | string | `NonSink`, `SmallSinkEscape`, `SmallSinkEvent` (from the supernode partition's attr tail, `CpuSupernodeCategory`), or `Unknown` when the checkpoint predates the category annotation. |
| `phase` | string | Always `General`; the manifest only covers the General phase branch. |
| `op_count` | int | Number of member ops = concatenation length of the supernode's child `Node` partitions' op lists. Equals the sum of `groups[*].count`. |
| `ops` | array[] | Per-op rows `[opId, kindIdx, width, [modIdx, ...]]`, in member-op order. **Present only when the producer ran with `--op-level`**; absent in the default compact manifest. `opId` is the model `OpId` (1-based row index into the checkpoint's `operations`). |
| `groups` | object[] | Always present. Aggregate histogram of identical `(kind, width, origin-set)` buckets within the supernode — the compact default view. Sorted by `(kind_idx, width, origins)`. |

Per-group fields:

| field | type | meaning |
| --- | --- | --- |
| `kind_idx` | int | Index into `kind_table`: the bucket's op type. |
| `width` | int | Op result width in bits (see "Width semantics" below). |
| `origins` | int[] | Sorted, deduplicated indices into `module_table`: the bucket's origin module set. `[]` = uncovered (op has no `origin_modules` parameter or an empty one). |
| `count` | int (>= 1) | Number of member ops in this bucket. |

## Width semantics

`width` is the bit width of the op's single `core.logic` result value
(`core.logic<width, ...>` — the total width including shape dimensions). It is `0`
("unknown bucket") when:

- the op has no result or more than one result (e.g. state/output writes), or
- the result type is not `core.logic` (e.g. `core.real`, `core.string`).

The attribution side must treat width 0 as the unknown bucket, not as a 1-bit or
zero-width value.

## Origin semantics and coverage

The `origin_modules` op parameter is a list of module instance path strings
(serialized as a `"strings"` parameter; the producer also tolerates a single
comma-joined `"string"`). An op is **covered** when its parsed origin set is
non-empty; manifest coverage = fraction of member ops covered. Checkpoints
written before the parameter exists yield `module_table: []`, every group with
`origins: []`, and coverage 0%.

In the per-op rows, `[modIdx, ...]` is the op's full sorted, deduplicated origin
set; a multi-origin op appears with more than one index (e.g. logic duplicated
across module boundaries or inlined shared logic).

## Join contract

- Generated C++: the CPU emitter names each supernode function `sn_<ordinal>`.
- Runtime profile: the timing TSV emitted by the simulator keys rows by
  `supernode_id` (and `phase`); for the General phase, `supernode_id == ordinal`.
- Checkpoint: `ordinal` is the index of the supernode among the General phase
  branch's `Supernode`-kind children in the `mappings[cpu][4][2]` partition
  array order (EmitFunction leaves interleaved in the branch are skipped).
