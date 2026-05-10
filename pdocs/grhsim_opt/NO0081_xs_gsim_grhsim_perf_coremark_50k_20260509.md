# NO0081 XS GSim / GrhSIM Perf CoreMark 50k

> 2026-05-09 记录一次无 runtime profile 环境下的 XiangShan `coremark 50k` host 侧 `perf stat` / `perf record` 对比。目标是量化 `grhsim` 相对 `gsim` 的 host 指令数、分支、cache/TLB 压力和热点分布，为后续优化排序。

## 结论

- `grhsim` wall time 是 `gsim` 的 `13.53x`，host cycles 是 `13.67x`。
- 但 `grhsim` host instructions 只到 `3.67x`，说明慢点不只是“生成代码指令更多”，更主要是 host IPC 从 `0.461` 掉到 `0.124`，即单位指令退休效率显著变差。
- `grhsim` branches 是 `11.30x`，branch misses 是 `12.51x`，branch miss rate 也从 `41.19%` 升到 `45.61%`。这说明 generated scheduler/batch dispatch 里的控制流压力是第一类优化目标。
- `grhsim` generic cache references 是 `5.13x`，cache misses 是 `4.29x`；L1D loads 是 `5.35x`，L1D load misses 是 `5.77x`。内存访问量显著放大，但 miss rate 只略高，更多像是 value slot / active bitset / batch metadata 访问密度过高，而不是单纯 locality 崩坏。
- `grhsim` L1I load misses 是 `8.56x`，iTLB load count 是 `8.82x`。结合 `grhsim` emu 二进制 `139M` vs `gsim` `54M`，前端 footprint 也是明确瓶颈。
- `perf record` 中 `gsim` 热点分散在多个 `SSimTop::subStep*()`，`grhsim` 热点集中在 `GrhSIM_SimTop::eval_compute_batch_{11,859,860,861,820}()`。下一步应优先抽这些 batch 做源代码/汇编级采样，验证是否对应 activation propagation、value compare/writeback 或大 batch 内部控制流。

## 产物与 Profile 核查

本轮使用现有已构建产物：

| emulator | path | size | build timestamp |
| --- | ---: | ---: | --- |
| `gsim` | `build/xs/gsim/gsim-compile/emu` | `54M` | `2026-05-09 17:16` |
| `grhsim` | `build/xs/grhsim/grhsim-compile/emu` | `139M` | `2026-05-09 15:29` |

核查结果：

- `build/xs/gsim/gsim-compile/{model,other}` 未搜到 `GSIM_RUNTIME_PROFILE` / `runtimeProfile` / `EMU_RUNTIME_PROFILE`。
- `build/xs/grhsim/grhsim-compile` 当前只保留对象和二进制，没有生成 `.cpp` 源文件可搜；`strings build/xs/grhsim/grhsim-compile/emu` 能看到 `EMU_RUNTIME_PROFILE` 与 `GRHSIM_RUNTIME_PROFILE` 字符串，说明二进制仍含“环境变量打开”的可选 runtime profile 路径。
- 本轮所有运行均显式 `env -u EMU_RUNTIME_PROFILE`，stdout/perf 日志也未出现 `[EMU_RUNTIME_PROFILE] enabled` 或 runtime profile 输出行，因此本轮数据是未启用 runtime profile 的仿真数据。

运行口径：

- workload: `testcase/xiangshan/ready-to-run/coremark-2-iteration.bin`
- reference: `testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`
- emulator args: `-b 0 -e 0 -C 50000`
- env: `EMU_PROGRESS_EVERY_CYCLES=0`，且 unset `EMU_RUNTIME_PROFILE`
- kernel perf 权限：`kernel.perf_event_paranoid=-1`，`kernel.nmi_watchdog=0`

## 命令

基础事件组：

```bash
env -u EMU_RUNTIME_PROFILE EMU_PROGRESS_EVERY_CYCLES=0 \
  perf stat -e cycles,instructions,branches,branch-misses,cache-references,cache-misses,duration_time,user_time,system_time \
  build/xs/gsim/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 50000

env -u EMU_RUNTIME_PROFILE EMU_PROGRESS_EVERY_CYCLES=0 \
  perf stat -e cycles,instructions,branches,branch-misses,cache-references,cache-misses,duration_time,user_time,system_time \
  build/xs/grhsim/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 50000
```

L1/TLB 事件组：

