# NO0098: no0162 Machine-Code Size Check

Date: 2026-05-21

## Goal

Check whether the source-level hot batch size from `NO0097` also means individual `grhsim` hot functions are larger than `gsim` hot functions in machine code.

No fresh emit, no build, no simulation.

## Method

Use existing binaries:

- `tmp/no0162_xs_assign_fullword_fastpath_emu/grhsim-compile/emu`
- `build/xs/gsim/gsim-compile/emu`

Command shape:

```bash
nm -S --size-sort <emu> | c++filt
```

## Hot Function Sizes

Representative `grhsim no0162` hot functions:

| function | size hex | size bytes |
| --- | ---: | ---: |
| `eval_commit_batch_990` | `0x413ed` | 267,245 |
| `eval_commit_batch_951` | `0x3d11a` | 250,138 |
| `eval_commit_batch_977` | `0x411dc` | 266,716 |
| `eval_compute_batch_259` | `0x327c6` | 206,790 |
| `eval_compute_batch_576` | `0x4a4d4` | 304,340 |

Representative `gsim` hot functions:

| function | size hex | size bytes |
| --- | ---: | ---: |
| `subStep18` | `0x8cbba` | 576,442 |
| `subStep315` | `0x81e1b` | 531,995 |
| `subStep133` | `0x3b055` | 241,749 |
| `subStep313` | `0x44cc3` | 281,795 |
| `subStep290` | `0x40b6c` | 265,068 |

## Interpretation

This rules out a simplistic explanation that "`grhsim` is slow because each hot generated function is much larger than `gsim`'s hot functions."

The stronger reading is:

- `grhsim` has more scheduled generated functions overall.
- `grhsim` has many more dynamic branches and storage/value references across those functions.
- Existing perf data shows much lower IPC plus higher branch/iTLB pressure.

So the likely root cause remains aggregate generated-code shape, not maximum single-function size.

## Next Step

The next no-fresh A/B should target dynamic branch/storage pressure inside generated batches, not simply function size or top-level call count.
