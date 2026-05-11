# NO0089 当前 GSim / GrhSIM Perf 静态与动态指令画像

## 1. 本次口径

本记录使用当前已有产物，不重新构建。

关键输入：

- GSim emu: `build/xs/gsim/gsim-compile/emu`
- GrhSIM emu: `build/xs/grhsim/grhsim-compile/emu`
- workload: `testcase/xiangshan/ready-to-run/coremark-2-iteration.bin`
- reference: `testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`
- emu args: `-b 0 -e 0 -C 50000`
- env: `env -u EMU_RUNTIME_PROFILE EMU_PROGRESS_EVERY_CYCLES=0`
- perf logs: `build/logs/xs_perf_no0089/`

机器环境：

- CPU: `AMD Ryzen 9 9950X 16-Core Processor`
- perf 基础事件可用：`cycles,instructions,branches,branch-misses,cache-references,cache-misses`
- AMD load/store 事件可用：`ls_dispatch.{all,ld_dispatch,store_dispatch,ld_st_dispatch}`
- Intel 风格 `mem_inst_retired.all_loads/all_stores` 在本机不可用，因此本文用 `ls_dispatch.*` 作为动态访存操作数/访存指令压力的主要口径。

静态计数说明：

- 静态指令来自 `objdump -d -Mintel --no-show-raw-insn`。
- 静态访存指令按反汇编文本含内存操作数 `[...]` 统计，并排除 `lea` / `nop` / `prefetch*`。
- 静态分支指令按 mnemonic 前缀 `j*`、`call*`、`ret*`、`loop*`、`iret*`、`syscall`、`sysret` 统计。
- 静态计数只覆盖 `emu` ELF 本体，不包含运行时动态库。

## 2. 结论

- 当前 GrhSIM 50k wall time 是 GSim 的 `11.40x`，host cycles 是 `11.50x`。
- GrhSIM 动态 retired instructions 是 GSim 的 `3.61x`，但 IPC 从 `0.413` 降到 `0.129`，只有 GSim 的 `0.314x`。这说明慢点仍不是单纯“多退休了几倍指令”。
- 静态二进制层面，GrhSIM `.text` 是 GSim 的 `2.15x`，静态总指令是 `2.36x`，静态访存形态指令是 `2.31x`，静态分支形态指令是 `3.42x`。分支形态膨胀明显高于总指令膨胀。
- 动态 branch count 是 `7.60x`，branch misses 是 `8.69x`，miss rate 从 `41.11%` 升到 `47.00%`。GrhSIM 的控制流压力仍是核心问题。
- 动态 load/store dispatch 总量是 `5.06x`；其中 load dispatch 是 `4.31x`，store dispatch 是 `5.49x`，load-store dispatch 是 `11.04x`。GrhSIM 的 data-side 压力明显高于 retired instruction ratio。
- L1D loads 是 `4.56x`，L1D load misses 是 `5.87x`，L1D miss rate 从 `3.77%` 升到 `4.86%`。访存次数和 miss 绝对量同时增加。
- L1I load misses 是 `6.39x`，iTLB loads 是 `6.67x`。结合 `.text 2.15x` 与静态分支 `3.42x`，前端 footprint / branch predictor / iTLB 压力仍是 GrhSIM 当前性能特征。

## 3. 现有二进制

| 项 | GSim | GrhSIM | GrhSIM / GSim |
| --- | ---: | ---: | ---: |
| emu path | `build/xs/gsim/gsim-compile/emu` | `build/xs/grhsim/grhsim-compile/emu` | - |
| mtime | `2026-05-11 10:45:33 +0800` | `2026-05-11 21:29:32 +0800` | - |
| file size | 56,020,248 B | 120,235,400 B | 2.146x |
| `.text` | 55,892,978 B | 119,902,985 B | 2.145x |

## 4. 静态二进制指令画像

| 静态计数 | GSim | GrhSIM | GrhSIM / GSim |
| --- | ---: | ---: | ---: |
| all instructions | 9,841,119 | 23,189,727 | 2.356x |
| memory-form instructions | 4,266,138 | 9,852,681 | 2.310x |
| branch/control-flow instructions | 454,356 | 1,553,168 | 3.418x |

Top mnemonic：