```bash
env -u EMU_RUNTIME_PROFILE EMU_PROGRESS_EVERY_CYCLES=0 \
  perf stat -e L1-dcache-loads,L1-dcache-load-misses,L1-icache-load-misses,dTLB-loads,dTLB-load-misses,iTLB-loads,iTLB-load-misses \
  build/xs/gsim/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 50000

env -u EMU_RUNTIME_PROFILE EMU_PROGRESS_EVERY_CYCLES=0 \
  perf stat -e L1-dcache-loads,L1-dcache-load-misses,L1-icache-load-misses,dTLB-loads,dTLB-load-misses,iTLB-loads,iTLB-load-misses \
  build/xs/grhsim/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 50000
```

采样：

```bash
env -u EMU_RUNTIME_PROFILE EMU_PROGRESS_EVERY_CYCLES=0 \
  perf record -F 99 -e cycles -o build/logs/xs_perf/gsim_coremark50k_cycles.data -- \
  build/xs/gsim/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 50000

env -u EMU_RUNTIME_PROFILE EMU_PROGRESS_EVERY_CYCLES=0 \
  perf record -F 99 -e cycles -o build/logs/xs_perf/grhsim_coremark50k_cycles.data -- \
  build/xs/grhsim/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 50000
```

说明：直接从仓库根目录运行 emu；从 `build/xs/gsim` 工作目录使用 `perf -o` 或 shell 重定向到上层日志路径时，当前执行环境会报 `Read-only file system`。

## Perf Stat 基础事件

| metric | gsim | grhsim | grhsim / gsim |
| --- | ---: | ---: | ---: |
| elapsed time | `30.489s` | `412.656s` | `13.53x` |
| host cycles | `173,270,681,581` | `2,367,819,835,745` | `13.67x` |
| host instructions | `79,954,722,251` | `293,224,359,350` | `3.67x` |
| host IPC | `0.461` | `0.124` | `0.27x` |
| branches | `4,510,004,624` | `50,961,221,682` | `11.30x` |
| branch misses | `1,857,652,175` | `23,242,526,001` | `12.51x` |
| branch miss rate | `41.19%` | `45.61%` | `1.11x` |
| cache references | `22,720,436,702` | `116,632,267,565` | `5.13x` |
| cache misses | `12,259,246,131` | `52,640,359,658` | `4.29x` |
| cache miss rate | `53.96%` | `45.13%` | `0.84x` |

对应仿真进度：

| emulator | guest instrCnt | guest cycleCnt | guest IPC | host time from emu |
| --- | ---: | ---: | ---: | ---: |
| `gsim` | `73,584` | `49,998` | `1.471739` | `30,486ms` |
| `grhsim` | `73,087` | `49,996` | `1.461857` | `412,646ms` |

两边都跑到 `-C 50000` limit，但结束 PC 不同：

- `gsim`: `pc = 0x8000131e`
- `grhsim`: `pc = 0x800010ce`

因此本文的 host perf 数据用于“同 cycle limit、同 workload 参数”的 host 成本对比，不应当解读为完全相同 guest dynamic instruction stream 的逐指令等价对比。

## Perf Stat L1/TLB 事件

该事件组 perf 显示 multiplex coverage 为 `85.71%`，表中计数已经是 perf 缩放后的估算值。`LLC-loads` / `LLC-load-misses` 在当前 PMU 上显示 `<not supported>`，未纳入本文。

| metric | gsim | grhsim | grhsim / gsim |
| --- | ---: | ---: | ---: |
| L1D loads | `48,677,887,021` | `260,391,544,746` | `5.35x` |
| L1D load misses | `1,832,037,784` | `10,568,930,111` | `5.77x` |
| L1D miss rate | `3.76%` | `4.06%` | `1.08x` |
| L1I load misses | `2,601,408,871` | `22,275,296,433` | `8.56x` |
| dTLB loads | `120,069,775` | `1,936,376,406` | `16.13x` |
| dTLB load misses | `120,915` | `1,252,643` | `10.36x` |
| dTLB miss rate | `0.10%` | `0.06%` | `0.64x` |
| iTLB loads | `467,077,951` | `4,118,243,735` | `8.82x` |
| iTLB load misses | `436,994,654` | `1,663,717,689` | `3.81x` |
| iTLB miss rate | `93.56%` | `40.40%` | `0.43x` |

解读重点：

