# NO0420 SimTop full active-word build gate

日期：2026-07-12

## 1. Build configuration

对 [NO0419](./NO0419_simtop_full_active_word_fresh_emit_gate_20260712.md) 验收的 fresh source 使用标准
XiangShan difftest GrhSIM Clang/O3 flow：

```text
GRHSIM=1
CXX=clang++
AR=ar
ARFLAGS=rv
CXXFLAGS=-std=c++20 -O3
NUM_CORES=1
WITH_CHISELDB=0
WITH_CONSTANTIN=0
WOLVRIX_GRHSIM_WAVEFORM=0
model build jobs=64
```

输入、输出和日志为：

```text
model: build/xs_grhsim_no0416_full_word_consume_20260712/grhsim/grhsim_emit
emu:   build/xs_grhsim_no0416_full_word_consume_20260712/grhsim/grhsim-compile/emu
log:   build/logs/xs/xs_wolf_grhsim_compile_no0420_full_word_consume_20260712.log
```

构建前 load average 为 `54.42/49.85/56.19`，主机有 384 个逻辑 CPU、约 937 GiB available memory，
且没有其他 `clang++/g++/cc1plus/ld.lld` 进程。该口径只用于判断并行 build 资源，不用于 runtime 性能结论。

## 2. Completion gate

构建 exit 0：

```text
difftest/harness CXX:       40
generated model compile:   153
generated model objects:   152
archive members:           152
archive commands:            1
final emu links:              1
warning/error/killed:         0
wall time:              108.08 s
user time:             2459.42 s
system time:             55.99 s
max RSS:             1,278,228 KiB
```

最终 `emu` 是未 strip 的 x86-64 PIE executable。artifact SHA256：

```text
libgrhsim_SimTop.a acd8438339954f63639b5fc572df79043614be88dd242451dce3b25b0cba1cde
emu                 173c4d571ea1181e46e98da91b67286df2756888993fecee20b54295f970680a
```

## 3. O3 size gate

与相同 schedule/config 的 NO0357 direct state-read O3 build 对比：

| metric | NO0357 | full-word | delta |
| --- | ---: | ---: | ---: |
| archive bytes | 99,341,410 | 98,669,722 | -671,688 (-0.676%) |
| emu file bytes | 93,707,232 | 93,035,488 | -671,744 (-0.717%) |
| `size` text bytes | 93,532,652 | 92,858,476 | -674,176 (-0.721%) |
| `size` data bytes | 9,368 | 9,368 | 0 |
| `size` bss bytes | 14,688 | 14,688 | 0 |

66 个 compute objects 均发生变化，而 35 个 state/eval/state-init objects 全部 SHA 相同。最终约 674 KiB
text 删除证明 full-word clear/restore 没有被 O3 完全等价消除；体积本身仍不是 runtime 性能结论。

## 4. Next gate

先运行 100-cycle CoreMark/NEMU smoke，检查 reset、终点和 `input_fullpass_blocked`。通过后分别做 10k 与
50k 功能回归，并与 NO0357/NO0360/NO0361 的 guest cycle、instruction、PC 和 progress checkpoints 对齐。
