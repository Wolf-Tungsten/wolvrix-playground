# NO0099: Hot Function Disassembly Shape

Date: 2026-05-21

## Goal

Quantify hot generated-function instruction shape in existing binaries, to avoid relying only on source line counts or function byte size.

No fresh emit, no build, no simulation.

## Method

Use `nm -S` to get hot function ranges, then `objdump -d --no-show-raw-insn --start-address --stop-address` to count:

- total instructions
- jumps
- conditional jumps
- calls
- memory-form instructions

Existing binaries:

- `tmp/no0162_xs_assign_fullword_fastpath_emu/grhsim-compile/emu`
- `build/xs/gsim/gsim-compile/emu`

## grhsim no0162 Hot Functions

| function | instructions | jumps | conditional jumps | calls | memory-form insns |
| --- | ---: | ---: | ---: | ---: | ---: |
| `eval_commit_batch_990` | 51,224 | 5,323 | 5,318 | 37 | 32,300 |
| `eval_commit_batch_951` | 48,415 | 8,043 | 8,043 | 19 | 32,226 |
| `eval_commit_batch_977` | 51,481 | 5,215 | 5,213 | 81 | 31,888 |
| `eval_compute_batch_259` | 44,121 | 515 | 370 | 0 | 21,366 |
| `eval_compute_batch_576` | 60,415 | 352 | 301 | 9 | 24,837 |

Top mnemonics for `eval_commit_batch_990`:

| mnemonic | count |
| --- | ---: |
| `orb` | 13,697 |
| `mov` | 6,734 |
| `movzbl` | 6,565 |
| `and` | 5,649 |
| `je` | 5,316 |
| `xor` | 3,791 |
| `movb` | 3,776 |
| `or` | 1,880 |
| `cmp` | 1,879 |
| `cmpb` | 1,466 |

## gsim Hot Functions

| function | instructions | jumps | conditional jumps | calls | memory-form insns |
| --- | ---: | ---: | ---: | ---: | ---: |
| `subStep18` | 115,124 | 1,728 | 1,536 | 0 | 60,501 |
| `subStep315` | 95,778 | 1,222 | 998 | 92 | 55,010 |
| `subStep133` | 49,383 | 5,420 | 3,525 | 244 | 19,018 |
| `subStep313` | 50,332 | 675 | 565 | 0 | 31,207 |
| `subStep290` | 49,710 | 2,849 | 2,066 | 0 | 26,914 |

Top mnemonics for `subStep18`:

| mnemonic | count |
| --- | ---: |
| `mov` | 50,348 |
| `or` | 22,599 |
| `shl` | 12,048 |
| `setne` | 11,376 |
| `cmp` | 11,338 |
| `test` | 1,536 |
| `movdqu` | 1,066 |
| `add` | 893 |
| `lea` | 880 |
| `jne` | 768 |

## Interpretation

This is a stronger shape signal than byte size:

- `grhsim` hot commit batches are branch dense. `eval_commit_batch_951` has `8,043` conditional jumps in `48,415` instructions.
- `gsim` can have larger hot functions, but its largest hot `subStep18` has only `1,536` conditional jumps in `115,124` instructions.
- `grhsim` hot commit batches also have high memory-form instruction density, consistent with generic slot/state access and many scalar write/activation paths.

This supports the current root-cause direction: the 10x gap is driven by aggregate generated-code control-flow and storage-access shape, not by one helper, one oversized function, or top-level function-call count alone.

## Next A/B

The next no-fresh A/B should reduce conditional-branch density inside hot commit batches while preserving schedule semantics. Candidate areas:

- scalar commit write activation checks
- per-entry/per-table scalar write path
- generated alias/read shape that expands into many `cmp`/`je`/`orb` patterns

The acceptance gate remains 20k CoreMark with difftest plus perf movement in the commit-batch bucket.
