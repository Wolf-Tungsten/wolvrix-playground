# CV32E40P single-thread simulator comparison

The driver is `scripts/cv32e40p_compare.py`. Run preparation on a host with network
access, then build and measure on node030. Defaults pin CV32E40P, CoreMark,
Wolvrix, sv2v and Yosys versions. Model and harness C++ use Clang 23.1.2 with
`-O3 -march=native`. Generated files and downloaded dependencies stay in `build/`.

```sh
python3 scripts/cv32e40p_compare.py prepare
ssh node030
cd /nfs/home/tanghaojin/wolvrix-SimpleTES-workspace-5/wolvrix-playground-cv32e40p
python3 scripts/cv32e40p_compare.py build
python3 scripts/cv32e40p_compare.py verify
python3 scripts/cv32e40p_compare.py measure
python3 scripts/cv32e40p_compare.py profile
python3 scripts/cv32e40p_compare.py control
python3 scripts/cv32e40p_compare.py report
```

Choose a fresh `--output` for a new experiment. `--tools` selects the native
tool build directory. Verification and measurement directories are exclusive;
reruns must not overwrite prior samples. No simulation measurements are run
during build. The runtime requires CPU96, NUMA1, one thread and disabled ASLR.
CPU288 sibling activity is recorded, without changing other users' processes.

## Shared hardware and firmware

`Cv32Bench.sv` wraps the original CV32E40P top with FPU and CORE-V extensions
disabled, the upstream simulation clock gate, one HPM counter, a zero initialized
4 MiB byte RAM, and deterministic one-cycle instruction/data responses. Stores
honor byte enables. Reads return pre-edge data; there are no random stalls or
external interrupts. Firmware boots at `0x180`.

RAM is part of the RTL in both backends. While reset is asserted, the common C++
harness loads the same binary through a 32-bit RTL write port. This avoids the
different compile-time/runtime interpretations of `$readmemh`. Only the loaded
image bytes are transferred; the rest of RAM has the same zero initializer.
Loading and reset are timed separately from the execution loop. The loader port
stays disabled throughout execution. UART output is buffered in the common
harness, not printed per character during measurement.

The address map is based on the upstream testbench: UART at `0x10000000`, exit
at `0x20000004`, and cycle ticks at `0x15001004` for the upstream CoreMark port.
Unmapped accesses fail the run. `smoke.c` checks startup, byte/halfword stores,
dependent loads/stores, UART and exit. CoreMark's algorithms are downloaded
unchanged, with RV32IM/ILP32, performance seeds, 2 KB data and ten iterations.
The local startup, linker script and integer-only libc surface remove the need
for an RV32 newlib installation. Its printed “seconds” field is upstream's cycle
placeholder, not a CoreMark score or host duration.

## Import compatibility and comparison boundary

Wolvrix `74d80cf` cannot directly import this upstream SystemVerilog: enum
constants, packed struct reads, generate-local symbols and mixed drivers expose
frontend limitations. The benchmark therefore runs sv2v 0.0.13 followed by Yosys
0.33 `proc; pmuxtree; flatten; opt -full; splitnets; opt_clean`, without technology
mapping. Only CPU RTL is normalized; testbench RAM remains unchanged. Yosys
specializes the same top parameter values before conversion.

Both primary backends receive exactly the same normalized RTL. An additional
Verilator model receives the original SystemVerilog and must match the complete
smoke and CoreMark traces. This functional check does not imply that normalization
has no effect on simulator speed. Reports distinguish that limitation explicitly.

## Measurement contract

Three models must match UART, exit code, completion cycle, and every cycle's
accepted instruction/data bus transaction. CoreMark must also match its known
CRCs; a zero exit code alone is insufficient. Trace records are nine little-endian
32-bit words: cycle low/high, instruction valid/address, data valid/address,
write enable, byte enables, and write data. Inactive payloads are zeroed.

Performance runs disable traces and generated instrumentation. Eight alternating
AB/BA pairs compare **GrhSIM / Verilator**; a ratio above one means GrhSIM is
slower. Each backend warms up once. Short workloads repeat complete initialization
and execution, with a common repeat count frozen from the Verilator warmup.
External process walltime includes startup, audit and teardown; `init_s` and
`sim_s` use common harness timers. Build times are separate.

Private runtime copies are prefaulted on NUMA1 using `grhsim_numa.py`. Start/end
audits check affinity, task count, ASLR, binary/library pages and anonymous pages.
Rejected placement records are retained; a pair gets at most one retry. Samples
are never discarded based on measured speed. Diagnostic `perf` and generated
counter runs are separate from the paired results.

`control` is the single additional diagnostic: original-RTL Verilator,
normalized-RTL Verilator, original-RTL Verilator, in that order. It records its
hypothesis before execution, checks the existing workload signature, and reports
no confidence interval. `profile` and `control` skip execution if the main paired
walltime CI lower bound is at most 1.20. `profile` also exports the actual emitter
operation/group/batch source mapping through `cv32e40p_map`.
