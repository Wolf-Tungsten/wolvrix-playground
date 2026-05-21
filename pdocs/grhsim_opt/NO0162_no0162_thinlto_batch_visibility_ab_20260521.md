# NO0162: no0162 ThinLTO Batch Visibility A/B

Date: 2026-05-21

## Goal

Use an existing `no0162` generated model to test whether the `gsim` / `grhsim` gap is mainly caused by cross-translation-unit batch calls and poor optimizer visibility.

This is intentionally a no-fresh-emit experiment. It does not run `scripts/wolvrix_xs_grhsim.py` and does not regenerate model C++.

## Setup

Baseline generated model:

```text
tmp/no0162_xs_assign_fullword_fastpath/grhsim_emit
```

Experimental copy:

```text
tmp/no0162_lto_ab/grhsim_emit_lto
```

The experimental directory was created by hardlink-copying the generated source tree and deleting only build products:

```sh
cp -al tmp/no0162_xs_assign_fullword_fastpath/grhsim_emit tmp/no0162_lto_ab/grhsim_emit_lto
find tmp/no0162_lto_ab/grhsim_emit_lto \( -name '*.o' -o -name '*.a' -o -name '*.pch' \) -delete
```

## Model Build

Command:

```sh
/usr/bin/time -p make -C tmp/no0162_lto_ab/grhsim_emit_lto -j32 \
  CXX=clang++ AR=llvm-ar CXXFLAGS='-std=c++20 -O3 -flto=thin'
```

Result:

```text
real 215.87
user 4308.47
sys 56.22
libgrhsim_SimTop.a: 226M
```

For reference, the non-LTO no0162 emu binary is `111M`; the ThinLTO emu after link is `109M`.

## Difftest EMU Link

First attempt failed with GNU ld because `LLVMgold.so` was missing:

```text
/usr/bin/ld: .../LLVMgold.so: cannot open shared object file: No such file or directory
```

Retry used `lld`:

```sh
/usr/bin/time -p make -C testcase/xiangshan/difftest grhsim-build-emu \
  NOOP_HOME=/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan \
  BUILD_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/no0162_lto_ab/emu \
  GEN_CSRC_DIR=/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/build/generated-src \
  NUM_CORES=1 WITH_CHISELDB=0 WITH_CONSTANTIN=0 \
  GRHSIM=1 \
  GRHSIM_MODEL_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/no0162_lto_ab/grhsim_emit_lto \
  WOLVRIX_GRHSIM_WAVEFORM=0 \
  CXX=clang++ AR=llvm-ar \
  GRHSIM_MODEL_CXXFLAGS='-std=c++20 -O3 -flto=thin' \
  PGO_LDFLAGS='-flto=thin -fuse-ld=lld'
```

Result:

```text
real 75.99
user 1205.38
sys 3.24
tmp/no0162_lto_ab/emu/grhsim-compile/emu: 109M
```

## CoreMark 20k Gate

Command:

```sh
cd tmp/no0162_lto_ab/emu
EMU_PROGRESS_EVERY_CYCLES=10000 /usr/bin/time -p ./grhsim-compile/emu \
  -i /home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff /home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 20000
```

Result:

```text
The first instruction of core 0 has commited. Difftest enabled.
[EMU_PROGRESS] host_cycles=10000 model_cycles=10000 instr=458 commit_pc=0x80001cdc trap_pc=0x800027c6 core=0 host_ms=23424
[EMU_PROGRESS] host_cycles=20000 model_cycles=20000 instr=14121 commit_pc=0x8000043a trap_pc=0x80000440 core=0 host_ms=99145
Guest cycle spent: 20001
Host time spent: 99151ms
real 99.16
user 99.13
sys 0.01
```

No difftest mismatch appeared.

## Comparison

Baseline no0162 50k summary contains:

```text
[EMU_PROGRESS] host_cycles=10000 ... host_ms=23471
[EMU_PROGRESS] host_cycles=20000 ... host_ms=98988
Host time spent: 350265ms
```

20k comparison:

| model | 10k host ms | 20k host ms |
| --- | ---: | ---: |
| no0162 baseline | `23471` | `98988` |
| no0162 ThinLTO | `23424` | `99145` |

The ThinLTO version is effectively neutral and slightly slower at 20k: `+157ms`, about `+0.16%`.

## Conclusion

This A/B weakens the hypothesis that the dominant gap is simply cross-TU batch call overhead or lack of optimizer visibility across `eval()` and `eval_*_batch_*` functions.

ThinLTO makes the model archive larger, makes the emu link much more expensive, and does not improve CoreMark 20k runtime. Therefore it is not worth running 50k or perf for this variant.

The root-cause direction remains generated-code shape inside the batch bodies:

- generic `grhsim_value_storage_ref(...)` state/value access,
- large branch- and memory-dense commit/compute batch bodies,
- activation update granularity and table-driven commit code,
- code footprint and frontend pressure from generated body shape rather than just function-call fragmentation.

Next useful no-fresh A/B should target a small hot batch body or one typed state-access class, not another whole-program visibility experiment.