| rank | GSim | count | GrhSIM | count |
| ---: | --- | ---: | --- | ---: |
| 1 | `mov` | 2,121,602 | `mov` | 4,257,231 |
| 2 | `or` | 1,362,139 | `or` | 3,068,566 |
| 3 | `movzx` | 1,281,936 | `movzx` | 2,479,953 |
| 4 | `and` | 809,669 | `cmp` | 1,951,283 |
| 5 | `cmp` | 580,822 | `and` | 1,737,985 |
| 6 | `test` | 322,082 | `setne` | 1,417,742 |
| 7 | `shl` | 306,461 | `xor` | 1,231,425 |
| 8 | `setne` | 302,515 | `je` | 865,629 |
| 9 | `xor` | 279,980 | `test` | 784,418 |
| 10 | `sete` | 175,364 | `shl` | 582,162 |

GrhSIM 的 `cmp` / `setne` / `je` / `jmp` 等形态显著增加，和 runtime branch pressure 对得上。

## 5. Guest 运行结果

| 指标 | GSim | GrhSIM |
| --- | ---: | ---: |
| guest cycle spent | 50,001 | 50,001 |
| core cycleCnt | 49,998 | 49,996 |
| guest instrCnt | 73,584 | 73,580 |
| guest IPC | 1.471739 | 1.471718 |
| end PC | `0x8000131e` | `0x80001312` |
| host time from emu | 34,086 ms | 388,730 ms |

两边都跑满 `-C 50000`。guest 指令数差 `4` 条，本文可视为同 workload / 同 cycle limit 下的 host 成本对比。

## 6. Perf 基础动态事件

命令输出：

- `build/logs/xs_perf_no0089/gsim_basic.stat`
- `build/logs/xs_perf_no0089/grhsim_basic.stat`

| perf 指标 | GSim | GrhSIM | GrhSIM / GSim |
| --- | ---: | ---: | ---: |
| elapsed time | 34.089382 s | 388.740922 s | 11.404x |
| cycles | 193,974,522,338 | 2,230,633,160,497 | 11.500x |
| instructions | 80,041,267,210 | 288,645,501,546 | 3.606x |
| IPC | 0.413 | 0.129 | 0.314x |
| branches | 4,518,767,074 | 34,333,402,633 | 7.598x |
| branch misses | 1,857,682,250 | 16,137,579,459 | 8.687x |
| branch miss rate | 41.11% | 47.00% | 1.143x |
| cache references | 22,924,299,265 | 100,733,228,073 | 4.394x |
| cache misses | 12,566,201,265 | 48,326,827,011 | 3.846x |
| cache miss rate | 54.82% | 47.98% | 0.875x |

归一到 guest cycle：

| 指标 | GSim | GrhSIM | GrhSIM / GSim |
| --- | ---: | ---: | ---: |
| host retired instructions / guest cycle | 1,600,793 | 5,772,795 | 3.606x |
| host branches / guest cycle | 90,373 | 686,655 | 7.598x |
| host branch misses / guest cycle | 37,153 | 322,745 | 8.687x |

## 7. 动态访存 / Cache / TLB

命令输出：

- `build/logs/xs_perf_no0089/gsim_ls.stat`
- `build/logs/xs_perf_no0089/grhsim_ls.stat`

该组包含 11 个事件，perf 显示 coverage 约 `54.55%`，表内数值为 perf 缩放后的估算计数。两边同一事件组、同一机器、同一 workload，适合做相对比较。

| perf 指标 | GSim | GrhSIM | GrhSIM / GSim |
| --- | ---: | ---: | ---: |
| `ls_dispatch.all` | 57,524,722,658 | 291,244,048,636 | 5.063x |
| `ls_dispatch.ld_dispatch` | 38,717,125,435 | 166,799,074,956 | 4.308x |
| `ls_dispatch.store_dispatch` | 14,952,434,103 | 82,037,785,924 | 5.487x |
| `ls_dispatch.ld_st_dispatch` | 3,865,414,969 | 42,674,618,639 | 11.040x |
| L1-dcache-loads | 48,735,559,119 | 222,098,108,571 | 4.557x |
| L1-dcache-load-misses | 1,838,855,548 | 10,798,622,275 | 5.872x |
| L1D load miss rate | 3.77% | 4.86% | 1.289x |
| L1-icache-load-misses | 2,618,618,516 | 16,734,725,651 | 6.391x |
| dTLB-loads | 120,527,577 | 1,974,054,319 | 16.378x |
| dTLB-load-misses | 165,620 | 1,451,784 | 8.766x |
| dTLB miss rate | 0.14% | 0.07% | 0.535x |
| iTLB-loads | 494,791,305 | 3,300,956,099 | 6.671x |
| iTLB-load-misses | 447,583,369 | 1,480,373,098 | 3.307x |
| iTLB miss rate | 90.46% | 44.85% | 0.496x |

