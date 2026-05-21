# NO0163: State Storage-Ref Alias Switch

Date: 2026-05-21

## Goal

Continue from NO0162. ThinLTO showed that cross-TU batch visibility is not the main cause, so the next target is generated batch body shape.

The strongest concrete clue is the hot commit batches in `no0162`: several top perf symbols contain thousands of per-supernode state storage aliases before doing the actual work.

## Evidence

From `build/logs/xs/no0162_fullword_fastpath_coremark20k.perf.data`, top commit symbols include:

| symbol | self overhead |
| --- | ---: |
| `eval_commit_batch_990` | `0.91%` |
| `eval_commit_batch_951` | `0.91%` |
| `eval_commit_batch_977` | `0.83%` |
| `eval_commit_batch_979` | `0.82%` |
| `eval_commit_batch_968` | `0.79%` |

Static inspection of the corresponding generated files showed:

| batch | lines | `grhsim_value_storage_ref` | state aliases | commit scalar table calls |
| ---: | ---: | ---: | ---: | ---: |
| `990` | `59863` | `4096` | `4096` | `30` |
| `951` | `56556` | `4096` | `4096` | `19` |
| `977` | `59148` | `4096` | `4096` | `61` |
| `979` | `61183` | `4096` | `4096` | `6` |
| `968` | `64188` | `4096` | `4096` | `6` |

This points to a concrete generated-code-shape issue: very large active supernodes eagerly declare thousands of state reference aliases, even when only a subset is on the hot path of that cycle.

## Generator Change

Added a default-on switch:

```text
WOLVRIX_GRHSIM_STATE_STORAGE_REF_ALIASES
```

Behavior:

- default: unchanged, state storage-ref aliases are emitted;
- `WOLVRIX_GRHSIM_STATE_STORAGE_REF_ALIASES=0`: skip only state aliases;
- value aliases remain enabled;
- existing global `WOLVRIX_GRHSIM_STORAGE_REF_ALIASES=0` still disables all storage-ref aliases.

Changed file:

```text
wolvrix/lib/emit/grhsim_cpp.cpp
```

## Local Validation

Added an emit test using the existing register-write interaction design:

- default emit still exercises normal register-write behavior;
- with `WOLVRIX_GRHSIM_STATE_STORAGE_REF_ALIASES=0`, generated schedule has no `auto &grhsim_state_` aliases;
- generated schedule still has `auto &grhsim_value_` aliases;
- state accesses fall back to direct `grhsim_value_storage_ref<std::uint8_t>(state_logic_storage_, ...)`.

Validation commands:

```sh
cmake --build wolvrix/build --target emit-grhsim-cpp -j32
ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'
```

Results:

```text
emit-grhsim-cpp build: passed
emit-grhsim-cpp test: passed, 56.57 sec
```

Generated small-test shape:

```text
state_alias: 0
value_alias: 3
state_direct_ref: 14
sched files: 2
```

## Abandoned No-Fresh Probe

Before adding the generator switch, I attempted a no-fresh generated-file A/B by hardlink-copying the no0162 generated tree and mechanically deleting state aliases in hot commit batches.

This was abandoned for two reasons:

1. `cp -al` created hardlinks, so writing the copy also changed the original no0162 source files.
2. The text rewrite was too slow for large generated files because each hot batch has thousands of alias identifiers.

Important status:

- The historical no0162 `libgrhsim_SimTop.a` and emu binary remain valid runtime evidence.
- The no0162 generated source tree under `tmp/no0162_xs_assign_fullword_fastpath/grhsim_emit` is now contaminated and should not be used as a pristine source baseline.
- Future writable generated-model experiments must use a real copy, for example `cp -a --reflink=auto` or `rsync -a`, not `cp -al`.

## Conclusion

The next clean validation should be a fresh emit specifically for this new switch, because the generator output is the thing under test. This is a justified fresh emit, unlike generic reruns.

Expected gate:

- fresh emit with `WOLVRIX_GRHSIM_STATE_STORAGE_REF_ALIASES=0`;
- structure/code-shape check: hot commit batches lose `auto &grhsim_state_` declarations while value aliases remain;
- build + 20k difftest;
- only run 50k if 20k is functional and not clearly slower.

If this improves runtime, the root-cause statement can be sharpened from generic "generated-code shape" to "eager state-ref aliasing and generic storage access inflate hot batch body frontend pressure." If it is neutral/negative, the next target should be commit activation/table structure or direct typed storage layout rather than alias declaration placement.