- `grhsim` L1D load 总量是 `5.35x`，比 host instruction `3.67x` 更高，说明每条 host 指令背后的 data-side 访存密度更高。
- `grhsim` L1D miss rate 只从 `3.76%` 到 `4.06%`，所以 data-side 主要问题是访问次数和带宽，而不是 miss rate 本身突然恶化。
- `grhsim` L1I misses 是 `8.56x`，明显高于 host instruction ratio，说明 generated code footprint / dispatch 分散度给前端带来额外压力。
- `iTLB-load-misses` 的绝对比值是 `3.81x`，低于 `iTLB-loads 8.82x`；但这组 iTLB 事件在该 PMU 上口径较特殊，适合做相对趋势，不宜过度解释 miss rate 绝对值。

## Perf Record 热点

采样命令使用 `perf record -F 99 -e cycles`：

- `gsim`: `3058 samples`
- `grhsim`: `40755 samples`
- kernel symbol resolution 受 `/proc/kallsyms` 权限限制；本文只使用用户态 emu 符号。

`gsim` top symbols：

| overhead | symbol |
| ---: | --- |
| `2.25%` | `SSimTop::subStep290()` |
| `2.04%` | `SSimTop::subStep315()` |
| `1.49%` | `SSimTop::subStep20()` |
| `1.43%` | `SSimTop::subStep291()` |
| `1.39%` | `SSimTop::subStep133()` |
| `1.38%` | `SSimTop::subStep18()` |
| `1.36%` | `SSimTop::subStep276()` |
| `1.28%` | `SSimTop::subStep134()` |
| `1.18%` | `SSimTop::subStep277()` |
| `1.16%` | `SSimTop::subStep273()` |

`grhsim` top symbols：

| overhead | symbol |
| ---: | --- |
| `1.18%` | `GrhSIM_SimTop::eval_compute_batch_11()` |
| `1.04%` | `GrhSIM_SimTop::eval_compute_batch_860()` |
| `0.95%` | `GrhSIM_SimTop::eval_compute_batch_859()` |
| `0.92%` | `GrhSIM_SimTop::eval_compute_batch_861()` |
| `0.51%` | `GrhSIM_SimTop::eval_compute_batch_820()` |

热点很分散，单个 symbol 没有压倒性占比。这更像“每个 batch 的单位成本普遍偏高”，而不是某一个局部函数异常慢。下一步应对 top batch 做局部反汇编和源码映射，重点看：

- active word / active bitset 扫描与分支形态；
- value slot old/new 读取、比较、写回的访存序列；
- activation propagation 的写入密度；
- compute batch 内部是否存在难预测的 per-node/per-op 分支；
- batch 代码体积是否导致 I-cache / iTLB 反复切换。

## Branch 来源补充

为回答 `grhsim` 多出来的 `11.30x` branches 来自哪里，追加了两组运行时采样：

```bash
env -u EMU_RUNTIME_PROFILE EMU_PROGRESS_EVERY_CYCLES=0 \
  perf record -e branches -c 1000000 -o build/logs/xs_perf/grhsim_coremark50k_branches.data -- \
  build/xs/grhsim/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 50000

env -u EMU_RUNTIME_PROFILE EMU_PROGRESS_EVERY_CYCLES=0 \
  perf record -e branch-misses -c 500000 -o build/logs/xs_perf/grhsim_coremark50k_branch_misses.data -- \
  build/xs/grhsim/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 50000
```

同样对 `gsim` 跑了对应命令用于对照。样本规模：

| event | gsim samples | grhsim samples |
| --- | ---: | ---: |
| `branches` | `4,505` | `50,967` |
| `branch-misses` | `3,703` | `46,498` |

`grhsim` retired branches top symbols：

| overhead | symbol |
| ---: | --- |
| `4.29%` | `grhsim_replicate_words<2,1>()` |
| `1.71%` | `grhsim_add_words<2>()` |
| `1.55%` | `grhsim_concat_words<2,1,1>()` |
| `1.29%` | `grhsim_concat_words<2,1,2>()` |
| `1.10%` | `GrhSIM_SimTop::eval_compute_batch_860()` |
| `1.08%` | `GrhSIM_SimTop::eval_compute_batch_859()` |
| `0.97%` | `GrhSIM_SimTop::eval_compute_batch_861()` |
| `0.92%` | `GrhSIM_SimTop::eval()` |
| `0.85%` | `GrhSIM_SimTop::eval_compute_batch_202()` |
| `0.70%` | `GrhSIM_SimTop::eval_compute_batch_624()` |
| `0.68%` | `GrhSIM_SimTop::eval_compute_batch_518()` |
| `0.63%` | `grhsim_assign_words<16>()` |
| `0.55%` | `GrhSIM_SimTop::eval_compute_batch_808()` |
| `0.54%` | `GrhSIM_SimTop::eval_compute_batch_820()` |
| `0.52%` | `GrhSIM_SimTop::eval_compute_batch_819()` |
| `0.51%` | `grhsim_assign_words<2>()` |
| `0.51%` | `GrhSIM_SimTop::eval_compute_batch_826()` |
| `0.48%` | `GrhSIM_SimTop::eval_compute_batch_821()` |
| `0.48%` | `GrhSIM_SimTop::eval_compute_batch_823()` |
| `0.48%` | `GrhSIM_SimTop::eval_compute_batch_409()` |

