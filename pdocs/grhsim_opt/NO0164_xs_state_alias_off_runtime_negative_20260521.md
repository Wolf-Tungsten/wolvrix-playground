# NO0164: XS State Alias Off Runtime Negative

Date: 2026-05-21

## Goal

Validate the generator switch from `NO0163` on XiangShan scale:

- emit with `WOLVRIX_GRHSIM_STATE_STORAGE_REF_ALIASES=0`;
- confirm hot commit batches no longer declare `auto &grhsim_state_...` aliases;
- build the generated model and difftest emu;
- run CoreMark 20k with difftest before deciding whether 50k is worth running.

This run accidentally did a fresh resume emit before the user clarified not to default to fresh emit. The generated directory is therefore treated as an existing artifact for the rest of this note; subsequent build/runtime steps did not rerun emit.

## Artifact

Generated model:

```text
tmp/no0164_xs_state_alias_off_structure/grhsim_emit
```

Emit command used `WOLVRIX_GRHSIM_STATE_STORAGE_REF_ALIASES=0` with the current C1/C2-style ESSENT settings from the recent flow:

```text
enable_essent_mffc_build=true
enable_essent_coarsen=true
enable_essent_small_sibling_merge=true
small_sibling_max_preds=2
small_sibling_candidate_budget=250000
sched_batch_target_count=800
```

Emit timing:

```text
read_json_file: 21201 ms
activity-schedule: 189601 ms
write_grhsim_cpp: 64434 ms
total: 275237 ms
real: 276.81 s
```

## Structure Gate

Final schedule stats:

| metric | value |
| --- | ---: |
| supernodes | `74171` |
| compute supernodes | `73656` |
| commit supernodes | `515` |
| dag edges | `670160` |
| boundary values | `1905504` |
| boundary activation edges | `3090763` |
| compute-compute value pairs | `2732649` |
| compute-commit value pairs | `358114` |
| sched cpp files | `993` |

ESSENT merge detail:

| metric | value |
| --- | ---: |
| initial compute supernodes | `3720195` |
| clusters after single-parent | `3414373` |
| clusters after small-siblings | `3323371` |
| single-parent merges | `305822` |
| small-sibling merges | `91002` |
| rejected by size | `0` |
| rejected by cycle | `25594` |
| rejected by bounded path | `974070` |

Hot commit batch shape after the switch:

| batch | lines | value aliases | direct state storage refs |
| ---: | ---: | ---: | ---: |
| `951` | `38546` | `2` | `8523` |
| `968` | `55413` | `173` | `11478` |
| `977` | `51054` | `234` | `10015` |
| `979` | `57027` | `1117` | `12155` |
| `990` | `56300` | `121` | `11431` |

Global generated schedule check:

```text
rg -c 'auto &grhsim_state_' .../grhsim_SimTop_sched_*.cpp
exit code 1, no matches
```

So the structure gate passed: state aliases were removed at XiangShan scale, while value aliases remained. The replacement form is repeated direct `grhsim_value_storage_ref<...>(state_logic_storage_, ...)` access.

## Build

Model build:

```sh
/usr/bin/time -p make -C tmp/no0164_xs_state_alias_off_structure/grhsim_emit -j32 CXX=clang++
```

Result:

```text
real 924.13
user 15133.12
sys 95.94
libgrhsim_SimTop.a: 183604380 bytes
```

Difftest emu build:

```sh
/usr/bin/time -p make -C testcase/xiangshan/difftest grhsim-build-emu \
  NOOP_HOME=/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan \
  BUILD_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/no0164_xs_state_alias_off_structure/build \
  GEN_CSRC_DIR=/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/build/generated-src \
  NUM_CORES=1 WITH_CHISELDB=0 WITH_CONSTANTIN=0 \
  GRHSIM=1 \
  GRHSIM_MODEL_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/no0164_xs_state_alias_off_structure/grhsim_emit \
  WOLVRIX_GRHSIM_WAVEFORM=0 \
  CXX=clang++
```

Result:

```text
real 7.27
user 6.52
sys 0.76
emu: 172422024 bytes
```

## CoreMark 20k Gate

Command:

```sh
cd tmp/no0164_xs_state_alias_off_structure/build
EMU_PROGRESS_EVERY_CYCLES=10000 /usr/bin/time -p ./grhsim-compile/emu \
  -i /home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff /home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 20000
```

Result:

```text
The first instruction of core 0 has commited. Difftest enabled.
[EMU_PROGRESS] host_cycles=10000 model_cycles=10000 instr=458 commit_pc=0x80001cdc trap_pc=0x800027c6 core=0 host_ms=43308
[EMU_PROGRESS] host_cycles=20000 model_cycles=20000 instr=14121 commit_pc=0x8000043a trap_pc=0x80000440 core=0 host_ms=166369
Guest cycle spent: 20001
Host time spent: 166379ms
real 166.39
user 166.35
sys 0.01
```

Exit code was `0`; no difftest mismatch appeared.

## Comparison

| model | 10k host ms | 20k host ms |
| --- | ---: | ---: |
| `NO0162` baseline | `23471` | `98988` |
| `NO0162` ThinLTO | `23424` | `99145` |
| `NO0154` current improved | `24299` | `103348` |
| `NO0164` state alias off | `43308` | `166369` |

`NO0164` is much slower than the nearest comparable runs:

- vs `NO0162` baseline 20k: `+67381 ms`, about `+68.1%`;
- vs `NO0154` 20k: `+63021 ms`, about `+61.0%`.

Therefore 50k is not worth running for this variant.

## Conclusion

Removing state storage-ref aliases is not the fix. It proves the opposite of the initial micro-hypothesis:

- eager state alias declarations are noisy in source shape, but they likely help the compiler keep repeated state slots in a local reference;
- replacing them with repeated direct `grhsim_value_storage_ref<...>(state_logic_storage_, offset)` materially worsens runtime;
- the root cause remains generated hot-batch body shape, but not simply "too many state alias declarations".

The next direction should keep or improve local state-slot binding while reducing hot batch body frontend pressure elsewhere:

- reduce activation / commit branch density;
- reduce repeated generic storage helper expressions without deleting useful locality;
- compare hot batch machine code before/after alias removal to see whether extra address recomputation or alias-analysis loss explains the regression;
- prefer typed direct state layout or compact commit table forms over raw direct `storage_ref` repetition.