Load/store dispatch 构成：

| 构成 | GSim | GrhSIM |
| --- | ---: | ---: |
| load dispatch / all | 67.31% | 57.27% |
| store dispatch / all | 25.99% | 28.17% |
| load-store dispatch / all | 6.72% | 14.65% |

GrhSIM 的 `ld_st_dispatch` 占比从 `6.72%` 提高到 `14.65%`，绝对量达到 `11.04x`。这和 GrhSIM runtime 中 value/state slot 读取、old/new 比较、写回、activation bitset 更新更密集的预期一致。

## 8. 命令记录

静态计数：

```bash
objdump -d -Mintel --no-show-raw-insn build/xs/gsim/gsim-compile/emu | awk '...'
objdump -d -Mintel --no-show-raw-insn build/xs/grhsim/grhsim-compile/emu | awk '...'
```

基础 perf：

```bash
env -u EMU_RUNTIME_PROFILE EMU_PROGRESS_EVERY_CYCLES=0 \
  perf stat -o build/logs/xs_perf_no0089/gsim_basic.stat \
  -e cycles,instructions,branches,branch-misses,cache-references,cache-misses,duration_time,user_time,system_time \
  build/xs/gsim/gsim-compile/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 50000

env -u EMU_RUNTIME_PROFILE EMU_PROGRESS_EVERY_CYCLES=0 \
  perf stat -o build/logs/xs_perf_no0089/grhsim_basic.stat \
  -e cycles,instructions,branches,branch-misses,cache-references,cache-misses,duration_time,user_time,system_time \
  build/xs/grhsim/grhsim-compile/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 50000
```

Load/store / cache / TLB perf：

```bash
env -u EMU_RUNTIME_PROFILE EMU_PROGRESS_EVERY_CYCLES=0 \
  perf stat -o build/logs/xs_perf_no0089/gsim_ls.stat \
  -e ls_dispatch.all,ls_dispatch.ld_dispatch,ls_dispatch.store_dispatch,ls_dispatch.ld_st_dispatch,L1-dcache-loads,L1-dcache-load-misses,L1-icache-load-misses,dTLB-loads,dTLB-load-misses,iTLB-loads,iTLB-load-misses \
  build/xs/gsim/gsim-compile/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 50000

env -u EMU_RUNTIME_PROFILE EMU_PROGRESS_EVERY_CYCLES=0 \
  perf stat -o build/logs/xs_perf_no0089/grhsim_ls.stat \
  -e ls_dispatch.all,ls_dispatch.ld_dispatch,ls_dispatch.store_dispatch,ls_dispatch.ld_st_dispatch,L1-dcache-loads,L1-dcache-load-misses,L1-icache-load-misses,dTLB-loads,dTLB-load-misses,iTLB-loads,iTLB-load-misses \
  build/xs/grhsim/grhsim-compile/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 50000
```

## 9. 当前判断

当前 GrhSIM 的性能特征可以概括为三层叠加：

1. 静态 code footprint 明显更大：`.text 2.15x`、静态总指令 `2.36x`。
2. 控制流比总指令放大更严重：静态分支 `3.42x`，动态 branches `7.60x`，branch misses `8.69x`。
3. 访存 dispatch 比 retired instruction 放大更严重：动态 `ls_dispatch.all 5.06x`，其中 store 和 load-store dispatch 更重。

因此后续优化仍应优先降低生成代码中的 per-value/per-edge 分支和 slot/bitset 访存密度；只减少静态指令条数但不降低 branch miss 与 load/store dispatch，预计难以显著改善 wall time。