`grhsim` branch misses top symbols：

| overhead | symbol |
| ---: | --- |
| `1.82%` | `GrhSIM_SimTop::eval_compute_batch_860()` |
| `1.65%` | `GrhSIM_SimTop::eval_compute_batch_861()` |
| `1.62%` | `GrhSIM_SimTop::eval_compute_batch_859()` |
| `0.88%` | `GrhSIM_SimTop::eval_compute_batch_821()` |
| `0.85%` | `GrhSIM_SimTop::eval_compute_batch_820()` |
| `0.82%` | `GrhSIM_SimTop::eval_compute_batch_819()` |
| `0.80%` | `GrhSIM_SimTop::eval_compute_batch_822()` |
| `0.79%` | `GrhSIM_SimTop::eval_compute_batch_823()` |
| `0.79%` | `GrhSIM_SimTop::eval_compute_batch_826()` |
| `0.71%` | `GrhSIM_SimTop::eval_compute_batch_202()` |

对照 `gsim`，其 retired branches 和 branch misses 都主要分散在 `SSimTop::subStep*()`：

- branches top5: `subStep20` / `subStep133` / `subStep304` / `subStep290` / `subStep99`，累计 `10.79%`；
- branch-misses top5: `subStep291` / `subStep304` / `subStep133` / `subStep276` / `subStep20`，累计 `12.80%`。

### Branch 来源判断

`grhsim` 多出来的 branch 不是单点热点，而是两类路径叠加：

1. 宽值 helper 内部条件和循环

`branches` 采样 top4 全是 wide-word helper：

- `grhsim_replicate_words<2,1>()`
- `grhsim_add_words<2>()`
- `grhsim_concat_words<2,1,1>()`
- `grhsim_concat_words<2,1,2>()`

这些 helper 的模板实现位于 [`wolvrix/lib/emit/grhsim_cpp.cpp`](../../wolvrix/lib/emit/grhsim_cpp.cpp)：

- `grhsim_assign_words`：约 `11669` 行，包含 live words loop、tail word width 判断、changed accumulation、zero tail loop；
- `grhsim_concat_words` / `grhsim_replicate_words`：约 `12568` 行，依赖 `grhsim_insert_words`、`std::min`、offset/width 判断和 truncate；
- `grhsim_add_words`：约 `12926` 行，先尝试 `u128` fast path，再回退 word carry loop。

`nm -S` 显示 top helper 本身不大，例如：

| symbol | size |
| --- | ---: |
| `grhsim_replicate_words<2,1>()` | `0x203` |
| `grhsim_add_words<2>()` | `0x13a` |
| `grhsim_concat_words<2,1,1>()` | `0x211` |
| `grhsim_concat_words<2,1,2>()` | `0x247` |
| `grhsim_assign_words<2>()` | `0xd5` |
| `grhsim_assign_words<16>()` | `0xde` |

因此它们成为 branch top，不是因为单个函数巨大，而是调用频率极高。尤其 `2-word` 宽值路径在 XiangShan 里很常见，当前 generic helper 每次都保留 width/tail/loop 控制流。

2. Batch 内 changed-check 与 activation propagation

`branch-misses` top 不再是 helper，而集中到 `eval_compute_batch_859/860/861` 和 `819-826`。这些 batch size 较大：

| symbol | size |
| --- | ---: |
| `eval_compute_batch_859()` | `0x82a6a` |
| `eval_compute_batch_860()` | `0x95441` |
| `eval_compute_batch_861()` | `0x87e6f` |
| `eval_compute_batch_819()` | `0x5f7b2` |
| `eval_compute_batch_820()` | `0x25ecd` |
| `eval_compute_batch_821()` | `0x25a59` |
| `eval_compute_batch_822()` | `0x25970` |
| `eval_compute_batch_823()` | `0x25cd3` |
| `eval_compute_batch_826()` | `0x29a99` |
| `eval_compute_batch_202()` | `0x4a83d6` |

局部反汇编显示 batch 内有大量形如：

```asm
cmp    ...
je/jne ...
orb    ...   ; mark downstream active word
mov    ...   ; update stored value
```

以及 `grhsim_assign_words(...)` 返回值后的：

```asm
test   %al,%al
je     ...
orb    ...
```

这说明预测失败主要来自 batch 内 old/new changed-check 和 active propagation，而 retired branch 总量还叠加了高频 wide-word helper 的内部控制流。

### 对优化的直接含义

- 优先为 `N=2` 的 `concat/repl/add/assign` 生成 specialized straight-line code。当前 top retired branches 明确指向 `2-word` helper，值得在 emitter 层把常量 width/rep/totalWidth 折进生成代码，避免通用 helper 的 loop 和 width 分支。
- 对 `assign_words<N>` 分离 fixed full-width 快路径。大量调用传入固定宽度，`liveWords` / tail width / zero tail loop 可以在生成期决定。
- 对 batch changed-check 做批量化或 branchless 化。`branch-misses` 指向 859/860/861、819-826，说明这些 batch 内的 `cmp + je/jne + orb` 链条是预测失败主因。
- 下一步可以只针对 `eval_compute_batch_860()` 和 `eval_compute_batch_859()` 做 `perf annotate` 或 `objdump --start-address/--stop-address` 小窗口分析，统计其中 helper call、`je/jne`、`orb` 的密度。

## 优化方向

1. 降低 branch 数和 branch miss

`grhsim` branches 是 `11.30x`，branch misses 是 `12.51x`。这和 runtime profile 里“总 op solve 数未到 13x，但单位 op 成本显著更高”的结论一致。优先考虑：

- 将 batch 内常见分支改为更直线化的数据流，尤其是 active check、dirty check、old/new changed check；
- 对低概率路径使用 `[[unlikely]]` 或局部分离，避免污染 hot path；
- 对连续 active word 扫描使用 word-level fast path，减少 per-node 分支。

2. 降低 data-side 访问次数

L1D loads 是 `5.35x`，generic cache references 是 `5.13x`。这说明当前 value storage / activation metadata 让每个 compute op 带了太多 host memory traffic。优先考虑：

- 合并 value slot 访问，减少 old/new 双读或重复 reload；
- 对窄值和常用临时值做 local scalar cache；
- 将 activation bitset 写入批量化，避免每个 sink/edge 都触发独立写路径；
- 对 compute batch 内部的 metadata 做 SoA/紧凑布局，减少跨 cache line 访问。

3. 降低 frontend footprint

`grhsim` emu 是 `139M`，`gsim` 是 `54M`；L1I misses 是 `8.56x`。即便 `grhsim` 的 host instructions 只多 `3.67x`，前端压力也更接近 `8-9x`。优先考虑：

- 继续推进 compact local expr emit，减少 batch 代码体积；
- 对 cold commit/propagation helper 做 outline，hot compute path 保持紧凑；
- 限制单个 `eval_compute_batch_*` 体积，避免 I-cache/iTLB 反复抖动；
- 对 top batch 进行 `objdump -dr --demangle` 局部采样，比较条件跳转密度和 load/store 密度。

## 原始数据

所有原始日志位于 `build/logs/xs_perf/`：

- `gsim_coremark50k_basic.perf`
- `gsim_coremark50k_basic.stdout`
- `grhsim_coremark50k_basic.perf`
- `grhsim_coremark50k_basic.stdout`
- `gsim_coremark50k_l1tlb.perf`
- `gsim_coremark50k_l1tlb.stdout`
- `grhsim_coremark50k_l1tlb.perf`
- `grhsim_coremark50k_l1tlb.stdout`
- `gsim_coremark50k_cycles.data`
- `gsim_coremark50k_cycles.report`
- `grhsim_coremark50k_cycles.data`
- `grhsim_coremark50k_cycles.report`
- `gsim_coremark50k_branches.data`
- `gsim_coremark50k_branches.report`
- `grhsim_coremark50k_branches.data`
- `grhsim_coremark50k_branches.report`
- `gsim_coremark50k_branch_misses.data`
- `gsim_coremark50k_branch_misses.report`
- `grhsim_coremark50k_branch_misses.data`
- `grhsim_coremark50k_branch_misses.report`
